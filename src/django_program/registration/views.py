"""Views for the registration app.

Provides ticket selection, cart management, checkout, and order views
scoped to a conference via the ``conference_slug`` URL kwarg.
"""

import logging
import secrets
import string
from datetime import timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models.functions import Coalesce
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views import View
from django.views.generic import DetailView, ListView

from django_program.features import FeatureRequiredMixin
from django_program.pretalx.views import ConferenceMixin
from django_program.registration.forms import CartItemForm, CheckoutForm, VoucherApplyForm
from django_program.registration.models import (
    AddOn,
    Cart,
    CartItem,
    Order,
    OrderLineItem,
    TicketType,
    Voucher,
)

if TYPE_CHECKING:
    from django.db.models import QuerySet
    from django.http import HttpRequest, HttpResponse

logger = logging.getLogger(__name__)


def _generate_order_reference() -> str:
    """Generate a unique order reference like ``ORD-A1B2C3``.

    Returns:
        A string in the format ``ORD-`` followed by 6 random uppercase
        alphanumeric characters.
    """
    alphabet = string.ascii_uppercase + string.digits
    chars = [secrets.choice(alphabet) for _ in range(6)]
    return f"ORD-{''.join(chars)}"


def _calculate_discount(subtotal: Decimal, voucher: Voucher | None) -> Decimal:
    """Calculate the discount amount for a cart based on the applied voucher.

    Args:
        subtotal: The cart subtotal before discount.
        voucher: The voucher applied to the cart, or ``None``.

    Returns:
        The discount amount, clamped to the subtotal so it never exceeds it.
    """
    if voucher is None:
        return Decimal("0.00")

    if voucher.voucher_type == Voucher.VoucherType.COMP:
        return subtotal

    if voucher.voucher_type == Voucher.VoucherType.PERCENTAGE:
        discount = subtotal * voucher.discount_value / Decimal(100)
        return min(discount, subtotal)

    if voucher.voucher_type == Voucher.VoucherType.FIXED_AMOUNT:
        return min(voucher.discount_value, subtotal)

    return Decimal("0.00")


def _cart_totals(cart: Cart) -> tuple[Decimal, Decimal, Decimal]:
    """Compute subtotal, discount, and total for a cart.

    Args:
        cart: The cart to calculate totals for.

    Returns:
        A tuple of ``(subtotal, discount, total)`` where total is never
        less than zero.
    """
    items = cart.items.select_related("ticket_type", "addon")
    subtotal = sum((item.line_total for item in items), Decimal("0.00"))
    discount = _calculate_discount(subtotal, cart.voucher)
    total = max(subtotal - discount, Decimal("0.00"))
    return subtotal, discount, total


class TicketSelectView(ConferenceMixin, FeatureRequiredMixin, ListView):
    """Lists available ticket types for a conference.

    Shows ticket types that are active and do not require a voucher,
    ordered by display order and name.
    """

    required_feature = ("registration", "public_ui")
    template_name = "django_program/registration/ticket_select.html"
    context_object_name = "ticket_types"

    def get_queryset(self) -> QuerySet[TicketType]:
        """Return available public ticket types for the current conference.

        Returns:
            A queryset of active, non-voucher-required TicketType instances.
        """
        return TicketType.objects.filter(
            conference=self.conference,
            is_active=True,
            requires_voucher=False,
        ).order_by("order", "name")

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        """Add current timestamp for availability display logic."""
        context = super().get_context_data(**kwargs)
        context["now"] = timezone.now()
        return context


class CartView(LoginRequiredMixin, ConferenceMixin, FeatureRequiredMixin, View):
    """Shopping cart view for adding/removing items and applying vouchers.

    Handles multiple POST actions distinguished by a hidden ``action``
    field: ``add_item``, ``remove_item``, and ``apply_voucher``.
    """

    required_feature = ("registration", "public_ui")
    template_name = "django_program/registration/cart.html"

    def _get_or_create_cart(self, request: HttpRequest) -> Cart:
        """Get or create an open cart for the current user and conference.

        Args:
            request: The incoming HTTP request.

        Returns:
            The user's open Cart for this conference.
        """
        cart, _created = Cart.objects.get_or_create(
            user=request.user,
            conference=self.conference,
            status=Cart.Status.OPEN,
        )
        return cart

    def _build_context(self, cart: Cart) -> dict[str, object]:
        """Build template context with cart data and available tickets/add-ons.

        Args:
            cart: The user's cart.

        Returns:
            Context dict with cart, items, available tickets/addons,
            voucher form, and totals.
        """
        items = cart.items.select_related("ticket_type", "addon")
        now = timezone.now()
        sold_filter = models.Q(
            order_line_items__order__status__in=[Order.Status.PAID, Order.Status.PARTIALLY_REFUNDED]
        ) | models.Q(
            order_line_items__order__status=Order.Status.PENDING,
            order_line_items__order__hold_expires_at__gt=now,
        )
        available_tickets = (
            TicketType.objects.filter(
                conference=self.conference,
                is_active=True,
                requires_voucher=False,
            )
            .filter(
                models.Q(available_from__isnull=True) | models.Q(available_from__lte=now),
            )
            .filter(
                models.Q(available_until__isnull=True) | models.Q(available_until__gte=now),
            )
            .annotate(
                sold_quantity=Coalesce(models.Sum("order_line_items__quantity", filter=sold_filter), 0),
            )
            .filter(
                models.Q(total_quantity=0) | models.Q(total_quantity__gt=models.F("sold_quantity")),
            )
            .order_by("order", "name")
        )
        available_addons = AddOn.objects.filter(
            conference=self.conference,
            is_active=True,
        ).order_by("order", "name")
        subtotal, discount, total = _cart_totals(cart)
        return {
            "conference": self.conference,
            "cart": cart,
            "items": items,
            "available_tickets": list(available_tickets),
            "available_addons": available_addons,
            "voucher_form": VoucherApplyForm(),
            "subtotal": subtotal,
            "discount": discount,
            "total": total,
        }

    def get(self, request: HttpRequest, **kwargs: str) -> HttpResponse:  # noqa: ARG002
        """Render the cart page with current items and totals.

        Handles an optional ``add_ticket`` query parameter to add a ticket
        by slug directly from the ticket selection page.

        Args:
            request: The incoming HTTP request.
            **kwargs: URL keyword arguments (unused).

        Returns:
            The rendered cart page (or redirect after adding a ticket).
        """
        cart = self._get_or_create_cart(request)

        add_slug = request.GET.get("add_ticket")
        if add_slug:
            ticket_type = TicketType.objects.filter(
                conference=self.conference,
                slug=add_slug,
                is_active=True,
            ).first()
            if ticket_type and ticket_type.is_available:
                item, created = CartItem.objects.get_or_create(
                    cart=cart,
                    ticket_type=ticket_type,
                    defaults={"quantity": 1},
                )
                if not created:
                    item.quantity += 1
                    item.save(update_fields=["quantity"])
                messages.success(request, f"Added {ticket_type.name} to your cart.")
            elif ticket_type:
                messages.error(request, "This ticket type is no longer available.")
            else:
                messages.error(request, "Ticket type not found.")
            return redirect(reverse("registration:cart", args=[self.conference.slug]))

        return render(request, self.template_name, self._build_context(cart))

    def post(self, request: HttpRequest, **kwargs: str) -> HttpResponse:  # noqa: ARG002
        """Handle cart actions dispatched by the ``action`` hidden field.

        Supported actions: ``add_item``, ``add_ticket``, ``add_addon``,
        ``remove_item``, ``apply_voucher``, ``remove_voucher``.

        Args:
            request: The incoming HTTP request.
            **kwargs: URL keyword arguments (unused).

        Returns:
            A redirect back to the cart page on success, or the cart page
            with errors on validation failure.
        """
        cart = self._get_or_create_cart(request)
        action = request.POST.get("action", "")
        handlers = {
            "add_item": self._handle_add_item,
            "add_ticket": self._handle_add_ticket,
            "add_addon": self._handle_add_addon,
            "remove_item": self._handle_remove_item,
            "apply_voucher": self._handle_apply_voucher,
            "remove_voucher": self._handle_remove_voucher,
        }
        handler = handlers.get(action)
        if handler:
            return handler(request, cart)

        messages.error(request, "Unknown cart action.")
        return redirect(reverse("registration:cart", args=[self.conference.slug]))

    def _handle_add_item(self, request: HttpRequest, cart: Cart) -> HttpResponse:
        """Validate and add a cart item.

        Args:
            request: The incoming HTTP request.
            cart: The user's open cart.

        Returns:
            A redirect to the cart page.
        """
        form = CartItemForm(request.POST)
        if not form.is_valid():
            messages.error(request, "Invalid item data.")
            return redirect(reverse("registration:cart", args=[self.conference.slug]))

        ticket_type_id = form.cleaned_data.get("ticket_type_id")
        addon_id = form.cleaned_data.get("addon_id")
        quantity = form.cleaned_data["quantity"]

        if ticket_type_id is not None:
            ticket_type = get_object_or_404(
                TicketType,
                pk=ticket_type_id,
                conference=self.conference,
                is_active=True,
            )
            if not ticket_type.is_available:
                messages.error(request, "This ticket type is no longer available.")
                return redirect(reverse("registration:cart", args=[self.conference.slug]))

            item, created = CartItem.objects.get_or_create(
                cart=cart,
                ticket_type=ticket_type,
                defaults={"quantity": quantity},
            )
            if not created:
                item.quantity += quantity
                item.save(update_fields=["quantity"])
            messages.success(request, f"Added {ticket_type.name} to your cart.")

        elif addon_id is not None:
            addon = get_object_or_404(
                AddOn,
                pk=addon_id,
                conference=self.conference,
                is_active=True,
            )
            item, created = CartItem.objects.get_or_create(
                cart=cart,
                addon=addon,
                defaults={"quantity": quantity},
            )
            if not created:
                item.quantity += quantity
                item.save(update_fields=["quantity"])
            messages.success(request, f"Added {addon.name} to your cart.")

        return redirect(reverse("registration:cart", args=[self.conference.slug]))

    def _handle_add_ticket(self, request: HttpRequest, cart: Cart) -> HttpResponse:
        """Add a ticket to the cart by slug (from the cart page dropdown).

        Args:
            request: The incoming HTTP request.
            cart: The user's open cart.

        Returns:
            A redirect to the cart page.
        """
        slug = request.POST.get("ticket_type", "")
        raw_quantity = request.POST.get("quantity", 1)
        try:
            quantity = int(raw_quantity or 1)
        except TypeError, ValueError:
            messages.error(request, "Quantity must be a number.")
            return redirect(reverse("registration:cart", args=[self.conference.slug]))
        if quantity < 1:
            messages.error(request, "Quantity must be at least 1.")
            return redirect(reverse("registration:cart", args=[self.conference.slug]))

        ticket_type = TicketType.objects.filter(
            conference=self.conference,
            slug=slug,
            is_active=True,
        ).first()

        if not ticket_type:
            messages.error(request, "Ticket type not found.")
            return redirect(reverse("registration:cart", args=[self.conference.slug]))

        if not ticket_type.is_available:
            messages.error(request, "This ticket type is no longer available.")
            return redirect(reverse("registration:cart", args=[self.conference.slug]))

        item, created = CartItem.objects.get_or_create(
            cart=cart,
            ticket_type=ticket_type,
            defaults={"quantity": quantity},
        )
        if not created:
            item.quantity += quantity
            item.save(update_fields=["quantity"])
        messages.success(request, f"Added {ticket_type.name} to your cart.")
        return redirect(reverse("registration:cart", args=[self.conference.slug]))

    def _handle_add_addon(self, request: HttpRequest, cart: Cart) -> HttpResponse:
        """Add an add-on to the cart by slug (from the cart page).

        Args:
            request: The incoming HTTP request.
            cart: The user's open cart.

        Returns:
            A redirect to the cart page.
        """
        slug = request.POST.get("addon_slug", "")
        addon = AddOn.objects.filter(
            conference=self.conference,
            slug=slug,
            is_active=True,
        ).first()

        if not addon:
            messages.error(request, "Add-on not found.")
            return redirect(reverse("registration:cart", args=[self.conference.slug]))

        item, created = CartItem.objects.get_or_create(
            cart=cart,
            addon=addon,
            defaults={"quantity": 1},
        )
        if not created:
            item.quantity += 1
            item.save(update_fields=["quantity"])
        messages.success(request, f"Added {addon.name} to your cart.")
        return redirect(reverse("registration:cart", args=[self.conference.slug]))

    def _handle_remove_item(self, request: HttpRequest, cart: Cart) -> HttpResponse:
        """Remove a cart item by its ID.

        Args:
            request: The incoming HTTP request.
            cart: The user's open cart.

        Returns:
            A redirect to the cart page.
        """
        item_id = request.POST.get("item_id")
        if item_id:
            deleted_count, _ = CartItem.objects.filter(pk=item_id, cart=cart).delete()
            if deleted_count:
                messages.success(request, "Item removed from your cart.")
            else:
                messages.error(request, "Item not found in your cart.")
        return redirect(reverse("registration:cart", args=[self.conference.slug]))

    def _handle_apply_voucher(self, request: HttpRequest, cart: Cart) -> HttpResponse:
        """Validate and apply a voucher code to the cart.

        Args:
            request: The incoming HTTP request.
            cart: The user's open cart.

        Returns:
            A redirect to the cart page.
        """
        code = request.POST.get("voucher_code", "").strip() or request.POST.get("code", "").strip()
        if not code:
            messages.error(request, "Please enter a voucher code.")
            return redirect(reverse("registration:cart", args=[self.conference.slug]))

        try:
            voucher = Voucher.objects.get(
                conference=self.conference,
                code__iexact=code,
            )
        except Voucher.DoesNotExist:
            messages.error(request, "Invalid voucher code.")
            return redirect(reverse("registration:cart", args=[self.conference.slug]))

        if not voucher.is_valid:
            messages.error(request, "This voucher is no longer valid.")
            return redirect(reverse("registration:cart", args=[self.conference.slug]))

        cart.voucher = voucher
        cart.save(update_fields=["voucher", "updated_at"])
        messages.success(request, f"Voucher '{code}' applied.")
        return redirect(reverse("registration:cart", args=[self.conference.slug]))

    def _handle_remove_voucher(self, request: HttpRequest, cart: Cart) -> HttpResponse:  # noqa: ARG002
        """Remove the applied voucher from the cart.

        Args:
            request: The incoming HTTP request (unused).
            cart: The user's open cart.

        Returns:
            A redirect to the cart page.
        """
        cart.voucher = None
        cart.save(update_fields=["voucher", "updated_at"])
        messages.success(self.request, "Voucher removed.")
        return redirect(reverse("registration:cart", args=[self.conference.slug]))


class CheckoutView(LoginRequiredMixin, ConferenceMixin, FeatureRequiredMixin, View):
    """Checkout view for creating an order from the current cart.

    Collects billing information, creates Order and OrderLineItem records
    inside a transaction, marks the cart as checked out, and redirects
    to the order confirmation page.
    """

    required_feature = ("registration", "public_ui")
    template_name = "django_program/registration/checkout.html"

    def _get_open_cart(self, request: HttpRequest) -> Cart | None:
        """Fetch the user's open cart for this conference, if any.

        Args:
            request: The incoming HTTP request.

        Returns:
            The open Cart, or ``None`` if no open cart exists.
        """
        return Cart.objects.filter(
            user=request.user,
            conference=self.conference,
            status=Cart.Status.OPEN,
        ).first()

    def get(self, request: HttpRequest, **kwargs: str) -> HttpResponse:  # noqa: ARG002
        """Render the checkout form with the cart summary.

        Args:
            request: The incoming HTTP request.
            **kwargs: URL keyword arguments (unused).

        Returns:
            The rendered checkout page, or a redirect to the cart if
            no open cart exists.
        """
        cart = self._get_open_cart(request)
        if cart is None:
            messages.error(request, "Your cart is empty.")
            return redirect(reverse("registration:cart", args=[self.conference.slug]))

        items = cart.items.select_related("ticket_type", "addon")
        if not items.exists():
            messages.error(request, "Your cart is empty.")
            return redirect(reverse("registration:cart", args=[self.conference.slug]))

        subtotal, discount, total = _cart_totals(cart)
        form = CheckoutForm(
            initial={
                "billing_email": request.user.email,
            }
        )
        return render(
            request,
            self.template_name,
            {
                "conference": self.conference,
                "form": form,
                "cart": cart,
                "items": items,
                "subtotal": subtotal,
                "discount": discount,
                "total": total,
            },
        )

    def post(self, request: HttpRequest, **kwargs: str) -> HttpResponse:  # noqa: ARG002
        """Validate billing info and create the order atomically.

        Creates Order and OrderLineItem records from the cart, marks the
        cart as checked out, and sets a 30-minute hold on the order for
        inventory reservation.

        Args:
            request: The incoming HTTP request.
            **kwargs: URL keyword arguments (unused).

        Returns:
            A redirect to the order confirmation page on success, or the
            checkout form with errors on validation failure.
        """
        cart = self._get_open_cart(request)
        if cart is None:
            messages.error(request, "Your cart is empty.")
            return redirect(reverse("registration:cart", args=[self.conference.slug]))

        items = cart.items.select_related("ticket_type", "addon")
        if not items.exists():
            messages.error(request, "Your cart is empty.")
            return redirect(reverse("registration:cart", args=[self.conference.slug]))

        form = CheckoutForm(request.POST)
        subtotal, discount, total = _cart_totals(cart)

        if not form.is_valid():
            return render(
                request,
                self.template_name,
                {
                    "conference": self.conference,
                    "form": form,
                    "cart": cart,
                    "items": items,
                    "subtotal": subtotal,
                    "discount": discount,
                    "total": total,
                },
            )

        try:
            with transaction.atomic():
                reference = _generate_order_reference()
                while Order.objects.filter(reference=reference).exists():
                    reference = _generate_order_reference()

                voucher_code = ""
                voucher_details = ""
                voucher = None
                if cart.voucher is not None:
                    voucher = Voucher.objects.select_for_update().get(pk=cart.voucher_id)
                    if not voucher.is_valid:
                        raise ValidationError(f"Voucher code '{voucher.code}' is no longer valid.")  # noqa: TRY301
                    voucher_code = str(voucher.code)
                    voucher_details = f"type={voucher.voucher_type}, value={voucher.discount_value}"

                order = Order.objects.create(
                    conference=self.conference,
                    user=request.user,
                    status=Order.Status.PENDING,
                    subtotal=subtotal,
                    discount_amount=discount,
                    total=total,
                    voucher_code=voucher_code,
                    voucher_details=voucher_details,
                    billing_name=form.cleaned_data["billing_name"],
                    billing_email=form.cleaned_data["billing_email"],
                    billing_company=form.cleaned_data.get("billing_company", ""),
                    reference=reference,
                    hold_expires_at=timezone.now() + timedelta(minutes=30),
                )

                for item in items:
                    description = str(item.ticket_type.name if item.ticket_type else item.addon.name)
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

                if voucher is not None:
                    voucher.times_used = models.F("times_used") + 1
                    voucher.save(update_fields=["times_used"])
        except ValidationError as exc:
            messages.error(request, str(exc))
            return render(
                request,
                self.template_name,
                {
                    "conference": self.conference,
                    "form": form,
                    "cart": cart,
                    "items": items,
                    "subtotal": subtotal,
                    "discount": discount,
                    "total": total,
                },
            )

        logger.info("Order %s created for user %s", order.reference, request.user)
        return redirect(reverse("registration:order-confirmation", args=[self.conference.slug, order.reference]))


class OrderConfirmationView(LoginRequiredMixin, ConferenceMixin, FeatureRequiredMixin, DetailView):
    """Confirmation page shown immediately after checkout.

    Displays the order summary and line items for the just-completed
    checkout.
    """

    required_feature = ("registration", "public_ui")
    template_name = "django_program/registration/order_confirmation.html"
    context_object_name = "order"

    def get_object(self, queryset: QuerySet[Order] | None = None) -> Order:  # noqa: ARG002
        """Look up the order by reference within the conference.

        Ensures the order belongs to the requesting user.

        Returns:
            The matched Order instance.

        Raises:
            Http404: If no matching order is found or the user does not own it.
        """
        order = get_object_or_404(
            Order,
            conference=self.conference,
            reference=self.kwargs["reference"],
        )
        if order.user != self.request.user:
            raise Http404
        return order

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        """Add line items to the template context.

        Returns:
            Context dict containing ``conference``, ``order``, and ``line_items``.
        """
        context = super().get_context_data(**kwargs)
        context["line_items"] = self.object.line_items.all()
        return context


class OrderDetailView(LoginRequiredMixin, ConferenceMixin, FeatureRequiredMixin, DetailView):
    """Detail view for any order owned by the current user.

    Displays order information, line items, and payment history.
    """

    required_feature = ("registration", "public_ui")
    template_name = "django_program/registration/order_detail.html"
    context_object_name = "order"

    def get_object(self, queryset: QuerySet[Order] | None = None) -> Order:  # noqa: ARG002
        """Look up the order by reference within the conference.

        Ensures the order belongs to the requesting user.

        Returns:
            The matched Order instance.

        Raises:
            Http404: If no matching order is found or the user does not own it.
        """
        order = get_object_or_404(
            Order,
            conference=self.conference,
            reference=self.kwargs["reference"],
        )
        if order.user != self.request.user:
            raise Http404
        return order

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        """Add line items and payments to the template context.

        Returns:
            Context dict containing ``conference``, ``order``,
            ``line_items``, and ``payments``.
        """
        context = super().get_context_data(**kwargs)
        context["line_items"] = self.object.line_items.all()
        context["payments"] = self.object.payments.all()
        return context
