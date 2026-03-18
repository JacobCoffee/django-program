# Admin Reports

The admin reports dashboard provides conference organizers with detailed operational and financial reporting across nine specialized views. Each report offers filterable data tables, interactive charts, and CSV exports for offline analysis.

The dashboard is designed for three audiences:

- **Conference organizers** -- high-level overview of registration health, ticket inventory, and speaker status.
- **Finance staff** -- reconciliation, credit notes, discount impact, and revenue tracking.
- **Operations teams** -- attendee manifests, check-in progress, and registration flow trends.

## Permissions

Access to all report views requires authentication and at least one of:

| Requirement | Description |
|---|---|
| Superuser | Django superuser flag |
| Permission | `program_conference.change_conference` |
| Group membership | "Program: Reports" group |

The permission check is implemented by `ReportPermissionMixin`, which resolves the conference from the URL's `conference_slug` and raises `PermissionDenied` if the user fails all three checks.

To grant a user report access without broader organizer permissions, add them to the "Program: Reports" group:

```python
from django.contrib.auth.models import Group

reports_group, _ = Group.objects.get_or_create(name="Program: Reports")
user.groups.add(reports_group)
```

---

## Available Reports

All report URLs are nested under `/manage/<conference-slug>/reports/`. Each report page includes a CSV export link that respects the same filters applied to the HTML view.

### Reports Dashboard

**URL**: `/manage/<slug>/reports/`

The landing page aggregates summary statistics from all report types into a single overview. It displays:

- Attendee summary (total, checked in, completed registration)
- Ticket inventory breakdown with a stacked bar chart
- Order status distribution (donut chart)
- Payment method distribution (donut chart)
- Voucher redemption rates (bar chart)
- Check-in progress (radial ring)
- Speaker registration status (radial ring)
- Registration flow over the last 30 days (line chart)
- Budget vs. actuals (when budget fields are configured)
- 30-day revenue total

### Attendee Manifest

**URL**: `/manage/<slug>/reports/attendees/`
**CSV**: `/manage/<slug>/reports/attendees/export/`

A paginated, filterable list of all attendees registered for the conference.

| Filter | Values | Description |
|---|---|---|
| `ticket_type` | Ticket type ID | Show only attendees with a specific ticket type |
| `checked_in` | `yes` / `no` | Filter by check-in status |
| `completed` | `yes` / `no` | Filter by completed registration |

Filters are passed as GET parameters and also applied to the CSV export. The CSV includes columns for username, email, full name, ticket type, check-in time, access code, and completed registration status.

Charts on this page: check-in progress ring and ticket type distribution donut.

### Product Inventory

**URL**: `/manage/<slug>/reports/inventory/`
**CSV**: `/manage/<slug>/reports/inventory/export/`

Shows stock status for all ticket types and add-ons. Each row displays the product name, price, total quantity (or "Unlimited"), sold count, reserved count (pending orders with active holds), remaining count, and availability window.

The ticket inventory chart visualizes sold/reserved/remaining as horizontal stacked bars.

### Voucher Usage

**URL**: `/manage/<slug>/reports/vouchers/`
**CSV**: `/manage/<slug>/reports/vouchers/export/`

Lists every voucher for the conference with redemption metrics. Columns include the voucher code, type, discount value, max uses, times used, redemption rate (percentage), revenue impact (total discount amount from orders using the code), active status, and validity window.

Summary stats at the top show total vouchers, active count, used count, and aggregate revenue impact.

### Discount Effectiveness

**URL**: `/manage/<slug>/reports/discounts/`
**CSV**: `/manage/<slug>/reports/discounts/export/`

Groups all discount conditions by type (Time/Stock Limit, Speaker, Group Member, Included Product, Product Discount, Category Discount) and shows each condition's name, active status, priority, discount type/value, usage count, and applicable products.

The discount impact chart shows gross vs. net revenue, the overall discount rate, and a per-voucher breakdown.

### Sales by Date

**URL**: `/manage/<slug>/reports/sales/`
**CSV**: `/manage/<slug>/reports/sales/export/`

Daily aggregation of paid orders showing order count and revenue per day.

| Filter | Format | Description |
|---|---|---|
| `date_from` | `YYYY-MM-DD` | Start of date range (inclusive) |
| `date_until` | `YYYY-MM-DD` | End of date range (inclusive) |

Includes two charts: a revenue bar chart with order count overlay, and a cumulative revenue line chart.

### Credit Notes

**URL**: `/manage/<slug>/reports/credits/`
**CSV**: `/manage/<slug>/reports/credits/export/`

Lists all credit records for the conference with user info, amounts (issued and remaining), status, source order reference, applied-to order reference, notes, and creation date.

Summary stats show total credits issued, outstanding balance, and applied total. The refund gauge chart visualizes the refund rate relative to total revenue.

### Speaker Registration

**URL**: `/manage/<slug>/reports/speakers/`
**CSV**: `/manage/<slug>/reports/speakers/export/`

Shows every speaker synced from Pretalx with their registration status. Each row includes the speaker name, email, talk count, and whether they have a paid order for the conference.

Summary counts at the top show total speakers, registered count, and unregistered count. The speaker status ring chart visualizes the registration ratio.

### Reconciliation

**URL**: `/manage/<slug>/reports/reconciliation/`
**CSV**: `/manage/<slug>/reports/reconciliation/export/`

Financial reconciliation comparing order totals against payment records. The report computes:

| Metric | Description |
|---|---|
| Sales Total | Sum of `total` from paid and partially-refunded orders |
| Payments Total | Sum of `amount` from succeeded payments |
| Refunds Total | Sum of credit amounts linked to source orders |
| Credits Outstanding | Remaining balance of available credits |
| Discrepancy | Sales Total minus Payments Total |

Breakdowns by payment method and order status are shown in tables and charts. The cash flow waterfall chart traces the path from gross sales through discounts, refunds, and credits to net revenue.

### Registration Flow

**URL**: `/manage/<slug>/reports/flow/`
**CSV**: `/manage/<slug>/reports/flow/export/`

Daily registration and cancellation counts over time. Registrations are counted from `Attendee.created_at` dates; cancellations from `Order.updated_at` dates for cancelled orders.

| Filter | Format | Description |
|---|---|---|
| `date_from` | `YYYY-MM-DD` | Start of date range (inclusive) |
| `date_until` | `YYYY-MM-DD` | End of date range (inclusive) |

Each row shows the date, registration count, cancellation count, and net (registrations minus cancellations). The registration pulse chart visualizes registrations vs. cancellations as a dual-series line chart.

---

## Chart Components

The reports dashboard uses a library of 18 reusable chart components built on the HTML Canvas API. Charts are rendered client-side with animated transitions and interactive tooltips. No external charting library is required.

All chart templates live in:

```
src/django_program/manage/templates/django_program/manage/charts/
```

### Usage

Include the shared utilities script once per page, before any chart partials:

```html+django
{% include "django_program/manage/charts/_chart_utils.html" %}
```

Then include individual chart components, passing JSON data via the `with` keyword:

```html+django
{% include "django_program/manage/charts/_revenue_bar.html" with chart_data=chart_sales_json %}

{% include "django_program/manage/charts/_donut.html" with chart_data=data chart_title="Orders" chart_subtitle="By status" chart_center="TOTAL" chart_id="orders" %}
```

### Component Reference

| Component | Template | Expected Data Format |
|---|---|---|
| Chart Utilities | `_chart_utils.html` | N/A (shared script, include once per page) |
| Revenue Bar | `_revenue_bar.html` | `[{"date": "YYYY-MM-DD", "count": int, "revenue": float}, ...]` |
| Ticket Inventory | `_ticket_inventory.html` | `[{"name": str, "sold": int, "reserved": int, "remaining": int, "total": int}, ...]` |
| Order Status | `_order_status.html` | `[{"status": str, "count": int, "total": float}, ...]` |
| Payment Methods | `_payment_methods.html` | `[{"method": str, "count": int, "total": float}, ...]` |
| Registration Pulse | `_registration_pulse.html` | `[{"date": "YYYY-MM-DD", "registrations": int, "cancellations": int}, ...]` |
| Voucher Performance | `_voucher_performance.html` | `[{"code": str, "used": int, "max": int, "impact": float}, ...]` |
| Check-in Progress | `_checkin_progress.html` | `{"checked_in": int, "total": int}` |
| Speaker Status | `_speaker_status.html` | `{"registered": int, "unregistered": int, "total": int}` |
| Generic Donut | `_donut.html` | `[{"status": str, "count": int}, ...]` (or `label`/`value` keys) |
| AOV Line | `_aov_line.html` | `[{"date": "YYYY-MM-DD", "aov": float, "count": int}, ...]` |
| Revenue Stacked | `_revenue_stacked.html` | `[{"date": "YYYY-MM-DD", "ticket_type": str, "revenue": float, "count": int}, ...]` |
| Discount Impact | `_discount_impact.html` | `{"total_discount": float, "total_gross": float, "total_net": float, "discount_rate": float, "by_voucher": [...], "orders_with_discount": int, "orders_without_discount": int}` |
| Refund Gauge | `_refund_gauge.html` | `{"total_refunded": float, "total_revenue": float, "refund_rate": float, "refund_count": int, "by_status": {...}}` |
| Waterfall | `_waterfall.html` | `[{"label": str, "value": float, "type": "total"\|"increase"\|"decrease"}, ...]` |
| Cumulative Revenue | `_cumulative_revenue.html` | `[{"date": "YYYY-MM-DD", "daily": float, "cumulative": float}, ...]` |
| Budget Gauge | `_budget_gauge.html` | `{"revenue_target": float, "revenue_actual": float, "revenue_pct": float, ...}` |
| Stripe Fees | `_stripe_fees.html` | Uses payment data from context (estimated at 2.9% + $0.30 per transaction) |

### Generic Donut

The `_donut.html` component is the most flexible chart and accepts several configuration parameters:

| Parameter | Required | Description |
|---|---|---|
| `chart_data` | Yes | JSON array of objects with `status`/`label`/`name` and `count`/`value` keys |
| `chart_title` | No | Card header title (default: "Breakdown") |
| `chart_subtitle` | No | Card header subtitle (default: "Distribution") |
| `chart_center` | No | Label shown in the center of the donut (default: "TOTAL") |
| `chart_id` | No | Unique DOM ID suffix (default: "main"). Required when using multiple donuts on one page |

### Chart Utilities API

The `_chart_utils.html` script exposes `window._chartUtils` with:

- `setupCanvas(canvas)` -- HiDPI-aware canvas initialization, returns `{ctx, w, h}`
- `animate(duration, drawFn, doneFn)` -- requestAnimationFrame-based animation loop
- `showTooltip(event, html)` / `hideTooltip()` -- floating tooltip management
- `formatCurrency(n)` / `formatCurrencyFull(n)` -- currency formatting (`$1.2k` / `$1,234.56`)
- `formatNumber(n)` -- locale-aware number formatting
- `formatDateShort(iso)` -- short date display (`3/17`)
- `hexToRgba(hex, alpha)` -- color conversion
- `COLORS` -- named color constants (indigo, teal, violet, amber, emerald, red, blue, fuchsia)
- `STATUS_COLORS` -- order status to color mapping
- `METHOD_COLORS` -- payment method to color mapping

---

## Budget Tracking

Three optional fields on the `Conference` model enable budget-vs-actuals reporting:

| Field | Type | Description |
|---|---|---|
| `revenue_budget` | `DecimalField` | Target revenue for the conference |
| `target_attendance` | `PositiveIntegerField` | Target number of attendees |
| `grant_budget` | `DecimalField` | Travel grant budget allocation |

When any of these fields are set, the reports dashboard and financial dashboard display budget progress indicators.

### Setting Budget Values

**Via the management dashboard**: Navigate to `/manage/<slug>/settings/` and fill in the budget fields.

**Via TOML bootstrap config**: Add budget fields to your conference definition:

```toml
[conference]
name = "PyCon US 2026"
revenue_budget = 500000.00
target_attendance = 2500
grant_budget = 75000.00
```

### How Budget Metrics Are Computed

| Metric | Computation |
|---|---|
| Revenue progress | `SUM(total)` of paid/partially-refunded orders / `revenue_budget` |
| Attendance progress | `COUNT(attendees)` / `target_attendance` |
| Grant utilization | `SUM(approved_amount)` of accepted/offered grants / `grant_budget` |
| Grant disbursed | `SUM(disbursed_amount)` of disbursed grants (shown separately) |

---

## Financial Dashboard

The financial dashboard at `/manage/<slug>/financial/` provides a comprehensive single-page view of all conference finances. It is separate from the reports dashboard but shares the same chart components and report service layer.

The financial dashboard displays:

- **Summary cards**: net revenue, total orders, active carts, credits outstanding
- **Revenue Over Time**: daily revenue bar chart with order count line overlay (last 60 days)
- **Ticket Inventory**: sold/reserved/remaining stacked bars
- **Order Status**: donut chart by order status
- **Payment Methods**: donut chart by payment method
- **AOV Over Time**: average order value line chart
- **Revenue by Ticket Type**: stacked area chart
- **Cash Flow Waterfall**: gross sales through discounts, refunds, credits to net
- **Cumulative Revenue**: running total line chart
- **Discount Impact**: gross vs. net with discount rate
- **Refund Gauge**: refund rate as a percentage of revenue
- **Stripe Fees**: estimated processing fees (2.9% + $0.30/txn)
- **Budget vs. Actuals**: progress bars when budget fields are configured

The financial dashboard uses the "Program: Finance & Accounting" group for permission checks (in addition to superuser and `change_conference`).

For detailed data, use the report sub-pages which offer filtering and CSV export.

---

## Extending with Custom Reports

You can create custom report pages that use the existing chart components and permission infrastructure.

### Custom View

Subclass `ReportPermissionMixin` to get conference resolution and permission checks for free:

```python
import json

from django.views.generic import TemplateView

from django_program.manage.views_reports import ReportPermissionMixin


class MyCustomReportView(ReportPermissionMixin, TemplateView):
    template_name = "myapp/custom_report.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # self.conference is already resolved from the URL
        context["chart_data"] = json.dumps([
            {"label": "Category A", "value": 42},
            {"label": "Category B", "value": 58},
        ])
        return context
```

### Custom Template

Use the base management template and include chart partials:

```html+django
{% extends "django_program/manage/base.html" %}

{% block content %}
<h2>Custom Report</h2>

{% include "django_program/manage/charts/_chart_utils.html" %}

{% include "django_program/manage/charts/_donut.html" with chart_data=chart_data chart_title="My Breakdown" chart_subtitle="Custom categories" chart_center="ITEMS" chart_id="custom" %}
{% endblock %}
```

### Wiring the URL

Add your view to a URL configuration that nests under the reports prefix:

```python
from django.urls import path

from myapp.views import MyCustomReportView

urlpatterns = [
    path(
        "manage/<slug:conference_slug>/reports/custom/",
        MyCustomReportView.as_view(),
        name="report-custom",
    ),
]
```

---

## Seed Data for Development

The example project includes a seed script that generates realistic demo data for all report types, including orders, payments, attendees, vouchers, credits, speakers, and travel grants.

```bash
# Full dev setup (includes migrations + seed data)
make dev

# Or run the seed script directly
DJANGO_SETTINGS_MODULE=settings uv run python examples/seed.py
```

The seed script creates a "Program: Reports" group and a demo user with report access, so you can immediately explore the reports dashboard after seeding.

---

## Report Service Layer

All report data is computed by functions in {mod}`django_program.manage.reports`. Views are thin wrappers that call these functions and serialize the results for templates and CSV export. This separation makes it straightforward to use the same data in custom views, management commands, or API endpoints.

Key functions:

| Function | Returns |
|---|---|
| `get_attendee_manifest()` | Filtered `QuerySet[Attendee]` with user and order pre-loaded |
| `get_attendee_summary()` | Dict with total, checked_in, completed counts |
| `get_ticket_inventory()` | `QuerySet[TicketType]` annotated with sold_count, reserved_count |
| `get_addon_inventory()` | `QuerySet[AddOn]` annotated with sold_count, reserved_count |
| `get_voucher_usage()` | `QuerySet[Voucher]` annotated with revenue_impact |
| `get_voucher_summary()` | Dict with total, active, used, total_revenue_impact |
| `get_discount_conditions()` | Dict mapping condition type names to condition data lists |
| `get_discount_summary()` | Dict with total and active condition counts |
| `get_discount_impact()` | Dict with gross/net/discount totals and per-voucher breakdown |
| `get_sales_by_date()` | List of dicts with date, count, revenue |
| `get_credit_notes()` | `QuerySet[Credit]` with related objects pre-loaded |
| `get_credit_summary()` | Dict with count, total_issued, total_outstanding, total_applied |
| `get_speaker_registrations()` | `QuerySet[Speaker]` annotated with has_paid_order, talk_count |
| `get_reconciliation()` | Dict with sales/payments/refunds/credits totals and breakdowns |
| `get_registration_flow()` | List of dicts with date, registrations, cancellations |
| `get_aov_by_date()` | List of dicts with date, aov, count |
| `get_revenue_by_ticket_type()` | List of dicts with date, ticket_type, revenue, count |
| `get_refund_metrics()` | Dict with refund totals, rate, and status breakdown |
| `get_cashflow_waterfall()` | List of waterfall steps (label, value, type) |
| `get_cumulative_revenue()` | List of dicts with date, daily, cumulative |
