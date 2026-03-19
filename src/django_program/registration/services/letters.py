"""Visa invitation letter PDF generation and delivery service.

Uses reportlab to produce formal invitation letters suitable for embassy
submission, embedding conference details and attendee travel information.
"""

import io
import logging
from typing import TYPE_CHECKING

from django.core.files.base import ContentFile
from django.utils import timezone

if TYPE_CHECKING:
    from django_program.registration.letter import LetterRequest

logger = logging.getLogger(__name__)


def generate_invitation_letter(letter_request: LetterRequest) -> bytes:
    """Generate a formal invitation letter PDF for a visa application.

    Produces a professional letter with conference letterhead, attendee
    passport details, and travel dates. Saves the PDF to the
    ``generated_pdf`` field and transitions the request to ``GENERATED``.

    Args:
        letter_request: The letter request containing attendee and travel info.

    Returns:
        The raw PDF bytes.
    """
    from reportlab.lib.pagesizes import A4  # noqa: PLC0415
    from reportlab.lib.units import mm  # noqa: PLC0415
    from reportlab.pdfgen import canvas  # noqa: PLC0415

    buf = io.BytesIO()
    width, height = A4
    c = canvas.Canvas(buf, pagesize=A4)
    margin = 25 * mm
    usable_width = width - 2 * margin

    y = _draw_letterhead(c, letter_request.conference, margin, height - margin, width)
    y = _draw_body(c, letter_request, margin, y, usable_width)
    y = _draw_attendee_details(c, letter_request, margin, y)
    _draw_closing(c, letter_request.conference, margin, y)

    c.showPage()
    c.save()
    pdf_bytes = buf.getvalue()

    filename = f"letter-{letter_request.pk}.pdf"
    letter_request.generated_pdf.save(filename, ContentFile(pdf_bytes), save=False)
    letter_request.transition_to(letter_request.Status.GENERATED)
    letter_request.save(update_fields=["status", "generated_pdf", "updated_at"])

    logger.info("Generated invitation letter PDF for request %s", letter_request.pk)
    return pdf_bytes


def send_invitation_letter(letter_request: LetterRequest) -> None:
    """Mark an invitation letter as sent.

    This is a stub for future email delivery integration. Currently it
    only transitions the request status to ``SENT`` and records the
    timestamp.

    Args:
        letter_request: The letter request to mark as sent. Must be in
            ``GENERATED`` status.
    """
    letter_request.transition_to(letter_request.Status.SENT)
    letter_request.sent_at = timezone.now()
    letter_request.save(update_fields=["status", "sent_at", "updated_at"])
    logger.info("Marked invitation letter %s as sent", letter_request.pk)


def _draw_letterhead(c: object, conference: object, margin: float, y: float, width: float) -> float:
    """Draw conference letterhead at the top of the page.

    Args:
        c: The reportlab Canvas instance.
        conference: The conference model instance.
        margin: Left margin in points.
        y: Current y position.
        width: Page width in points.

    Returns:
        Updated y position after the letterhead.
    """
    from reportlab.lib.units import mm  # noqa: PLC0415

    c.setFont("Helvetica-Bold", 16)  # type: ignore[attr-defined]
    c.drawString(margin, y, str(conference.name))  # type: ignore[attr-defined]
    y -= 7 * mm

    if conference.venue or conference.address:
        c.setFont("Helvetica", 10)  # type: ignore[attr-defined]
        venue_line = ", ".join(filter(None, [str(conference.venue), str(conference.address)]))
        c.drawString(margin, y, venue_line)  # type: ignore[attr-defined]
        y -= 5 * mm

    if conference.website_url:
        c.setFont("Helvetica", 9)  # type: ignore[attr-defined]
        c.drawString(margin, y, str(conference.website_url))  # type: ignore[attr-defined]
        y -= 5 * mm

    y -= 5 * mm
    c.setStrokeColorRGB(0.7, 0.7, 0.7)  # type: ignore[attr-defined]
    c.line(margin, y, width - margin, y)  # type: ignore[attr-defined]
    y -= 12 * mm

    c.setFont("Helvetica", 10)  # type: ignore[attr-defined]
    today_str = timezone.now().strftime("%B %d, %Y")
    c.drawString(margin, y, today_str)  # type: ignore[attr-defined]
    y -= 12 * mm

    return y


def _draw_body(c: object, letter_request: LetterRequest, margin: float, y: float, usable_width: float) -> float:
    """Draw the letter title, greeting, and body paragraphs.

    Args:
        c: The reportlab Canvas instance.
        letter_request: The letter request with conference and travel details.
        margin: Left margin in points.
        y: Current y position.
        usable_width: Available text width in points.

    Returns:
        Updated y position after the body text.
    """
    from reportlab.lib.units import mm  # noqa: PLC0415

    c.setFont("Helvetica-Bold", 14)  # type: ignore[attr-defined]
    c.drawString(margin, y, "Visa Invitation Letter")  # type: ignore[attr-defined]
    y -= 10 * mm

    c.setFont("Helvetica", 11)  # type: ignore[attr-defined]
    y -= 4 * mm
    c.drawString(margin, y, "To Whom It May Concern,")  # type: ignore[attr-defined]
    y -= 10 * mm

    body_lines = _build_body_text(letter_request)
    c.setFont("Helvetica", 11)  # type: ignore[attr-defined]
    line_height = 5 * mm

    for line in body_lines:
        wrapped = _wrap_text(c, line, "Helvetica", 11, usable_width)
        for segment in wrapped:
            c.drawString(margin, y, segment)  # type: ignore[attr-defined]
            y -= line_height
        y -= 2 * mm

    return y


def _draw_attendee_details(c: object, letter_request: LetterRequest, margin: float, y: float) -> float:
    """Draw the attendee details table section.

    Args:
        c: The reportlab Canvas instance.
        letter_request: The letter request with passport and travel info.
        margin: Left margin in points.
        y: Current y position.

    Returns:
        Updated y position after the details table.
    """
    from reportlab.lib.units import mm  # noqa: PLC0415

    y -= 6 * mm
    c.setFont("Helvetica-Bold", 11)  # type: ignore[attr-defined]
    c.drawString(margin, y, "Attendee Details:")  # type: ignore[attr-defined]
    y -= 7 * mm

    details = [
        ("Full Name (as on passport)", str(letter_request.passport_name)),
        ("Passport Number", str(letter_request.passport_number)),
        ("Nationality", str(letter_request.nationality)),
    ]
    if letter_request.date_of_birth:
        details.append(("Date of Birth", letter_request.date_of_birth.strftime("%B %d, %Y")))
    details.extend(
        [
            ("Travel From", letter_request.travel_from.strftime("%B %d, %Y")),
            ("Travel Until", letter_request.travel_until.strftime("%B %d, %Y")),
            ("Destination Address", str(letter_request.destination_address)),
        ]
    )
    if letter_request.embassy_name:
        details.append(("Embassy / Consulate", str(letter_request.embassy_name)))

    for label, value in details:
        c.setFont("Helvetica-Bold", 10)  # type: ignore[attr-defined]
        c.drawString(margin + 5 * mm, y, f"{label}:")  # type: ignore[attr-defined]
        c.setFont("Helvetica", 10)  # type: ignore[attr-defined]
        c.drawString(margin + 65 * mm, y, value)  # type: ignore[attr-defined]
        y -= 6 * mm

    return y


def _draw_closing(c: object, conference: object, margin: float, y: float) -> None:
    """Draw the closing paragraph, signature line, and organizer title.

    Args:
        c: The reportlab Canvas instance.
        conference: The conference model instance.
        margin: Left margin in points.
        y: Current y position.
    """
    from reportlab.lib.units import mm  # noqa: PLC0415

    y -= 10 * mm
    c.setFont("Helvetica", 11)  # type: ignore[attr-defined]
    c.drawString(margin, y, "We kindly request that the appropriate visa be granted to the above individual.")  # type: ignore[attr-defined]
    y -= 8 * mm
    c.drawString(margin, y, "Sincerely,")  # type: ignore[attr-defined]
    y -= 14 * mm

    c.line(margin, y, margin + 60 * mm, y)  # type: ignore[attr-defined]
    y -= 5 * mm
    c.setFont("Helvetica", 10)  # type: ignore[attr-defined]
    c.drawString(margin, y, f"Conference Organizer, {conference.name}")  # type: ignore[attr-defined]


def _build_body_text(letter_request: LetterRequest) -> list[str]:
    """Build the paragraphs of the invitation letter body.

    Args:
        letter_request: The letter request with conference and travel details.

    Returns:
        A list of paragraph strings.
    """
    conference = letter_request.conference
    conf_dates = f"{conference.start_date.strftime('%B %d, %Y')} to {conference.end_date.strftime('%B %d, %Y')}"
    venue_info = ""
    if conference.venue:
        venue_info = f" at {conference.venue}"
    if conference.address:
        venue_info += f", {conference.address}"

    return [
        (
            f"This letter confirms that {letter_request.passport_name} has been "
            f"invited to attend {conference.name}, taking place from "
            f"{conf_dates}{venue_info}."
        ),
        (
            f"The attendee plans to travel from {letter_request.travel_from.strftime('%B %d, %Y')} "
            f"to {letter_request.travel_until.strftime('%B %d, %Y')} and will be staying at: "
            f"{letter_request.destination_address}."
        ),
        (
            "We confirm that this individual is a registered participant of our "
            "conference and we take full responsibility for verifying their "
            "registration status."
        ),
    ]


def _wrap_text(canvas_obj: object, text: str, font: str, size: int, max_width: float) -> list[str]:
    """Wrap text to fit within a given width on a reportlab canvas.

    Args:
        canvas_obj: The reportlab Canvas instance.
        text: The text to wrap.
        font: Font name for width calculation.
        size: Font size in points.
        max_width: Maximum line width in points.

    Returns:
        A list of text segments, each fitting within ``max_width``.
    """
    words = text.split()
    lines: list[str] = []
    current_line = ""

    for word in words:
        test_line = f"{current_line} {word}".strip() if current_line else word
        tw = canvas_obj.stringWidth(test_line, font, size)  # type: ignore[attr-defined]
        if tw <= max_width:
            current_line = test_line
        else:
            if current_line:
                lines.append(current_line)
            current_line = word

    if current_line:
        lines.append(current_line)

    return lines or [""]
