"""Built-in "needs attention" provider for the management dashboard.

Registered by default via ``ManageConfig.attention``. Each check is a cheap
``COUNT`` query guarded by the relevant feature flag and the same
permission the corresponding manage list view requires, so disabled
modules and unauthorized users never pay for a query.
"""

from typing import TYPE_CHECKING

from django.urls import reverse

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
            if pending_grants:
                yield AttentionItem(
                    key="travel-grants-pending",
                    label="Travel grant applications awaiting review",
                    count=pending_grants,
                    url=(
                        reverse("manage:travel-grant-list", kwargs={"conference_slug": conference.slug})
                        + f"?status={TravelGrant.GrantStatus.SUBMITTED}"
                    ),
                    tone="warning",
                )

        if _can_review_receipts(user):
            pending_receipts = Receipt.objects.filter(
                grant__conference=conference,
                approved=False,
                flagged=False,
            ).count()
            if pending_receipts:
                yield AttentionItem(
                    key="receipts-pending",
                    label="Receipts awaiting review",
                    count=pending_receipts,
                    url=reverse("manage:receipt-review-queue", kwargs={"conference_slug": conference.slug}),
                    tone="warning",
                )
