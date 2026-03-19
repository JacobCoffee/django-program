"""Staff-facing JSON API views for Stripe Terminal point-of-sale operations.

These views power the on-site POS UI used by registration desk staff.
All endpoints require staff or superuser authentication and are scoped
to a conference via the ``conference_slug`` URL kwarg.
"""

import json
import logging
import secrets
import string
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING

import stripe
from django.db import models, transaction
from django.http import JsonResponse
from django.utils import timezone
from django.views import View

from django_program.registration.attendee import Attendee
from django_program.registration.models import (
    AddOn,
    Cart,
    CartItem,
    Credit,
    Order,
    OrderLineItem,
    Payment,
    TicketType,
)
from django_program.registration.services.checkin import CheckInService
from django_program.registration.stripe_client import StripeClient
from django_program.registration.terminal import TerminalPayment
from django_program.registration.views_checkin import StaffRequiredMixin
from django_program.settings import get_config

if TYPE_CHECKING:
    from django.http import HttpRequest

logger = logging.getLogger(__name__)


def _parse_json_body(request: HttpRequest) -> dict[str, object] | None:
    """Parse JSON from request body, returning None on failure."""
    try:
        return json.loads(request.body)  # type: ignore[no-any-return]
    except json.JSONDecodeError, ValueError:
        return None


def _generate_order_reference() -> str:
    """Generate a unique order reference like ``ORD-A1B2C3``."""
    chars = string.ascii_uppercase + string.digits
    suffix = "".join(secrets.choice(chars) for _ in range(6))
    return f"ORD-{suffix}"


def _stripe_error_response(exc: stripe.StripeError) -> JsonResponse:
    """Build a consistent JSON error response from a Stripe exception."""
    logger.warning("Stripe error: %s", exc)
    return JsonResponse(
        {"error": "Payment processing error. Please try again."},
        status=502,
    )


class ConnectionTokenView(StaffRequiredMixin, View):
    """Create a Stripe Terminal connection token for the JS SDK.

    The frontend calls this endpoint to initialize the Stripe Terminal
    SDK with a short-lived connection token scoped to the conference's
    Stripe account.
    """

    def post(self, request: HttpRequest, **kwargs: str) -> JsonResponse:  # noqa: ARG002
        """Return a new connection token secret.

        Args:
            request: The incoming HTTP request.
            **kwargs: URL keyword arguments (unused).

        Returns:
            JSON with ``secret`` on success, or an error payload.
        """
        try:
            client = StripeClient(self.conference)
            secret = client.create_connection_token()
        except ValueError as exc:
            return JsonResponse({"error": str(exc)}, status=400)
        except stripe.StripeError as exc:
            return _stripe_error_response(exc)

        return JsonResponse({"secret": secret})


class CreatePaymentIntentView(StaffRequiredMixin, View):
    """Create a PaymentIntent and send it to a Stripe Terminal reader.

    Supports two modes:
    - Order-linked: provide ``order_id`` to pay for an existing order.
    - Walk-up sale: provide ``amount`` directly for ad-hoc charges.

    Both modes require a ``reader_id`` to dispatch the payment to a
    physical reader.
    """

    def post(self, request: HttpRequest, **kwargs: str) -> JsonResponse:  # noqa: ARG002
        """Create a terminal PaymentIntent and dispatch to a reader.

        Args:
            request: The incoming HTTP request with JSON body.
            **kwargs: URL keyword arguments (unused).

        Returns:
            JSON with intent details and reader action on success.
        """
        body = _parse_json_body(request)
        if body is None:
            return JsonResponse({"error": "Invalid JSON body"}, status=400)

        reader_id = str(body.get("reader_id", "")).strip()
        if not reader_id:
            return JsonResponse({"error": "reader_id is required"}, status=400)

        result = self._resolve_order_and_amount(body)
        if isinstance(result, JsonResponse):
            return result
        order, amount = result

        return self._create_and_dispatch(request, reader_id, order, amount)

    def _resolve_order_and_amount(self, body: dict[str, object]) -> tuple[Order | None, Decimal] | JsonResponse:
        """Resolve the order and amount from the request body."""
        order_id = body.get("order_id")
        raw_amount = body.get("amount")

        if not order_id and not raw_amount:
            return JsonResponse({"error": "Either order_id or amount is required"}, status=400)

        if order_id:
            try:
                order = Order.objects.get(pk=int(order_id), conference=self.conference)  # type: ignore[arg-type]
            except Order.DoesNotExist, TypeError, ValueError:
                return JsonResponse({"error": "Order not found"}, status=404)
            return order, order.total

        try:
            amount = Decimal(str(raw_amount))
            if amount <= 0:
                return JsonResponse({"error": "Amount must be positive"}, status=400)
        except InvalidOperation, TypeError:
            return JsonResponse({"error": "Invalid amount"}, status=400)
        return None, amount

    def _create_and_dispatch(
        self,
        request: HttpRequest,
        reader_id: str,
        order: Order | None,
        amount: Decimal,
    ) -> JsonResponse:
        """Create PaymentIntent, dispatch to reader, and record in DB."""
        try:
            client = StripeClient(self.conference)
        except ValueError as exc:
            return JsonResponse({"error": str(exc)}, status=400)

        config = get_config()
        currency = config.currency

        metadata: dict[str, str] = {
            "conference_id": str(self.conference.pk),
            "conference_slug": str(self.conference.slug),
            "terminal": "true",
            "staff_user_id": str(request.user.pk),
        }
        description = f"Terminal payment for {self.conference.name}"
        if order is not None:
            metadata["order_id"] = str(order.pk)
            metadata["reference"] = str(order.reference)
            description = f"Order {order.reference} (terminal) for {self.conference.name}"

        try:
            intent = client.create_terminal_payment_intent(
                amount=amount,
                currency=currency.lower(),
                metadata=metadata,
                description=description,
            )
            reader_result = client.process_terminal_payment(
                reader_id=reader_id,
                payment_intent_id=intent.id,
            )
        except stripe.StripeError as exc:
            return _stripe_error_response(exc)

        with transaction.atomic():
            if order is None:
                order = Order.objects.create(
                    conference=self.conference,
                    user=request.user,
                    status=Order.Status.PENDING,
                    subtotal=amount,
                    total=amount,
                    billing_name=str(getattr(request.user, "get_full_name", lambda: "")()),
                    billing_email=str(getattr(request.user, "email", "")),
                    reference=_generate_order_reference(),
                )

            payment = Payment.objects.create(
                order=order,
                method=Payment.Method.TERMINAL,
                status=Payment.Status.PENDING,
                amount=amount,
                stripe_payment_intent_id=intent.id,
                created_by=request.user,
            )

            TerminalPayment.objects.create(
                payment=payment,
                conference=self.conference,
                reader_id=reader_id,
                payment_intent_id=intent.id,
                capture_status=TerminalPayment.CaptureStatus.AUTHORIZED,
            )

        reader_action = {}
        if hasattr(reader_result, "action") and reader_result.action:
            action = reader_result.action
            reader_action = {
                "status": getattr(action, "status", None),
                "type": getattr(action, "type", None),
            }

        return JsonResponse(
            {
                "payment_intent_id": intent.id,
                "status": "processing",
                "order_id": order.pk,
                "order_reference": str(order.reference),
                "client_secret": intent.client_secret,
                "reader_action": reader_action,
            }
        )


class CapturePaymentView(StaffRequiredMixin, View):
    """Capture a previously authorized terminal PaymentIntent.

    After the cardholder taps/inserts their card and the payment is
    authorized, this endpoint captures the funds and marks the order
    as paid.
    """

    def post(self, request: HttpRequest, **kwargs: str) -> JsonResponse:  # noqa: ARG002
        """Capture the authorized PaymentIntent.

        Args:
            request: The incoming HTTP request with JSON body.
            **kwargs: URL keyword arguments (unused).

        Returns:
            JSON with capture status on success.
        """
        body = _parse_json_body(request)
        if body is None:
            return JsonResponse({"error": "Invalid JSON body"}, status=400)

        payment_intent_id = str(body.get("payment_intent_id", "")).strip()
        if not payment_intent_id:
            return JsonResponse({"error": "payment_intent_id is required"}, status=400)

        try:
            terminal_payment = TerminalPayment.objects.select_related(
                "payment__order",
            ).get(payment_intent_id=payment_intent_id, conference=self.conference)
        except TerminalPayment.DoesNotExist:
            return JsonResponse({"error": "Terminal payment not found"}, status=404)

        try:
            client = StripeClient(self.conference)
            client.capture_payment_intent(payment_intent_id)
        except ValueError as exc:
            return JsonResponse({"error": str(exc)}, status=400)
        except stripe.StripeError as exc:
            return _stripe_error_response(exc)

        now = timezone.now()
        with transaction.atomic():
            terminal_payment.capture_status = TerminalPayment.CaptureStatus.CAPTURED
            terminal_payment.captured_at = now
            terminal_payment.save(update_fields=["capture_status", "captured_at", "updated_at"])

            payment = terminal_payment.payment
            payment.status = Payment.Status.SUCCEEDED
            payment.save(update_fields=["status"])

            order = payment.order
            if order.status == Order.Status.PENDING:
                order.status = Order.Status.PAID
                order.save(update_fields=["status", "updated_at"])

        return JsonResponse(
            {
                "status": "captured",
                "payment_intent_id": payment_intent_id,
                "order_id": order.pk,
                "order_reference": str(order.reference),
            }
        )


class CancelPaymentView(StaffRequiredMixin, View):
    """Cancel a terminal payment in progress.

    Cancels the reader action and the PaymentIntent, then marks the
    local records as failed/cancelled.
    """

    def post(self, request: HttpRequest, **kwargs: str) -> JsonResponse:  # noqa: ARG002
        """Cancel the terminal payment and reader action.

        Args:
            request: The incoming HTTP request with JSON body.
            **kwargs: URL keyword arguments (unused).

        Returns:
            JSON with cancellation status on success.
        """
        body = _parse_json_body(request)
        if body is None:
            return JsonResponse({"error": "Invalid JSON body"}, status=400)

        payment_intent_id = str(body.get("payment_intent_id", "")).strip()
        reader_id = str(body.get("reader_id", "")).strip()

        if not payment_intent_id:
            return JsonResponse({"error": "payment_intent_id is required"}, status=400)

        try:
            terminal_payment = TerminalPayment.objects.select_related(
                "payment__order",
            ).get(payment_intent_id=payment_intent_id, conference=self.conference)
        except TerminalPayment.DoesNotExist:
            return JsonResponse({"error": "Terminal payment not found"}, status=404)

        try:
            client = StripeClient(self.conference)
        except ValueError as exc:
            return JsonResponse({"error": str(exc)}, status=400)

        try:
            if reader_id:
                client.cancel_reader_action(reader_id)
            client.client.v1.payment_intents.cancel(payment_intent_id)
        except stripe.StripeError as exc:
            return _stripe_error_response(exc)

        now = timezone.now()
        with transaction.atomic():
            terminal_payment.capture_status = TerminalPayment.CaptureStatus.CANCELLED
            terminal_payment.cancelled_at = now
            terminal_payment.save(update_fields=["capture_status", "cancelled_at", "updated_at"])

            payment = terminal_payment.payment
            payment.status = Payment.Status.FAILED
            payment.save(update_fields=["status"])

        return JsonResponse(
            {
                "status": "cancelled",
                "payment_intent_id": payment_intent_id,
            }
        )


class FetchAttendeeView(StaffRequiredMixin, View):
    """Look up an attendee by access code for the POS terminal.

    Returns attendee info, order status, and available store credits
    so the registration desk can identify walk-up attendees and apply
    credits to new purchases.
    """

    def get(self, request: HttpRequest, access_code: str, **kwargs: str) -> JsonResponse:  # noqa: ARG002
        """Return attendee details by access code.

        Args:
            request: The incoming HTTP request.
            access_code: The attendee's unique access code from the URL.
            **kwargs: URL keyword arguments (unused).

        Returns:
            JSON with attendee info, order status, and available credits.
        """
        try:
            attendee = CheckInService.lookup_attendee(
                conference=self.conference,
                access_code=access_code.strip(),
            )
        except Attendee.DoesNotExist:
            return JsonResponse(
                {"error": "Attendee not found", "access_code": access_code},
                status=404,
            )

        order = attendee.order
        order_data: dict[str, object] | None = None
        if order is not None:
            line_items = [
                {
                    "id": item.pk,
                    "description": str(item.description),
                    "quantity": item.quantity,
                    "unit_price": str(item.unit_price),
                    "line_total": str(item.line_total),
                    "ticket_type_slug": str(item.ticket_type.slug) if item.ticket_type else None,
                    "addon_slug": str(item.addon.slug) if item.addon else None,
                }
                for item in order.line_items.all()
            ]
            order_data = {
                "id": order.pk,
                "reference": str(order.reference),
                "status": str(order.status),
                "total": str(order.total),
                "line_items": line_items,
            }

        available_credits = Credit.objects.filter(
            user=attendee.user,
            conference=self.conference,
            status=Credit.Status.AVAILABLE,
        )
        credits_total = sum(c.remaining_amount for c in available_credits)
        credits_data = [
            {
                "id": c.pk,
                "amount": str(c.amount),
                "remaining_amount": str(c.remaining_amount),
            }
            for c in available_credits
        ]

        return JsonResponse(
            {
                "attendee": {
                    "id": attendee.pk,
                    "access_code": str(attendee.access_code),
                    "name": str(getattr(attendee.user, "get_full_name", lambda: "")()),
                    "email": str(getattr(attendee.user, "email", "")),
                    "checked_in": attendee.checked_in_at is not None,
                    "checked_in_at": (attendee.checked_in_at.isoformat() if attendee.checked_in_at else None),
                },
                "order": order_data,
                "credits": credits_data,
                "credits_total": str(credits_total),
                "registered": order is not None
                and order.status
                in {
                    Order.Status.PAID,
                    Order.Status.PARTIALLY_REFUNDED,
                },
            }
        )


class FetchInventoryView(StaffRequiredMixin, View):
    """Return available ticket types and add-ons for the conference.

    Filters to active items currently within their availability window
    and includes remaining quantity information for the POS display.
    """

    def get(self, request: HttpRequest, **kwargs: str) -> JsonResponse:  # noqa: ARG002
        """Return the conference inventory.

        Args:
            request: The incoming HTTP request.
            **kwargs: URL keyword arguments (unused).

        Returns:
            JSON with ticket_types and addons arrays.
        """
        now = timezone.now()

        ticket_types = (
            TicketType.objects.filter(
                conference=self.conference,
                is_active=True,
            )
            .filter(
                models.Q(available_from__isnull=True) | models.Q(available_from__lte=now),
            )
            .filter(
                models.Q(available_until__isnull=True) | models.Q(available_until__gte=now),
            )
        )

        addons = (
            AddOn.objects.filter(
                conference=self.conference,
                is_active=True,
            )
            .filter(
                models.Q(available_from__isnull=True) | models.Q(available_from__lte=now),
            )
            .filter(
                models.Q(available_until__isnull=True) | models.Q(available_until__gte=now),
            )
        )

        return JsonResponse(
            {
                "ticket_types": [
                    {
                        "id": tt.pk,
                        "name": str(tt.name),
                        "slug": str(tt.slug),
                        "description": str(tt.description),
                        "price": str(tt.price),
                        "remaining_quantity": tt.remaining_quantity,
                        "requires_voucher": tt.requires_voucher,
                    }
                    for tt in ticket_types
                ],
                "addons": [
                    {
                        "id": addon.pk,
                        "name": str(addon.name),
                        "slug": str(addon.slug),
                        "description": str(addon.description),
                        "price": str(addon.price),
                    }
                    for addon in addons
                ],
            }
        )


class CartOperationsView(StaffRequiredMixin, View):
    """Handle cart operations for the terminal POS.

    Supports two actions via JSON body:
    - ``update``: create or update cart items for an attendee.
    - ``checkout``: convert the cart into an order.
    """

    def post(self, request: HttpRequest, **kwargs: str) -> JsonResponse:  # noqa: ARG002
        """Dispatch cart action (update or checkout).

        Args:
            request: The incoming HTTP request with JSON body.
            **kwargs: URL keyword arguments (unused).

        Returns:
            JSON with cart or order details on success.
        """
        body = _parse_json_body(request)
        if body is None:
            return JsonResponse({"error": "Invalid JSON body"}, status=400)

        action = str(body.get("action", "")).strip()
        if action not in {"update", "checkout"}:
            return JsonResponse({"error": "action must be 'update' or 'checkout'"}, status=400)

        if action == "update":
            return self._handle_update(request, body)
        return self._handle_checkout(request, body)

    def _handle_update(self, request: HttpRequest, body: dict[str, object]) -> JsonResponse:
        """Create or update cart items for an attendee."""
        access_code = str(body.get("attendee_access_code", "")).strip()
        items = body.get("items", [])

        if not isinstance(items, list):
            return JsonResponse({"error": "items must be a list"}, status=400)

        attendee: Attendee | None = None
        if access_code:
            try:
                attendee = CheckInService.lookup_attendee(
                    conference=self.conference,
                    access_code=access_code,
                )
            except Attendee.DoesNotExist:
                return JsonResponse(
                    {"error": "Attendee not found", "access_code": access_code},
                    status=404,
                )

        cart_user = attendee.user if attendee else request.user

        with transaction.atomic():
            cart, _created = Cart.objects.get_or_create(
                user=cart_user,
                conference=self.conference,
                status=Cart.Status.OPEN,
            )

            cart.items.all().delete()

            cart_total = Decimal("0.00")
            cart_items: list[dict[str, object]] = []
            for item_data in items:
                result = self._add_cart_item(cart, item_data)
                if isinstance(result, JsonResponse):
                    return result
                if result is not None:
                    cart_total += Decimal(str(result["line_total"]))
                    cart_items.append(result)

        return JsonResponse(
            {
                "cart_id": cart.pk,
                "items": cart_items,
                "total": str(cart_total),
            }
        )

    def _add_cart_item(
        self, cart: Cart, item_data: object
    ) -> dict[str, object] | JsonResponse | None:
        """Process a single cart item from the request payload."""
        if not isinstance(item_data, dict):
            return None
        ticket_type_id = item_data.get("ticket_type_id")
        addon_id = item_data.get("addon_id")
        try:
            quantity = int(item_data.get("quantity", 1))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return JsonResponse({"error": "Invalid quantity value"}, status=400)

        if ticket_type_id:
            return self._add_ticket_item(cart, ticket_type_id, quantity)
        if addon_id:
            return self._add_addon_item(cart, addon_id, quantity)
        return None

    def _add_ticket_item(
        self, cart: Cart, ticket_type_id: object, quantity: int
    ) -> dict[str, object] | None:
        """Create a ticket CartItem and return its data."""
        try:
            tt = TicketType.objects.get(pk=int(ticket_type_id), conference=self.conference)  # type: ignore[arg-type]
        except (TicketType.DoesNotExist, TypeError, ValueError):
            return None
        ci = CartItem.objects.create(cart=cart, ticket_type=tt, quantity=quantity)
        line_total = tt.price * quantity
        return {
            "id": ci.pk, "ticket_type_id": tt.pk, "name": str(tt.name),
            "quantity": quantity, "unit_price": str(tt.price), "line_total": str(line_total),
        }

    def _add_addon_item(
        self, cart: Cart, addon_id: object, quantity: int
    ) -> dict[str, object] | None:
        """Create an addon CartItem and return its data."""
        try:
            addon = AddOn.objects.get(pk=int(addon_id), conference=self.conference)  # type: ignore[arg-type]
        except (AddOn.DoesNotExist, TypeError, ValueError):
            return None
        ci = CartItem.objects.create(cart=cart, addon=addon, quantity=quantity)
        line_total = addon.price * quantity
        return {
            "id": ci.pk, "addon_id": addon.pk, "name": str(addon.name),
            "quantity": quantity, "unit_price": str(addon.price), "line_total": str(line_total),
        }

    def _handle_checkout(self, request: HttpRequest, body: dict[str, object]) -> JsonResponse:
        """Convert the cart into a pending order."""
        access_code = str(body.get("attendee_access_code", "")).strip()
        billing_name = str(body.get("billing_name", "")).strip()
        billing_email = str(body.get("billing_email", "")).strip()

        attendee: Attendee | None = None
        if access_code:
            try:
                attendee = CheckInService.lookup_attendee(
                    conference=self.conference,
                    access_code=access_code,
                )
            except Attendee.DoesNotExist:
                return JsonResponse(
                    {"error": "Attendee not found", "access_code": access_code},
                    status=404,
                )

        cart_user = attendee.user if attendee else request.user

        try:
            cart = Cart.objects.prefetch_related(
                "items__ticket_type",
                "items__addon",
            ).get(
                user=cart_user,
                conference=self.conference,
                status=Cart.Status.OPEN,
            )
        except Cart.DoesNotExist:
            return JsonResponse({"error": "No open cart found"}, status=404)

        cart_items = list(cart.items.all())
        if not cart_items:
            return JsonResponse({"error": "Cart is empty"}, status=400)

        with transaction.atomic():
            subtotal = sum(item.line_total for item in cart_items)
            order = Order.objects.create(
                conference=self.conference,
                user=cart_user,
                status=Order.Status.PENDING,
                subtotal=subtotal,
                total=subtotal,
                billing_name=billing_name or str(getattr(cart_user, "get_full_name", lambda: "")()),
                billing_email=billing_email or str(getattr(cart_user, "email", "")),
                reference=_generate_order_reference(),
            )

            for item in cart_items:
                description = str(item.ticket_type.name if item.ticket_type else item.addon.name if item.addon else "")
                OrderLineItem.objects.create(
                    order=order,
                    description=description,
                    quantity=item.quantity,
                    unit_price=item.unit_price,
                    line_total=item.line_total,
                    ticket_type=item.ticket_type,
                    addon=item.addon,
                )

            cart.status = Cart.Status.CHECKED_OUT
            cart.save(update_fields=["status", "updated_at"])

        line_items = [
            {
                "id": li.pk,
                "description": str(li.description),
                "quantity": li.quantity,
                "unit_price": str(li.unit_price),
                "line_total": str(li.line_total),
            }
            for li in order.line_items.all()
        ]

        return JsonResponse(
            {
                "order_id": order.pk,
                "reference": str(order.reference),
                "status": str(order.status),
                "total": str(order.total),
                "line_items": line_items,
            }
        )


class ListReadersView(StaffRequiredMixin, View):
    """List available Stripe Terminal readers for the conference.

    Optionally filtered by Stripe location ID via the ``location``
    query parameter.
    """

    def get(self, request: HttpRequest, **kwargs: str) -> JsonResponse:  # noqa: ARG002
        """Return the list of terminal readers.

        Args:
            request: The incoming HTTP request.
            **kwargs: URL keyword arguments (unused).

        Returns:
            JSON with a ``readers`` array.
        """
        location = request.GET.get("location", "").strip() or None

        try:
            client = StripeClient(self.conference)
            readers = client.list_readers(location=location)
        except ValueError as exc:
            return JsonResponse({"error": str(exc)}, status=400)
        except stripe.StripeError as exc:
            return _stripe_error_response(exc)

        return JsonResponse(
            {
                "readers": [
                    {
                        "id": getattr(r, "id", None),
                        "label": getattr(r, "label", ""),
                        "status": getattr(r, "status", ""),
                        "device_type": getattr(r, "device_type", ""),
                        "location": getattr(r, "location", None),
                        "serial_number": getattr(r, "serial_number", ""),
                    }
                    for r in readers
                ],
            }
        )
