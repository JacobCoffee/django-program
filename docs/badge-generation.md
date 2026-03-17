# Badge Generation

Badge generation produces print-ready attendee badges with QR codes for on-site check-in. Badges are rendered as PDF (via reportlab) or PNG (via Pillow) and can be generated individually or in bulk for an entire conference.

## Models

| Model | Purpose |
|---|---|
| {class}`~django_program.registration.badges.BadgeTemplate` | A reusable layout definition for a conference. Controls dimensions, colors, content toggles, and optional logo. One template per conference can be marked as the default. |
| {class}`~django_program.registration.badges.Badge` | A generated badge file linked to an attendee and template. Stores the rendered file (PDF or PNG) and tracks generation metadata. |

## Badge Templates

A badge template defines the visual layout and content of generated badges. Each template belongs to a single conference and can be marked as the default for that conference.

### Dimensions

Templates use millimeter measurements matching standard badge/card sizes:

| Field | Default | Description |
|---|---|---|
| `width_mm` | `86` | Badge width in millimeters |
| `height_mm` | `54` | Badge height in millimeters |

The default 86x54mm matches a standard credit card / ISO 7810 ID-1 size, which fits most badge holders and lanyards.

### Content Toggles

Boolean fields control which elements appear on the badge:

| Field | Default | Description |
|---|---|---|
| `show_name` | `True` | Attendee's full name |
| `show_email` | `False` | Attendee's email address |
| `show_company` | `True` | Company or organization |
| `show_ticket_type` | `True` | Ticket type label (e.g. "Individual", "Speaker") |
| `show_qr_code` | `True` | QR code for check-in scanning |
| `show_conference_name` | `True` | Conference name header |

### Color Customization

Three color fields accept hex color codes:

| Field | Default | Description |
|---|---|---|
| `background_color` | `#FFFFFF` | Badge background |
| `text_color` | `#000000` | Primary text color |
| `accent_color` | `#3B82F6` | Accent elements (header bar, ticket type label) |

### Conference Logo

The optional `logo` field accepts an image upload. When set, the logo is rendered on the badge alongside the conference name. The logo is scaled proportionally to fit within the badge layout.

### Default Template

Each conference can have one default template, controlled by the `is_default` boolean field. When a new template is saved with `is_default=True`, any existing default template for the same conference is automatically unset. The default template is used when generating badges without explicitly specifying a template.

## QR Code Generation

Each badge includes a QR code (unless `show_qr_code` is disabled on the template) that encodes a string in the format:

```
{conference_slug}:{access_code}
```

For example, a badge for an attendee with access code `A3K9M2X1` at conference `pycon-us-2027` encodes:

```
pycon-us-2027:A3K9M2X1
```

This format gives check-in scanners everything they need: the conference context and the unique attendee identifier. The access code maps directly to the {class}`~django_program.registration.attendee.Attendee` model's `access_code` field.

## Output Formats

### PDF

PDF output uses reportlab to produce vector-based badges suitable for professional print shops. PDF badges scale cleanly to any DPI and support CMYK workflows when needed. This is the recommended format for bulk printing.

### PNG

PNG output uses Pillow to render raster badges at 300 DPI. PNG works well for on-site badge printing with thermal or inkjet printers, and for quick previews in the management dashboard.

## Badge Service API

The `BadgeGenerationService` in `django_program.registration.services.badges` provides programmatic access to all badge operations.

### Generating a QR Code

```python
from django_program.registration.services.badges import BadgeGenerationService

# Returns PNG bytes of the QR code image
qr_bytes = BadgeGenerationService.generate_qr_code(
    data="pycon-us-2027:A3K9M2X1",
    size=200,  # pixels
)
```

### Generating a Single Badge

```python
from django_program.registration.services.badges import BadgeGenerationService

# PDF output
pdf_bytes = BadgeGenerationService.generate_badge_pdf(attendee, template)

# PNG output
png_bytes = BadgeGenerationService.generate_badge_png(attendee, template)
```

Both methods return raw bytes of the rendered badge file.

### Get or Create

```python
badge = BadgeGenerationService.generate_or_get_badge(
    attendee,
    template,
    format="pdf",  # or "png"
)
```

Returns an existing `Badge` record if one already exists for this attendee/template/format combination. Otherwise generates a new badge, saves the file, and returns the new `Badge` instance. This prevents redundant re-generation when an attendee's badge has already been created.

### Bulk Generation

```python
badges = BadgeGenerationService.bulk_generate_badges(
    conference,
    template,
    format="pdf",
    ticket_type=None,  # optional: filter attendees by ticket type
)
```

Generates badges for all attendees of the conference (or a subset filtered by ticket type). Returns a list of `Badge` instances. Attendees who already have a badge for the given template and format are skipped.

## Badge Management UI

Badge management is available in the organizer dashboard under **Registration > Badges** at `/manage/<conference-slug>/badges/`.

### Template Management

- **List templates** -- View all badge templates for the conference with their dimensions, default status, and badge count.
- **Create template** -- Define a new template with dimensions, colors, content toggles, and optional logo.
- **Edit template** -- Update an existing template. Previously generated badges are not automatically regenerated.
- **Preview** -- Render a sample badge from the template before committing to a full generation run.

### Badge Generation

- **Generate badges** -- Bulk generate badges for all attendees, optionally filtered by ticket type. Select the template and output format (PDF or PNG).
- **Download individual** -- Download a single attendee's badge from the attendee list or badge list.
- **Bulk download** -- Download all generated badges as a ZIP archive, organized for print shop delivery.

## Django Admin

Both `BadgeTemplate` and `Badge` are registered in the Django admin:

- **BadgeTemplate** -- Create and edit templates with all layout fields. The admin enforces one default template per conference.
- **Badge** -- Read-only view of generated badges with links to the attendee, template, and downloadable file.

## Self-Service Badge Access

A future release will allow attendees to download their own badge using their access code, without needing to log in. This is planned but not yet implemented.

---

## Workflow Example

A typical badge workflow for a conference:

1. **Create a template** in the management dashboard with your conference branding (colors, logo, dimensions).
2. **Preview** the template to verify the layout looks correct.
3. **Bulk generate** PDF badges for all attendees after registration closes.
4. **Download the ZIP** and send to your print shop.
5. **Generate individual badges** on-site for late registrations or replacements.
6. **Scan QR codes** at check-in using any standard QR scanner app -- the `{conference_slug}:{access_code}` payload identifies the attendee.
