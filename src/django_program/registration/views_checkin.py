"""Staff-facing JSON API views for on-site check-in and product redemption.

These views power the scanner UI used by registration desk volunteers.
All endpoints require staff or superuser authentication and are scoped
to a conference via the ``conference_slug`` URL kwarg. The scanner UI
is responsible for including the CSRF token in POST requests.
"""

import json

from django.db.models import Count, Prefetch
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views import View

from django_program.conference.models import Conference
from django_program.registration.attendee import Attendee
from django_program.registration.models import Order, OrderLineItem
from django_program.registration.services.checkin import CheckInService, RedemptionService


class StaffRequiredMixin:
    """Require staff or superuser access for check-in API views.

    Resolves the conference from ``conference_slug`` and stores it on
    ``self.conference``. Returns a 403 JSON error if the user lacks
    permission or a 404 if the conference does not exist.
    """

    conference: Conference

    def dispatch(self, request: HttpRequest, *args: str, **kwargs: str) -> HttpResponse:
        """Validate staff access and resolve conference before dispatching.

        Args:
            request: The incoming HTTP request.
            *args: Positional URL arguments.
            **kwargs: URL keyword arguments including ``conference_slug``.

        Returns:
            The response from the downstream view, or a 403/401 JSON error.
        """
        if not request.user.is_authenticated:
            return JsonResponse({"error": "Authentication required"}, status=401)
        if not (request.user.is_superuser or request.user.has_perm("program_conference.change_conference")):
            return JsonResponse({"error": "Staff access required"}, status=403)
        self.conference = get_object_or_404(Conference, slug=kwargs.get("conference_slug"))
        return super().dispatch(request, *args, **kwargs)  # type: ignore[misc]


def _serialize_attendee(attendee: Attendee) -> dict[str, object]:
    """Serialize an attendee record for JSON API responses.

    Args:
        attendee: The attendee to serialize.

    Returns:
        A dict with attendee fields suitable for JSON encoding.
    """
    return {
        "id": attendee.pk,
        "access_code": str(attendee.access_code),
        "name": str(getattr(attendee.user, "get_full_name", lambda: "")()),
        "email": str(getattr(attendee.user, "email", "")),
        "checked_in": attendee.checked_in_at is not None,
        "checked_in_at": (attendee.checked_in_at.isoformat() if attendee.checked_in_at else None),
    }


def _serialize_line_item(item: OrderLineItem) -> dict[str, object]:
    """Serialize an order line item for JSON API responses.

    Args:
        item: The order line item to serialize.

    Returns:
        A dict with line item fields suitable for JSON encoding.
    """
    return {
        "id": item.pk,
        "description": str(item.description),
        "quantity": item.quantity,
        "ticket_type_slug": (str(item.ticket_type.slug) if item.ticket_type else None),
        "addon_slug": str(item.addon.slug) if item.addon else None,
    }


def _get_ticket_type_name(order: Order | None) -> str:
    """Extract the ticket type name from an order's prefetched line items."""
    if order is None:
        return ""
    for item in order.line_items.all():
        if item.ticket_type is not None:
            return str(item.ticket_type.name)
    return ""


def _parse_json_body(request: HttpRequest) -> dict[str, object] | None:
    """Parse JSON from request body, returning None on failure.

    Returns None if the body is not valid JSON or is not an object (dict).
    """
    try:
        payload = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    return payload


class ScanView(StaffRequiredMixin, View):
    """Scan an attendee's access code and perform check-in.

    Accepts a JSON body with ``access_code`` and records the check-in
    via ``CheckInService``. Returns the attendee data and badge info
    on success.
    """

    def post(self, request: HttpRequest, **kwargs: str) -> JsonResponse:  # noqa: ARG002
        """Process a scan and check in the attendee.

        Args:
            request: The incoming HTTP request with JSON body.
            **kwargs: URL keyword arguments (unused).

        Returns:
            JSON response with attendee data on success, or an error payload.
        """
        body = _parse_json_body(request)
        if body is None:
            return JsonResponse({"error": "Invalid JSON body"}, status=400)

        access_code = str(body.get("access_code", "")).strip()
        if not access_code:
            return JsonResponse({"error": "access_code is required"}, status=400)

        station = str(body.get("station", ""))

        try:
            attendee = CheckInService.lookup_attendee(conference=self.conference, access_code=access_code)
        except Attendee.DoesNotExist:
            return JsonResponse(
                {"error": "Attendee not found", "access_code": access_code},
                status=404,
            )

        status_error = CheckInService.validate_order_status(attendee)
        if status_error is not None:
            return JsonResponse(
                {
                    "error": status_error,
                    "access_code": access_code,
                    "order_status": str(attendee.order.status) if attendee.order else None,
                },
                status=409,
            )

        checkin = CheckInService.check_in(
            attendee=attendee,
            checked_in_by=request.user,
            station=station,
        )

        order = attendee.order
        products = []
        if order is not None:
            products = [_serialize_line_item(item) for item in order.line_items.all()]

        return JsonResponse(
            {
                "status": "checked_in",
                "attendee": _serialize_attendee(attendee),
                "badge": {
                    "name": str(getattr(attendee.user, "get_full_name", lambda: "")()),
                    "ticket_type": _get_ticket_type_name(order),
                },
                "products": products,
                "order_status": str(order.status) if order else None,
                "checkin_id": checkin.pk,
                "checked_in_at": checkin.checked_in_at.isoformat(),
            }
        )


class LookupView(StaffRequiredMixin, View):
    """Look up an attendee by access code without performing check-in.

    Read-only endpoint that returns attendee details, purchased products,
    check-in status, and redeemable line items.
    """

    def get(self, request: HttpRequest, access_code: str, **kwargs: str) -> JsonResponse:  # noqa: ARG002
        """Look up attendee data by access code.

        Args:
            request: The incoming HTTP request.
            access_code: The attendee's access code from the URL.
            **kwargs: URL keyword arguments (unused).

        Returns:
            JSON response with attendee data, products, and redemption status.
        """
        try:
            attendee = CheckInService.lookup_attendee(conference=self.conference, access_code=access_code.strip())
        except Attendee.DoesNotExist:
            return JsonResponse(
                {"error": "Attendee not found", "access_code": access_code},
                status=404,
            )

        order = attendee.order
        products: list[dict[str, object]] = []
        redeemable: list[dict[str, object]] = []
        if order is not None:
            line_items = list(order.line_items.all())
            products = [_serialize_line_item(item) for item in line_items]

            redeemed_counts: dict[int, int] = {}
            for r in attendee.redemptions.values("order_line_item_id").annotate(count=Count("id")):
                redeemed_counts[r["order_line_item_id"]] = r["count"]

            redeemable = [
                {
                    **_serialize_line_item(item),
                    "redeemed_count": redeemed_counts.get(item.pk, 0),
                    "remaining": item.quantity - redeemed_counts.get(item.pk, 0),
                }
                for item in line_items
                if item.addon_id is not None
            ]

        return JsonResponse(
            {
                "attendee": {
                    **_serialize_attendee(attendee),
                    "ticket_type": _get_ticket_type_name(order),
                },
                "products": products,
                "redeemable": redeemable,
                "order_status": str(attendee.order.status) if attendee.order else None,
            }
        )


class RedeemView(StaffRequiredMixin, View):
    """Redeem a purchased product (order line item) for an attendee.

    Accepts a JSON body with ``access_code`` and ``line_item_id`` and
    records the redemption via ``RedemptionService``.
    """

    def post(self, request: HttpRequest, **kwargs: str) -> JsonResponse:  # noqa: ARG002
        """Process a product redemption.

        Args:
            request: The incoming HTTP request with JSON body.
            **kwargs: URL keyword arguments (unused).

        Returns:
            JSON response with redemption result, or an error payload.
        """
        body = _parse_json_body(request)
        if body is None:
            return JsonResponse({"error": "Invalid JSON body"}, status=400)

        access_code = str(body.get("access_code", "")).strip()
        raw_line_item_id = body.get("line_item_id")

        try:
            line_item_id = int(raw_line_item_id)  # type: ignore[arg-type]
            if not access_code:
                raise ValueError  # noqa: TRY301
        except TypeError, ValueError:
            return JsonResponse({"error": "access_code and a valid integer line_item_id are required"}, status=400)

        try:
            attendee = CheckInService.lookup_attendee(conference=self.conference, access_code=access_code)
        except Attendee.DoesNotExist:
            return JsonResponse(
                {"error": "Attendee not found", "access_code": access_code},
                status=404,
            )

        status_error = CheckInService.validate_order_status(attendee)
        if status_error is not None:
            return JsonResponse(
                {
                    "error": status_error,
                    "access_code": access_code,
                    "order_status": str(attendee.order.status) if attendee.order else None,
                },
                status=409,
            )

        try:
            line_item = attendee.order.line_items.get(pk=line_item_id)
        except OrderLineItem.DoesNotExist:
            return JsonResponse(
                {"error": "Line item not found in attendee's order", "line_item_id": line_item_id},
                status=400,
            )

        return self._do_redeem(attendee, line_item, request)

    def _do_redeem(self, attendee: Attendee, line_item: OrderLineItem, request: HttpRequest) -> JsonResponse:
        """Execute the redemption and return the result."""
        try:
            redemption = RedemptionService.redeem_product(
                attendee=attendee,
                order_line_item=line_item,
                redeemed_by=request.user,
            )
        except ValueError:
            return JsonResponse(
                {"error": "Product already fully redeemed", "line_item_id": line_item.pk},
                status=409,
            )

        return JsonResponse(
            {
                "status": "redeemed",
                "redemption_id": redemption.pk,
                "redeemed_at": redemption.redeemed_at.isoformat(),
                "line_item": _serialize_line_item(line_item),
                "attendee": _serialize_attendee(attendee),
            }
        )


class OfflinePreloadView(StaffRequiredMixin, View):
    """Bulk export attendee data for offline scanner fallback.

    Returns a JSON array of attendee records for all paid orders in the
    conference. Optionally filtered by ticket type slug via the
    ``ticket_type`` query parameter.
    """

    def get(self, request: HttpRequest, **kwargs: str) -> JsonResponse:  # noqa: ARG002
        """Return preloaded attendee data for offline scanner use.

        Args:
            request: The incoming HTTP request.
            **kwargs: URL keyword arguments (unused).

        Returns:
            JSON response with an array of attendee records.
        """
        attendees = (
            Attendee.objects.filter(
                conference=self.conference,
                order__isnull=False,
                order__status__in=[Order.Status.PAID, Order.Status.PARTIALLY_REFUNDED],
            )
            .select_related("user", "order")
            .prefetch_related(
                Prefetch(
                    "order__line_items",
                    queryset=OrderLineItem.objects.select_related("ticket_type", "addon"),
                ),
                "redemptions",
            )
        )

        ticket_type_slug = request.GET.get("ticket_type", "").strip()
        if ticket_type_slug:
            attendees = attendees.filter(
                order__line_items__ticket_type__slug=ticket_type_slug,
            ).distinct()

        records = [self._serialize_preload_attendee(attendee) for attendee in attendees]

        return JsonResponse(
            {
                "conference": str(self.conference.slug),
                "generated_at": timezone.now().isoformat(),
                "count": len(records),
                "attendees": records,
            }
        )

    @staticmethod
    def _serialize_preload_attendee(attendee: Attendee) -> dict[str, object]:
        """Serialize a single attendee for the preload export."""
        order = attendee.order
        products: list[dict[str, object]] = []
        ticket_type_name = ""

        if order is not None:
            # Use prefetched redemptions to avoid N+1 queries
            redeemed_counts: dict[int, int] = {}
            for redemption in attendee.redemptions.all():
                redeemed_counts[redemption.order_line_item_id] = (
                    redeemed_counts.get(redemption.order_line_item_id, 0) + 1
                )
            for item in order.line_items.all():
                product_data = _serialize_line_item(item)
                product_data["redeemed_count"] = redeemed_counts.get(item.pk, 0)
                product_data["remaining"] = item.quantity - redeemed_counts.get(item.pk, 0)
                products.append(product_data)

                if item.ticket_type and not ticket_type_name:
                    ticket_type_name = str(item.ticket_type.name)

        return {
            "access_code": str(attendee.access_code),
            "name": str(getattr(attendee.user, "get_full_name", lambda: "")()),
            "email": str(getattr(attendee.user, "email", "")),
            "ticket_type": ticket_type_name,
            "products": products,
            "checked_in": attendee.checked_in_at is not None,
            "checked_in_at": (attendee.checked_in_at.isoformat() if attendee.checked_in_at else None),
        }
