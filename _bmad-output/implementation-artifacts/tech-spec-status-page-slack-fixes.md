---
title: 'Status Page & Slack Notification Fixes (Issues #52, #53, #54)'
slug: 'status-page-slack-fixes'
created: '2026-06-07'
status: 'ready-for-dev'
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
  - 'Slack user resolution by email via client.users_lookupByEmail (user_service.py pattern)'
test_patterns:
  - 'pytest with SQLite in-memory DB; fixtures in tests/conftest.py (app, client, db, staff_client, make_equipment, make_repair_record)'
  - 'Slack handler tests capture handlers via mock Bolt decorators (_register_and_capture), invoke with MagicMock ack/client/body/view'
  - 'Notification format tests call _format_slack_message directly (pure function)'
  - 'Admin trigger tests POST to /admin/config and assert config_service values'
---

# Tech-Spec: Status Page & Slack Notification Fixes (Issues #52, #53, #54)

**Created:** 2026-06-07

## Overview

### Problem Statement

Three small UX defects, tracked as GitHub Issues #52, #53, and #54:

1. **Issue #52** — On the static status page, the generated date/time is right-aligned and gray (`#6c757d`), making it visually unobtrusive to the point that users might miss it.
2. **Issue #53** — In the `/esb-repair` Slack flow, after selecting a repair, editing it, and clicking "Apply", the user is sent back to the "Open Repairs" dialog instead of the flow terminating.
3. **Issue #54** — When a repair is assigned, the Slack notification only says it was assigned (`New -> Assigned`); it does not say who it was assigned to.

### Solution

1. CSS change in the static page template: center the generated timestamp under the page title and make it black.
2. Change the final `ack()` in the `/esb-repair` action-modal submission handler to `ack(response_action='clear')` so the entire modal stack closes; the ephemeral confirmation message still posts.
3. Include the assignee in assignment notifications — Slack @mention when the user has a linked `slack_handle`, falling back to ESB username. Enrich the `status_changed` message when status transitions to `Assigned` alongside an assignee change, and add a new `assignee_changed` event type (with its own admin notification-trigger toggle) for assignee changes that occur without a status change, so reassignments/claims of already-assigned repairs are no longer silent. Avoid double-notifying when both change in one update.

### Scope

**In Scope:**

- `.generated-at` styling in `esb/templates/public/static_page.html` (center, black)
- `ack(response_action='clear')` in `handle_repair_action_submission` (`esb/slack/handlers.py`)
- Assignee name (Slack @mention w/ username fallback) in assignment-related Slack notifications
- New `assignee_changed` notification event type + `notify_assignee_changed` trigger config + admin UI toggle
- Tests for all three changes

**Out of Scope:**

- Other Slack flows (`/esb-update`, problem reporting via Slack)
- Other static status page styling changes
- Notification delivery/retry mechanics (worker behavior unchanged)
- @-mention escaping/resolution beyond what existing `slack_handle` data supports

## Context for Development

### Codebase Patterns

- **Service layer**: views/Slack handlers delegate to `esb/services/`; notifications are queued via `notification_service.queue_notification()` and delivered by the background worker (`flask worker run`, 30s poll, retry/backoff).
- **Slack notification triggers**: gated in `repair_service` by `config_service.get_config('notify_<event>', 'true')`. Existing keys: `notify_new_report`, `notify_resolved`, `notify_status_changed`, `notify_severity_changed`, `notify_eta_updated`. All default `'true'`; values stored as `'true'`/`'false'` strings in the `AppConfig` table.
- **Trigger admin UI pattern** (to copy for the new toggle): `BooleanField` on `AppConfigForm` (`esb/forms/admin_forms.py:33-64`) → key added to `config_keys` tuple in `/admin/config` view (`esb/views/admin.py:247-322`, GET loads with default `'true'`, POST persists via `config_service.set_config` only on change) → `form-check form-switch` block in `esb/templates/admin/config.html:59-116` ("Notification Triggers" card).
- **Notification queueing** (`esb/services/repair_service.py`):
  - `_queue_slack_notification(equipment, event_type, extra_payload)` (lines 33-59) builds payload with `event_type`, `equipment_id`, `equipment_name`, `area_name` + extras; target channel = `equipment.area.slack_channel` or `'#general'`.
  - `update_repair_record()` queues from `audit_changes` at lines ~704-735: status→closed ⇒ `resolved`; status→open ⇒ `status_changed`; `severity` ⇒ `severity_changed`; `eta` ⇒ `eta_updated`. **An `assignee_id` change alone fires NO notification today** (confirmed by existing test `tests/test_services/test_repair_service.py:216-228`, which must be updated).
  - `claim_repair_record()` (lines 244-294) funnels through `update_repair_record()` with `{'assignee_id': ...}` and adds `status='Assigned'` only when current status is `'New'` — so a claim on an already-assigned repair is a pure assignee swap, currently silent.
- **Message formatting**: `notification_service._format_slack_message(payload)` (lines 288-355) is a pure function dispatching on `event_type`, returns `(text, blocks=None)`; mrkdwn plain text with emoji prefixes (`_STATUS_PREFIX` = `:arrows_counterclockwise:` etc.). Delivery in `_deliver_slack_message()` (lines 230-286) posts to `notification.target` and also to `SLACK_OOPS_CHANNEL` (default `'#oops'`).
- **`User.slack_handle`** (`esb/models/user.py:21`): nullable free-text display handle (UI convention `@name`), max 80 chars, **not** a Slack user ID — plain `@name` text in API messages does not ping. It serves as a "wants Slack" flag elsewhere (`user_service.py:261`). Real Slack identity resolution uses `client.users_lookupByEmail(email=user.email)` (`user_service.py:271`); `_resolve_esb_user` in handlers matches Slack→ESB by email too.
- **`/esb-repair` flow** (`esb/slack/handlers.py`): dispatcher modal submission (`repair_dispatcher_submission`, line 467) pushes the action modal via `ack(response_action='push', view=...)` (line 522); `handle_repair_action_submission` (line 525) ends its success path with bare `ack()` at **line 678** — pops only the top view, revealing the dispatcher again — then posts the ephemeral confirmation at lines 698-702.

### Files to Reference

| File | Purpose |
| ---- | ------- |
| `esb/templates/public/static_page.html` | `.generated-at` CSS rule at line 12 (`text-align: right; color: #6c757d`); div renders at line 41. Template used only by `static_page_service.generate()` (Issue #52) |
| `esb/services/static_page_service.py` | Renders template with `generated_at`, `generated_year`, `areas`, `repair_severities` (lines 38-58) |
| `esb/slack/handlers.py` | Bare success `ack()` at line 678 in `handle_repair_action_submission` (Issue #53); `_resolve_esb_user` email matching (lines 30-60) |
| `esb/services/repair_service.py` | `_queue_slack_notification()` (33-59), notification queueing block (~704-735), `claim_repair_record()` (244-294) (Issue #54) |
| `esb/services/notification_service.py` | `_format_slack_message()` (288-355), `_deliver_slack_message()` (230-286) (Issue #54) |
| `esb/models/user.py` | `username` (line 17), `slack_handle` (line 21, nullable free text) |
| `esb/services/user_service.py` | `users_lookupByEmail` mention-resolution pattern (line 271); `slack_handle` as Slack-delivery gate (line 261) |
| `esb/forms/admin_forms.py` | `AppConfigForm` trigger BooleanFields (lines 33-64) — add `notify_assignee_changed` |
| `esb/views/admin.py` | `/admin/config` view, `config_keys` tuple (lines 247-322) — add new key |
| `esb/templates/admin/config.html` | "Notification Triggers" card (lines 59-116) — add switch block |
| `esb/services/config_service.py` | `get_config`/`set_config` upsert + mutation logging (lines 13-80) |
| `tests/test_services/test_static_page_service.py` | Static page HTML tests, e.g. `test_includes_generated_timestamp` (line 49), `test_generated_at_subheading_renders_above_areas` (line 131) |
| `tests/test_slack/test_handlers.py` | `TestRepairActionSubmission` (line 1147) — success paths assert bare `ack.assert_called_once_with()`; `TestRepairDispatcherSubmission` (line 1027) asserts `response_action='push'` |
| `tests/test_services/test_repair_service.py` | Notification queueing tests (lines 245-399); assignee-change-is-silent test at 216-228 (must change) |
| `tests/test_services/test_notification_service.py` | `TestFormatSlackMessage` (lines 930-1079) — add `assignee_changed` + enriched `status_changed` cases |
| `tests/test_views/test_admin_views.py` | `TestAppConfigNotificationTriggers` (lines 960-1050) — extend for new toggle |

### Technical Decisions

- **#52**: change `.generated-at` to `text-align: center;` and `color: #000;` (issue asks for black). Keep font-size/margin as-is. No service changes.
- **#53 fix**: replace the bare success-path `ack()` (`esb/slack/handlers.py:678`) with `ack(response_action='clear')`, which closes the entire modal stack (dispatcher + pushed action modal). The follow-up `chat_postEphemeral` confirmation is preserved. Error paths (`response_action='errors'`) unchanged. Applies to all four actions (claim / set_eta / set_status / resolve_with_note) — they share the single success `ack()`.
- **#54 events**:
  - Status change (open transition) **and** assignee change in the same `update_repair_record()` call (the common claim path) ⇒ single enriched `status_changed` notification with an "Assigned to: {assignee}" line; no separate `assignee_changed` fires.
  - Assignee change **without** a status change (claim of already-assigned repair, web UI reassignment, unassignment) ⇒ new `assignee_changed` event, gated by new `notify_assignee_changed` config key (default `'true'`). Message covers assigned / reassigned / unassigned (new assignee `None`).
  - Status→closed (`resolved` event) with simultaneous assignee change ⇒ `resolved` message unchanged (assignee at closure not interesting); no `assignee_changed` fires.
- **#54 mention resolution**: a true @mention requires the Slack user ID (`<@U123>`); `slack_handle` is free text and cannot ping. Follow the existing `user_service` pattern: queue the payload with `assignee_username`, `assignee_email`, `assignee_has_slack` (bool: `slack_handle` set). At **delivery** time in `_deliver_slack_message()`, if `assignee_has_slack`, call `client.users_lookupByEmail(email=assignee_email)` and inject `assignee_display = '<@{id}>'` into the payload before `_format_slack_message()`; on lookup failure or `assignee_has_slack=False`, `assignee_display = assignee_username`. `_format_slack_message()` stays a pure function reading `assignee_display`. Lookup errors must not fail delivery (fallback, not raise).
- **#54 trigger config**: new `notify_assignee_changed` key following the existing three-place pattern (form field, `config_keys`, template switch). Label: "Repair assignee changed".

## Implementation Plan

### Tasks

**Issue #52 — Center generated time on static status page**

- [ ] Task 1: Restyle `.generated-at` rule
  - File: `esb/templates/public/static_page.html`
  - Action: On line 12, change `.generated-at { text-align: right; font-size: 0.85rem; color: #6c757d; margin-bottom: 1rem; }` to `text-align: center;` and `color: #000;` (keep `font-size: 0.85rem; margin-bottom: 1rem;` unchanged).
  - Notes: The div renders at line 41 directly below the centered `<h1>`, so no markup change is needed — CSS only.

- [ ] Task 2: Test the new styling
  - File: `tests/test_services/test_static_page_service.py`
  - Action: Add a test (near `test_includes_generated_timestamp`, line 49) asserting the generated HTML's `.generated-at` rule contains `text-align: center` and `color: #000`, and does NOT contain `text-align: right`.
  - Notes: Existing tests `test_includes_generated_timestamp` (49) and `test_generated_at_subheading_renders_above_areas` (131) assert structure, not style — they should pass unchanged.

**Issue #53 — `/esb-repair` flow terminates on Apply**

- [ ] Task 3: Close the full modal stack on successful submission
  - File: `esb/slack/handlers.py`
  - Action: In `handle_repair_action_submission` (line 525), change the success-path bare `ack()` at line 678 to `ack(response_action='clear')`.
  - Notes: `response_action='clear'` closes ALL views in the stack (pushed action modal + underlying dispatcher). This is the single shared success ack for all four actions (claim / set_eta / set_status / resolve_with_note). Do NOT touch the error-path `ack(response_action='errors', ...)` calls, the dispatcher's `ack(response_action='push', ...)` (line 522), or the `chat_postEphemeral` confirmation (lines 698-702), which still fires after the clear.

- [ ] Task 4: Update Slack handler tests for the clear ack
  - File: `tests/test_slack/test_handlers.py`
  - Action: In `TestRepairActionSubmission` (line 1147), update every success-path assertion of the form `ack.assert_called_once_with()` to `ack.assert_called_once_with(response_action='clear')` (e.g. `test_claim_assigns_to_caller_and_sets_status_to_assigned_when_new`, line 1201; `test_set_eta_updates_eta_when_value_differs`, line 1261; and all sibling success-path tests). Add/keep an assertion that `chat_postEphemeral` is still called after the clear ack.
  - Notes: Error-path tests asserting `response_action='errors'` are unaffected. `TestRepairDispatcherSubmission` (`response_action='push'`) is unaffected.

**Issue #54 — Assignee in Slack notifications**

- [ ] Task 5: Add the `notify_assignee_changed` trigger toggle (admin config)
  - Files: `esb/forms/admin_forms.py`, `esb/views/admin.py`, `esb/templates/admin/config.html`
  - Action:
    1. `admin_forms.py` (lines 33-64): add `notify_assignee_changed = BooleanField('Repair assignee changed')` to `AppConfigForm`, alongside the existing five trigger fields.
    2. `admin.py` (`/admin/config` view, lines 247-322): add `notify_assignee_changed` to the `config_keys` tuple with default `'true'`; add the matching `get_config('notify_assignee_changed', 'true')` load in the GET branch.
    3. `templates/admin/config.html` (Notification Triggers card, lines 59-116): add a `form-check form-switch` block for `form.notify_assignee_changed`, copying the structure of the existing five switches.
  - Notes: Follow the existing pattern exactly; values are `'true'`/`'false'` strings persisted via `config_service.set_config` only on change.

- [ ] Task 6: Queue assignee notification data in `update_repair_record`
  - File: `esb/services/repair_service.py`
  - Action: In the Slack-notification block of `update_repair_record()` (lines ~704-735):
    1. Add a helper (module-level, near `_queue_slack_notification`) `_assignee_payload_fields(user)` returning `{'assignee_username': user.username, 'assignee_email': user.email, 'assignee_has_slack': bool(user.slack_handle)}` for a `User`, or `{'assignee_username': None, 'assignee_email': None, 'assignee_has_slack': False}` for `None`.
    2. **Enriched status_changed**: in the existing open-transition `status_changed` branch (lines 714-718), if `'assignee_id' in audit_changes` and the new assignee is not None, merge `_assignee_payload_fields(record.assignee)` into the extra payload (record.assignee is already updated at this point). This covers the claim path (`New → Assigned` + assignee in one call).
    3. **New assignee_changed event**: after the existing status/severity/eta blocks, add: if `'assignee_id' in audit_changes` and `'status' not in audit_changes` and `config_service.get_config('notify_assignee_changed', 'true') == 'true'`, queue `_queue_slack_notification(record.equipment, 'assignee_changed', {...})` with: `old_assignee_username` (fetch old user via `db.session.get(User, old_id)` from `audit_changes['assignee_id'][0]`, None if unassigned) plus the new-assignee fields from `_assignee_payload_fields(record.assignee)` (handles unassignment with `record.assignee is None`).
    4. **Resolved untouched**: when status transitions to a closed status, do NOT add assignee fields and do NOT queue `assignee_changed`, even if `assignee_id` changed in the same call.
  - Notes: `claim_repair_record()` (lines 244-294) needs no changes — it funnels through `update_repair_record()`. A claim from `'New'` produces the enriched `status_changed`; a claim on an already-assigned repair produces `assignee_changed`. The dict ordering rule: `assignee_changed` fires ONLY when there is no status change in the same update.

- [ ] Task 7: Format and resolve the assignee mention in `notification_service`
  - File: `esb/services/notification_service.py`
  - Action:
    1. **Delivery-time mention resolution** in `_deliver_slack_message()` (lines 230-286), before the `_format_slack_message(payload)` call (line 254): if `payload.get('assignee_username')` is present, compute `payload['assignee_display']`: when `payload.get('assignee_has_slack')` and `assignee_email`, call `client.users_lookupByEmail(email=...)` and set `assignee_display = f"<@{result['user']['id']}>"`; on ANY exception or missing user, fall back to `payload['assignee_username']`. When `assignee_has_slack` is falsy, use `assignee_username` directly. The lookup must never raise out of delivery (wrap in try/except, log at debug/info). Mutate only the local payload dict (don't persist).
    2. **Enriched `status_changed`** in `_format_slack_message()` (lines 336-342): if `payload.get('assignee_display')`, append a line `Assigned to: {assignee_display}` to the existing `status_changed` text.
    3. **New `assignee_changed` branch** in `_format_slack_message()`: add a module-level `_ASSIGNEE_PREFIX = ':bust_in_silhouette: '` constant (matching the style of `_STATUS_PREFIX` etc.). Messages (all with `*{equipment_name}* ({area_name})` like siblings): new assignee + no old → `Assigned to: {assignee_display}`; old + new → `Reassigned: {old_assignee_username} -> {assignee_display}`; old + no new → `Unassigned (was {old_assignee_username})`.
  - Notes: `_format_slack_message` stays a pure function — it only reads `assignee_display`/`old_assignee_username` from the payload; the Slack API call lives in delivery. `old_assignee_username` renders as plain text (no mention) — only the NEW assignee gets pinged.

- [ ] Task 8: Service-layer tests for assignee notifications
  - File: `tests/test_services/test_repair_service.py`
  - Action:
    1. **Update** the existing test at lines 216-228 that asserts an assignee-only change queues no notification — it now queues exactly one `assignee_changed` notification.
    2. Add tests (following the `TestUpdateRepairRecordSlackNotification` pattern, lines 293-399): (a) assignee-only change queues `assignee_changed` with correct payload fields (`old_assignee_username`, `assignee_username`, `assignee_email`, `assignee_has_slack`); (b) no `assignee_changed` when `notify_assignee_changed` config is `'false'`; (c) claim from `'New'` queues a single `status_changed` (no `assignee_changed`) whose payload includes the assignee fields; (d) unassignment (`assignee_id=None`) queues `assignee_changed` with `assignee_username=None`; (e) status→closed + assignee change in one call queues only `resolved` with no assignee fields; (f) reassignment between two users carries both old and new usernames; (g) `assignee_has_slack` is False when the user has no `slack_handle`.
  - Notes: Use existing fixtures (`make_repair_record`, user factories) and the established `PendingNotification` query assertions.

- [ ] Task 9: Formatting/delivery tests for assignee messages
  - File: `tests/test_services/test_notification_service.py`
  - Action:
    1. In `TestFormatSlackMessage` (lines 930-1079) add: (a) `assignee_changed` assigned-case format; (b) reassigned-case format (`old -> new`); (c) unassigned-case format; (d) `status_changed` with `assignee_display` appends the `Assigned to:` line; (e) `status_changed` without assignee fields is byte-identical to current output (regression guard).
    2. In the `_deliver_slack_message` tests: (a) `assignee_has_slack=True` + successful `users_lookupByEmail` → posted text contains `<@U...>`; (b) lookup raises → falls back to plain username, delivery still succeeds; (c) `assignee_has_slack=False` → no lookup call made, plain username used.
  - Notes: Mock the Slack client per existing delivery-test pattern in this file.

- [ ] Task 10: Admin UI tests for the new toggle
  - File: `tests/test_views/test_admin_views.py`
  - Action: Extend `TestAppConfigNotificationTriggers` (lines 960-1050): the config page shows the new switch; it defaults to enabled; disabling persists `notify_assignee_changed='false'`; re-enabling persists `'true'`; mutation logging fires on change (mirror `test_disable_status_changed_trigger`, line 1008).
  - Notes: Copy the structure of the existing per-trigger tests.

**Wrap-up**

- [ ] Task 11: Full verification and release bump
  - Files: `pyproject.toml`
  - Action: Run `make test` (full suite) and `make lint`; fix any fallout. Bump `version` in `pyproject.toml` by a **patch** increment (all three issues are fixes) so the release workflow publishes on merge to `main`.
  - Notes: Per project release procedure — no manual tags, no CHANGELOG.

### Acceptance Criteria

**Issue #52**

- [ ] AC 1: Given the static status page is generated, when viewing the HTML, then the `.generated-at` CSS rule specifies `text-align: center` and `color: #000`, and the "Generated: ..." line renders directly under the page title.
- [ ] AC 2: Given the static status page is generated, when inspecting the rest of the page, then all other styling (status colors, footer, layout) is unchanged.

**Issue #53**

- [ ] AC 3: Given a technician submits the `/esb-repair` action modal with any valid action (claim, set ETA, set status, resolve with note), when they click Apply, then the handler acks with `response_action='clear'` (entire modal stack closes — no return to "Open Repairs") and the ephemeral confirmation message is still posted.
- [ ] AC 4: Given the action modal submission fails validation (e.g. missing ETA, closed record, unauthorized user), when the handler acks, then it still uses `response_action='errors'` and the modal stack remains open showing the error.
- [ ] AC 5: Given a technician selects a repair in the dispatcher modal and clicks Continue, when the dispatcher acks, then it still pushes the action modal (`response_action='push'`) — dispatcher behavior unchanged.

**Issue #54**

- [ ] AC 6: Given an unassigned repair in status `New`, when a technician claims it (status promotes to `Assigned` and assignee is set in one update), then exactly one `status_changed` Slack notification is queued whose payload includes the assignee fields, and the delivered message contains an `Assigned to:` line naming the assignee.
- [ ] AC 7: Given an already-assigned repair, when the assignee changes without a status change (claim by another tech, web UI reassignment), then exactly one `assignee_changed` notification is queued, and the delivered message shows `Reassigned: {old} -> {new}`.
- [ ] AC 8: Given an assigned repair, when the assignee is cleared without a status change, then an `assignee_changed` notification is queued and the delivered message shows it was unassigned, naming the previous assignee.
- [ ] AC 9: Given the new assignee has a `slack_handle` set and `users_lookupByEmail` resolves their email, when the notification is delivered, then the message contains a real Slack mention (`<@U...>`) for the new assignee.
- [ ] AC 10: Given the new assignee has no `slack_handle` (or the email lookup fails/raises), when the notification is delivered, then the message falls back to the plain ESB username and delivery still succeeds (no retry/failure caused by the lookup).
- [ ] AC 11: Given `notify_assignee_changed` is set to `'false'` in admin config, when an assignee-only change occurs, then no `assignee_changed` notification is queued.
- [ ] AC 12: Given a repair is closed (status → `Resolved`/`Closed - *`) in the same update that changes the assignee, when notifications are queued, then only the `resolved` notification fires, with its existing message format (no assignee line, no `assignee_changed`).
- [ ] AC 13: Given a status change with no assignee change, when the `status_changed` notification is delivered, then its message is identical to the current format (no `Assigned to:` line).
- [ ] AC 14: Given a staff user opens `/admin/config`, when viewing the Notification Triggers card, then a "Repair assignee changed" switch appears, defaults to enabled, and toggling it persists `notify_assignee_changed` with mutation logging.

## Additional Context

### Dependencies

- No new libraries. Slack Bolt SDK / Slack WebClient already in use.
- `users_lookupByEmail` requires the `users:read.email` Slack OAuth scope — **already granted and used** by `user_service.deliver_temp_password_via_slack` (`user_service.py:271`), so no Slack app config change is needed.
- The three issues are independent of each other; #54 tasks (5-10) must land together but have no ordering dependency on #52/#53.

### Testing Strategy

- **Unit tests** (bulk of coverage — Tasks 2, 4, 8, 9, 10): static page CSS assertion; handler ack argument assertions; service-layer notification queueing matrix (enriched status_changed / assignee_changed / disabled trigger / unassignment / closed suppression); pure-function format cases; delivery-time mention resolution with mocked Slack client; admin toggle round-trip.
- **Full suite**: `make test` and `make lint` must pass (Task 11).
- **Manual verification** (post-deploy or local with real Slack workspace):
  1. Regenerate the static page and confirm the timestamp is centered, black, under the title.
  2. Run `/esb-repair`, pick a repair, apply an action — all dialogs close; confirmation DM arrives.
  3. Claim a repair from Slack — channel notification names (and pings) the assignee; reassign via web UI — `Reassigned` notification arrives.

### Notes

- **Behavior change (intentional)**: assignee-only changes were previously silent — the existing test at `tests/test_services/test_repair_service.py:216-228` codifies that and must be inverted, per Issue #54 and the chosen "any assignee change" scope.
- **Risk — mention resolution**: `users_lookupByEmail` adds one Slack API call per assignee-notification delivery, executed in the background worker. It is wrapped in fallback try/except so a Slack API hiccup degrades to a plain username rather than failing/retrying the notification.
- **Risk — Slack modal `clear`**: `response_action='clear'` is standard Slack view-submission behavior (closes all views). The slack-bolt version in use (1.27.0) already passes `response_action='push'` through `ack()` in this codebase, so `clear` follows the same verified mechanism.
- **Not pinged**: the OLD assignee in a reassignment is plain text by design; only the new assignee gets a mention.
- **Future consideration (out of scope)**: storing the resolved Slack user ID on the `User` model would avoid the per-delivery email lookup.
- GitHub Issues: #52 (static page timestamp), #53 (`/esb-repair` modal flow), #54 (assignment notification content).
