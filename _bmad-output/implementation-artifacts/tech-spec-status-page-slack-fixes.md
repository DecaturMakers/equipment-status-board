---
title: 'Status Page & Slack Notification Fixes (Issues #52, #53, #54)'
slug: 'status-page-slack-fixes'
created: '2026-06-07'
status: 'Completed'
stepsCompleted: [1, 2, 3, 4]
tech_stack: ['Python 3.14', 'Flask', 'Flask-SQLAlchemy', 'MariaDB (Docker) / SQLite in tests', 'Slack Bolt SDK', 'Jinja2', 'Flask-WTF', 'pytest', 'ruff']
files_to_modify:
  - 'esb/templates/public/static_page.html'
  - 'esb/slack/handlers.py'
  - 'esb/services/repair_service.py'
  - 'esb/services/notification_service.py'
  - 'esb/forms/admin_forms.py'
  - 'esb/views/admin.py'
  - 'esb/templates/admin/config.html'
  - 'pyproject.toml'
  - 'tests/test_services/test_static_page_service.py'
  - 'tests/test_slack/test_handlers.py'
  - 'tests/test_services/test_repair_service.py'
  - 'tests/test_services/test_notification_service.py'
  - 'tests/test_views/test_admin_views.py'
code_patterns:
  - 'Service layer: views/Slack handlers delegate to esb/services/'
  - 'Notifications queued via notification_service.queue_notification(), delivered by background worker'
  - 'Slack triggers gated by config_service.get_config("notify_<event>", "true")'
  - 'Slack message text formatted centrally in notification_service._format_slack_message(payload) keyed on event_type'
  - 'update_repair_record() builds audit_changes {field: [old, new]} and queues notifications from it'
  - 'ESB-user -> Slack-ID resolution via client.users_lookupByEmail(email=...) (user_service.py:271)'
test_patterns:
  - 'pytest with SQLite in-memory DB; fixtures in tests/conftest.py (app, client, db, staff_client, make_equipment, make_repair_record)'
  - 'Slack handler tests capture handlers via mock Bolt decorators (_register_and_capture), invoke with MagicMock ack/client/body/view'
  - 'Notification format tests call _format_slack_message directly (pure function)'
  - 'Admin trigger tests POST to /admin/config and assert config_service values'
---

# Tech-Spec: Status Page & Slack Notification Fixes (Issues #52, #53, #54)

**Created:** 2026-06-07 (revised after adversarial review round 1)

## Overview

### Problem Statement

Three small UX defects, tracked as GitHub Issues #52, #53, and #54:

1. **Issue #52** — On the static status page, the generated date/time is right-aligned and gray (`#6c757d`), making it visually unobtrusive to the point that users might miss it.
2. **Issue #53** — In the `/esb-repair` Slack flow, after selecting a repair, editing it, and clicking "Apply", the user is sent back to the "Open Repairs" dialog instead of the flow terminating.
3. **Issue #54** — When a repair is assigned, the Slack notification only says it was assigned (`New -> Assigned`); it does not say who it was assigned to.

### Solution

1. CSS change in the static page template: center the generated timestamp under the page title and make it black.
2. Change the final `ack()` in the `/esb-repair` action-modal submission handler to `ack(response_action='clear')` so the entire modal stack closes; the ephemeral confirmation message still posts.
3. Include the assignee in Slack notifications — a real Slack @mention (resolved by email) when the user has a `slack_handle` set, falling back to ESB username. Specifically:
   - **Any open-transition status change** that also changes the assignee in the same update gets an assignee delta line appended to the `status_changed` message (assigned / reassigned with previous name / unassigned with previous name — the assignee change is never swallowed).
   - A **new `assignee_changed` event type** (with its own admin notification-trigger toggle, `notify_assignee_changed`) fires when the assignee changes without a status change, OR as a fall-through when a combined status+assignee update is suppressed because `notify_status_changed` is disabled — assignment visibility is always governed by its own toggle.
   - **Assignment at creation**: when a repair record is created already assigned, the `new_report` message gains an "Assigned to:" line.
   - Closed transitions (`resolved` event) are unchanged; no assignee info is added at closure.

### Scope

**In Scope:**

- `.generated-at` styling in `esb/templates/public/static_page.html` (center, black)
- `ack(response_action='clear')` in `handle_repair_action_submission` (`esb/slack/handlers.py`)
- Assignee identity (Slack @mention w/ username fallback) in `status_changed`, `new_report`, and new `assignee_changed` Slack notifications
- New `assignee_changed` notification event type + `notify_assignee_changed` trigger config + admin UI toggle
- Tests for all three changes

**Out of Scope:**

- Other Slack flows (`/esb-update`, problem reporting via Slack)
- Other static status page styling changes
- Notification delivery/retry mechanics (worker behavior unchanged)
- Assignee info on closed transitions (`resolved` messages unchanged)
- Storing resolved Slack user IDs on the `User` model (future optimization)

## Context for Development

### Codebase Patterns

- **Service layer**: views/Slack handlers delegate to `esb/services/`; notifications are queued via `notification_service.queue_notification()` and delivered by the background worker (`flask worker run`, 30s poll, retry/backoff).
- **Slack notification triggers**: gated in `repair_service` by `config_service.get_config('notify_<event>', 'true')`. Existing keys: `notify_new_report`, `notify_resolved`, `notify_status_changed`, `notify_severity_changed`, `notify_eta_updated`. All default `'true'`; values stored as `'true'`/`'false'` strings in the `AppConfig` table.
- **Trigger admin UI pattern** (to copy for the new toggle): `BooleanField` on `AppConfigForm` (`esb/forms/admin_forms.py:33-64`) → key added to the `config_keys` list of `(key, default)` tuples in the `/admin/config` view (`esb/views/admin.py:247-322`; GET loads with default `'true'`, POST persists via `config_service.set_config` only on change) → `form-check form-switch` block in `esb/templates/admin/config.html:59-116` ("Notification Triggers" card).
- **Notification queueing** (`esb/services/repair_service.py`):
  - `_queue_slack_notification(equipment, event_type, extra_payload)` (lines 33-59) builds payload with `event_type`, `equipment_id`, `equipment_name`, `area_name` + extras; target channel = `equipment.area.slack_channel` or `'#general'`.
  - `create_repair_record()` accepts `assignee_id` (validated at lines 105-108, where the `assignee` User object is loaded) and queues a `new_report` notification (lines ~168-176) — currently with no assignee info.
  - `update_repair_record()` queues from `audit_changes` at lines ~704-735: status→closed ⇒ `resolved`; status→open ⇒ `status_changed`; `severity` ⇒ `severity_changed`; `eta` ⇒ `eta_updated`. **An `assignee_id` change alone fires NO Slack notification today** — the notification block keys only on `status`/`severity`/`eta` (verify by reading `repair_service.py:704-735`; no test asserts the Slack silence directly).
  - **`audit_changes` values are serialized strings** (`_serialize()` at `repair_service.py:28-30` is `str(value)`), so `audit_changes['assignee_id']` holds `['3', '5']`-style strings — do NOT feed them to `db.session.get(User, ...)`. The assignee timeline-entry branch (`repair_service.py:631-641`) already resolves `old_user` and `new_user` from the raw (unserialized) values; capture them there.
  - `claim_repair_record()` (lines 244-294) funnels through `update_repair_record()` with `{'assignee_id': ...}` and adds `status='Assigned'` only when current status is `'New'` — so a claim on an already-assigned repair is a pure assignee swap, currently silent.
  - The static-page-push hook (`repair_service.py:691-699`) regenerates the static page only on `status`/`severity`/`eta` changes — assignee changes correctly do NOT regenerate it, and the guard test `tests/test_services/test_repair_service.py:216-228` (`test_assignee_only_does_not_queue_notification` in `TestUpdateRepairRecordStaticPageHook`, filtering `notification_type='static_page_push'`) must remain unchanged.
- **Message formatting**: `notification_service._format_slack_message(payload)` (lines 288-355) is a pure function dispatching on `event_type`, returns `(text, blocks=None)`; mrkdwn plain text with emoji-prefix constants at lines 25-30 (`_STATUS_PREFIX = ':arrows_counterclockwise: '` etc. — note the trailing space). Delivery in `_deliver_slack_message()` (lines 230-286) posts to `notification.target` and also to `SLACK_OOPS_CHANNEL` (default `'#oops'`). **Caution**: at line 253, `payload = notification.payload or {}` aliases the ORM `db.JSON` attribute — mutating it mutates the model in memory.
- **`User.slack_handle`** (`esb/models/user.py:21`): nullable free-text display handle (UI convention `@name`), max 80 chars, **not** a Slack user ID — plain `@name` text in API messages does not ping. It serves as a "wants Slack" flag elsewhere (`user_service.py:261`). The feature's required resolution is **ESB-user → Slack-ID**, via `client.users_lookupByEmail(email=user.email)` → `<@U...>` — the **sole** correct reference is `user_service.py:271`. (Note: `_resolve_esb_user` in `handlers.py:50-57` goes the OPPOSITE direction — Slack-ID → email via `client.users_info(user=slack_id)` — do NOT copy it for this lookup.)
- **`/esb-repair` flow** (`esb/slack/handlers.py`): dispatcher modal submission (`repair_dispatcher_submission`, line 467) pushes the action modal via `ack(response_action='push', view=...)` (line 522); `handle_repair_action_submission` (line 525) ends its success path with bare `ack()` at **line 678** — pops only the top view, revealing the dispatcher again — then posts the ephemeral confirmation at lines 698-702.

### Files to Reference

| File | Purpose |
| ---- | ------- |
| `esb/templates/public/static_page.html` | `.generated-at` rule line 12 (`text-align: right; color: #6c757d`); div line 41. Used only by `static_page_service.generate()` (Issue #52) |
| `esb/services/static_page_service.py` | Renders template with `generated_at`, `generated_year`, `areas`, `repair_severities` (lines 38-58) |
| `esb/slack/handlers.py` | Bare success `ack()` line 678 in `handle_repair_action_submission` (Issue #53); `_resolve_esb_user` email matching (lines 30-60) |
| `esb/services/repair_service.py` | `_queue_slack_notification()` (33-59), `_serialize()` (28-30), `create_repair_record()` new_report queueing (~168-176), timeline assignee branch (631-641), notification block (~704-735), `claim_repair_record()` (244-294) (Issue #54) |
| `esb/services/notification_service.py` | Prefix constants (25-30), `_format_slack_message()` (288-355), `_deliver_slack_message()` (230-286, payload alias at 253) (Issue #54) |
| `esb/models/user.py` | `username` (line 17), `slack_handle` (line 21, nullable free text) |
| `esb/models/pending_notification.py` | `payload` is a plain `db.JSON` column — no mutation tracking |
| `esb/services/user_service.py` | `users_lookupByEmail` mention-resolution pattern (line 271); `slack_handle` as Slack-delivery gate (line 261) |
| `esb/views/repairs.py` | Web create form allows assignment at creation (lines 170-175); edit form submits status + assignee together (~line 343) |
| `esb/forms/admin_forms.py` | `AppConfigForm` trigger BooleanFields (lines 33-64) — add `notify_assignee_changed` |
| `esb/views/admin.py` | `/admin/config` view (lines 247-322); `config_keys` list of `(key, default)` tuples (~line 277) — add new entry |
| `esb/templates/admin/config.html` | "Notification Triggers" card (lines 59-116) — add switch block |
| `esb/services/config_service.py` | `get_config`/`set_config` upsert + mutation logging (lines 13-80) |
| `tests/test_services/test_static_page_service.py` | Static page HTML tests, e.g. `test_includes_generated_timestamp` (line 49), `test_generated_at_subheading_renders_above_areas` (line 131) |
| `tests/test_slack/test_handlers.py` | `TestRepairActionSubmission` (line 1147) — only the claim-from-New test (~1214) and closed-duplicate test (~1562) assert the bare success ack today; other success-path tests (set_eta ~1261, set_status, resolve_with_note) have NO ack assertion and need one added. `TestRepairDispatcherSubmission` (line 1027) asserts `response_action='push'` |
| `tests/test_services/test_repair_service.py` | Slack notification queueing tests at 245-693 (`TestCreateRepairRecordSlackNotification` ~248, `TestUpdateRepairRecordSlackNotification` at 318); static-page guard test at 216-228 (KEEP unchanged) |
| `tests/test_services/test_notification_service.py` | `TestFormatSlackMessage` (lines 929-1129, incl. unknown-event fallback at 1110 and empty-payload fallback at 1122) — add `assignee_changed` + enriched cases |
| `tests/test_views/test_admin_views.py` | `TestAppConfigNotificationTriggers` (class at line 959) — extend for new toggle |

### Technical Decisions

- **#52**: change `.generated-at` to `text-align: center;` and `color: #000;` (issue asks for black). Keep font-size/margin as-is. No service changes.
- **#53 fix**: replace the bare success-path `ack()` (`esb/slack/handlers.py:678`) with `ack(response_action='clear')`, which closes the entire modal stack (dispatcher + pushed action modal). The follow-up `chat_postEphemeral` confirmation is preserved. Error paths (`response_action='errors'`) unchanged. Applies to all four actions (claim / set_eta / set_status / resolve_with_note) — they share the single success `ack()`.
- **#54 event matrix** (one `update_repair_record()` call; "open transition" = status changed to a non-closed status):

  The matrix below concerns **only the interaction between the status field and the assignee field**. The `severity` and `eta` notification branches (`repair_service.py:721,729`) are **independent `if`s** and are NOT modified — a `severity_changed` and/or `eta_updated` notification co-occurs with whatever the matrix produces whenever severity/eta also changed in the same update. So "single enriched `status_changed`" and "`assignee_changed`" below describe the **status/assignee outcome**, not the total notification count for the update.

  | Status/assignee change in the update | Trigger gate | Status/assignee notification |
  | --- | --- | --- |
  | Status → closed (± assignee change) | `notify_resolved` | `resolved`, format unchanged; assignee info never added; no `assignee_changed` |
  | Open transition, no assignee change | `notify_status_changed` | `status_changed`, format unchanged |
  | Open transition + assignee change (ANY open transition, not just →`Assigned`) | `notify_status_changed` | enriched `status_changed` with assignee delta line (assigned / reassigned-with-previous / unassigned-with-previous) — the assignee is NOT also notified via `assignee_changed` |
  | Open transition + assignee change, but `notify_status_changed` disabled | `notify_assignee_changed` | **fall-through**: `assignee_changed` fires instead, so assignment visibility is governed by its own toggle (both disabled ⇒ no status/assignee notification) |
  | Assignee change, no status change (claim of already-assigned repair, web reassignment, unassignment — regardless of whether severity/eta also changed) | `notify_assignee_changed` | `assignee_changed` |
  | Creation with `assignee_id` set | `notify_new_report` | `new_report` enriched with "Assigned to:" line |

  **Mutual exclusivity (explicit)**: the `assignee_changed` event fires in exactly two situations — (a) an assignee change with NO status change in the update (guard: `'assignee_id' in audit_changes and 'status' not in audit_changes`), or (b) the fall-through when an open-transition status+assignee update has `notify_status_changed` disabled. It must NEVER fire alongside `resolved` or an enriched `status_changed` for the same update.

- **#54 exact message templates** (normative — tests assert them exactly; `{display}` = resolved mention or username fallback; `{old}` = `old_assignee_username`, plain text). Note the sibling templates are NOT uniform: `severity_changed`/`status_changed`/`eta_updated`/`resolved` are two-line, but `new_report` is **three-line** (`notification_service.py:307-311`). `assignee_changed` is a new two-line template:
  - New constant `_ASSIGNEE_PREFIX = ':bust_in_silhouette: '` (trailing space, matching the prefix constants at `notification_service.py:25-30`).
  - `assignee_changed` (heading line + detail line):
    - assigned (no previous): `{_ASSIGNEE_PREFIX}Assignee changed: *{equipment_name}* ({area_name})\nAssigned to: {display}`
    - reassigned: `{_ASSIGNEE_PREFIX}Assignee changed: *{equipment_name}* ({area_name})\nReassigned: {old} -> {display}`
    - unassigned: `{_ASSIGNEE_PREFIX}Assignee changed: *{equipment_name}* ({area_name})\nUnassigned (was {old})`
  - Enriched `status_changed`: existing two-line text + `\n` + one of: `Assigned to: {display}` (no previous) / `Assigned to: {display} (was {old})` (reassigned) / `Unassigned (was {old})` (unassigned).
  - Enriched `new_report`: existing three-line text + `\nAssigned to: {display}` (creation has no previous assignee, so always the simple form).
  - **Intentional divergence (do not "fix")**: the `assignee_changed` reassignment line (`Reassigned: {old} -> {display}`) and the enriched `status_changed` reassignment line (`Assigned to: {display} (was {old})`) word the same event differently because they read in different surrounding contexts. Format each surface independently; do NOT factor them into one shared helper.
- **#54 payload contract**: when (and only when) the assignee changed in the update — or was set at creation — the payload carries `old_assignee_username` (str|None; always None for `new_report`), `assignee_username` (str|None — None means unassigned), `assignee_email` (str|None), `assignee_has_slack` (bool). **Detection is uniform across all three event types: by key presence (`'assignee_username' in payload`), never by truthiness** — so unassignment (key present, value None) still renders its line. The formatter then branches on the VALUES: `assignee_username is None` ⇒ unassigned line (uses only `{old}`); else ⇒ assigned/reassigned line (uses `assignee_display`, which delivery guarantees is set whenever `assignee_username` is truthy — see below). For `new_report` the key is present only when assigned at creation and `assignee_username` is always truthy there, so the same logic applies.
- **#54 mention resolution**: a true @mention requires the Slack user ID (`<@U123>`); `slack_handle` is free text and cannot ping. At **delivery** time in `_deliver_slack_message()`, FIRST copy the payload (`payload = dict(notification.payload or {})` — line 253 currently aliases the ORM `db.JSON` attribute; in-place mutation would hit the model object with undefined persistence behavior). Then, if `payload.get('assignee_username')` is truthy, set `payload['assignee_display']` via a **total** branch (every path assigns it):
  - `assignee_has_slack` AND `assignee_email` ⇒ try `client.users_lookupByEmail(email=...)`, set `<@{result['user']['id']}>`; on ANY exception or missing id, fall back to `assignee_username`.
  - else (including `has_slack` truthy but `assignee_email` falsy — defensive, since `User.email` is `nullable=False`) ⇒ `assignee_display = assignee_username`.

  The lookup must never raise out of delivery. `_format_slack_message()` stays a pure function reading `assignee_display`/`assignee_username`/`old_assignee_username`. (When `assignee_username` is None — unassignment — `assignee_display` is intentionally never set; the formatter doesn't read it on that path.)
- **#54 snapshot semantics (accepted)**: `assignee_email`/`assignee_has_slack` are snapshotted at queue time and consumed at delivery time, possibly after retry/backoff delays. A user changing email or clearing `slack_handle` in between yields a stale lookup, masked by the username fallback. This intentionally diverges from the live-read `user_service` pattern; accepted for simplicity.
- **#54 data handling (accepted)**: assignee email addresses are persisted in `PendingNotification.payload` JSON and remain after delivery (`mark_delivered` only flips status). Accepted for this internal tool — the same table already stores reporter names and repair descriptions.
- **#54 trigger config**: new `notify_assignee_changed` key following the existing three-place pattern (form field, `config_keys` entry, template switch). Label: "Repair assignee changed".

## Implementation Plan

### Tasks

**Issue #52 — Center generated time on static status page**

- [x] Task 1: Restyle `.generated-at` rule
  - File: `esb/templates/public/static_page.html`
  - Action: On line 12, change `.generated-at { text-align: right; font-size: 0.85rem; color: #6c757d; margin-bottom: 1rem; }` to `text-align: center;` and `color: #000;` (keep `font-size: 0.85rem; margin-bottom: 1rem;` unchanged).
  - Notes: The div renders at line 41 directly below the centered `<h1>`, so no markup change is needed — CSS only.

- [x] Task 2: Test the new styling
  - File: `tests/test_services/test_static_page_service.py`
  - Action: Add a test (near `test_includes_generated_timestamp`, line 49) asserting the generated HTML's `.generated-at` rule contains `text-align: center` and `color: #000`, and does NOT contain `text-align: right`.
  - Notes: Existing tests `test_includes_generated_timestamp` (49) and `test_generated_at_subheading_renders_above_areas` (131) assert structure, not style — they should pass unchanged.

**Issue #53 — `/esb-repair` flow terminates on Apply**

- [x] Task 3: Close the full modal stack on successful submission
  - File: `esb/slack/handlers.py`
  - Action: In `handle_repair_action_submission` (line 525), change the success-path bare `ack()` at line 678 to `ack(response_action='clear')`.
  - Notes: `response_action='clear'` closes ALL views in the stack (pushed action modal + underlying dispatcher). This is the single shared success ack for all four actions (claim / set_eta / set_status / resolve_with_note). Do NOT touch the error-path `ack(response_action='errors', ...)` calls, the dispatcher's `ack(response_action='push', ...)` (line 522), or the `chat_postEphemeral` confirmation (lines 698-702), which still fires after the clear.

- [x] Task 4: Update and EXTEND Slack handler tests for the clear ack
  - File: `tests/test_slack/test_handlers.py`
  - Action: In `TestRepairActionSubmission` (line 1147):
    1. **Update** the only two existing success-ack assertions — `test_claim_assigns_to_caller_and_sets_status_to_assigned_when_new` (~line 1214) and `test_set_status_closed_duplicate_with_target_succeeds` (~line 1562) — from `ack.assert_called_once_with()` to `ack.assert_called_once_with(response_action='clear')`.
    2. **Add** `ack.assert_called_once_with(response_action='clear')` to every other success-path test that currently has NO ack assertion: the set_eta success test (`test_set_eta_updates_eta_when_value_differs`, ~line 1261), set_status success test(s), resolve_with_note success test(s), and the claim-on-already-assigned test. AC 3 ("any valid action") is only verified if every action's success path asserts the clear.
    3. Keep/confirm an assertion that `chat_postEphemeral` is still called after the clear ack.
  - Notes: Error-path tests asserting `response_action='errors'` are unaffected. `TestRepairDispatcherSubmission` (`response_action='push'`) is unaffected.

**Issue #54 — Assignee in Slack notifications**

- [x] Task 5: Add the `notify_assignee_changed` trigger toggle (admin config)
  - Files: `esb/forms/admin_forms.py`, `esb/views/admin.py`, `esb/templates/admin/config.html`
  - Action:
    1. `admin_forms.py` (lines 33-64): add `notify_assignee_changed = BooleanField('Repair assignee changed')` to `AppConfigForm`, alongside the existing five trigger fields.
    2. `admin.py` (`/admin/config` view, lines 247-322): add `('notify_assignee_changed', 'true')` to the `config_keys` list of tuples (~line 277); add the matching `get_config('notify_assignee_changed', 'true')` load in the GET branch.
    3. `templates/admin/config.html` (Notification Triggers card, lines 59-116): add a `form-check form-switch` block for `form.notify_assignee_changed`, copying the structure of the existing five switches.
  - Notes: Follow the existing pattern exactly; values are `'true'`/`'false'` strings persisted via `config_service.set_config` only on change.

- [x] Task 6: Queue assignee notification data in `repair_service`
  - File: `esb/services/repair_service.py`
  - Action:
    1. Add a module-level helper (near `_queue_slack_notification`) `_assignee_payload_fields(user)` returning `{'assignee_username': user.username, 'assignee_email': user.email, 'assignee_has_slack': bool(user.slack_handle)}` for a `User`, or `{'assignee_username': None, 'assignee_email': None, 'assignee_has_slack': False}` for `None`.
    2. In `update_repair_record()`: in the existing assignee timeline-entry branch (lines 631-641), `old_user` and `new_user` are already resolved from the RAW (unserialized) values. Capture the **scalar fields** (not the ORM objects) into function-scope variables pre-initialized to `None` before the audit loop — e.g. `old_assignee_username = old_user.username if old_user else None` and a small dict `new_assignee_fields = _assignee_payload_fields(new_user)`. Capturing scalars HERE (before the `db.session.commit()` at line ~682) matters: with Flask-SQLAlchemy's default `expire_on_commit=True`, reading `.username`/`.email`/`.slack_handle` off the ORM objects in the notification block (which runs after the commit) would each trigger a refresh SELECT. Do NOT re-derive the old assignee from `audit_changes['assignee_id']` — those values are `_serialize()`d strings (`repair_service.py:28-30`), not ints.
    3. In the Slack-notification block (~704-735), when `'assignee_id' in audit_changes` build `assignee_delta = {'old_assignee_username': old_assignee_username, **new_assignee_fields}`, else `assignee_delta = None`. Then implement the event matrix from Technical Decisions. **The status/assignee logic is one `if/elif/elif` chain keyed on the status field; the existing independent `severity`/`eta` `if` blocks (lines 721-734) are left exactly as-is and still fire on top when severity/eta also changed:**
       - `if 'status' in audit_changes and new status in CLOSED_STATUSES`: existing `resolved` branch unchanged — never merge `assignee_delta`, never queue `assignee_changed`.
       - `elif 'status' in audit_changes` (open transition): if `notify_status_changed` enabled, queue `status_changed` with the existing fields plus `assignee_delta` merged in (when present). **Elif** `assignee_delta` is present and `notify_assignee_changed` enabled, queue `assignee_changed` with `assignee_delta` (fall-through so assignment visibility isn't silently lost).
       - `elif assignee_delta is not None` (i.e. assignee changed AND `'status' not in audit_changes`): if `notify_assignee_changed` enabled, queue `assignee_changed` with `assignee_delta`. **This branch MUST be guarded by the absence of a status change** (it is the `elif` tail of the status-keyed chain) so it can never double-fire alongside `resolved` or an enriched `status_changed`.
    4. In `create_repair_record()`: the `assignee` User object is already loaded for validation (lines 105-108). When `assignee_id` was provided, merge `{'old_assignee_username': None, **_assignee_payload_fields(assignee)}` into the `new_report` extra payload (~lines 168-176).
  - Notes: `claim_repair_record()` (lines 244-294) needs no changes — it funnels through `update_repair_record()`. A claim from `'New'` produces the enriched `status_changed` (or the fall-through `assignee_changed` if that toggle is off); a claim on an already-assigned repair produces `assignee_changed`. The severity/eta notification branches are untouched. The static-page-push hook (691-699) is untouched — assignee changes still don't regenerate the page.

- [x] Task 7: Format and resolve the assignee mention in `notification_service`
  - File: `esb/services/notification_service.py`
  - Action:
    1. **Copy the payload first** in `_deliver_slack_message()`: change line 253 from `payload = notification.payload or {}` to `payload = dict(notification.payload or {})` — the current expression aliases the ORM `db.JSON` attribute and any mutation would hit the model object.
    2. **Delivery-time mention resolution**, after the copy and before `_format_slack_message(payload)` (line 254): if `payload.get('assignee_username')` is truthy, assign `payload['assignee_display']` via a **total** branch (every path sets it):
       - `payload.get('assignee_has_slack')` AND `payload.get('assignee_email')` ⇒ `try` `client.users_lookupByEmail(email=...)` → `f"<@{result['user']['id']}>"`; on ANY exception or missing id, fall back to `payload['assignee_username']`.
       - `else` (covers `has_slack` falsy AND the defensive `has_slack`-truthy-but-`email`-falsy case) ⇒ `assignee_display = payload['assignee_username']`.

       Wrap the lookup in try/except (log at debug/info); it must never raise out of delivery. When `assignee_username` is None (unassignment) leave `assignee_display` unset — the formatter doesn't read it on that path.
    3. **New `assignee_changed` branch** in `_format_slack_message()` plus `_ASSIGNEE_PREFIX = ':bust_in_silhouette: '` constant at lines 25-30 — implement the exact templates from Technical Decisions (assigned / reassigned / unassigned; heading line `{_ASSIGNEE_PREFIX}Assignee changed: *{equipment_name}* ({area_name})` + detail line). Branch on values: `payload.get('assignee_username') is None` ⇒ `Unassigned (was {old})`; `old_assignee_username` falsy ⇒ `Assigned to: {display}`; else ⇒ `Reassigned: {old} -> {display}`.
    4. **Enriched `status_changed`** (lines 336-342): detect by **key presence** — `if 'assignee_username' in payload`, append `\n` + the delta line, branching on values the same way: `assignee_username is None` ⇒ `Unassigned (was {old})`; no previous ⇒ `Assigned to: {display}`; reassigned ⇒ `Assigned to: {display} (was {old})`. Do NOT share a helper with the `assignee_changed` branch — the reassignment wording intentionally differs (see Technical Decisions).
    5. **Enriched `new_report`** (lines 302-311, three-line template): detect by **key presence** — `if 'assignee_username' in payload`, append `\nAssigned to: {display}` (creation never unassigns, so `assignee_username` is always truthy and `assignee_display` is always set here).
  - Notes: `_format_slack_message` stays a pure function — it only reads `assignee_display`/`old_assignee_username`/`assignee_username` from the payload; the Slack API call lives in delivery. Detection is **uniformly key-presence** across all three event types; the unassignment line needs no `assignee_display`. `old_assignee_username` renders as plain text (no mention) — only the NEW assignee gets pinged. The unknown-event/empty-payload fallbacks (tests at 1110/1122) must keep passing.

- [x] Task 8: Service-layer tests for assignee notifications
  - File: `tests/test_services/test_repair_service.py`
  - Action:
    1. **Do NOT touch** `test_assignee_only_does_not_queue_notification` (lines 216-228, in `TestUpdateRepairRecordStaticPageHook`) — it guards static-page-push behavior (`notification_type='static_page_push'`), which is unchanged: assignee changes still must not regenerate the static page.
    2. **Add** new `slack_message`-typed tests (pattern: `TestUpdateRepairRecordSlackNotification`, class at line 318): (a) assignee-only change queues exactly one `assignee_changed` with correct payload fields (`old_assignee_username`, `assignee_username`, `assignee_email`, `assignee_has_slack`); (b) no `assignee_changed` when `notify_assignee_changed` is `'false'`; (c) claim from `'New'` queues a single enriched `status_changed` (no `assignee_changed`) whose payload includes the assignee delta; (d) any other open transition + assignee change (e.g. `New` → `In Progress` with assignment) also enriches `status_changed`; (e) **fall-through**: `notify_status_changed='false'` + `notify_assignee_changed='true'` + combined status+assignee update queues exactly one `assignee_changed`; (f) both toggles `'false'` + combined update queues nothing; (g) unassignment (`assignee_id=None`) queues `assignee_changed` with `assignee_username=None` and `old_assignee_username` set; (h) status→closed + assignee change queues only `resolved` with no assignee fields and no `assignee_changed`; (i) reassignment carries both old and new usernames; (j) `assignee_has_slack` is `False` when the user has no `slack_handle`; (k) `create_repair_record` with `assignee_id` includes the assignee fields in the `new_report` payload; without `assignee_id` it does not; (l) assignee change + severity change with NO status change queues BOTH `assignee_changed` AND `severity_changed` (the independent severity branch is unaffected) — assert both are present.
  - Notes: Use existing fixtures (`make_repair_record`, user factories) and the established `PendingNotification` query assertions filtered by `notification_type='slack_message'`.

- [x] Task 9: Formatting/delivery tests for assignee messages
  - File: `tests/test_services/test_notification_service.py`
  - Action:
    1. In `TestFormatSlackMessage` (lines 929-1129) add exact-string tests for the normative templates in Technical Decisions: (a) `assignee_changed` assigned; (b) `assignee_changed` reassigned; (c) `assignee_changed` unassigned; (d) enriched `status_changed` assigned; (e) enriched `status_changed` reassigned (`(was {old})`); (f) enriched `status_changed` unassigned; (g) `status_changed` without assignee keys is byte-identical to current output (regression guard); (h) `new_report` with `assignee_display` appends the line; (i) `new_report` without it is unchanged.
    2. In the `_deliver_slack_message` tests: (a) `assignee_has_slack=True` + successful `users_lookupByEmail` → posted text contains `<@U...>`; (b) lookup raises → falls back to plain username, delivery still succeeds (notification marked delivered, not failed); (c) `assignee_has_slack=False` → `users_lookupByEmail` is never called, plain username used; (d) `notification.payload` (the model attribute) is not mutated by delivery — assert `assignee_display` is absent from it afterward.
  - Notes: Mock the Slack client per existing delivery-test pattern in this file. The unknown-event fallback (line 1110) and empty-payload fallback (line 1122) tests must keep passing.

- [x] Task 10: Admin UI tests for the new toggle
  - File: `tests/test_views/test_admin_views.py`
  - Action: Extend `TestAppConfigNotificationTriggers` (class at line 959): the config page shows the new switch; it defaults to enabled; disabling persists `notify_assignee_changed='false'`; re-enabling persists `'true'`; mutation logging fires on change (mirror `test_disable_status_changed_trigger`, ~line 1008).
  - Notes: Copy the structure of the existing per-trigger tests.

**Wrap-up**

- [x] Task 11: Full verification and release bump
  - Files: `pyproject.toml`
  - Action: Run `make test` (full suite) and `make lint`; fix any fallout. Bump `version` in `pyproject.toml` from `0.9.0` by a **minor** increment to `0.10.0` so the release workflow publishes on merge to `main`.
  - Notes: Per CLAUDE.md release guidance, **minor for new features** — #54 adds a new notification event type, a new persisted config key, and a new admin UI control, so a minor bump (not patch) is correct even though #52/#53 are pure fixes. No manual tags, no CHANGELOG.

### Acceptance Criteria

**Issue #52**

- [x] AC 1: Given the static status page is generated, when viewing the HTML, then the `.generated-at` CSS rule specifies `text-align: center` and `color: #000`, and the "Generated: ..." line renders directly under the page title.
- [x] AC 2: Given the static status page is generated, when inspecting the rest of the page, then all other styling (status colors, footer, layout) is unchanged.

**Issue #53**

- [x] AC 3: Given a technician submits the `/esb-repair` action modal with any valid action (claim, set ETA, set status, resolve with note), when they click Apply, then the handler acks with `response_action='clear'` (entire modal stack closes — no return to "Open Repairs") and the ephemeral confirmation message is still posted. Every action's success path has a test asserting the clear ack.
- [x] AC 4: Given the action modal submission fails validation (e.g. missing ETA, closed record, unauthorized user), when the handler acks, then it still uses `response_action='errors'` and the modal stack remains open showing the error.
- [x] AC 5: Given a technician selects a repair in the dispatcher modal and clicks Continue, when the dispatcher acks, then it still pushes the action modal (`response_action='push'`) — dispatcher behavior unchanged.

**Issue #54**

- [x] AC 6: Given an unassigned repair in status `New` and `notify_status_changed` enabled (default), when a technician claims it (status promotes to `Assigned` and assignee is set in one update, with no severity/eta change), then exactly one `status_changed` Slack notification is queued whose payload includes the assignee fields, and the delivered message ends with `Assigned to: {assignee}`.
- [x] AC 7: Given any other open-transition status change bundled with an assignment in one update (e.g. `New` → `In Progress` + assign via the web edit form), then the `status_changed` notification is enriched with the assignee line and no separate `assignee_changed` is queued. ("Enriched, not separately notified" — the total notification count may still exceed one if severity/eta also changed in the same update.)
- [x] AC 7b: Given an assignee change AND a severity change in one update with NO status change, then both an `assignee_changed` and a `severity_changed` notification are queued (the independent severity branch is unaffected by the assignee logic).
- [x] AC 8: Given a status change bundled with a reassignment A→B in one update, then the enriched `status_changed` message shows `Assigned to: {B} (was {A})` — the displaced assignee is never silently dropped.
- [x] AC 9: Given a status change bundled with an unassignment in one update, then the enriched `status_changed` message shows `Unassigned (was {A})`.
- [x] AC 10: Given an already-assigned repair, when the assignee changes without a status change, then exactly one `assignee_changed` notification is queued and the delivered message shows `Reassigned: {old} -> {new}`.
- [x] AC 11: Given an assigned repair, when the assignee is cleared without a status change, then an `assignee_changed` notification is queued and the delivered message shows `Unassigned (was {old})`.
- [x] AC 12: Given `notify_status_changed` is `'false'` and `notify_assignee_changed` is `'true'`, when a single update changes both status (open transition) and assignee, then exactly one `assignee_changed` notification fires (fall-through); given both toggles are `'false'`, nothing fires.
- [x] AC 13: Given a repair record is created with an assignee, when the `new_report` notification is delivered, then its message includes an `Assigned to:` line; without an assignee at creation the message is unchanged.
- [x] AC 14: Given the new assignee has a `slack_handle` set and `users_lookupByEmail` resolves their email, when the notification is delivered, then the message contains a real Slack mention (`<@U...>`) for the new assignee.
- [x] AC 15: Given the new assignee has no `slack_handle` (or the email lookup fails/raises), when the notification is delivered, then the message falls back to the plain ESB username, delivery still succeeds, and `users_lookupByEmail` is not called at all in the no-handle case.
- [x] AC 16: Given `notify_assignee_changed` is `'false'`, when an assignee-only change occurs, then no `assignee_changed` notification is queued.
- [x] AC 17: Given a repair is closed (status → `Resolved`/`Closed - *`) in the same update that changes the assignee, then only the `resolved` notification fires, with its existing message format (no assignee line, no `assignee_changed`).
- [x] AC 18: Given a status change with no assignee change, when the `status_changed` notification is delivered, then its message is byte-identical to the current format (no assignee line).
- [x] AC 19: Given any assignment-related delivery, when it completes, then the persisted `PendingNotification.payload` does not contain `assignee_display` (delivery works on a copy, never mutates the model).
- [x] AC 20: Given a staff user opens `/admin/config`, when viewing the Notification Triggers card, then a "Repair assignee changed" switch appears, defaults to enabled, and toggling it persists `notify_assignee_changed` with mutation logging.
- [x] AC 21: Given an assignee-only change, when notifications are queued, then no `static_page_push` notification is queued (existing guard test at `test_repair_service.py:216-228` passes unchanged).

## Additional Context

### Dependencies

- No new libraries. Slack Bolt SDK / Slack WebClient already in use.
- `users_lookupByEmail` requires the `users:read.email` Slack OAuth scope — **already granted and used** by `user_service.deliver_temp_password_via_slack` (`user_service.py:271`), so no Slack app config change is needed.
- The three issues are independent of each other; #54 tasks (5-10) must land together but have no ordering dependency on #52/#53.

### Testing Strategy

- **Unit tests** (bulk of coverage — Tasks 2, 4, 8, 9, 10): static page CSS assertion; per-action handler ack assertions; service-layer queueing matrix (enriched status_changed incl. reassign/unassign delta, assignee_changed, fall-through, both-disabled, closed suppression, creation-with-assignee, static-page guard untouched); exact-template format cases incl. regression guards; delivery-time mention resolution incl. no-mutation assertion; admin toggle round-trip.
- **Full suite**: `make test` and `make lint` must pass (Task 11).
- **Manual verification** (post-deploy or local with real Slack workspace):
  1. Regenerate the static page and confirm the timestamp is centered, black, under the title.
  2. Run `/esb-repair`, pick a repair, apply an action — all dialogs close; confirmation DM arrives.
  3. Claim a repair from Slack — channel notification names (and pings) the assignee; reassign via web UI — `Reassigned` notification arrives; unassign — `Unassigned (was ...)` arrives.

### Notes

- **Behavior change (intentional)**: assignee changes were previously silent on Slack; they now notify per the event matrix. No existing test asserted the Slack silence directly — the test at `tests/test_services/test_repair_service.py:216-228` guards static-page-push only and stays valid (see Task 8).
- **Risk — mention resolution**: `users_lookupByEmail` adds one Slack API call per assignee-notification delivery, executed in the background worker. It is wrapped in fallback try/except so a Slack API hiccup degrades to a plain username rather than failing/retrying the notification.
- **Accepted — payload snapshot staleness**: assignee email/handle state is snapshotted at queue time; changes before delivery yield a stale lookup masked by the username fallback (see Technical Decisions).
- **Accepted — email persistence**: assignee emails live in `PendingNotification.payload` and are not purged after delivery (see Technical Decisions).
- **Risk — Slack modal `clear`**: `response_action='clear'` is standard Slack view-submission behavior (closes all views). The slack-bolt version in use (1.27.0) already passes `response_action='push'` through `ack()` in this codebase, so `clear` follows the same verified mechanism.
- **Not pinged**: the OLD assignee in a reassignment/unassignment is plain text by design; only the new assignee gets a mention.
- **Future consideration (out of scope)**: storing the resolved Slack user ID on the `User` model would avoid the per-delivery email lookup.
- GitHub Issues: #52 (static page timestamp), #53 (`/esb-repair` modal flow), #54 (assignment notification content).

## Review Notes

- Adversarial review completed (information-asymmetry subagent: diff-only context).
- Findings: 5 total (0 Critical/High; 1 Medium, 4 Low) — 4 fixed, 1 skipped as noise.
  - **F1 (Medium, fixed)**: `docs/administrators.md` trigger table said "All five default to true" and omitted `notify_assignee_changed` — updated to six keys with the new row (user-visible via the #58 docs site).
  - **F2 (Low, fixed)**: documented the deliberate status→assignee fall-through in `docs/administrators.md`.
  - **F3 (Low, fixed)**: `create_repair_record` now snapshots assignee scalars before `commit()` (avoids `expire_on_commit` reload SELECTs; matches `update_repair_record`).
  - **F4 (Low, fixed)**: added a delivery test for a malformed `users_lookupByEmail` success response (KeyError → username fallback).
  - **F5 (Low, skipped/noise)**: end-to-end delivery test for `<@U...>` injection only covers `assignee_changed`; format and delivery layers are independently covered.
- Resolution approach: auto-fix real findings.
- Verification: `make lint` clean; full suite **1731 passed**. Version bumped `0.10.0` → `0.11.0` (minor; the spec's planned 0.9.0→0.10.0 was superseded because #58 already published 0.10.0).
