---
title: 'MAC (Machine Access Control) Integration'
slug: 'mac-integration'
created: '2026-07-04'
status: 'completed'
stepsCompleted: [1, 2, 3, 4]
tech_stack: [Python 3.14, Flask, Flask-SQLAlchemy, MariaDB, Alembic, WTForms/Flask-WTF, Jinja2, requests, pytest]
files_to_modify: [
  'esb/config.py',
  'esb/models/__init__.py',
  'esb/models/equipment.py',
  'esb/models/machine_status.py (new)',
  'esb/models/machine_activity_event.py (new)',
  'migrations/versions/*_add_equipment_mac_machine_name.py (new)',
  'migrations/versions/*_add_machine_status.py (new)',
  'migrations/versions/*_add_machine_activity_events.py (new)',
  'esb/services/mac_service.py (new)',
  'esb/services/notification_service.py',
  'esb/services/repair_service.py',
  'esb/services/status_service.py',
  'esb/services/config_service.py (read-only usage)',
  'esb/views/webhooks.py (new)',
  'esb/views/__init__.py',
  'esb/views/equipment.py',
  'esb/__init__.py',
  'esb/forms/admin_forms.py',
  'esb/forms/equipment_forms.py (EquipmentCreateForm + EquipmentEditForm)',
  'esb/services/equipment_service.py (create kwargs + _UPDATABLE_FIELDS)',
  'esb/views/admin.py',
  'esb/templates/admin/config.html',
  'esb/templates/equipment/detail.html',
  'esb/templates/equipment/_form.html (equipment create/edit form)',
  'esb/templates/public/status_dashboard.html',
  'esb/templates/public/kiosk.html',
  'esb/templates/public/kiosk_dense.html',
  'esb/templates/public/equipment_page.html',
  'esb/static/js/app.js (or detail.html extra_js block)',
]
code_patterns: [
  'Optional integration gated on empty env var: MAC_URL = os.environ.get(...); empty => disabled',
  'AppConfig key/value store via config_service.get_config/set_config; booleans as "true"/"false"; one bool key per (surface,status)',
  'Nullable string column idiom: db.Column(db.String(200), nullable=True)',
  'Equipment-child model via backref (not back_populates); append-only children omit updated_at',
  'PendingNotification queue: add type to VALID_NOTIFICATION_TYPES + handlers dict; handler returns None on success, raises to retry',
  'Outbound call: explicit timeout, let primary call raise (worker retries via mark_failed + BACKOFF_SCHEDULE)',
  'machine_status injected in BOTH status_service dashboard builders (different dict shapes) + at the view for equipment_page/detail (tuple context)',
  'upsert_machine_status is race-safe (IntegrityError-retry) because webhook + worker both write the UNIQUE machine_name row',
  'mac_clear excludes Closed - Duplicate and requires no other open repair; webhook is idempotent via (machine_name,event_type,event_timestamp) dedup',
  'CSRF-exempt POST route: csrf.exempt(blueprint) in create_app after register_blueprints',
  'Alembic: op.batch_alter_table for add_column; op.create_table + batch create_index; chain down_revision from head 77b248bd052d',
]
test_patterns: [
  'pytest, SQLite in-memory (TestingConfig), CSRF disabled in tests',
  'Fixtures: app, client, db, staff_client, tech_client, make_area, make_equipment(**kwargs), make_repair_record',
  'Mock outbound HTTP with unittest.mock.patch at module boundary (patch esb.services.mac_service.requests...); no responses/requests_mock in repo',
  'Model tests in tests/test_models/, class-grouped, assert IntegrityError with pytest.raises then rollback',
  'View tests assert on resp.status_code, resp.data bytes, resp.headers[Location]',
]
---

# Tech-Spec: MAC (Machine Access Control) Integration

**Created:** 2026-07-04

## Review Notes

- Status: **Completed** (implementation + adversarial review).
- Adversarial review findings: 8 total (all real) — 7 fixed, 1 deferred with rationale.
  Resolution approach: auto-fix real findings.
  - **F1 (High, fixed):** auto-repair was gated on the activity dedup, so a failure after
    the activity commit would permanently lose the repair on retry. Decoupled — the webhook
    now attempts `maybe_create_oops_repair` on every `oops` (its open-repair guard prevents
    duplicates).
  - **F2 (Med/High, fixed):** `get_equipment_by_machine_name` now filters `is_archived=False`
    (matching its docstring and the uniqueness rule), so auto-repair can't resolve to an
    archived equipment.
  - **F3 (Med, fixed):** the `(machine_name, event_type, event_timestamp)` dedup index is now
    UNIQUE and `record_activity_event` handles `IntegrityError` (rollback → None), closing the
    concurrent-duplicate-delivery race. (Deviation from the spec's `unique=False`.)
  - **F4 (Med, fixed):** the webhook now returns 500 (not 400) on internal/transient failures
    so MAC retries; 400 is reserved for validated bad input.
  - **F5 (Med, fixed):** the webhook validates `name`/`event`/`timestamp` up front, before any
    DB write, so a malformed payload can't leave a half-written status row.
  - **F6 (Low, fixed):** webhook token compared with `hmac.compare_digest`.
  - **F7 (Low, fixed):** the `mac-activity.json` route is gated on `mac_enabled()`.
  - **F8 (Low, deferred):** activity rows for machines removed/renamed in MAC are not pruned.
    Deleting them conflicts with the "history is ESB-persisted and retained" design intent;
    left as a known slow-growth limitation (revisit with an age-bound if needed).

### Deviations from spec (spec authored against a different repo state)

- At implementation time the migration head was `c2f9a8d4e6b1` (not `77b248bd052d`) and
  `esb/models/equipment_note.py` did not exist, so the child-model idiom was mirrored from
  `repair_timeline_entry.py`. **Resolved on merge:** issue #69 (equipment notes) landed on
  `main` first, so `main` now provides `77b248bd052d` and `equipment_note.py` exactly as the
  spec assumed. `main` was merged in and the MAC migration re-pointed to chain after
  `77b248bd052d` (single head `a1b2c3d4e5f6`); the equipment detail view/template were merged
  to carry both the notes card and the MAC status card.
- Updated one pre-existing test (`test_config_mutation_logging`) whose hard-coded config-key
  count changed due to the 12 new default-`true` MAC display toggles.
- Version bumped `0.16.0` → `0.17.0` (minor: new feature).

## Overview

### Problem Statement

ESB has no connection to the makerspace's Machine Access Control (MAC) system
(https://github.com/jantman/machine-access-control, released at v0.15.0). As a result:

- ESB equipment records are not linked to their MAC machine.
- Staff/members cannot see live machine status (in use / idle / oops / locked out) on any ESB view.
- When a machine is "Oops'ed" in MAC (someone flagged it as needing maintenance), no repair record is
  created in ESB.
- Resolving an ESB repair does not clear the machine's oops/lockout in MAC, so a fixed machine stays locked.
- There is no way to oops / lock out / clear a machine from within ESB.
- There is no visibility into a machine's recent activity (logins, oops, lockouts, etc.).

### Solution

Add an **optional, MAC_URL-gated** two-way integration. Link each equipment record to a MAC machine by
name. Cache live machine status via an **inbound webhook receiver** (MAC's `STATUS_WEBHOOK_URL` points at ESB)
plus a **periodic poll** of `GET /api/machines`, and display admin-configurable statuses on the public, kiosk,
and equipment admin/detail views. Persist incoming webhook events as an **activity log** shown on-demand on the
equipment admin page. **Auto-create a "Down" repair record** when a machine is oops'ed, add admin **control
buttons** to oops / lock out / clear a machine, and **clear the machine's oops/lockout when a repair is
resolved**.

### Scope

**In Scope:**

- **Config**: `MAC_URL` env var (empty = integration disabled); admin `AppConfig` toggles controlling which
  MAC statuses are displayed on each surface (public / kiosk / admin).
- **Data model**: nullable `Equipment.mac_machine_name` column (+ Alembic migration); a cached machine-status
  table; a capped machine activity-event table.
- **Outbound MAC client** service: `GET /api/machines` (status), `POST/DELETE /api/machine/oops/<name>`,
  `POST/DELETE /api/machine/locked_out/<name>`. No auth (network-trusted).
- **Inbound webhook receiver** endpoint (network-trusted by default; optional `MAC_WEBHOOK_TOKEN` guard): updates the
  status cache, appends an activity event, and triggers auto-repair on `oops`.
- **Periodic status refresh** via the background worker polling `GET /api/machines`.
- **Status display** on public dashboard, kiosk, public equipment page, and equipment admin/detail, gated by
  the per-surface config.
- **Activity history UI**: on-demand "load recent activity" control on the equipment admin page.
- **Admin control buttons** (oops / lockout / clear) with confirmation dialogs on the equipment admin page.
- **Auto-repair**: on an `oops` webhook event, create a `severity='Down'` repair record if none is open,
  attaching the active user's name (and email if available).
- **Resolve-clears-machine**: resolving a repair clears the machine's oops + lockout in MAC (queued for retry).

**Out of Scope:**

- Any changes to the MAC project itself. Integration only requires pointing MAC's `STATUS_WEBHOOK_URL` at the
  ESB receiver — no new MAC code (confirmed against MAC 0.15.0 source).
- Mandatory inbound-webhook auth — the endpoint is network-trusted by default; an OPTIONAL `MAC_WEBHOOK_TOKEN`
  shared-secret is provided (Task 9) but not required.
- Historical backfill — activity history accumulates from the first received webhook onward (MAC 0.15.0 has no
  history API to backfill from).
- Resolving MAC's `account_id` to an email address if the webhook payload does not include one.

## Context for Development

### Codebase Patterns

**Optional-integration gating.** `esb/config.py` `class Config` uses `os.environ.get('NAME', 'default')`; optional
integrations default to `''` and code treats empty as "disabled" (e.g. `SLACK_BOT_TOKEN`,
`CLOUDFRONT_DISTRIBUTION_ID`). Add `MAC_URL = os.environ.get('MAC_URL', '')` right after `ESB_BASE_URL`; read it in
services via `current_app.config.get('MAC_URL', '')`. A `mac_enabled()` helper (`bool(MAC_URL)`) in
`mac_service` centralizes the gate.

**Two config layers.** Deploy-time secrets/URLs → `esb/config.py` env vars. Admin-toggleable runtime settings →
`AppConfig` key/value table via `esb/services/config_service.py`: `get_config(key, default='') -> str` and
`set_config(key, value, changed_by, *, log_old_override=None, log_new_override=None)`. **Booleans are the literal
strings `'true'`/`'false'`**; read with `get_config(key, 'false') == 'true'`, write with `'true' if x else 'false'`.
There is **no list/set config helper** — everything is a single string.

**Adding an admin toggle = 3 edits, field name MUST equal the config key** (the view uses `getattr(form, key)`):
1. `esb/forms/admin_forms.py::AppConfigForm` — add `BooleanField('label')` named exactly `<key>` (keep `submit`
   last). `notify_*` toggles use the `form-switch` style.
2. `esb/views/admin.py::app_config()` (`/admin/config`, `@role_required('staff')`) — add a GET-populate line
   (`form.<key>.data = config_service.get_config('<key>', '<default>') == 'true'`) and append `('<key>', '<default>')`
   to the `config_keys` list in the POST block. For MAC's per-surface × per-status matrix, generate keys in a loop:
   `for surface in ('public','kiosk','admin'): for status in ('in_use','idle','oops','locked_out','unknown'): key = f'mac_show_{surface}_{status}'` — but the matching `AppConfigForm` fields must still exist by name.
3. `esb/templates/admin/config.html` — hand-written Bootstrap cards (`<div class="card mb-4">`); render each toggle
   with the `form-check form-switch` block, grouped in a new "MAC Status Display" card before `{{ form.submit(...) }}`.

**Recommended toggle model (reduce 15-field boilerplate):** per issue #2 the requirement is per-surface control of
which statuses show. Represent as one bool key per (surface, status): `mac_show_{surface}_{status}` (3×5=15 keys),
defaulting to a sensible matrix (public: oops+locked_out only; kiosk & admin: all five). This exactly fits the
existing one-bool-per-key `config_keys` loop. (Considered but rejected: a single comma-joined string per surface —
no precedent, would need custom parse/serialize with no reusable plumbing.)

**Models.** `from esb.extensions import db`; subclass `db.Model`. Nullable string idiom:
`mac_machine_name = db.Column(db.String(200), nullable=True)` (add `index=True` for lookups). Timestamps use
`default=lambda: datetime.now(UTC)` (`from datetime import UTC, datetime`). Equipment-child tables use **`backref`**
(defined on the child), e.g. `equipment = db.relationship('Equipment', backref=db.backref('mac_events',
lazy='dynamic', order_by='...'))`; append-only children omit `updated_at`. Register new models by importing them in
`esb/models/__init__.py` and adding to `__all__` (Alembic discovery). No model defines `to_dict`; every model defines
`__repr__`. **There is no existing row-pruning precedent** — the per-machine event cap is net-new. Do NOT prune on
every insert (F10: costly ordered scan+DELETE per webhook, and it races concurrent inserts). Instead prune once per
machine per worker-poll cycle in a service function `prune_activity_events(machine_name, keep=500)` (delete rows whose
`id` is not in the newest `keep` for that machine) and log via `log_mutation`.

**Migrations (`migrations/versions/`).** Current head = **`77b248bd052d`** (add_equipment_notes_table). **Author ONE
hand-written migration** (`down_revision = '77b248bd052d'`) that (a) adds `equipment.mac_machine_name`, (b) creates
`machine_status`, (c) creates `machine_activity_events` — all in a single revision. Do this AFTER the model files and
the column exist (Tasks 3, 5, 6). **Do NOT run `flask db migrate`** (F8: autogenerate emits its own single revision
and, combined with a hand-authored file, produces a multiple-heads error) — write the migration by hand from the
templates below and apply with `flask db upgrade`, then confirm `flask db heads` shows exactly one head.
Add-column uses `with op.batch_alter_table('equipment') as batch_op: batch_op.add_column(...)`; create-table uses
`op.create_table(...)` + `batch_op.create_index(batch_op.f('ix_<table>_<col>'), [...], unique=...)`. Table
`downgrade` = `op.drop_table(...)` directly (do NOT drop the FK index first — MariaDB error 1553; replicate that
verbatim comment). Generate/verify against the Docker DB per CLAUDE.md.

**Notification queue = the async/outbound seam.** `esb/services/notification_service.py`:
`VALID_NOTIFICATION_TYPES = {'slack_message', 'static_page_push'}` and the `handlers` dict inside
`process_notification()`. Add a type by extending BOTH. Handler contract: `def _deliver_x(notification): ...` returns
`None` on success, **raises on retryable failure**; the worker loop calls `mark_delivered`/`mark_failed`. Retries:
`BACKOFF_SCHEDULE = [30,60,120,300,900,3600]`, `MAX_RETRIES = 10`, managed in `mark_failed`. `queue_notification(
notification_type, target, payload=None)` stores `payload` in a `db.JSON` column. Worker: `flask worker run
--poll-interval N` (default 30) → `run_worker_loop()`. Add the periodic MAC status refresh **AFTER the
`for notification in notifications:` drain loop completes** (near where `_record_iteration_timestamp()` runs), NOT
before it (F3: `upsert_machine_status` commits with `expire_on_commit=True` and would expire the already-loaded
`PendingNotification` objects mid-drain, forcing a re-SELECT per notification; and a slow MAC's `timeout` would delay
draining every cycle). Wrap it in its own try/except so a MAC failure cannot trigger the outer poll-failure backoff,
and **throttle it to run at most every ~60s** (track the last-refresh time in a module-level variable, since a single
worker process owns the loop) so a fast `--poll-interval` doesn't hammer MAC.

**Outbound HTTP.** No `requests`/`httpx` in the tree yet — add `requests` for the MAC client (SDK-based Slack/boto3
calls are the only current outbound). Pattern: explicit `timeout=` (Slack uses 15s), let the primary call raise
(worker retries); only wrap best-effort secondary calls in `try/except Exception: logger.warning(..., exc_info=True)`.

**Status rendering — THREE shapes to touch, not one (F9).** Live machine status is NOT a single chokepoint:
1. `esb/services/status_service.py::get_area_status_dashboard()` (defined ~line 186; per-equipment `dict` appended
   ~line 274, keys `equipment`/`status`/`open_records`) — add a `'machine_status'` key. Feeds public dashboard +
   full/dense kiosk.
2. `get_single_area_status_dashboard()` (defined ~line 288; per-equipment `dict` appended ~line 347 — a **different,
   smaller shape**: `equipment`/`status` only) — add `'machine_status'` here too. Feeds `kiosk_area`.
3. `equipment_page` builds context via `public.py::_build_equipment_page_context()` which returns a **tuple**
   `(status, open_repairs, eta)`, NOT a dict — so `machine_status` cannot be injected in the service there; the VIEW
   fetches and passes it (Task 12). Same for `equipment.py::_render_equipment_detail` (`render_template` kwargs).
Treat the `~line` numbers as approximate anchors — verify before editing. `_status_indicator.html` is an
`{% include %}` (reads `status` + `variant` in scope), NOT a macro; add MAC badges next to its include sites.

**Inbound webhook (clean slate).** No existing REST/JSON API, no token-auth, no CSRF-exempt route today (Slack uses
Socket Mode, not HTTP). Create `esb/views/webhooks.py` with `webhooks_bp = Blueprint('webhooks', __name__,
url_prefix='/webhooks')` and `@webhooks_bp.route('/mac', methods=['POST'])` (no login decorator). Register it in
`esb/views/__init__.py::register_blueprints`, then in `esb/__init__.py::create_app` after `register_blueprints(app)`:
`from esb.extensions import csrf; csrf.exempt(webhooks_bp)`. The `csrf` instance lives in `esb/extensions.py`.
**Optional shared-secret (F5):** default is network-trusted (unauthenticated), but support an optional
`MAC_WEBHOOK_TOKEN` env var — when non-empty, the route (which is `/webhooks/mac/<token>`) rejects a mismatched or
missing token with 403; when empty, it stays open per the network-trusted decision. MAC's `STATUS_WEBHOOK_URL` is
then configured to include the token. This makes hardening available without forcing it and directly caps the
forged-`oops` amplification surface (auto-repair + Slack/static-push flooding).

**On-demand activity UI (clean slate — no AJAX exists).** Add a `@login_required` GET JSON route (e.g.
`@equipment_bp.route('/<int:id>/mac-activity.json')` returning `jsonify(...)`; mirrors `export_csv`), and a small
`fetch()` in `equipment/detail.html`'s `{% block extra_js %}` triggered by a "Load recent activity" button. GET → no
CSRF token needed. Row-navigation JS already lives in `esb/static/js/app.js` (delegated `data-href` clicks).

**Repair write-path seams.** `create_repair_record(equipment_id, description, created_by, severity=None,
reporter_name=None, reporter_email=None, ...)`; new records get `status='New'`. "Open repair for equipment X" guard:
`db.select(RepairRecord).filter(RepairRecord.equipment_id==id).filter(RepairRecord.status.notin_(CLOSED_STATUSES))`
`.scalars().first()`. Resolve/close Slack notifications actually fire from `update_repair_record` (lines ~767-774) in
the branch `if 'status' in audit_changes and audit_changes['status'][1] in CLOSED_STATUSES:` — this is where to also
queue the `mac_clear` notification. `resolve_repair_record(...)` is a thin wrapper delegating to
`update_repair_record(..., status='Resolved', note=...)`. `REPAIR_SEVERITIES = ['Down','Degraded','Not Sure']`;
`CLOSED_STATUSES = ('Resolved','Closed - No Issue Found','Closed - Duplicate')`.

**Tests.** pytest, SQLite in-memory (`TestingConfig`), CSRF disabled. Fixtures: `app`, `client`, `db`,
`staff_client`, `tech_client`, `make_area`, `make_equipment(**kwargs → Equipment(...))` (so `make_equipment(
mac_machine_name='planer')` works once the column exists), `make_repair_record`, `capture` (mutation-log assertions).
Mock outbound HTTP with `unittest.mock.patch` at the module boundary — `patch('esb.services.mac_service.requests')`
(or the client name imported into the module); set `return_value`/`side_effect` on a `MagicMock`; drive URLs via
`app.config`. **No `responses`/`requests_mock` in the repo.** Model tests → `tests/test_models/` (class-grouped,
`pytest.raises(IntegrityError)` then rollback); view/service tests → `tests/test_views/`, `tests/test_services/`.

### Files to Reference

| File | Purpose |
| ---- | ------- |
| `esb/config.py` (`class Config`) | Add `MAC_URL` env var; optional-integration gating pattern |
| `esb/services/config_service.py` | `get_config`/`set_config`; 'true'/'false' bool convention |
| `esb/forms/admin_forms.py` (`AppConfigForm`) | Add per-surface×status `BooleanField`s (name == key) |
| `esb/views/admin.py` (`app_config`) | GET-populate + `config_keys` POST loop (`getattr(form,key)`) |
| `esb/templates/admin/config.html` | `form-check form-switch` toggle markup; card sections |
| `esb/models/equipment.py` | Nullable-string idiom; add `mac_machine_name`; `__repr__`, UTC timestamps |
| `esb/models/equipment_note.py` | Canonical equipment-child (`backref`, append-only) to mirror for new tables |
| `esb/models/repair_timeline_entry.py` | `entry_type` discriminator + allowed-values list (event-type template) |
| `esb/models/__init__.py` | Register new models (import + `__all__`) for Alembic discovery |
| `esb/models/pending_notification.py` | Queue row columns (`payload` JSON, `status`, `retry_count`, `next_retry_at`) |
| `migrations/versions/77b248bd052d_*.py` | Current head; add-column & create-table templates + MariaDB drop caveat |
| `esb/services/notification_service.py` | `VALID_NOTIFICATION_TYPES`, `handlers`, `queue_notification`, `run_worker_loop` |
| `esb/services/repair_service.py` | `create_repair_record`, `update_repair_record` closed-transition seam, `_queue_slack_notification` |
| `esb/services/status_service.py` | Two dashboard builders w/ DIFFERENT dict shapes (`get_area_status_dashboard` ~186/274, `get_single_area_status_dashboard` ~288/347) — inject `machine_status` in both |
| `esb/services/static_page_service.py` | Outbound-call error/timeout + worker-handler pattern reference |
| `esb/views/public.py` | `status_dashboard`/`kiosk`/`kiosk_dense` context; `_build_equipment_page_context()` returns a **tuple** (inject `machine_status` at the view, not the service) |
| `esb/views/equipment.py` | `detail`/`_render_equipment_detail` context; `export_csv` (Response) pattern |
| `esb/views/__init__.py` | `register_blueprints()` — register new `webhooks_bp` |
| `esb/__init__.py` (`create_app`) | `csrf.init_app`, blueprint registration, `csrf.exempt(webhooks_bp)`, worker CLI |
| `esb/extensions.py` | `csrf = CSRFProtect()`, `db` instances |
| `esb/templates/components/_status_indicator.html` | `{% include %}` (reads `status`,`variant`); badge injection sites |
| `esb/templates/public/status_dashboard.html`, `kiosk.html`, `kiosk_dense.html`, `equipment_page.html` | Status display badge sites |
| `esb/templates/equipment/detail.html` | Staff-gated card slot (~line 39) for machine panel + controls + activity |
| `esb/static/js/app.js` | Delegated `data-href` JS; where the activity-fetch JS pattern lives |
| `tests/conftest.py` | Fixtures (`make_equipment(**kwargs)`, `staff_client`, `capture`) |
| `tests/test_services/test_user_service.py`, `test_notification_service.py` | `unittest.mock.patch` outbound-HTTP mocking idiom |

### Technical Decisions

1. **Single phased spec** covering all six issue requirements, ordered lowest-level-first.
2. **History = ESB-persisted webhook events.** MAC 0.15.0 exposes **no** per-machine history API — only a live
   outbound webhook (`STATUS_WEBHOOK_URL`) that POSTs a status_dict + `event` + `timestamp` + `user` on each
   state change. ESB stores these events itself (capped per machine) and displays them on-demand.
3. **Inbound webhook is network-trusted by default, with optional shared-secret (F5).** No auth is required, but an
   optional `MAC_WEBHOOK_TOKEN` env var enables a `/webhooks/mac/<token>` guard (403 on mismatch) so deployments that
   can't fully isolate the endpoint can still cap the forged-`oops` amplification surface. The route is registered
   always but no-ops (204) when `MAC_URL` is unset. CSRF-exempt via `csrf.exempt(webhooks_bp)`.
4. **Status shown from a DB-backed local cache** (`MachineStatus` table, one row per machine keyed by unique
   `machine_name`), updated by BOTH incoming webhooks AND a periodic `GET /api/machines` poll on the worker — so page
   renders never block on MAC and survive brief MAC outages. In-memory cache is ruled out because ESB runs multiple
   gunicorn workers plus a separate worker process.
   - **Concurrent-writer safety (F1):** the webhook (web process) and the poll (worker process) both upsert the same
     `machine_name` row, and `machine_name` is UNIQUE. `upsert_machine_status` MUST be race-safe — mirror
     `config_service.set_config`'s IntegrityError-retry pattern: `SELECT`→ if found `UPDATE` else `INSERT`; on
     `IntegrityError` (lost the insert race) `rollback`, re-`SELECT`, `UPDATE`. Do NOT leave it as a naive
     find-or-create.
   - **Orphan reconciliation (F10):** the poll only upserts; machines removed/renamed in MAC would leak stale rows.
     When a full `fetch_all_status()` succeeds and returns a non-empty list, delete `MachineStatus` rows whose
     `machine_name` is not in that list.
5. **Outbound MAC calls** live in a new `esb/services/mac_service.py` using `requests` with an explicit timeout.
   Synchronous control-button actions call it directly (surfacing errors to the user via flash); the
   resolve-clears-machine action is queued as a new `mac_clear` notification type so it retries with backoff.
6. **`mac_clear` fires only on a genuine resolution (F2).** Queue `mac_clear` ONLY when the repair transitions into
   `Resolved` or `Closed - No Issue Found` **and no other open repair exists for that equipment** — explicitly
   EXCLUDE `Closed - Duplicate` (the authoritative repair is still open, so the machine must stay locked). Define
   `MAC_CLEAR_STATUSES = ('Resolved', 'Closed - No Issue Found')` for this gate; it is a strict subset of
   `CLOSED_STATUSES`.
7. **Idempotent webhook (F4).** Deliveries can be retried/duplicated. Dedup on `(machine_name, event_type,
   event_timestamp)`: if a `MachineActivityEvent` with that triple already exists, treat the whole webhook as a
   duplicate — skip the activity insert AND `maybe_create_oops_repair`. Combined with the open-repair guard, this
   prevents duplicate activity rows and duplicate auto-repairs from retried `oops` events.
   - **Assumptions & limits (R2):** correctness relies on MAC resending the **identical `timestamp`** on a retried
     delivery (an external-behavior assumption — verify per F12; if MAC re-stamps on retry, the open-repair guard is
     the backstop against duplicate repairs, but duplicate activity rows could still appear). `timestamp` is
     second-granularity, so two genuinely-distinct same-type events for one machine within the same second would be
     collapsed into one — acceptable given how rarely a single machine emits two identical-type events per second.
8. **Toggle matrix**: 15 `mac_show_{surface}_{status}` boolean AppConfig keys (fits the existing one-bool-per-key
   loop), default matrix = public shows oops+locked_out; kiosk & admin show all five.
9. **503 handling**: MAC returns HTTP 503 with `{"action_applied": true}` on a state-save timeout for control
   calls — `mac_service` treats that specific response as success-with-warning, not failure.
10. **Machine-name uniqueness (F6).** `Equipment.mac_machine_name` is a nullable, indexed, but NOT unique column.
    Enforce at most one equipment per name via form validation (Task 13): reject saving a `mac_machine_name` already
    used by another non-archived equipment. All lookups use `.first()` and, if a multi-match ever occurs, log a
    warning and act on the first deterministically-ordered (by `id`) row.
11. **Epoch→datetime (F7, corrected in R2).** Convert MAC epoch floats to a UTC instant with
    `datetime.fromtimestamp(value, tz=UTC)` (this yields the correct instant and matches how the codebase *writes*
    its `datetime.now(UTC)` columns). **Critical caveat:** `db.DateTime` is not tz-aware storage — SQLite AND
    MariaDB/PyMySQL both return **naive** datetimes on read, so a value written aware comes back with `tzinfo=None`.
    Therefore: (a) do NOT assert "is aware" after a DB round-trip; (b) NEVER compute
    `datetime.now(UTC) - row.last_checkin` directly — that raises `can't compare offset-naive and offset-aware`;
    normalize first, treating the stored column as naive-UTC (e.g. compare against `datetime.now(UTC).replace(
    tzinfo=None)`, the existing codebase convention). A `None` epoch (e.g. `last_checkin=null`) stores `None`. The
    F4 dedup equality filter (`event_timestamp == <converted>`) is unaffected — it matches in SQL.

### MAC 0.15.0 API facts (verified from external source — cite before relying)

**F12 caveat:** these facts live in the external repo `github.com/jantman/machine-access-control` at **tag `0.15.0`
(NOT `v0.15.0` — the `v`-prefixed tag 404s)**, which is not in this workspace. They were read from that tag's source
during spec authoring; the citing files are listed below. Before implementing Tasks 8/9/10/15, the dev MUST re-open
these files at tag `0.15.0` and confirm each fact — a single wrong assumption (auth required, different 503 body,
different JSON shape) breaks the integration. MAC is built on **Quart** (async Flask), not FastAPI. Source citations:
`docs/source/http-api.rst` (HTTP API docs), `src/dm_mac/views/api.py` + `src/dm_mac/views/machine.py` (routes),
`src/dm_mac/models/machine.py` (status/state decision tree + event strings), `src/dm_mac/webhook.py` (outbound
webhook + `STATUS_WEBHOOK_URL`).

- Base under `MAC_URL`. Machines keyed by **`name`** (string). Blueprint prefixes nest: machine routes are under
  `/api/machine/...` (the `machine` blueprint is registered inside the `/api` blueprint).
- `GET /api/machines` → `{"machines": [status_dict, ...]}`, **no auth**. No single-machine GET endpoint (fetch all,
  filter by `name` client-side).
- `status_dict`: `name`, `display_name`, `status`, `relay` (bool), `oops` (bool), `locked_out` (bool),
  `current_user` (`{"account_id","full_name"}` or null), `last_checkin` (epoch or null), `last_update`.
- `status` ∈ { `in_use`, `idle`, `oops`, `locked_out`, `unknown` }.
- Controls (no request body; return `{"success": true}`; may return HTTP 503 `{"error":..., "action_applied": true}`
  on save timeout): `POST/DELETE /api/machine/oops/<name>`, `POST/DELETE /api/machine/locked_out/<name>`.
  "Clear" = DELETE oops AND DELETE locked_out.
- Webhook payload = status_dict + `event` (∈ `login`, `logout`, `unauthorized`, `unknown_fob`, `override_login`,
  `oops`, `unoops`, `lockout`, `unlock`, `reboot`), `timestamp` (epoch seconds), `user`
  (`{"account_id","full_name"}` or null). **No email** in the payload — auto-repair reporter uses `full_name`;
  `reporter_email` is left blank.

## Implementation Plan

Tasks are ordered lowest-level-first. Each is independently completable; later tasks depend only on earlier ones.
Group A = foundation, B = data/service core, C = inbound + async, D = display, E = write actions, F = tests/docs.

#### Group A — Config & dependency

- [x] **Task 1: Add `requests` dependency.**
  - File: `pyproject.toml` (and `requirements*.txt`/lock if present — verify how deps are declared).
  - Action: Add `requests` to the project dependencies. Run `make setup` (or the venv pip install) to install it.
  - Notes: This is the only new runtime dependency. It is the first HTTP client in the tree.

- [x] **Task 2: Add `MAC_URL` env var.**
  - File: `esb/config.py` (`class Config`).
  - Action: Add `MAC_URL = os.environ.get('MAC_URL', '')` immediately after `ESB_BASE_URL`. Inherited by all env
    subclasses. Leave it `''` in `TestingConfig` (tests set it via `app.config` when needed).
  - Notes: Empty string ⇒ integration disabled everywhere.

#### Group B — Data model & MAC service

- [x] **Task 3: Add `Equipment.mac_machine_name` column.**
  - File: `esb/models/equipment.py`.
  - Action: Add `mac_machine_name = db.Column(db.String(200), nullable=True, index=True)` alongside `serial_number`.
  - Notes: Optional link from an ESB equipment to a MAC machine `name`. Indexed for reverse lookup by machine name.

- [x] **Task 4: Create the SINGLE Alembic migration file (starts with the column add).** _(F8 — perform after Tasks
      3, 5, 6 exist; this is the one ordering exception, called out explicitly.)_
  - File: `migrations/versions/<rev>_add_mac_integration.py` (new — ONE file for all MAC schema changes).
  - Action: Hand-author (do NOT run `flask db migrate`). `down_revision = '77b248bd052d'`. In `upgrade()` add the
    column: `with op.batch_alter_table('equipment') as batch_op:
    batch_op.add_column(sa.Column('mac_machine_name', sa.String(length=200), nullable=True))` +
    `batch_op.create_index(batch_op.f('ix_equipment_mac_machine_name'), ['mac_machine_name'], unique=False)`.
    `downgrade()` reverses it (Task 7 adds the two tables to this SAME file's `upgrade`/`downgrade`).
  - Notes: One revision ⇒ one head. Apply with `flask db upgrade`; confirm `flask db heads` shows exactly one head.

- [x] **Task 5: `MachineStatus` cache model.**
  - File: `esb/models/machine_status.py` (new); register in `esb/models/__init__.py` (import + `__all__`).
  - Action: One row per MAC machine, keyed by `machine_name`. Columns: `id` PK; `machine_name` String(200)
    NOT NULL UNIQUE index; `display_name` String(200) nullable; `status` String(20) NOT NULL; `relay`/`oops`/
    `locked_out` Boolean NOT NULL default False; `current_user_account_id` String(200) nullable;
    `current_user_full_name` String(200) nullable; `last_checkin` DateTime nullable; `last_update` DateTime
    nullable; `updated_at` DateTime NOT NULL default+onupdate `lambda: datetime.now(UTC)`. Add `__repr__`.
  - Notes: `last_checkin`/`last_update` are converted from MAC epoch floats to UTC datetimes on write.

- [x] **Task 6: `MachineActivityEvent` model (append-only, capped, dedup-able).**
  - File: `esb/models/machine_activity_event.py` (new); register in `esb/models/__init__.py`.
  - Action: Columns: `id` PK; `machine_name` String(200) NOT NULL index; `event_type` String(30) NOT NULL;
    `status` String(20) nullable; `user_account_id` String(200) nullable; `user_full_name` String(200) nullable;
    `event_timestamp` DateTime NOT NULL (from webhook epoch); `created_at` DateTime NOT NULL default
    `lambda: datetime.now(UTC)`; `raw_payload` `db.JSON` nullable. Add a **composite index** on
    `(machine_name, event_type, event_timestamp)` to support the F4 dedup lookup. Add a module-level
    `MAC_EVENT_TYPES = ['login','logout','unauthorized','unknown_fob','override_login','oops','unoops','lockout','unlock','reboot']`
    (mirrors `TIMELINE_ENTRY_TYPES`). `__repr__`.
  - Notes: No `updated_at` (append-only). Mirror the `equipment_note.py` child idiom (minus the equipment FK — keyed
    by machine name, since events arrive before/independently of an equipment link).

- [x] **Task 7: Extend the Task-4 migration file with the two `create_table` blocks.**
  - File: the SAME `migrations/versions/<rev>_add_mac_integration.py` created in Task 4 (do NOT make new files — F8).
  - Action: In that file's `upgrade()`, after the column add, `op.create_table('machine_status', ...)` with a UNIQUE
    index on `machine_name` (`batch_op.create_index(..., unique=True)`) and `op.create_table('machine_activity_events',
    ...)` with a plain index on `machine_name` plus the composite `(machine_name, event_type, event_timestamp)` index.
    Prepend the table drops (with the verbatim MariaDB-1553 comment) to `downgrade()` so it reverses in LIFO order
    (drop tables, then drop the column/index). Follow the `77b248bd052d` create-table template.
  - Notes: Result is one revision, one head. Re-verify with `flask db upgrade` + `flask db heads`.

- [x] **Task 8: `mac_service.py` — outbound client + gating + cache/activity writers.**
  - File: `esb/services/mac_service.py` (new).
  - Action: Implement:
    - `mac_enabled() -> bool` → `bool(current_app.config.get('MAC_URL', ''))`.
    - `_base_url()` → trimmed `MAC_URL`.
    - `fetch_all_status() -> list[dict]` → `requests.get(f'{base}/api/machines', timeout=10)`, raise_for_status,
      return `resp.json()['machines']`.
    - `set_oops(name)`, `clear_oops(name)`, `set_lockout(name)`, `clear_lockout(name)`, `clear(name)` (clear = both
      clears) → `requests.post`/`requests.delete(f'{base}/api/machine/{oops|locked_out}/{name}', timeout=10)`.
      **Treat HTTP 503 with JSON `action_applied: true` as success** (return a success-with-warning marker); raise
      `RuntimeError` on other non-2xx or transport errors.
    - `upsert_machine_status(status_dict) -> MachineStatus` → **race-safe upsert (F1)**: `SELECT` by `machine_name`;
      if found `UPDATE` fields else `INSERT`; on `IntegrityError` (lost the insert race vs. the other process)
      `db.session.rollback()`, re-`SELECT`, `UPDATE`. Mirror `config_service.set_config`'s IntegrityError-retry.
      Convert epoch floats with `datetime.fromtimestamp(v, tz=UTC)` (tz-AWARE; **never** `utcfromtimestamp`), and
      store `None` for a null epoch (F7).
    - `record_activity_event(payload) -> MachineActivityEvent | None` → **dedup first (F4)**: if a row already exists
      with the same `(machine_name, event_type, event_timestamp)`, return `None` (duplicate delivery — caller skips
      auto-repair too). Otherwise insert. **Do NOT prune here** — pruning happens in the worker poll (F10).
    - `prune_activity_events(machine_name, keep=500)` → delete rows for that machine whose `id` is not among the newest
      `keep` (by `event_timestamp`/`id` desc); log via `log_mutation`. Called from the poll (Task 10), not per-insert.
    - `reconcile_orphans(seen_names: set[str])` → delete `MachineStatus` rows whose `machine_name` ∉ `seen_names`
      (F10); called from the poll only after a successful non-empty `fetch_all_status()`.
    - `visible_statuses(surface) -> set[str]` → read the 5 `mac_show_{surface}_{status}` config keys, return the set
      of statuses whose key is `'true'`.
    - `get_status_for_equipment(equipment) -> MachineStatus | None` → lookup by `equipment.mac_machine_name`
      (`.first()`; if `mac_machine_name` is falsy, return `None`).
    - `get_equipment_by_machine_name(name) -> Equipment | None` → `.order_by(Equipment.id).first()`; if more than one
      matches, log a warning (F6 — form validation in Task 13 should prevent this).
  - Notes: All outbound calls use `requests` with explicit `timeout=`. Follow the "let primary call raise" pattern.
    Guard every public function early with `if not mac_enabled(): return ...` sensible-empty.

#### Group C — Inbound webhook & periodic poll

- [x] **Task 9: Inbound webhook blueprint (idempotent, optionally token-guarded).**
  - Files: `esb/views/webhooks.py` (new); `esb/views/__init__.py` (register); `esb/__init__.py` (CSRF-exempt);
    `esb/config.py` (add `MAC_WEBHOOK_TOKEN = os.environ.get('MAC_WEBHOOK_TOKEN', '')`).
  - Action: `webhooks_bp = Blueprint('webhooks', __name__, url_prefix='/webhooks')`. Define the route with an OPTIONAL
    token segment: `@webhooks_bp.route('/mac', methods=['POST'])` AND `@webhooks_bp.route('/mac/<token>',
    methods=['POST'])` → `def mac_status(token=None):` — no login decorator. **F5 token check:** if
    `current_app.config.get('MAC_WEBHOOK_TOKEN')` is non-empty and `token != MAC_WEBHOOK_TOKEN` → `('', 403)`. If
    `not mac_service.mac_enabled()` → `('', 204)`. Parse `request.get_json(silent=True)`; if missing/not a dict →
    `400`. Call `mac_service.upsert_machine_status(payload)`; then `event = mac_service.record_activity_event(payload)`
    — **if it returns `None` (duplicate delivery, F4), return `('', 204)` without auto-repair**. Otherwise, if
    `payload.get('event') == 'oops'`, call the auto-repair helper (Task 15). Return `('', 204)`. Wrap the whole body in
    try/except so a single bad payload returns `400`, never `500`. Register `webhooks_bp` in `register_blueprints()`,
    and in `create_app` after `register_blueprints(app)` add
    `from esb.extensions import csrf; csrf.exempt(webhooks_bp)`.
  - Notes: Network-trusted by default; `MAC_WEBHOOK_TOKEN` hardens it. Idempotent via the F4 dedup — retried identical
    webhooks re-upsert status but do NOT duplicate activity rows or auto-repairs.

- [x] **Task 10: Periodic status refresh + prune + orphan-reconcile in the worker loop.**
  - File: `esb/services/notification_service.py` (`run_worker_loop`).
  - Action: Split into TWO functions (R2 — keep the throttle out of the testable core):
    - `_do_mac_refresh()` — the actual work, no throttle: `if not mac_service.mac_enabled(): return`;
      `machines = mac_service.fetch_all_status()`; for each `mac_service.upsert_machine_status(s)`; then
      `mac_service.reconcile_orphans({m['name'] for m in machines})` (only if `machines` non-empty); then for each
      seen machine `mac_service.prune_activity_events(name, keep=500)` (F10).
    - `_refresh_mac_status()` — the throttle wrapper: skip if `<60s` since the module-level `_last_mac_refresh`
      timestamp (initialize the module global to `None` so the FIRST call always runs — bootstrap at worker startup),
      else set it and call `_do_mac_refresh()`. Wrap the whole thing in one try/except:
      `except Exception: logger.warning('MAC refresh failed', exc_info=True)`.
    Call `_refresh_mac_status()` **AFTER the `for notification in notifications:` drain loop** (near
    `_record_iteration_timestamp()`), NOT before it (F3 — avoid expiring loaded `PendingNotification`s and blocking
    drain on a slow MAC).
  - Notes: The dedicated try/except keeps a MAC outage out of the outer poll-failure backoff. AC9 tests
    `_do_mac_refresh()` directly (no throttle); the throttle is tested separately, and tests must reset
    `_last_mac_refresh` (monkeypatch the module global) for isolation (R2). A single worker process owns the loop, so
    the module-level timestamp is safe in production. `fetch_all_status`'s `timeout=10` now adds latency only after
    draining, not before.

#### Group D — Status display

- [x] **Task 11: Inject `machine_status` in BOTH dashboard builders (F9).**
  - File: `esb/services/status_service.py`.
  - Action: In `get_area_status_dashboard()` (def ~line 186; per-equipment dict appended ~line 274) AND
    `get_single_area_status_dashboard()` (def ~line 288; per-equipment dict appended ~line 347 — the smaller
    `equipment`/`status`-only shape), add `'machine_status': <status-or-None>` to each per-equipment dict — only when
    `mac_service.mac_enabled()`; else `None`. Import `mac_service` lazily. (The third surface — `equipment_page` —
    is handled at the VIEW in Task 12 because `_build_equipment_page_context()` returns a tuple, not a dict.)
  - Notes: Unfiltered here (surface filtering is per-view). **Avoid N+1:** batch-load all `MachineStatus` rows for the
    build's `mac_machine_name`s in ONE query (`WHERE machine_name IN (...)`), then map in-memory — do not call
    `get_status_for_equipment` per equipment. Verify the `~line` anchors before editing.

- [x] **Task 12: Pass per-surface visible statuses from views; render badges.**
  - Files: `esb/views/public.py` (`status_dashboard`→'public', `kiosk`/`kiosk_area`/`kiosk_dense`→'kiosk',
    `equipment_page`→'public'); `esb/views/equipment.py` (`_render_equipment_detail`→'admin'); templates
    `public/status_dashboard.html`, `public/kiosk.html`, `public/kiosk_dense.html`, `public/equipment_page.html`,
    `equipment/detail.html`.
  - Action: Each view computes `mac_visible = mac_service.visible_statuses('<surface>')` and passes it to the
    template. **For `equipment_page` and `detail`** (whose contexts do NOT carry `machine_status` from the service —
    `_build_equipment_page_context()` returns a tuple, F9), the view ALSO calls
    `mac_service.get_status_for_equipment(equipment)` and passes the single `machine_status=` kwarg. In each template,
    next to the
    `_status_indicator.html` include site, render a MAC badge **only if** `item.machine_status` and
    `item.machine_status.status in mac_visible`. Add a small badge partial `components/_mac_status_badge.html`
    (maps `in_use`→blue "In Use", `idle`→grey "Idle", `oops`→orange "Oops", `locked_out`→red "Locked Out",
    `unknown`→light "Unknown") and `{% include %}` it.
  - Notes: When `MAC_URL` is unset, `mac_visible` is empty and `machine_status` is `None`, so nothing renders —
    zero visual change for non-MAC deployments.

#### Group E — Equipment linkage, controls, activity UI, auto-repair, resolve-clears

- [x] **Task 13: Add `mac_machine_name` to BOTH equipment forms + the update allow-list.**
  - Files: `esb/forms/equipment_forms.py` (**two classes** — `EquipmentCreateForm` AND `EquipmentEditForm`, R2);
    the equipment form template(s); `esb/services/equipment_service.py` (`create_equipment` keyword params AND
    `_UPDATABLE_FIELDS`).
  - Action: Add `mac_machine_name = StringField('MAC Machine Name', validators=[Optional(), Length(max=200)])` to
    **both** `EquipmentCreateForm` and `EquipmentEditForm` and render it in the form template(s). Thread it through
    `create_equipment` (explicit keyword param) **and add `'mac_machine_name'` to `_UPDATABLE_FIELDS`** in
    `update_equipment` (R2 — `update_equipment` only persists allow-listed fields; omit this and edits silently drop
    the value while create still works). **Uniqueness validation (F6):** reject saving a non-empty `mac_machine_name`
    already used by another non-archived equipment — on the **edit** form exclude the current record's `id`, on the
    **create** form there is nothing to exclude. Implement as a validator/service check raising `ValidationError`;
    it must guard BOTH forms. This guarantees name→equipment lookups resolve to at most one row.
  - Notes: Only meaningful when MAC is enabled; render the field unconditionally (harmless if blank). Persist empty as
    `NULL`, not `''` — **coerce `'' → None` in `create_equipment`/`update_equipment`** (WTForms `StringField` yields
    `''` for blank input and `update_equipment` does a bare `setattr`, so without coercion `''` is stored) so the
    uniqueness check doesn't collide multiple blanks. All writes to `mac_machine_name` go through these two
    views/forms — the webhook only reads — so form/service validation fully covers creation.

- [x] **Task 14: Admin machine panel + control buttons on the detail page.**
  - Files: `esb/views/equipment.py` (new staff-only POST routes); `esb/templates/equipment/detail.html`.
  - Action: Add a staff-gated card (`{% if current_user.role == 'staff' %}`, ~line 39) showing current
    `machine_status` (state, current user, last check-in) and three buttons: **Oops**, **Maintenance Lockout**,
    **Clear** — each a POST form with inline `csrf_token()` and a JS `confirm(...)` (do NOT use `alert()`; a native
    `confirm` on submit is fine). New routes on `equipment_bp`, `@role_required('staff')`:
    `/<int:id>/mac/oops` → `mac_service.set_oops`, `/<int:id>/mac/lockout` → `mac_service.set_lockout`,
    `/<int:id>/mac/clear` → `mac_service.clear`. On success `flash(...)` success (mention the 503 warning case if
    returned); on `RuntimeError` flash danger; redirect back to detail.
  - Notes: Only render the card when `machine_status` is not None (i.e. equipment is linked and MAC enabled).

- [x] **Task 15: Auto-create Down repair on `oops` webhook.**
  - Files: `esb/services/mac_service.py` (helper) or `esb/views/webhooks.py`; uses `repair_service`.
  - Action: `maybe_create_oops_repair(payload)`: resolve equipment via `get_equipment_by_machine_name(payload.get(
    'name'))`; if `None`, return (no-match is fine — status/activity were still recorded, AC18). Guard: if an open
    repair exists for that equipment (`RepairRecord.status.notin_(CLOSED_STATUSES)` → `.scalars().first()`), return
    (no duplicate). Else `repair_service.create_repair_record(equipment_id=eq.id, description="Machine reported 'Oops'
    via MAC.", created_by='mac-webhook', severity='Down', reporter_name=(payload.get('user') or {}).get('full_name'),
    reporter_email=None)`.
  - Notes: **F13** — read the reporter name defensively with `(payload.get('user') or {}).get('full_name')` so a
    `user` object missing `full_name` yields `None`, not a `KeyError`. This helper is only invoked when
    `record_activity_event` returned a non-duplicate event (F4), so retried `oops` webhooks don't re-create repairs.
    `create_repair_record` already queues the `new_report` Slack + `static_page_push` notifications, so the oops repair
    flows through the normal pipeline. Email is unavailable from MAC (see Notes).

- [x] **Task 16: Resolve-clears-machine via `mac_clear` notification.**
  - Files: `esb/services/notification_service.py` (register type + handler); `esb/services/repair_service.py`
    (queue on closed transition).
  - Action: Add `'mac_clear'` to `VALID_NOTIFICATION_TYPES` and `handlers` (`'mac_clear': _deliver_mac_clear`).
    `def _deliver_mac_clear(notification): mac_service.clear(notification.target)` — returns None on success, raises
    on failure (worker retries). In `update_repair_record`, inside the existing closed-transition branch
    (`audit_changes['status'][1] in CLOSED_STATUSES`), queue `mac_clear` ONLY when **all** hold (F2):
    (a) the new status ∈ `MAC_CLEAR_STATUSES = ('Resolved', 'Closed - No Issue Found')` — i.e. NOT `Closed -
    Duplicate`; (b) `record.equipment.mac_machine_name` is set and `mac_service.mac_enabled()`; and (c) **no OTHER
    open repair exists** for that equipment (re-query `RepairRecord.status.notin_(CLOSED_STATUSES)` excluding
    `record.id`). Then `notification_service.queue_notification('mac_clear',
    target=record.equipment.mac_machine_name, payload={'repair_record_id': record.id})`.
  - Notes: **F2** — excluding `Closed - Duplicate` (and requiring no other open repair) prevents physically unlocking
    a machine whose authoritative repair is still open. **R2 placement:** the closed-transition branch body is
    `if config_service.get_config('notify_resolved','true')=='true': _queue_slack_notification(...)`. Queue `mac_clear`
    as a **SIBLING** of that `notify_resolved` check — NOT nested inside it — so turning off the Slack "resolved"
    notification does not also stop physically clearing the machine. Queued (not synchronous) so it retries with
    `BACKOFF_SCHEDULE`. Clears BOTH oops and lockout.

- [x] **Task 17: On-demand recent-activity UI.**
  - Files: `esb/views/equipment.py` (JSON route); `esb/templates/equipment/detail.html` (`{% block extra_js %}`).
  - Action: `@equipment_bp.route('/<int:id>/mac-activity.json')` `@login_required` → query
    `MachineActivityEvent` by the equipment's `mac_machine_name`, newest first, limit (e.g. 100), return
    `jsonify([...])` (event_type, status, user_full_name, event_timestamp ISO). Add a "Load recent activity" button
    in the machine card that `fetch()`es the JSON and renders rows into a table/list. GET → no CSRF token needed.
  - Notes: First AJAX in the app; keep the JS minimal and inline in `extra_js`. Button hidden when no
    `mac_machine_name`.

#### Group F — Admin config, tests, docs

- [x] **Task 18: Per-surface status-display admin toggles (15 keys).**
  - Files: `esb/forms/admin_forms.py`; `esb/views/admin.py` (`app_config`); `esb/templates/admin/config.html`.
  - Action: Add 15 `BooleanField`s named exactly `mac_show_{surface}_{status}` for surface ∈
    {public, kiosk, admin} × status ∈ {in_use, idle, oops, locked_out, unknown} (keep `submit` last). In
    `app_config()`, add GET-populate lines and append `('mac_show_{surface}_{status}', '<default>')` to `config_keys`
    (loopable). Defaults: **public** → oops & locked_out `'true'`, others `'false'`; **kiosk** & **admin** → all
    `'true'`. Render a new `<div class="card mb-4">` "MAC Machine Status Display" section (three sub-groups) using the
    `form-check form-switch` markup, before `{{ form.submit(...) }}`.
  - Notes: Field name MUST equal the config key (view uses `getattr(form, key)`).

- [x] **Task 19: Tests.**
  - Files: `tests/test_models/test_machine_status.py`, `test_machine_activity_event.py` (new);
    `tests/test_services/test_mac_service.py` (new); `tests/test_views/test_webhooks.py` (new);
    `tests/test_services/test_repair_service.py` (extend), `tests/test_services/test_notification_service.py`
    (extend), `tests/test_services/test_status_service.py` (extend); `tests/test_views/test_equipment_views.py`
    (extend for controls + activity JSON); `tests/test_views/test_admin.py` (extend for toggles).
  - Action: See Testing Strategy. Mock all MAC HTTP via `patch('esb.services.mac_service.requests')`.
  - Notes: Drive `MAC_URL` through `app.config`. `make_equipment(mac_machine_name='planer')` works once Task 3 lands.

- [x] **Task 20: Documentation.**
  - Files: `README.md` / deployment docs; `.env.example` if present; `docs/` if the built-in docs site covers config.
  - Action: Document `MAC_URL`; the OPTIONAL `MAC_WEBHOOK_TOKEN` and that MAC's `STATUS_WEBHOOK_URL` must point at
    `https://<esb>/webhooks/mac` (or `https://<esb>/webhooks/mac/<token>` when the token is set); the
    network-trusted-by-default nature of that endpoint and the recommendation to set the token or firewall it; the
    admin status-display toggles; and the control/auto-repair/resolve-clears behaviors.
  - Notes: Also bump `version` in `pyproject.toml` per the release process (feature ⇒ minor bump) when merging.

### Acceptance Criteria

**Configuration & gating**

- [ ] AC1: Given `MAC_URL` is unset, when any public/kiosk/detail page renders, then no MAC badge, card, or control
  appears AND the mocked `requests.get/post/delete` are asserted **never called** (`assert_not_called()`).
- [ ] AC2: Given `MAC_URL` is unset, when a POST hits `/webhooks/mac`, then the response is `204` and nothing is
  written to `machine_status`/`machine_activity_events`.
- [ ] AC2b: Given `MAC_WEBHOOK_TOKEN` is set, when a POST hits `/webhooks/mac` without the matching token (or
  `/webhooks/mac/<wrong>`), then the response is `403` and nothing is written; and with the correct
  `/webhooks/mac/<token>` it succeeds (`204`). Given `MAC_WEBHOOK_TOKEN` is empty, `/webhooks/mac` is accepted.
- [ ] AC3: Given `MAC_URL` is set, when `mac_service.mac_enabled()` is called, then it returns `True`.

**Equipment linkage**

- [ ] AC4: Given a staff user editing equipment, when they set "MAC Machine Name" to `planer` and save, then
  `equipment.mac_machine_name == 'planer'` is persisted and shown on re-edit.
- [ ] AC4b (F6 uniqueness — BOTH forms, R2): Given equipment A already uses `mac_machine_name = 'planer'`, when a
  staff user tries to **create** equipment B with `mac_machine_name = 'planer'`, then it is rejected; and when they
  try to **edit** a different equipment C to `'planer'`, it is also rejected. Given the value is re-saved on A itself
  (edit), it is accepted (self excluded).
- [ ] AC4c (R2 update allow-list): Given an existing equipment, when a staff user edits it and sets
  `mac_machine_name = 'lathe'`, then the value is persisted (proving `mac_machine_name` is in `_UPDATABLE_FIELDS`,
  not silently dropped).

**Inbound webhook & cache**

- [ ] AC5: Given `MAC_URL` is set, when MAC POSTs a valid status_dict webhook for `planer`, then a `MachineStatus`
  row for `planer` is created/updated with the payload's `status`, `oops`, `locked_out`, current user, and epoch
  timestamps converted to UTC datetimes.
- [ ] AC6: Given a webhook arrives, when it is processed, then a `MachineActivityEvent` row is appended with the
  event's `event_type`, `status`, user, and `event_timestamp`.
- [ ] AC6b (F4 idempotency): Given a webhook with a given `(machine_name, event_type, event_timestamp)` has already
  been processed, when an identical webhook is POSTed again, then no second `MachineActivityEvent` is inserted and
  (for an `oops` event) no second repair is created — the response is still `204`.
- [ ] AC7 (F10): Given a machine has more than 500 activity events, when the worker poll runs
  `prune_activity_events(machine_name, keep=500)`, then no more than 500 rows remain for that machine (pruning is
  driven by the poll, not by each webhook insert).
- [ ] AC8: Given a malformed/non-JSON body, when POSTed to `/webhooks/mac`, then the response is `400` and no rows
  are written (no `500`).
- [ ] AC8b (F1 concurrency): Given `upsert_machine_status` is called for an existing `machine_name` and the first
  `INSERT` raises `IntegrityError` (simulating a concurrent insert), when the retry path runs, then the existing row
  is `UPDATE`d exactly once, no exception propagates, and only one row exists for that `machine_name`.

**Periodic poll**

- [ ] AC9: Given `MAC_URL` is set, when `_do_mac_refresh()` runs (the un-throttled core), then `GET /api/machines`
  is fetched and every returned machine's `MachineStatus` is upserted, and machines no longer returned are removed
  (`reconcile_orphans`). (Throttle behavior of `_refresh_mac_status()` — first-call-runs, then ≥60s gate — is a
  separate test that resets the module-level `_last_mac_refresh`.)
- [ ] AC9b (F3, testable without internals): Given MAC is unreachable (mocked `requests.get` raises), when a worker
  cycle runs with a pending notification queued, then a warning is logged AND the pending notification is still
  delivered in that same cycle (assert `mark_delivered` / delivered status) — i.e. the failed refresh does not block
  or crash the drain.

**Status display**

- [ ] AC10: Given equipment `planer` is `oops` in the cache and the `mac_show_public_oops` toggle is on, when the
  public dashboard renders, then an "Oops" badge shows on that equipment card.
- [ ] AC11: Given `mac_show_public_in_use` is off, when the public dashboard renders for an `in_use` machine, then no
  MAC badge shows on public — but the same machine shows an "In Use" badge on the kiosk if `mac_show_kiosk_in_use`
  is on.

**Controls**

- [ ] AC12: Given a staff user on a linked equipment's detail page, when they click "Oops" and confirm, then
  `POST /api/machine/oops/<name>` is called on MAC and a success flash appears.
- [ ] AC13: Given a MAC control call returns HTTP 503 with `action_applied: true`, when the button handler runs, then
  it is treated as success-with-warning (flash warning, not error).
- [ ] AC14: Given a MAC control call fails (transport error / non-2xx without `action_applied`), when the handler
  runs, then a danger flash appears and the user is redirected back to the detail page.
- [ ] AC15: Given a non-staff user, when they POST to a `/<id>/mac/*` control route, then access is denied
  (`@role_required('staff')`).

**Auto-repair on oops**

- [ ] AC16: Given equipment linked to `planer` has no open repair, when an `oops` webhook arrives for `planer` with a
  current user, then a `RepairRecord` is created with `severity='Down'`, `reporter_name` = the user's full name,
  `reporter_email` blank, and the normal `new_report` + `static_page_push` notifications are queued.
- [ ] AC17: Given equipment linked to `planer` already has an open repair, when an `oops` webhook arrives, then no
  duplicate repair is created.
- [ ] AC18: Given an `oops` webhook for a machine name not matching any `equipment.mac_machine_name`, when processed,
  then the status/activity are still recorded but no repair is created.

**Resolve-clears-machine**

- [ ] AC19: Given a repair on equipment linked to `planer` is resolved to `Resolved` (or `Closed - No Issue Found`)
  and no other open repair exists for that equipment, when the update commits, then exactly one `mac_clear`
  notification targeting `planer` is queued.
- [ ] AC19b (F2): Given a repair is closed as `Closed - Duplicate`, OR another open repair still exists for that
  equipment, when the update commits, then **no** `mac_clear` notification is queued (the machine stays locked).
- [ ] AC20: Given a queued `mac_clear` notification, when the worker delivers it, then MAC receives DELETE on both
  `/api/machine/oops/planer` and `/api/machine/locked_out/planer` (assert the mocked `requests.delete` calls).
- [ ] AC20b (F11): Given `mac_service.clear` raises (mocked MAC failure), when the worker processes the `mac_clear`
  notification, then `mark_failed` is invoked, `retry_count` increments, and `next_retry_at` is set per
  `BACKOFF_SCHEDULE` (no permanent loss until `MAX_RETRIES`).

**Activity UI**

- [ ] AC21: Given a staff/tech user on a linked equipment's detail page, when they click "Load recent activity", then
  a `fetch()` to `/<id>/mac-activity.json` returns the recent events (newest first) and they render into the panel.

## Additional Context

### Dependencies

- New Python dependency: `requests` (outbound MAC HTTP client).
- ONE Alembic migration (single revision) for the new `Equipment` column and both new tables (F8).
- Env vars: `MAC_URL` (enables the integration) and optional `MAC_WEBHOOK_TOKEN` (hardens the inbound webhook).
- Runtime: a reachable MAC instance at `MAC_URL`; MAC configured with `STATUS_WEBHOOK_URL` pointing at the ESB
  receiver (for status cache freshness, activity history, and auto-repair).

### Testing Strategy

**Framework:** pytest, SQLite in-memory (`TestingConfig`), CSRF disabled. Drive `MAC_URL` via `app.config`. Mock ALL
MAC HTTP with `unittest.mock.patch('esb.services.mac_service.requests')` (set `.get`/`.post`/`.delete` return
`MagicMock` with `.json()`, `.status_code`, `.raise_for_status`); no live network. No `responses`/`requests_mock` in
the repo.

**Unit / service tests**
- `mac_service`: `mac_enabled()` true/false by config; `fetch_all_status()` parses `{'machines':[...]}`;
  control functions hit the right URL/method; **503-with-`action_applied`** returns success while other failures raise
  `RuntimeError`; `upsert_machine_status` create + update paths and epoch→datetime conversion **(assert the stored
  value equals the expected UTC instant after refetch — compare naive-to-naive, NOT `tzinfo` awareness, per F7-R2)**
  and null-epoch → `None`; **F1 concurrency**: patch the first `INSERT` to raise `IntegrityError`
  and assert the retry updates the existing row exactly once with no exception; `record_activity_event` **F4 dedup**:
  a second call with the same `(machine_name, event_type, event_timestamp)` returns `None` and inserts nothing;
  `prune_activity_events` keeps only the newest N; `reconcile_orphans` deletes rows not in the seen set;
  `visible_statuses('public')` reflects the config toggles; `get_status_for_equipment` / `get_equipment_by_machine_name`
  lookups (including the multi-match warning path).
- Models: `MachineStatus` unique-`machine_name` constraint (`pytest.raises(IntegrityError)` then rollback);
  `MachineActivityEvent` append + `MAC_EVENT_TYPES` + composite-index dedup query.
- `notification_service`: `queue_notification('mac_clear', ...)` accepted; `process_notification` dispatches to
  `_deliver_mac_clear`; handler success vs raise→`mark_failed` (retry_count++/next_retry_at set); **F3**: a cycle where
  the MAC refresh raises still delivers a queued notification (assert delivered) and logs a warning.
- `repair_service`: closed-transition queues `mac_clear` for `Resolved`/`Closed - No Issue Found` with no other open
  repair; **F2**: does NOT queue for `Closed - Duplicate` nor when another open repair exists; does NOT when
  unlinked/MAC-disabled; `maybe_create_oops_repair` create / no-duplicate / no-equipment / missing-`full_name` (F13)
  branches.
- `status_service`: both `get_area_status_dashboard` and `get_single_area_status_dashboard` per-equipment dicts include
  `machine_status` when enabled, `None` when disabled; batched load issues one `MachineStatus` query (no N+1).

**View / integration tests**
- `/webhooks/mac`: `204` when disabled; valid payload writes status + activity (+ `oops` → repair); malformed → `400`;
  the route is CSRF-exempt (POST with no CSRF token still succeeds); **F5 token**: with `MAC_WEBHOOK_TOKEN` set, wrong/
  missing token → `403`, correct `/webhooks/mac/<token>` → `204`; **F4**: duplicate identical POST is idempotent.
- Equipment detail: staff sees machine card + controls when linked; control POSTs call `mac_service` (mocked) and
  flash success/warning(503)/error; `@role_required('staff')` blocks non-staff; `mac-activity.json` returns events for
  a logged-in user.
- Public/kiosk rendering: badge appears/absent per `mac_show_*` toggles and cache state (test public vs kiosk
  divergence per AC11); nothing renders when `MAC_URL` unset.
- Admin config: the 15 `mac_show_*` toggles round-trip (GET populate ↔ POST save) via `staff_client`.
- Equipment form: **F6** duplicate `mac_machine_name` rejected; self-edit accepted.

**Manual testing**
1. Run a local MAC (or stub) at `MAC_URL`; set MAC's `STATUS_WEBHOOK_URL` to `http://<esb>/webhooks/mac`.
2. Link an equipment's MAC Machine Name; oops the machine in MAC → confirm ESB badge flips, a Down repair appears,
   and an activity event is logged.
3. Resolve the repair in ESB → confirm MAC's oops/lockout clear.
4. Use the detail-page Oops/Lockout/Clear buttons → confirm MAC state changes; toggle admin display settings and
   confirm per-surface badge visibility.

### Notes

- **Email limitation**: MAC's webhook `user` object is `{account_id, full_name}` only — no email — so auto-created
  repair records have `reporter_name` set and `reporter_email` blank. If member email is ever needed, a future
  `account_id`→email mapping (via the user directory) would be required (out of scope).
- **503 on controls**: MAC may return HTTP 503 with `action_applied: true` on a state-save timeout; ESB treats that
  specific response as success-with-warning, not failure (AC13).
- **Webhook auth is now IN scope but optional (F5)**: `/webhooks/mac` defaults to network-trusted, but the optional
  `MAC_WEBHOOK_TOKEN` provides a `/webhooks/mac/<token>` guard (403 on mismatch). This matters because the endpoint
  can create repair records and enqueue Slack/static-push notifications, so an unguarded, internet-reachable receiver
  is a repair/notification amplification (DoS) vector — set the token or firewall the endpoint in such deployments.
  **R2 caveat:** the token is a URL **path segment**, so it appears in access/proxy logs; for stronger secrecy a
  future variant could read it from a request header instead (the stacked route decorators share one endpoint, so
  there is no `url_for` collision). With `MAC_WEBHOOK_TOKEN` empty, both `/webhooks/mac` and `/webhooks/mac/<any>`
  are accepted (token check skipped) — expected under the network-trusted default.
- **Concurrency (F1)**: the webhook (web process) and the poll (worker process) both upsert the same UNIQUE
  `machine_name` row; `upsert_machine_status` uses the IntegrityError-retry pattern to stay correct under the race.
- **Resolve-clears safety (F2)**: `mac_clear` deliberately excludes `Closed - Duplicate` and requires no other open
  repair, so closing a duplicate never unlocks a machine whose real repair is still open.
- **Cache staleness / worker dependency**: displayed status is only as fresh as the last webhook or the ≤60s worker
  refresh. If the worker is down and no webhooks arrive, badges go stale (they never block page loads). Consider
  showing `last_update` age on the admin card — but compute it treating the stored column as **naive-UTC** (e.g.
  `datetime.now(UTC).replace(tzinfo=None) - status.last_update`); comparing a refetched `db.DateTime` directly to an
  aware `datetime.now(UTC)` raises (F7-R2).
- **N+1 risk**: dashboards render many equipment; batch-load `MachineStatus` by machine name once per dashboard
  build rather than per-equipment queries (Task 11).
- **Migration**: ONE hand-authored revision; do NOT run `flask db migrate` (F8). Apply/verify against the Docker
  MariaDB per CLAUDE.md (port not host-mapped; inspect container IP fresh); confirm a single `flask db heads`.
- **External-fact risk (F12)**: the MAC 0.15.0 API facts are from an external repo; re-verify them at tag `0.15.0`
  before implementing Tasks 8/9/10/15 (citations listed in the MAC facts section).
- **Future considerations (out of scope)**: `account_id`→email mapping; surfacing MAC `current_user` on public views
  (privacy); a dedicated MAC health indicator; per-machine polling if MAC adds a single-machine GET endpoint.
