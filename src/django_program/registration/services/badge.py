"""Badge generation service for creating attendee badges with QR codes.

Generates PDF and PNG badges using reportlab and Pillow respectively,
with embedded QR codes encoding the attendee's access code for check-in
scanning.
"""

import io
from dataclasses import dataclass
from typing import TYPE_CHECKING

from django.core.files.base import ContentFile
from django.utils import timezone

from django_program.registration.badge import Badge, BadgeTemplate

if TYPE_CHECKING:
    from collections.abc import Iterator

    from django_program.conference.models import Conference
    from django_program.registration.attendee import Attendee
    from django_program.registration.models import TicketType

_MIN_FONT_SIZE = 8


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    """Convert a hex color string to an RGB tuple.

    Args:
        hex_color: A hex color like ``"#4338CA"``.

    Returns:
        Tuple of (red, green, blue) integers 0-255.
    """
    hex_color = hex_color.lstrip("#")
    return (
        int(hex_color[0:2], 16),
        int(hex_color[2:4], 16),
        int(hex_color[4:6], 16),
    )


def _hex_to_reportlab(hex_color: str) -> tuple[float, float, float]:
    """Convert a hex color string to reportlab's 0-1 float RGB.

    Args:
        hex_color: A hex color like ``"#4338CA"``.

    Returns:
        Tuple of (red, green, blue) floats 0.0-1.0.
    """
    r, g, b = _hex_to_rgb(hex_color)
    return r / 255.0, g / 255.0, b / 255.0


@dataclass
class _PDFLayout:
    """Intermediate layout parameters for PDF badge rendering."""

    width: float
    margin: float
    mm_unit: float
    accent_rgb: tuple[float, float, float]
    text_rgb: tuple[float, float, float]


class BadgeGenerationService:
    """Generates badge PDFs and PNGs with QR codes for attendee check-in."""

    def generate_qr_code(self, data: str, size: int = 200) -> bytes:
        """Generate a QR code PNG as bytes.

        Args:
            data: The string to encode in the QR code.
            size: The pixel dimensions of the output image.

        Returns:
            PNG image bytes.
        """
        import qrcode  # noqa: PLC0415

        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=10,
            border=2,
        )
        qr.add_data(data)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        img = img.resize((size, size))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    def _get_attendee_display_name(self, attendee: Attendee) -> str:
        """Get the display name for an attendee.

        Args:
            attendee: The attendee to get the name for.

        Returns:
            Full name if available, otherwise the username.
        """
        user = attendee.user
        full_name = f"{user.first_name} {user.last_name}".strip()
        return full_name or str(user.username)

    def _get_company(self, attendee: Attendee) -> str:
        """Get the company/organization for an attendee from their order billing info.

        Args:
            attendee: The attendee whose company to look up.

        Returns:
            The billing company, or an empty string if not found.
        """
        if attendee.order is None:
            return ""
        return str(attendee.order.billing_company or "")

    def _get_ticket_type_label(self, attendee: Attendee) -> str:
        """Get the ticket type label for an attendee's order.

        Args:
            attendee: The attendee whose ticket type to look up.

        Returns:
            The ticket type name, or ``"General Admission"`` if not found.
        """
        if attendee.order is None:
            return "General Admission"
        first_line = (
            attendee.order.line_items.filter(
                ticket_type__isnull=False,
            )
            .select_related("ticket_type")
            .first()
        )
        if first_line and first_line.ticket_type:
            return str(first_line.ticket_type.name)
        return "General Admission"

    def _get_qr_data(self, attendee: Attendee) -> str:
        """Build the QR code payload for an attendee.

        Args:
            attendee: The attendee to encode.

        Returns:
            A string like ``"pycon-us-2026:A1B2C3D4"``.
        """
        conference_slug = str(attendee.conference.slug)
        return f"{conference_slug}:{attendee.access_code}"

    def _draw_pdf_text_fields(
        self,
        c: object,
        attendee: Attendee,
        template: BadgeTemplate,
        layout: _PDFLayout,
        y_cursor: float,
    ) -> float:
        """Draw text fields on a PDF canvas.

        Args:
            c: The reportlab canvas object.
            attendee: The attendee whose info to render.
            template: The badge template with field visibility flags.
            layout: Layout parameters (dimensions, colors, units).
            y_cursor: The current vertical position.

        Returns:
            Updated y_cursor position.
        """
        mm = layout.mm_unit

        if template.show_conference_name:
            c.setFillColorRGB(*layout.accent_rgb)  # type: ignore[attr-defined]
            c.setFont("Helvetica-Bold", 7)  # type: ignore[attr-defined]
            c.drawString(layout.margin, y_cursor, str(attendee.conference.name))  # type: ignore[attr-defined]
            y_cursor -= 4 * mm

        if template.show_name:
            c.setFillColorRGB(*layout.text_rgb)  # type: ignore[attr-defined]
            display_name = self._get_attendee_display_name(attendee)
            font_size = 12
            c.setFont("Helvetica-Bold", font_size)  # type: ignore[attr-defined]
            text_width = c.stringWidth(display_name, "Helvetica-Bold", font_size)  # type: ignore[attr-defined]
            max_text_width = layout.width - 2 * layout.margin
            while text_width > max_text_width and font_size > _MIN_FONT_SIZE:
                font_size -= 1
                text_width = c.stringWidth(display_name, "Helvetica-Bold", font_size)  # type: ignore[attr-defined]
            c.setFont("Helvetica-Bold", font_size)  # type: ignore[attr-defined]
            c.drawString(layout.margin, y_cursor, display_name)  # type: ignore[attr-defined]
            y_cursor -= 3.5 * mm

        if template.show_email:
            c.setFillColorRGB(*layout.text_rgb)  # type: ignore[attr-defined]
            c.setFont("Helvetica", 6)  # type: ignore[attr-defined]
            c.drawString(layout.margin, y_cursor, str(attendee.user.email))  # type: ignore[attr-defined]
            y_cursor -= 3 * mm

        if template.show_company:
            company = self._get_company(attendee)
            if company:
                c.setFillColorRGB(*layout.text_rgb)  # type: ignore[attr-defined]
                c.setFont("Helvetica", 6)  # type: ignore[attr-defined]
                c.drawString(layout.margin, y_cursor, company)  # type: ignore[attr-defined]
                y_cursor -= 3 * mm

        if template.show_ticket_type:
            c.setFillColorRGB(*layout.accent_rgb)  # type: ignore[attr-defined]
            c.setFont("Helvetica-Bold", 7)  # type: ignore[attr-defined]
            c.drawString(layout.margin, y_cursor, self._get_ticket_type_label(attendee))  # type: ignore[attr-defined]
            y_cursor -= 3 * mm

        return y_cursor

    def _draw_pdf_qr(self, c: object, attendee: Attendee, layout: _PDFLayout, height: float) -> None:
        """Draw QR code and access code on a PDF canvas.

        Positions the QR code in the bottom-right area of the badge,
        sized proportionally to the badge height.

        Args:
            c: The reportlab canvas object.
            attendee: The attendee whose QR code to render.
            layout: Layout parameters (dimensions, colors, units).
            height: The badge height for proportional sizing.
        """
        from reportlab.lib.utils import ImageReader  # noqa: PLC0415

        mm = layout.mm_unit
        qr_bytes = self.generate_qr_code(self._get_qr_data(attendee), size=200)
        qr_image = ImageReader(io.BytesIO(qr_bytes))
        qr_size = min(14 * mm, height * 0.3)
        qr_x = layout.width - qr_size - layout.margin
        qr_y = layout.margin + 2 * mm
        c.drawImage(qr_image, qr_x, qr_y, width=qr_size, height=qr_size)  # type: ignore[attr-defined]

        c.setFillColorRGB(*layout.text_rgb)  # type: ignore[attr-defined]
        c.setFont("Courier", 5)  # type: ignore[attr-defined]
        code_text = str(attendee.access_code)
        code_width = c.stringWidth(code_text, "Courier", 5)  # type: ignore[attr-defined]
        code_x = qr_x + (qr_size - code_width) / 2
        c.drawString(code_x, layout.margin, code_text)  # type: ignore[attr-defined]

    def generate_badge_pdf(self, attendee: Attendee, template: BadgeTemplate) -> bytes:
        """Generate a single badge as a PDF using reportlab.

        The badge includes the conference name (top, accent color),
        attendee full name (large, centered), ticket type label,
        and a QR code in the bottom-right corner with the access code
        printed below it in monospace.

        Args:
            attendee: The attendee to generate a badge for.
            template: The badge template defining layout and colors.

        Returns:
            PDF file bytes.
        """
        from reportlab.lib.units import mm  # noqa: PLC0415
        from reportlab.pdfgen import canvas  # noqa: PLC0415

        width = template.width_mm * mm
        height = template.height_mm * mm
        margin = 3 * mm
        bar_height = 4 * mm

        layout = _PDFLayout(
            width=width,
            margin=margin,
            mm_unit=mm,
            accent_rgb=_hex_to_reportlab(str(template.accent_color)),
            text_rgb=_hex_to_reportlab(str(template.text_color)),
        )

        buf = io.BytesIO()
        c = canvas.Canvas(buf, pagesize=(width, height))

        bg_rgb = _hex_to_reportlab(str(template.background_color))
        c.setFillColorRGB(*bg_rgb)
        c.rect(0, 0, width, height, fill=1, stroke=0)

        c.setFillColorRGB(*layout.accent_rgb)
        c.rect(0, height - bar_height, width, bar_height, fill=1, stroke=0)

        y_cursor = height - bar_height - 2 * mm
        self._draw_pdf_text_fields(c, attendee, template, layout, y_cursor)

        if template.show_qr_code:
            self._draw_pdf_qr(c, attendee, layout, height)

        c.showPage()
        c.save()
        return buf.getvalue()

    def _load_png_fonts(self, px_per_mm: float) -> tuple[object, object, object, object]:
        """Load fonts for PNG badge rendering, falling back to defaults.

        Args:
            px_per_mm: Pixels per millimeter for font sizing.

        Returns:
            Tuple of (large, medium, small, mono) font objects.
        """
        from PIL import ImageFont  # noqa: PLC0415

        try:
            return (
                ImageFont.truetype("Helvetica", int(14 * px_per_mm / 2.5)),
                ImageFont.truetype("Helvetica", int(8 * px_per_mm / 2.5)),
                ImageFont.truetype("Helvetica", int(7 * px_per_mm / 2.5)),
                ImageFont.truetype("Courier", int(6 * px_per_mm / 2.5)),
            )
        except OSError:
            default = ImageFont.load_default()
            return default, default, default, default

    def _draw_png_qr(
        self,
        img: object,
        draw: object,
        attendee: Attendee,
        layout: _PNGLayout,
    ) -> None:
        """Draw QR code and access code on a PNG image.

        Args:
            img: The Pillow Image object.
            draw: The Pillow ImageDraw object.
            attendee: The attendee whose QR code to render.
            layout: Layout parameters (dimensions, colors, fonts).
        """
        from PIL import Image  # noqa: PLC0415

        qr_size = int(18 * layout.px_per_mm)
        qr_bytes = self.generate_qr_code(self._get_qr_data(attendee), size=qr_size)
        qr_img = Image.open(io.BytesIO(qr_bytes)).resize((qr_size, qr_size))
        qr_x = layout.width - qr_size - layout.margin
        qr_y = layout.height - qr_size - layout.margin - int(3 * layout.px_per_mm)
        img.paste(qr_img, (qr_x, qr_y))  # type: ignore[union-attr]

        code_text = str(attendee.access_code)
        code_bbox = draw.textbbox((0, 0), code_text, font=layout.font_mono)  # type: ignore[union-attr]
        code_width = code_bbox[2] - code_bbox[0]
        code_x = qr_x + (qr_size - code_width) // 2
        code_y = layout.height - layout.margin
        draw.text((code_x, code_y), code_text, fill=layout.text_color, font=layout.font_mono)  # type: ignore[union-attr]

    def generate_badge_png(self, attendee: Attendee, template: BadgeTemplate) -> bytes:
        """Generate a single badge as a PNG using Pillow.

        Args:
            attendee: The attendee to generate a badge for.
            template: The badge template defining layout and colors.

        Returns:
            PNG image bytes.
        """
        from PIL import Image, ImageDraw  # noqa: PLC0415

        dpi = 300
        px_per_mm = dpi / 25.4
        width = int(template.width_mm * px_per_mm)
        height = int(template.height_mm * px_per_mm)
        margin = int(4 * px_per_mm)
        bar_height = int(6 * px_per_mm)

        bg_color = _hex_to_rgb(str(template.background_color))
        text_color = _hex_to_rgb(str(template.text_color))
        accent_color = _hex_to_rgb(str(template.accent_color))

        img = Image.new("RGB", (width, height), bg_color)
        draw = ImageDraw.Draw(img)
        draw.rectangle([0, 0, width, bar_height], fill=accent_color)

        font_large, font_medium, font_small, font_mono = self._load_png_fonts(px_per_mm)
        y_cursor = bar_height + int(2 * px_per_mm)

        if template.show_conference_name:
            draw.text((margin, y_cursor), str(attendee.conference.name), fill=accent_color, font=font_medium)
            y_cursor += int(5 * px_per_mm)

        if template.show_name:
            name = self._get_attendee_display_name(attendee)
            draw.text((margin, y_cursor), name, fill=text_color, font=font_large)
            y_cursor += int(6 * px_per_mm)

        if template.show_email:
            draw.text((margin, y_cursor), str(attendee.user.email), fill=text_color, font=font_small)
            y_cursor += int(4 * px_per_mm)

        if template.show_company:
            company = self._get_company(attendee)
            if company:
                draw.text((margin, y_cursor), company, fill=text_color, font=font_small)
                y_cursor += int(4 * px_per_mm)

        if template.show_ticket_type:
            label = self._get_ticket_type_label(attendee)
            draw.text((margin, y_cursor), label, fill=accent_color, font=font_medium)

        if template.show_qr_code:
            layout = _PNGLayout(
                width=width,
                height=height,
                margin=margin,
                px_per_mm=px_per_mm,
                text_color=text_color,
                font_mono=font_mono,
            )
            self._draw_png_qr(img, draw, attendee, layout)

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    def generate_or_get_badge(
        self,
        attendee: Attendee,
        template: BadgeTemplate | None = None,
        badge_format: str = "pdf",
    ) -> Badge:
        """Generate a badge and save it, or return an existing one.

        If a badge already exists for the given attendee, template, and format
        combination, it is returned without regenerating. Otherwise a new badge
        is generated and persisted.

        Args:
            attendee: The attendee to generate a badge for.
            template: The badge template to use. If ``None``, the conference
                default template is used.
            badge_format: Output format — ``"pdf"`` or ``"png"``.

        Returns:
            The existing or newly created ``Badge`` instance.

        Raises:
            ValueError: If no template is provided and no default exists.
        """
        valid_formats = {Badge.Format.PDF, Badge.Format.PNG}
        if badge_format not in valid_formats:
            msg = f"Unsupported badge format '{badge_format}'. Must be one of: {', '.join(valid_formats)}"
            raise ValueError(msg)

        if template is None:
            template = BadgeTemplate.objects.filter(
                conference=attendee.conference,
                is_default=True,
            ).first()
            if template is None:
                msg = f"No default badge template found for conference '{attendee.conference.slug}'"
                raise ValueError(msg)

        existing = Badge.objects.filter(
            attendee=attendee,
            template=template,
            format=badge_format,
        ).first()
        if existing and existing.file:
            return existing

        if badge_format == Badge.Format.PNG:
            content = self.generate_badge_png(attendee, template)
            ext = "png"
        else:
            content = self.generate_badge_pdf(attendee, template)
            ext = "pdf"

        badge = existing or Badge(
            attendee=attendee,
            template=template,
            format=badge_format,
        )
        filename = f"badge-{attendee.access_code}.{ext}"
        badge.file.save(filename, ContentFile(content), save=False)
        badge.generated_at = timezone.now()
        badge.save()
        return badge

    def bulk_generate_badges(
        self,
        conference: Conference,
        template: BadgeTemplate | None = None,
        badge_format: str = "pdf",
        ticket_type: TicketType | None = None,
    ) -> Iterator[Badge]:
        """Generate badges for all attendees of a conference.

        Yields badges as they are generated, allowing progress tracking.
        Optionally filters attendees by ticket type.

        Args:
            conference: The conference whose attendees need badges.
            template: The badge template to use. If ``None``, the conference
                default template is used.
            badge_format: Output format — ``"pdf"`` or ``"png"``.
            ticket_type: When provided, only generate badges for attendees
                whose order contains this ticket type.

        Yields:
            ``Badge`` instances as they are generated.

        Raises:
            ValueError: If no template is provided and no default exists.
        """
        from django.db.models import Prefetch  # noqa: PLC0415

        from django_program.registration.attendee import Attendee  # noqa: PLC0415
        from django_program.registration.models import OrderLineItem  # noqa: PLC0415

        queryset = (
            Attendee.objects.filter(conference=conference)
            .select_related(
                "user",
                "conference",
                "order",
            )
            .prefetch_related(
                Prefetch(
                    "order__line_items",
                    queryset=OrderLineItem.objects.filter(ticket_type__isnull=False).select_related("ticket_type"),
                ),
            )
        )

        if ticket_type is not None:
            queryset = queryset.filter(
                order__line_items__ticket_type=ticket_type,
            ).distinct()

        for attendee in queryset:
            yield self.generate_or_get_badge(attendee, template=template, badge_format=badge_format)


@dataclass
class _PNGLayout:
    """Intermediate layout parameters for PNG badge rendering."""

    width: int
    height: int
    margin: int
    px_per_mm: float
    text_color: tuple[int, int, int]
    font_mono: object
