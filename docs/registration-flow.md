# Registration Flow

This document covers the full cart-to-payment pipeline: how items get into a cart, how carts become orders, how payments are collected, and how refunds work. All service code lives in `django_program.registration.services`.

## Models

Before getting into the flow, here are the models involved:

| Model | Purpose |
|---|---|
| {class}`~django_program.registration.models.TicketType` | A purchasable ticket category (e.g. "Individual", "Student"). Has pricing, availability windows, stock limits, and an optional voucher gate. |
| {class}`~django_program.registration.models.AddOn` | An optional extra (e.g. tutorial, t-shirt). Can require specific ticket types via `requires_ticket_types` M2M. |
| {class}`~django_program.registration.models.Voucher` | A discount or access code. Three types: `COMP`, `PERCENTAGE`, `FIXED_AMOUNT`. Scoped to specific tickets/add-ons via M2M. |
| {class}`~django_program.registration.models.Cart` | A user's shopping cart. Statuses: `OPEN`, `CHECKED_OUT`, `EXPIRED`, `ABANDONED`. |
| {class}`~django_program.registration.models.CartItem` | A line in the cart. References exactly one of `ticket_type` or `addon` (enforced by a DB check constraint). |
| {class}`~django_program.registration.models.Order` | A completed checkout. Statuses: `PENDING`, `PAID`, `REFUNDED`, `PARTIALLY_REFUNDED`, `CANCELLED`. |
| {class}`~django_program.registration.models.OrderLineItem` | Immutable snapshot of a purchased item at checkout time. |
| {class}`~django_program.registration.models.Payment` | A financial transaction against an order. Methods: `STRIPE`, `COMP`, `CREDIT`, `MANUAL`. |
| {class}`~django_program.registration.models.Credit` | A store credit issued from a refund, applicable to future orders. |

## Global Ticket Capacity

The `Conference.total_capacity` field sets a hard venue-wide cap on the number of tickets sold across all ticket types. Add-ons do not count toward this cap since they do not consume venue seats.

### Setting the capacity

Set `total_capacity` on the Conference model through any of these:

- **Management dashboard** -- edit the conference and fill in the "Total capacity" field on the `ConferenceForm`.
- **Django admin** -- set the field directly on the Conference admin page.
- **TOML bootstrap** -- add `total_capacity = 2500` to the `[conference]` table in your config file.

A value of `0` means unlimited (no global cap enforced). This is the default.

### How enforcement works

Global capacity is checked at two points in the registration flow:

1. **Adding a ticket to the cart** -- `add_ticket()` calls `validate_global_capacity()` with the cart's current ticket count plus the new quantity. If the total exceeds the remaining global capacity, a `ValidationError` is raised.

2. **Checkout** -- `CheckoutService.checkout()` re-validates global capacity for all ticket items in the cart via `_revalidate_global_capacity()`. This catches the case where capacity filled up between adding items and checking out.

Both paths call the same underlying function in `django_program.registration.services.capacity`:

```python
from django_program.registration.services.capacity import (
    get_global_remaining,
    get_global_sold_count,
)

# How many tickets have been sold (paid + pending with active hold)?
sold = get_global_sold_count(conference)

# How many tickets are left? Returns None if capacity is unlimited.
remaining = get_global_remaining(conference)
```

### Sold count calculation

`get_global_sold_count()` counts `OrderLineItem` quantities where:

- The line item is a **ticket** (not an add-on), identified by `addon__isnull=True`.
- The order status is `PAID`, `PARTIALLY_REFUNDED`, or `PENDING` with `hold_expires_at` still in the future.

Using `addon__isnull=True` instead of `ticket_type__isnull=False` is deliberate: if a ticket type is deleted (SET_NULL on the FK), its line items are still counted. This prevents overselling after administrative cleanup.

### Concurrency safety

`validate_global_capacity()` acquires a row-level lock on the Conference row with `select_for_update()` before reading the sold count. The caller must already be inside a `transaction.atomic` block. This prevents two concurrent requests from both seeing "1 ticket remaining" and both succeeding.

### Error messages

When capacity is exceeded, the user sees one of:

- `"This conference is sold out (venue capacity: 2500)."` -- when zero tickets remain.
- `"Only 12 tickets remaining for this conference (venue capacity: 2500)."` -- when some tickets remain but fewer than requested.

## Cart Lifecycle

The cart service (`django_program.registration.services.cart`) is a collection of stateless functions. No classes to instantiate.

### Getting a Cart

```python
from django_program.registration.services.cart import get_or_create_cart

cart = get_or_create_cart(user, conference)
```

`get_or_create_cart` does three things in sequence:

1. Expires any stale open carts for this user/conference combination (sets status to `EXPIRED` where `expires_at < now`).
2. Looks for an existing `OPEN` cart. If found, returns it (fixing up `expires_at` if it was null).
3. Creates a new `OPEN` cart with `expires_at` set to `now + cart_expiry_minutes` (from `DJANGO_PROGRAM` config, default 30 minutes).

Each user gets one open cart per conference at a time.

### Adding Tickets

```python
from django_program.registration.services.cart import add_ticket

item = add_ticket(cart, ticket_type, qty=1)
```

`add_ticket` runs inside `@transaction.atomic` and validates the following, in order:

1. **Cart is open** and not expired.
2. **Ticket belongs to this conference** (compares `conference_id`).
3. **Ticket is available** -- `is_active` is true, current time is within the `available_from`/`available_until` window, and remaining stock is sufficient.
4. **Stock check** -- uses `SELECT FOR UPDATE` on the existing CartItem row to prevent race conditions. Checks `remaining_quantity` against the total of what is already in the cart plus the new `qty`.
5. **Per-user limit** -- sums quantity in cart plus quantity in previous paid/partially-refunded orders for this ticket type. If the total exceeds `limit_per_user`, the add is rejected.
6. **Voucher requirement** -- if `ticket_type.requires_voucher` is `True`, the cart must have a voucher attached where `unlocks_hidden_tickets` is `True` and the voucher's `applicable_ticket_types` includes this ticket type (or is empty, meaning all types qualify).

If a `CartItem` for this ticket type already exists, the quantity is incremented. If not, a new row is created. Concurrent inserts are handled: if the `CREATE` hits an `IntegrityError` (unique constraint on cart + ticket_type), it falls back to `SELECT FOR UPDATE` and increment.

After a successful add, the cart's `expires_at` is pushed forward to `now + cart_expiry_minutes`.

### Adding Add-Ons

```python
from django_program.registration.services.cart import add_addon

item = add_addon(cart, addon, qty=1)
```

Same pattern as `add_ticket`, with one extra validation: if the add-on has `requires_ticket_types` set, at least one of those ticket types must already be in the cart. You cannot buy a tutorial add-on without a conference ticket.

### Removing Items

```python
from django_program.registration.services.cart import remove_item

remove_item(cart, item_id)
```

When you remove a ticket, `remove_item` cascades. It checks every add-on in the cart: if an add-on required the ticket type being removed, and no other qualifying ticket type remains in the cart, that add-on is also deleted. This prevents orphaned add-ons that would fail validation at checkout.

### Updating Quantity

```python
from django_program.registration.services.cart import update_quantity

item = update_quantity(cart, item_id, qty=3)  # set absolute quantity
item = update_quantity(cart, item_id, qty=0)  # removes the item, returns None
```

`update_quantity` sets the absolute quantity (not a delta). It re-validates stock and per-user limits for the new value. If `qty <= 0`, the item is removed via `remove_item` and the function returns `None`.

### Applying a Voucher

```python
from django_program.registration.services.cart import apply_voucher

voucher = apply_voucher(cart, "SPKR-A3K9M2X1")
```

Looks up the voucher by code and conference. Validates that the voucher `is_valid` (active, has remaining uses, within validity window). Attaches it to the cart.

A cart holds at most one voucher. Calling `apply_voucher` again replaces the previous one.

## Voucher System

Vouchers live on the {class}`~django_program.registration.models.Voucher` model. Three types:

### COMP

100% off all applicable items. The discount equals the full line total for each applicable line.

### PERCENTAGE

`discount_value`% off applicable items. Applied per-line with `ROUND_HALF_UP` to the nearest cent.

```python
# A 20% voucher on a $100 ticket:
# discount = ($100.00 * 20 / 100) = $20.00
```

### FIXED_AMOUNT

`discount_value` dollars off, distributed proportionally across applicable lines. The last applicable line gets the remainder to avoid rounding drift.

```python
# A $25 voucher on a $100 ticket + $25 t-shirt ($125 applicable total):
# ticket share  = ($25 * $100 / $125) = $20.00
# t-shirt share = remainder            = $5.00
```

### Voucher Scoping

Vouchers have two M2M fields: `applicable_ticket_types` and `applicable_addons`. When empty, the voucher applies to all items of that type. When populated, only matching items get the discount.

Vouchers can also set `unlocks_hidden_tickets = True`. This lets the voucher reveal ticket types that have `requires_voucher = True` (e.g., speaker tickets or student tickets that should not appear in the public storefront).

### Validity Rules

A voucher is valid when all of the following are true:

- `is_active` is `True`
- `times_used < max_uses`
- Current time is within the `valid_from`/`valid_until` window (if set)

## Pricing Summary

```python
from django_program.registration.services.cart import get_summary

summary = get_summary(cart)
# summary.items       -> list[LineItemSummary]
# summary.subtotal    -> Decimal (before discount)
# summary.discount    -> Decimal (total discount from voucher)
# summary.total       -> Decimal (subtotal - discount, floored at $0.00)
```

Each {class}`~django_program.registration.services.cart.LineItemSummary` contains:

| Field | Type | Description |
|---|---|---|
| `item_id` | `int` | CartItem primary key |
| `description` | `str` | Ticket type name or add-on name |
| `quantity` | `int` | Number of this item |
| `unit_price` | `Decimal` | Per-unit price |
| `discount` | `Decimal` | Discount applied to this line |
| `line_total` | `Decimal` | Final line total after discount |

The summary computation:

1. Iterates cart items, computes undiscounted line totals (`unit_price * quantity`).
2. Identifies which lines are voucher-applicable based on the M2M scope.
3. Applies the discount strategy for the voucher type (comp, percentage, or fixed).
4. Sets each line's `line_total` to `undiscounted - discount`.
5. Returns the aggregate: `total = max(subtotal - discount, 0.00)`.

## Checkout

```python
from django_program.registration.services.checkout import CheckoutService

order = CheckoutService.checkout(
    cart,
    billing_name="Alice Smith",
    billing_email="alice@example.com",
    billing_company="",
)
```

{class}`~django_program.registration.services.checkout.CheckoutService` is a class with static methods. `checkout()` runs inside `@transaction.atomic` and does the following:

1. **Expires stale pending orders** for this conference. Any `PENDING` order whose `hold_expires_at` has passed is marked `CANCELLED` and its voucher usage is decremented.
2. **Locks the cart** with `SELECT FOR UPDATE`. Verifies status is `OPEN` and not expired.
3. **Validates the cart is not empty.**
4. **Re-validates stock** for every item at checkout time. This catches the case where stock ran out between the user adding items and clicking "checkout".
5. **Computes the pricing summary** using `get_summary_from_items()`.
6. **Validates the voucher** is still valid (active, has uses remaining, within date window).
7. **Creates an Order** with status `PENDING`. The order reference is generated as `{prefix}-{8 random alphanumeric chars}` (e.g. `ORD-A1B2C3D4`). Retries up to 10 times on reference collision.
8. **Copies each CartItem into an OrderLineItem**. Line items are immutable snapshots -- they capture the price, description, and discount at checkout time.
9. **Marks the cart as `CHECKED_OUT`.**
10. **Increments voucher usage** atomically with a conditional `UPDATE` that re-checks validity constraints.

The order's `hold_expires_at` is set to `now + pending_order_expiry_minutes` (default 15 minutes). During this window, the ordered items are counted as "sold" for stock purposes. If payment is not completed before the hold expires, the order auto-cancels on the next checkout attempt for this conference.

### Cancelling an Order

```python
order = CheckoutService.cancel_order(order)
```

Cancellation reverses everything: credit payments are restored to `AVAILABLE`, the order status becomes `CANCELLED`, and voucher usage is decremented. Only `PENDING` orders can be cancelled.

### Applying Store Credits

```python
payment = CheckoutService.apply_credit(order, credit)
```

Deducts the credit amount from the order's remaining balance. If the credit covers the full amount, the order transitions to `PAID` and the `order_paid` signal fires. Partial credit application leaves the order `PENDING` for the remaining balance.

## Payment

Three payment paths exist, all on {class}`~django_program.registration.services.payment.PaymentService`:

### Stripe Payment

```python
from django_program.registration.services.payment import PaymentService

client_secret = PaymentService.initiate_payment(order)
# Pass client_secret to Stripe.js on the frontend
```

`initiate_payment()` does:

1. Creates a Stripe customer for this user/conference (or retrieves the existing one).
2. Creates a Stripe `PaymentIntent` with the order total, currency, and metadata (`order_id`, `conference_id`, `reference`).
3. Creates a `Payment` record with status `PENDING` and the `stripe_payment_intent_id`.
4. Returns the `client_secret` for the frontend to confirm via Stripe.js.

The `StripeClient` is initialized per-conference -- each conference can use different Stripe account keys.

### Complimentary Payment

```python
payment = PaymentService.record_comp(order)
```

For zero-total orders (speaker comps, 100% voucher discounts). Creates a `Payment` with method `COMP` and amount `$0.00`, immediately transitions the order to `PAID`.

### Manual Payment

```python
payment = PaymentService.record_manual(
    order,
    amount=Decimal("100.00"),
    reference="Receipt #1234",
    note="Cash payment at registration desk",
    staff_user=request.user,
)
```

For at-the-door payments, wire transfers, or any off-platform method. If cumulative succeeded payments meet or exceed the order total, the order transitions to `PAID`.

## Webhooks

Stripe webhook events are handled by a registry-based dispatch system in `django_program.registration.webhooks`.

### Setup

The webhook is included automatically by the registration URL conf. Mount it with the
standard conference-slug prefix:

```python
from django.urls import include, path

urlpatterns = [
    path(
        "<slug:conference_slug>/register/",
        include("django_program.registration.urls"),
    ),
]
```

This exposes the webhook at `/<conference_slug>/register/webhooks/stripe/`. Each
conference has its own webhook endpoint. The view verifies the event signature against
the conference's webhook secret, deduplicates by Stripe event ID (stored in
{class}`~django_program.registration.models.StripeEvent`), and dispatches to the
registered handler.

The view always returns HTTP 200, even on processing errors. Errors are captured to {class}`~django_program.registration.models.EventProcessingException` with the full traceback.

### Handled Events

| Stripe Event | Handler | What It Does |
|---|---|---|
| `payment_intent.succeeded` | `PaymentIntentSucceededWebhook` | Creates/updates a `Payment` to `SUCCEEDED`, marks the order `PAID`, clears the inventory hold, fires the `order_paid` signal. |
| `payment_intent.payment_failed` | `PaymentIntentPaymentFailedWebhook` | Marks the matching `PENDING` payment as `FAILED`. The order stays `PENDING`. |
| `charge.refunded` | `ChargeRefundedWebhook` | Compares `amount_refunded` to `amount`. Full refund sets both `Payment` and `Order` to `REFUNDED`. Partial refund sets the order to `PARTIALLY_REFUNDED`. |
| `charge.dispute.created` | `ChargeDisputeCreatedWebhook` | Logs the dispute details for manual review. No automated action. |

### The `order_paid` Signal

```python
from django_program.registration.signals import order_paid

@receiver(order_paid)
def handle_order_paid(sender, order, user, **kwargs):
    # Send confirmation email, provision badge, etc.
    ...
```

Fired when an order transitions to `PAID`, whether from a Stripe webhook, a comp payment, a manual payment, or a credit application that covers the full balance. Sender is the `Order` class.

## Refunds

{class}`~django_program.registration.services.refund.RefundService` handles refund creation and credit-as-payment application.

### Creating a Refund

```python
from django_program.registration.services.refund import RefundService

credit = RefundService.create_refund(
    order,
    amount=Decimal("50.00"),
    reason="requested_by_customer",
    staff_user=request.user,
)
```

`create_refund()`:

1. Validates the order is `PAID` or `PARTIALLY_REFUNDED`.
2. Calculates the refundable balance: `total_paid_via_stripe - total_already_refunded`.
3. Calls `StripeClient.create_refund()` against the Stripe API (with idempotency key).
4. Creates a {class}`~django_program.registration.models.Credit` with status `AVAILABLE` and a note documenting the refund.
5. Updates the order status: `REFUNDED` if the cumulative refund covers the full total, `PARTIALLY_REFUNDED` otherwise.

The `reason` parameter is passed directly to Stripe. Valid values: `"requested_by_customer"`, `"duplicate"`, `"fraudulent"`.

### Applying Credits to New Orders

```python
payment = RefundService.apply_credit_as_refund(credit, new_order)
```

Takes an available credit and applies it as payment toward a pending order. Deducts from `credit.remaining_amount`, creates a `CREDIT` payment. If the order is fully paid, transitions it to `PAID` and fires `order_paid`.

Credits are scoped to a user and conference -- you cannot apply a credit from one conference to an order for a different conference.

## Concurrency

The registration system is built for concurrent access. Key patterns:

- **`SELECT FOR UPDATE`** on cart items during `add_ticket` and `add_addon` to prevent double-counting.
- **Unique constraints** on (cart, ticket_type) and (cart, addon) prevent duplicate rows from concurrent inserts. The upsert pattern catches `IntegrityError` and falls back to lock-and-increment.
- **`SELECT FOR UPDATE`** on the cart during checkout, and on the order during payment/refund operations.
- **Idempotency keys** on all Stripe API calls (customer creation, payment intent, refund) so retried requests are safe.
- **Webhook deduplication** via `StripeEvent.stripe_id` unique constraint. Duplicate events are acknowledged with HTTP 200 and skipped.

## State Diagram

```
Cart:   OPEN ──checkout──> CHECKED_OUT
         │
         └──expiry──> EXPIRED
         └──abandon──> ABANDONED

Order:  PENDING ──payment──> PAID ──refund──> PARTIALLY_REFUNDED ──full refund──> REFUNDED
           │                                         │
           │                                         └──refund──> REFUNDED
           └──cancel/expire──> CANCELLED

Payment: PENDING ──success──> SUCCEEDED ──refund──> REFUNDED
            │
            └──failure──> FAILED

Credit:  AVAILABLE ──apply──> APPLIED
            │
            └──expire──> EXPIRED
```
