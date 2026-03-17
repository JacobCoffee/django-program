"""Badge generation service for creating attendee badges with QR codes.

Generates PDF and PNG badges using reportlab and Pillow respectively,
with embedded QR codes encoding the attendee's access code for check-in
scanning.
"""

import io
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from django.core.files.base import ContentFile
from django.utils import timezone

from django_program.registration.badge import Badge, BadgeTemplate

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from django_program.conference.models import Conference
    from django_program.registration.attendee import Attendee
    from django_program.registration.models import TicketType

_MIN_FONT_SIZE = 8
_FONT_CACHE: dict[str, str] = {}


def _resolve_font_path(font_name: str) -> str | None:
    """Resolve a font name to a file path.

    Searches in order:
    1. Absolute path (if the string is already a valid file)
    2. Django STATICFILES_DIRS
    3. Django STATIC_ROOT
    4. Common system font directories

    Args:
        font_name: Font filename or path (e.g. "Roboto-Bold.ttf" or "/path/to/font.ttf").

    Returns:
        Resolved absolute path, or ``None`` if not found.
    """
    from pathlib import Path  # noqa: PLC0415

    if not font_name:
        return None

    if font_name in _FONT_CACHE:
        return _FONT_CACHE[font_name]

    # Direct path
    if Path(font_name).is_file():
        _FONT_CACHE[font_name] = font_name
        return font_name

    from django.conf import settings  # noqa: PLC0415

    # Search STATICFILES_DIRS
    search_dirs: list[str | Path] = []
    search_dirs.extend(getattr(settings, "STATICFILES_DIRS", []))
    static_root = getattr(settings, "STATIC_ROOT", None)
    if static_root:
        search_dirs.append(static_root)

    # Common system font dirs
    search_dirs.extend(
        [
            "/usr/share/fonts",
            "/usr/local/share/fonts",
            Path.home() / ".fonts",
            Path.home() / "Library/Fonts",
            "/System/Library/Fonts",
            "/Library/Fonts",
        ]
    )

    for base_dir in search_dirs:
        base = Path(base_dir)
        if not base.exists():
            continue
        # Direct match
        candidate = base / font_name
        if candidate.is_file():
            _FONT_CACHE[font_name] = str(candidate)
            return str(candidate)
        # Recursive search
        for match in base.rglob(font_name):
            if match.is_file():
                _FONT_CACHE[font_name] = str(match)
                return str(match)

    return None


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

    canvas: object
    width: float
    height: float
    margin: float
    mm_unit: float
    accent_rgb: tuple[float, float, float]
    text_rgb: tuple[float, float, float]
    font_name: str = "Helvetica-Bold"
    font_body: str = "Helvetica"


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

    @staticmethod
    def _register_pdf_font(font_spec: str, register_name: str) -> str | None:
        """Resolve and register a TrueType font for PDF rendering.

        Args:
            font_spec: Font filename or path to resolve.
            register_name: Name to register the font under in reportlab.

        Returns:
            The registered font name, or ``None`` if registration failed.
        """
        if not font_spec:
            return None
        path = _resolve_font_path(font_spec)
        if not path:
            return None
        from reportlab.pdfbase import pdfmetrics  # noqa: PLC0415
        from reportlab.pdfbase.ttfonts import TTFont  # noqa: PLC0415

        try:
            pdfmetrics.registerFont(TTFont(register_name, path))
        except Exception:  # noqa: BLE001
            logger.warning("Failed to register font '%s' from '%s'", font_spec, path)
            return None
        return register_name

    def _pdf_centered(  # noqa: PLR0913
        self, layout: _PDFLayout, text: str, font: str, max_size: int, min_size: int, y: float
    ) -> float:
        """Draw centered text on a PDF canvas, auto-shrinking to fit.

        Args:
            layout: PDF layout parameters including canvas and dimensions.
            text: The text to draw.
            font: The font name.
            max_size: Starting font size.
            min_size: Minimum font size.
            y: Vertical position.

        Returns:
            The font size that was used.
        """
        c = layout.canvas
        max_w = layout.width - 2 * layout.margin
        font_size = max_size
        c.setFont(font, font_size)  # type: ignore[attr-defined]
        tw = c.stringWidth(text, font, font_size)  # type: ignore[attr-defined]
        while tw > max_w and font_size > min_size:
            font_size -= 1
            tw = c.stringWidth(text, font, font_size)  # type: ignore[attr-defined]
        c.setFont(font, font_size)  # type: ignore[attr-defined]
        c.drawString((layout.width - tw) / 2, y, text)  # type: ignore[attr-defined]
        return font_size

    def _pdf_draw_name(self, layout: _PDFLayout, attendee: Attendee, content_top: float) -> float:
        """Draw the attendee name as the dominant badge element.

        Splits multi-word names across lines for maximum readability.

        Args:
            layout: PDF layout parameters.
            attendee: The attendee.
            content_top: Starting y position.

        Returns:
            Updated content_top position.
        """
        display_name = self._get_attendee_display_name(attendee)
        name_parts = display_name.split()
        mm = layout.mm_unit

        font = layout.font_name
        if len(name_parts) > 1:
            first = name_parts[0]
            last = " ".join(name_parts[1:])
            font_size = 42.0
            for line, y_offset in [(first, 0), (last, 1)]:
                font_size = self._pdf_centered(layout, line, font, 42, 18, content_top - y_offset * (font_size + 6))
            content_top -= 2 * (font_size + 6) + 4 * mm
        else:
            font_size = self._pdf_centered(layout, display_name, font, 42, 18, content_top)
            content_top -= font_size + 8 * mm

        return content_top

    def _pdf_draw_background(self, layout: _PDFLayout, template: BadgeTemplate) -> None:
        """Draw background color and optional background image.

        Args:
            layout: PDF layout parameters.
            template: Badge template with background settings.
        """
        from reportlab.lib.utils import ImageReader  # noqa: PLC0415

        c = layout.canvas
        c.setFillColorRGB(*_hex_to_reportlab(str(template.background_color)))  # type: ignore[attr-defined]
        c.rect(0, 0, layout.width, layout.height, fill=1, stroke=0)  # type: ignore[attr-defined]

        if template.background_image and template.background_image.name:
            try:
                bg_img = ImageReader(template.background_image.path)
                c.drawImage(  # type: ignore[attr-defined]
                    bg_img, 0, 0, width=layout.width, height=layout.height, preserveAspectRatio=True, anchor="c"
                )
            except FileNotFoundError, OSError:
                pass

    def _pdf_draw_header(self, layout: _PDFLayout, attendee: Attendee, template: BadgeTemplate) -> float:
        """Draw the accent header bar with logo and conference name.

        Args:
            layout: PDF layout parameters.
            attendee: The attendee (for conference name).
            template: Badge template with logo and color settings.

        Returns:
            The y position below the header.
        """
        from reportlab.lib.utils import ImageReader  # noqa: PLC0415

        mm = layout.mm_unit
        c = layout.canvas
        header_h = 22 * mm

        # Only draw header bar if no custom background image
        if not (template.background_image and template.background_image.name):
            c.setFillColorRGB(*layout.accent_rgb)  # type: ignore[attr-defined]
            c.rect(0, layout.height - header_h, layout.width, header_h, fill=1, stroke=0)  # type: ignore[attr-defined]

        # Logo — left side of header
        if template.logo and template.logo.name:
            try:
                logo_img = ImageReader(template.logo.path)
                logo_h = 14 * mm
                iw, ih = logo_img.getSize()
                logo_w = logo_h * (iw / ih)
                logo_x = layout.margin
                logo_y = layout.height - header_h + (header_h - logo_h) / 2
                c.drawImage(logo_img, logo_x, logo_y, width=logo_w, height=logo_h)  # type: ignore[attr-defined]
            except FileNotFoundError, OSError:
                pass

        # Conference name — centered (or right of logo)
        if template.show_conference_name:
            c.setFillColorRGB(1, 1, 1)  # type: ignore[attr-defined]
            conf_name = str(attendee.conference.name)
            conf_y = layout.height - header_h + (header_h - 18) / 2
            self._pdf_centered(layout, conf_name, layout.font_name, 18, 10, conf_y)

        return layout.height - header_h

    def generate_badge_pdf(self, attendee: Attendee, template: BadgeTemplate) -> bytes:
        """Generate a conference-style portrait badge as PDF.

        Fills the page with content: header with logo, huge centered name,
        company/email, ticket type, and QR code. Supports custom background
        images from a graphic designer.

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
        margin = 6 * mm

        accent_rgb = _hex_to_reportlab(str(template.accent_color))
        text_rgb = _hex_to_reportlab(str(template.text_color))

        buf = io.BytesIO()
        c = canvas.Canvas(buf, pagesize=(width, height))

        # Resolve custom fonts
        name_font = "Helvetica-Bold"
        body_font = "Helvetica"
        font_name_str = str(template.font_name) if template.font_name else ""
        font_body_str = str(template.font_body) if template.font_body else ""
        name_font = self._register_pdf_font(font_name_str, "CustomName") or name_font
        body_font = self._register_pdf_font(font_body_str, "CustomBody") or body_font

        layout = _PDFLayout(
            canvas=c,
            width=width,
            height=height,
            margin=margin,
            mm_unit=mm,
            accent_rgb=accent_rgb,
            text_rgb=text_rgb,
            font_name=name_font,
            font_body=body_font,
        )

        self._pdf_draw_background(layout, template)
        header_bottom = self._pdf_draw_header(layout, attendee, template)

        ticket_label = self._get_ticket_type_label(attendee) if template.show_ticket_type else ""
        banner_pos = str(template.ticket_banner_position)

        # Draw banner at configured position (below_header draws it now, others defer to body)
        if banner_pos == BadgeTemplate.BannerPosition.BELOW_HEADER:
            header_bottom = self._pdf_draw_ticket_banner(layout, ticket_label, header_bottom)
            ticket_label = ""  # consumed

        qr_zone_h = 30 * mm if template.show_qr_code else 8 * mm
        self._pdf_draw_body(layout, attendee, template, ticket_label, banner_pos, header_bottom, margin + qr_zone_h)

        if template.show_qr_code:
            self._pdf_draw_qr(layout, attendee)

        c.showPage()
        c.save()
        return buf.getvalue()

    def _pdf_draw_ticket_banner(self, layout: _PDFLayout, ticket_label: str, header_bottom: float) -> float:
        """Draw a colored ticket-type banner below the header for special types.

        Speaker, Sponsor, and other non-general ticket types get a prominent
        banner. General Admission is shown inline with the body text instead.

        Args:
            layout: PDF layout parameters.
            ticket_label: The ticket type label.
            header_bottom: Y position of the bottom of the header.

        Returns:
            Updated header_bottom position.
        """
        if ticket_label and ticket_label != "General Admission":
            mm = layout.mm_unit
            c = layout.canvas
            banner_h = 10 * mm
            c.setFillColorRGB(*layout.accent_rgb)  # type: ignore[attr-defined]
            c.rect(0, header_bottom - banner_h, layout.width, banner_h, fill=1, stroke=0)  # type: ignore[attr-defined]
            c.setFillColorRGB(1, 1, 1)  # type: ignore[attr-defined]
            banner_y = header_bottom - banner_h + 3 * mm
            self._pdf_centered(layout, ticket_label.upper(), "Helvetica-Bold", 14, 10, banner_y)
            return header_bottom - banner_h
        return header_bottom

    def _pdf_draw_body(  # noqa: PLR0913, C901, PLR0912
        self,
        layout: _PDFLayout,
        attendee: Attendee,
        template: BadgeTemplate,
        ticket_label: str,
        banner_pos: str,
        header_bottom: float,
        content_floor: float,
    ) -> None:
        """Draw the body content (name, company, email) vertically centered.

        Also draws the ticket type banner at the configured position
        if it wasn't already drawn below the header.

        Args:
            layout: PDF layout parameters.
            attendee: The attendee.
            template: Badge template.
            ticket_label: Ticket type label (empty if already drawn).
            banner_pos: Banner position from template config.
            header_bottom: Top of available content zone.
            content_floor: Bottom of available content zone.
        """
        c = layout.canvas
        mm = layout.mm_unit
        is_special = ticket_label and ticket_label != "General Admission"

        # Estimate content height for vertical centering
        content_h = 0.0
        if is_special and banner_pos == BadgeTemplate.BannerPosition.ABOVE_NAME:
            content_h += 14 * mm
        if template.show_name:
            content_h += 50
        if is_special and banner_pos == BadgeTemplate.BannerPosition.BELOW_NAME:
            content_h += 14 * mm
        if template.show_company and self._get_company(attendee):
            content_h += 24
        if template.show_email:
            content_h += 20
        if not is_special and ticket_label:
            content_h += 20

        zone_top = header_bottom - 4 * mm
        zone_h = zone_top - content_floor
        y = zone_top - max(0, (zone_h - content_h) / 2)

        if is_special and banner_pos == BadgeTemplate.BannerPosition.ABOVE_NAME:
            y = self._pdf_draw_ticket_banner(layout, ticket_label, y + 10 * mm)
            y -= 4 * mm

        if template.show_name:
            c.setFillColorRGB(*layout.text_rgb)  # type: ignore[attr-defined]
            y = self._pdf_draw_name(layout, attendee, y)

        if is_special and banner_pos == BadgeTemplate.BannerPosition.BELOW_NAME:
            y_before = y
            y = self._pdf_draw_ticket_banner(layout, ticket_label, y + 10 * mm)
            y = min(y, y_before) - 4 * mm

        if template.show_company:
            company = self._get_company(attendee)
            if company:
                c.setFillColorRGB(*layout.text_rgb)  # type: ignore[attr-defined]
                self._pdf_centered(layout, company, layout.font_body, 16, 10, y)
                y -= 8 * mm

        if template.show_email:
            c.setFillColorRGB(*layout.text_rgb)  # type: ignore[attr-defined]
            self._pdf_centered(layout, str(attendee.user.email), layout.font_body, 13, 8, y)
            y -= 7 * mm

        if not is_special and ticket_label:
            c.setFillColorRGB(*layout.accent_rgb)  # type: ignore[attr-defined]
            self._pdf_centered(layout, ticket_label, "Helvetica-Bold", 14, 10, y)

        if is_special and banner_pos == BadgeTemplate.BannerPosition.BOTTOM:
            self._pdf_draw_ticket_banner(layout, ticket_label, content_floor + 14 * mm)

    def _pdf_draw_qr(self, layout: _PDFLayout, attendee: Attendee) -> None:
        """Draw QR code with white backing and access code in the bottom-right.

        The white backing ensures QR readability on any background color
        or custom background image.

        Args:
            layout: PDF layout parameters.
            attendee: The attendee whose QR code to render.
        """
        from reportlab.lib.utils import ImageReader  # noqa: PLC0415

        mm = layout.mm_unit
        c = layout.canvas
        qr_size = 20 * mm
        pad = 2 * mm
        qr_bytes = self.generate_qr_code(self._get_qr_data(attendee), size=200)
        qr_x = layout.width - qr_size - layout.margin
        qr_y = layout.margin + 4 * mm

        # White backing with rounded corners for readability on any background
        c.setFillColorRGB(1, 1, 1)  # type: ignore[attr-defined]
        c.setStrokeColorRGB(0.85, 0.85, 0.85)  # type: ignore[attr-defined]
        c.roundRect(  # type: ignore[attr-defined]
            qr_x - pad,
            qr_y - pad - 3 * mm,
            qr_size + 2 * pad,
            qr_size + 2 * pad + 5 * mm,
            radius=2 * mm,
            fill=1,
            stroke=1,
        )

        c.drawImage(  # type: ignore[attr-defined]
            ImageReader(io.BytesIO(qr_bytes)), qr_x, qr_y, width=qr_size, height=qr_size
        )
        c.setFillColorRGB(0, 0, 0)  # type: ignore[attr-defined]
        c.setFont("Courier", 7)  # type: ignore[attr-defined]
        code_text = str(attendee.access_code)
        code_width = c.stringWidth(code_text, "Courier", 7)  # type: ignore[attr-defined]
        c.drawString(qr_x + (qr_size - code_width) / 2, qr_y - 3 * mm, code_text)  # type: ignore[attr-defined]

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
