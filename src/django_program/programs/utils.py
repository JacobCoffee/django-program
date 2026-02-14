"""Utility functions for the programs app."""

from collections import Counter
from typing import TYPE_CHECKING

from django_program.pretalx.models import ScheduleSlot

if TYPE_CHECKING:
    import datetime

    from django_program.conference.models import Conference


def get_conference_days(conference: Conference) -> list[tuple[str, str]]:
    """Extract unique conference days from schedule data with type labels.

    Queries ScheduleSlot records for the given conference and determines the
    predominant session type for each day based on the linked talks'
    ``submission_type``.  A type is considered predominant when it accounts
    for more than half of the talk-linked slots on that day.

    Args:
        conference: The Conference instance to extract days from.

    Returns:
        Sorted list of ``(iso_date_str, human_label)`` tuples.  Returns an
        empty list if no schedule data exists for the conference.
    """
    slots = ScheduleSlot.objects.filter(conference=conference).select_related("talk")

    if not slots.exists():
        return []

    # Group slots by date, counting submission types for talk-linked slots
    day_type_counts: dict[datetime.date, Counter[str]] = {}
    for slot in slots:
        slot_date = slot.start.date()
        if slot_date not in day_type_counts:
            day_type_counts[slot_date] = Counter()
        if slot.talk and slot.talk.submission_type:
            day_type_counts[slot_date][slot.talk.submission_type] += 1

    result: list[tuple[str, str]] = []
    for day in sorted(day_type_counts):
        counts = day_type_counts[day]
        date_label = day.strftime("%a, %b %-d")

        if counts:
            total = sum(counts.values())
            most_common_type, most_common_count = counts.most_common(1)[0]
            label = f"{date_label} ({most_common_type})" if most_common_count > total / 2 else date_label
        else:
            label = date_label

        result.append((day.isoformat(), label))

    return result
