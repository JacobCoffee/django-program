"""Built-in "needs attention" provider for the management dashboard.

Registered by default via ``ManageConfig.attention``. Each check is a cheap
``COUNT`` query guarded by the relevant feature flag and the same
permission the corresponding manage list view requires, so disabled
modules and unauthorized users never pay for a query.
"""

from typing import TYPE_CHECKING

from django.urls import NoReverseMatch, reverse

from django_program.features import is_feature_enabled
from django_program.manage.attention import AttentionItem
from django_program.manage.nav import manage_perm
from django_program.programs.models import Receipt, TravelGrant

if TYPE_CHECKING:
    from collections.abc import Iterable

    from django.http import HttpRequest

    from django_program.conference.models import Conference

_can_review_grants = manage_perm("program_programs.view_travel_grant")
_can_review_receipts = manage_perm("program_programs.review_receipt")


def _reverse_or_none(name: str, kwargs: dict[str, str]) -> str | None:
    """Reverse ``name``, or ``None`` when its URLs aren't mounted (e.g. ``manage:``)."""
    try:
        return reverse(name, kwargs=kwargs)
    except NoReverseMatch:
        return None


def builtin_attention(request: HttpRequest, conference: Conference | None) -> Iterable[AttentionItem]:
    """Yield built-in attention items for the current conference.

    Args:
        request: The current request.
        conference: The conference in scope. No items are produced outside
            a conference-scoped page.

    Yields:
        AttentionItem: Travel grant applications and receipts awaiting
        review, each only when the travel grants module is enabled, the
        user has the matching manage permission, and the count is non-zero.
    """
    if conference is None:
        return

    user = request.user

    if is_feature_enabled("travel_grants", conference=conference):
        if _can_review_grants(user):
            pending_grants = TravelGrant.objects.filter(
                conference=conference,
                status=TravelGrant.GrantStatus.SUBMITTED,
            ).count()
            grant_list_url = _reverse_or_none("manage:travel-grant-list", {"conference_slug": conference.slug})
            if pending_grants and grant_list_url is not None:
                yield AttentionItem(
                    key="travel-grants-pending",
                    label="Travel grant applications awaiting review",
                    count=pending_grants,
                    url=grant_list_url + f"?status={TravelGrant.GrantStatus.SUBMITTED}",
                    tone="warning",
                )

        if _can_review_receipts(user):
            pending_receipts = Receipt.objects.filter(
                grant__conference=conference,
                approved=False,
                flagged=False,
            ).count()
            receipt_queue_url = _reverse_or_none("manage:receipt-review-queue", {"conference_slug": conference.slug})
            if pending_receipts and receipt_queue_url is not None:
                yield AttentionItem(
                    key="receipts-pending",
                    label="Receipts awaiting review",
                    count=pending_receipts,
                    url=receipt_queue_url,
                    tone="warning",
                )
