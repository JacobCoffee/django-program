# Programs & Activities

The `django_program.programs` app handles conference activities (sprints, tutorials, open spaces) and travel grant applications. All views are scoped to a conference via the `conference_slug` URL parameter and gated behind feature flags.

## Travel Grants

Travel grants follow the PyCon US model: attendees apply for financial assistance, reviewers evaluate and offer grants, and recipients submit receipts for reimbursement.

### Application flow

An attendee submits a {class}`~django_program.programs.models.TravelGrant` through the `TravelGrantApplyView`. The application form collects:

- **Request type** -- ticket only, or ticket plus travel grant.
- **Travel details** -- origin city, international flag, first-time attendee status.
- **Travel plan breakdown** -- airfare and lodging with descriptions and estimated amounts.
- **Requested amount** -- total USD amount requested. Validated against `max_grant_amount` from `DJANGO_PROGRAM` settings (default `3000`).
- **Applicant profile** -- experience level, occupation, community involvement, and reason for the grant.
- **Days attending** -- which conference days the applicant plans to attend (see [Day Detection](#day-detection) below).

Each user can submit one grant application per conference, enforced by a `unique_together` constraint on `(conference, user)`.

### Day detection

The `days_attending` field renders as a set of checkboxes with labels derived from the conference schedule. The form uses a two-tier strategy to build these labels:

**Tier 1: Schedule-derived days** -- `get_conference_days()` in `django_program.programs.utils` queries `ScheduleSlot` records for the conference. For each unique date, it counts the `submission_type` of linked talks. When one type accounts for more than half the slots on a given day, that type name is appended to the date label:

```
Wednesday, May 14 (Tutorial)
Thursday, May 15 (Tutorial)
Friday, May 16 (Talk)
Saturday, May 17 (Talk)
Sunday, May 18
```

**Tier 2: Section-based fallback** -- when no schedule slots exist (e.g., before a Pretalx sync), the form falls back to `_build_day_choices()`. This method iterates conference `Section` records and labels each date with the section name and day number:

```
Tutorials Day 1 -- Wednesday, May 14
Tutorials Day 2 -- Thursday, May 15
Talks Day 1 -- Friday, May 16
Talks Day 2 -- Saturday, May 17
Sprints Day 1 -- Sunday, May 18
```

Days not covered by any section get a generic `Day N` label.

The selected checkboxes are serialized to a comma-separated string for storage in `TravelGrant.days_attending`. On edit, the stored string is split back into checkbox selections.

### Grant statuses and lifecycle

The `TravelGrant.GrantStatus` choices define the full lifecycle:

| Status | Description | Applicant can... |
|---|---|---|
| `SUBMITTED` | Application received, awaiting review. | Edit, withdraw, send messages. |
| `INFO_NEEDED` | Reviewers requested more information. | Provide info (resets to `SUBMITTED`), edit, withdraw. |
| `OFFERED` | Grant approved and offer extended. | Accept or decline. |
| `NEED_MORE` | Applicant requesting additional funds. | -- |
| `ACCEPTED` | Applicant accepted the offer. | Upload receipts, submit payment info. |
| `REJECTED` | Application denied. | -- |
| `DECLINED` | Applicant declined the offer. | -- |
| `WITHDRAWN` | Applicant withdrew the application. | -- |
| `DISBURSED` | Funds sent to the recipient. | -- |

State transitions are enforced by property guards on the model (`is_editable`, `is_actionable`, `show_accept_button`, etc.) and checked in each view before allowing the action.

### Receipts and payment info

After accepting a grant, the recipient uploads expense receipts through `ReceiptUploadView`:

- **Receipt types**: `AIRFARE` and `LODGING`.
- **File validation**: PDF, JPG, JPEG, or PNG, max 10 MB.
- **Review workflow**: receipts start as pending, can be approved or flagged by reviewers with a reason.
- **Deletion**: applicants can delete receipts that have not been approved or flagged.

Payment information is collected via {class}`~django_program.programs.models.PaymentInfo`, a one-to-one model on the grant. Supported payment methods:

- Zelle
- PayPal
- ACH (Direct Deposit)
- Wire Transfer
- Wise
- Check

Sensitive fields (bank account numbers, routing numbers, email addresses) are stored using `EncryptedCharField` and `EncryptedTextField`. Method-specific fields are validated in `PaymentInfoForm.clean()` -- selecting PayPal requires a PayPal email, selecting ACH requires bank name, account number, and routing number, and so on.

A grant is ready for disbursement (`is_ready_for_disbursement`) when its status is `ACCEPTED`, it has a `PaymentInfo` record, and at least one approved receipt exists.

### Max grant amount

The maximum requestable amount is set by `DJANGO_PROGRAM["max_grant_amount"]` (default `3000`). The `TravelGrantApplicationForm` validates this during `clean()` when the request type is `TICKET_AND_GRANT`. Configure it in your Django settings:

```python
DJANGO_PROGRAM = {
    "max_grant_amount": 5000,  # USD
    # ...
}
```

### Messaging

Both applicants and reviewers can exchange messages on a grant via {class}`~django_program.programs.models.TravelGrantMessage`. Each message has a `visible` flag:

- **Applicant messages** are always visible to reviewers.
- **Reviewer messages** with `visible=True` appear on the applicant's status page.
- **Reviewer messages** with `visible=False` are internal notes, visible only to other reviewers.

### Admin management

Reviewers manage grants through the management dashboard (`django_program.manage`). The `TravelGrantForm` in the dashboard exposes `status`, `approved_amount`, `promo_code`, and `reviewer_notes`. The `ReviewerMessageForm` lets reviewers send messages with visibility control.

The disbursement flow uses `DisbursementForm` to record the actual amount sent and timestamp.

Permissions are controlled by the `review_travel_grant` custom permission on the `TravelGrant` model and `review_receipt` on the `Receipt` model.

## Activities

Activities represent scheduled or drop-in events at the conference: sprints, workshops, tutorials, lightning talks, social events, open spaces, and summits.

### Activity types

The {class}`~django_program.programs.models.Activity` model supports these types via `ActivityType`:

| Type | Label |
|---|---|
| `SPRINT` | Sprint |
| `WORKSHOP` | Workshop |
| `TUTORIAL` | Tutorial |
| `LIGHTNING_TALK` | Lightning Talk |
| `SOCIAL` | Social Event |
| `OPEN_SPACE` | Open Space |
| `SUMMIT` | Summit |
| `OTHER` | Other |

### Signup caps and waitlisting

Set `max_participants` on an activity to limit signups. When `max_participants` is `None`, signups are unlimited.

When an activity reaches capacity, new signups are created with status `WAITLISTED` instead of `CONFIRMED`. Cancelling a confirmed signup automatically promotes the oldest waitlisted signup via `promote_next_waitlisted()`, which runs inside a transaction with `select_for_update()` to prevent race conditions.

```python
activity.spots_remaining  # int | None -- None means unlimited
```

Each user can have at most one active (non-cancelled) signup per activity, enforced by a conditional `UniqueConstraint`.

### Pretalx integration

Activities can link to Pretalx submission types via the `pretalx_submission_type` field. During a Pretalx sync, all talks matching that submission type are added to the activity's `talks` M2M relationship. The activity detail page then displays linked talks grouped by day with their speakers and schedule slots.

### API reference

For full model, form, and view details, see the autodoc reference:

- {mod}`django_program.programs.models`
- {mod}`django_program.programs.forms`
- {mod}`django_program.programs.views`
