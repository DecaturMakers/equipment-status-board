---
title: 'Technician Web UI UX Improvements'
slug: 'technician-web-ux-improvements'
created: '2026-05-11'
status: 'Completed'
stepsCompleted: [1, 2, 3, 4, 5, 6]
adversarial_review_applied: '2026-05-11 (round 1: 25 findings; round 2: 21 findings; round 3: 21 findings; round 4: 21 findings; all addressed)'
tech_stack:
  - 'Python 3.14'
  - 'Flask + Flask-SQLAlchemy + Flask-WTF + Flask-Login'
  - 'Bootstrap 5 (bundled via static/js/bootstrap.bundle.min.js, includes Modal component)'
  - 'Vanilla JavaScript (no framework). All event handlers in esb/static/js/app.js or scoped <script> blocks — never inline HTML attributes (CSP-friendly).'
  - 'Jinja2 templates'
  - 'pytest for views + services tests'
files_to_modify:
  - 'esb/__init__.py (register CLOSED_STATUSES as Jinja context)'
  - 'esb/services/repair_service.py (add resolve_repair_record; extend get_repair_queue with assignee_id + unassigned kwargs)'
  - 'esb/views/repairs.py (two new POST routes; queue/detail view inject forms)'
  - 'esb/forms/repair_forms.py (two new form classes)'
  - 'esb/slack/handlers.py (converge resolve_with_note onto new service helper)'
  - 'esb/static/js/app.js (add assignee filter; mobile-card click-nav; modal-trigger handler; modal-textarea reset)'
  - 'esb/templates/repairs/queue.html (Actions column; restructured mobile cards; new filter select; resolve modal include)'
  - 'esb/templates/repairs/detail.html (Claim/Resolve buttons in header; resolve modal include)'
  - 'esb/templates/components/_resolve_modal.html (new)'
  - 'tests/test_services/test_repair_service.py'
  - 'tests/test_views/test_repair_views.py'
  - 'tests/test_slack/test_handlers.py (re-validated unchanged; OPTIONAL new mock-based test at implementer''s discretion per Task 19)'
  - 'docs/technicians.md'
code_patterns:
  - 'Blueprint route handlers in esb/views/repairs.py protected by @role_required("technician")'
  - 'POST forms render CSRF via raw input matching admin/areas.html: <input type="hidden" name="csrf_token" value="{{ csrf_token() }}"> (NOT form.hidden_tag() — that emits id="csrf_token" which collides when multiple forms exist on one page)'
  - 'Service-layer functions raise ValidationError; views catch and flash(str(e), "danger")'
  - 'POST-then-redirect with allowlist-validated next param (only two valid targets: queue index, repair detail)'
  - 'Service-layer claim_repair_record already exists with closed-record guard (esb/services/repair_service.py:225). The new resolve_repair_record mirrors that pattern at the same file.'
  - 'Queue filtering is a hybrid pattern: URL query params drive initial server-side filtering (esb/views/repairs.py:62-67 reads ?area= and ?status=, passes to get_repair_queue); dropdowns then trigger client-side display-toggling via esb/static/js/app.js:80-118. The new Assignee filter mirrors this hybrid pattern (?assignee=me|unassigned param + client-side dropdown change handler) for consistency.'
  - 'Clickable rows + cards use data-href + JS navigation (existing pattern at esb/static/js/app.js:5-16). Mobile cards adopt the same pattern, eliminating anchor-inside-anchor issues.'
  - 'Bootstrap modal with the form wrapping modal-body + modal-footer (textarea must be inside the form; submit button must be inside the form). admin/areas.html:54-73 is referenced for the raw csrf_token input pattern only — that template''s modal is a single-button confirm with no body inputs and uses a different form-placement, which does not apply here.'
test_patterns:
  - 'tests/test_views/test_repair_views.py uses staff_client / tech_client / make_equipment / make_repair_record fixtures from tests/conftest.py'
  - 'tests/test_services/test_repair_service.py groups tests in classes per-function (e.g. TestClaimRepairRecord starts at line 1357)'
  - 'View tests assert status codes, flash messages in resp.data, and DB state via _db.session.refresh(record)'
  - 'CSRF is disabled in TestingConfig (esb/config.py:67) so test POSTs do not need a token'
  - 'tests/test_slack/test_handlers.py uses _register_and_capture(app) to capture handler fns from a MagicMock bolt_app, then invokes them directly'
issue: 'https://github.com/jantman/equipment-status-board/issues/35'
---

# Tech-Spec: Technician Web UI UX Improvements

**Created:** 2026-05-11
**GitHub Issue:** [#35 Technician web UI UX improvements](https://github.com/jantman/equipment-status-board/issues/35)
**Adversarial Review Applied:** 2026-05-11 — four rounds, 88 findings total (25 + 21 + 21 + 21), all real findings addressed. See frontmatter `adversarial_review_applied` for the authoritative record.

## Overview

### Problem Statement

The two most common technician actions on the web UI — **claiming a new repair** and **resolving an open one** — require navigating multiple pages and form fields:

1. Today, to claim a `New` repair: open the queue → click the row → click **Edit** → change *Status* to "Assigned" → change *Assignee* to self → click **Save Changes**. That's 5 clicks for an action that is logically one decision.
2. To resolve an open repair: open the queue → click the row → click **Edit** → change *Status* to "Resolved" → type a note in the *Add Note* textarea (a convention, not enforced) → click **Save Changes**. The note is not required, and nothing prompts the technician to add one.
3. The repair queue has no way to quickly see "my open repairs" or "open unassigned repairs" — a technician must visually scan the *Assignee* column.

The Slack `/esb-repair` dispatcher already exposes one-button **Claim** and **Resolve with Note** flows (issue #34, the `repair_action_submission` handler at `esb/slack/handlers.py:597-625`), and the underlying `repair_service.claim_repair_record()` helper exists with the New→Assigned promotion rule baked in. The web UI lags this UX.

### Solution

Three changes:

1. **Claim button** on every open repair record whose status is `'New'` AND whose `assignee_id != current_user.id`. POSTs to `/repairs/<id>/claim`, calls the existing `repair_service.claim_repair_record()`, redirects back to the originating page (allowlist-validated) with a success flash. Single click, no form input.

2. **Resolve button** on every open repair record whose status is NOT in `CLOSED_STATUSES` AND NOT `'New'` (UI nudge — technicians triage `New` records first, not blind-resolve them). Clicking opens a Bootstrap modal with a required note textarea. Submitting POSTs to `/repairs/<id>/resolve`, calls a new `repair_service.resolve_repair_record()` helper that sets `status='Resolved'` and appends the note as a timeline entry in one call, then redirects with a success flash.

3. **Assignee filter** on `/repairs/queue` with options All / Mine / Unassigned. **Hybrid pattern matching the existing Area + Status filters** — accepts `?assignee=me|unassigned` URL query param (server-side filter via a new `get_repair_queue` kwargs extension), AND the dropdown's `change` event triggers client-side display-toggling via `app.js` (mirrors how the Area and Status filters work today). Server-side filtering is the source of truth on page load and reload; client-side toggling lets the user refine without a reload. The URL param is bookmarkable and shareable.

Buttons appear in three surfaces: the queue table row (desktop), the queue card (mobile), and the repair detail page header. The Resolve modal is extracted as a Jinja partial (`components/_resolve_modal.html`) and included once per page; a single `show.bs.modal` handler in `app.js` reads the trigger button's `data-repair-id`, patches the modal's form `action`, clears any stale textarea text, and updates the visible title. The Slack dispatcher's `resolve_with_note` branch is also converged onto the new service helper for single-source-of-truth.

### Scope

**In Scope:**

- New service function `repair_service.resolve_repair_record(repair_record_id, resolved_by_user_id, resolved_by_username, note)`. Body: validate **in this order** — note non-empty after stripping, then user exists (the explicit `User.get` check that mirrors `update_repair_record`'s `assignee_id` validation), then record exists, then record open (raise `ValidationError` if in `CLOSED_STATUSES`). Finally call `update_repair_record(status='Resolved', note=note.strip())`. Order matters: a malformed request with empty note + bogus user + bogus record-id flashes "Resolution note is required" (the cleanest user-facing message), not the user-not-found error. The combined-failure test T12.12 pins this ordering.
- Extension to `repair_service.get_repair_queue(area_id=None, status=None)`: add two new kwargs `assignee_id: int | None = None` and `unassigned: bool = False`. When `assignee_id is not None`, filter `RepairRecord.assignee_id == assignee_id`. When `unassigned is True`, filter `RepairRecord.assignee_id IS NULL`. Mutually exclusive: raise `ValidationError` if both passed. Matches the existing Area/Status kwargs pattern at `esb/services/repair_service.py:338-372`.
- Two new view routes in `esb/views/repairs.py`:
  - `POST /repairs/<int:id>/claim` — calls `claim_repair_record`, redirects via allowlist-validated `next`.
  - `POST /repairs/<int:id>/resolve` — calls `resolve_repair_record`, narrows form-error flashing to the `note` field (CSRF/other failures flash a generic "Invalid resolve request" message).
- A `_safe_next_url(next_val, record_id)` helper using an **explicit allowlist** of two paths: `url_for('repairs.queue')` and `url_for('repairs.detail', id=record_id)`. Anything else (including backslash, scheme, protocol-relative, URL-encoded variants) falls back to detail. (The fallback is constructed inside the function — not passed as an argument.)
- Two new Flask-WTF forms in `esb/forms/repair_forms.py`: `RepairClaimForm` (CSRF only) and `RepairResolveForm` (note + submit).
- `esb/static/js/app.js` extension:
  - Add Assignee filter to `applyFilters()` — comparison against `dataset.assigneeId` and `dataset.unassigned` on rows/cards. The dropdown's `change` event triggers `applyFilters()` (no URL update; the URL state is the page-load state).
  - Extend the click-to-navigate selector to include `.queue-card[data-href]` (mobile cards adopt the same `data-href` pattern as desktop rows). Preserve the existing `row.style.cursor = 'pointer';` line so the new mobile-card click target gets the affordance.
  - Update `.queue-card` filter display-toggle to set `display` directly on the card div (not via `closest('a')`, since the mobile-card restructure drops the wrapping `<a>`).
  - Add a `show.bs.modal` listener on `#resolveModal` that reads `data-repair-id` from the trigger, sets the form's `action` to `/repairs/<id>/resolve`, **clears the textarea**, and updates the visible repair-id badge.
- `esb/__init__.py`: register a context processor exposing `CLOSED_STATUSES` so templates use a single source of truth — `{% if record.status not in CLOSED_STATUSES %}` rather than hard-coding the list.
- Slack convergence: `esb/slack/handlers.py:597-625` (the `repair_action_submission` view-submission handler's `resolve_with_note` branch) refactored to call `repair_service.resolve_repair_record(...)` instead of `update_repair_record(status='Resolved', note=...)`. Single source of truth for resolve invariants (closed-record guard, empty-note guard, user-exists guard). The pre-validation in the Slack handler is retained for per-input-block error attribution.
- Template updates:
  - `esb/templates/repairs/queue.html`: add an **Actions** `<th>`/`<td>` column to the desktop table; restructure mobile cards (drop wrapping `<a>`, add `data-href` + `data-assignee-id` + `data-unassigned` on `.queue-card` itself, action buttons live in a separate `card-body` row inside the same card div); add the **Assignee** filter `<select>`; embed `data-current-user-id` on a queue-scoped container; include the resolve-modal partial. All buttons carry `aria-label` annotations.
  - `esb/templates/repairs/detail.html`: add Claim and Resolve buttons in the header row alongside the existing Edit button, with `{% if %}` guards using the new Jinja global `CLOSED_STATUSES`; include the resolve-modal partial.
  - `esb/templates/components/_resolve_modal.html` (new): the modal markup — `<form>` lives **inside** `modal-content`, sibling to `modal-header`, wrapping `modal-body` + `modal-footer` (this is a valid Bootstrap pattern; `admin/areas.html` uses a different layout for its single-button confirm modal, which doesn't apply here because we have a body-level textarea). CSRF rendered via raw `<input type="hidden" name="csrf_token" value="{{ csrf_token() }}">` (matches `admin/areas.html:67`) rather than `form.hidden_tag()` to avoid duplicate `id="csrf_token"` collisions across multiple forms on the same page.
- Tests in `tests/test_services/test_repair_service.py`:
  - New `TestResolveRepairRecord` class covering: resolve open record → status='Resolved', note timeline entry created; closed record raises `ValidationError`; empty / whitespace-only note raises `ValidationError`; nonexistent record raises `ValidationError`; nonexistent user_id raises `ValidationError`; resolve from `New` is allowed at the service layer; the `resolved` Slack notification is queued via the existing trigger; non-ASCII (emoji + multilingual) note round-trips through the timeline entry intact.
  - Tests for re-claim no-op behavior (regression test for the concurrent-claim case): claiming an already-self-assigned record produces zero new `assignee_change` or `status_change` timeline entries and queues zero notifications (the `update_repair_record` no-op guard catches it).
- Tests in `tests/test_views/test_repair_views.py`:
  - New `TestClaimRepairRoute` class (13 tests per Task 14): tech and staff happy path on `New` and on later open statuses; closed-record danger flash with no mutation; nonexistent ID → 404; unauthenticated → login redirect; member-role → 403; safe `next` honored (queue + detail); cross-record `next` falls back; unsafe `next` (`//evil.com/`, `/\evil.com/`, `http://evil.com/`) falls back.
  - New `TestResolveRepairRoute` class (12 tests per Task 15): tech and staff happy path; empty note flashes WTForms validation error and does not mutate; whitespace-only note flashes service-layer "Resolution note is required" and does not mutate; closed-record danger flash; nonexistent → 404; unauthenticated → login; member-role → 403; resolve-from-`New` allowed via route; safe `next` honored; unsafe `next` falls back; non-ASCII note round-trips.
  - Extension of existing queue tests (17 tests per Task 16): button-rendering visibility (5), data-attribute assertions (4 — including the empty-queue guard test 5b), filter-`<select>` and modal-include presence (2), URL-param-driven server-side filter behavior (4 — `?assignee=me|unassigned|empty|bogus`), dropdown `selected`-state reflecting URL state (3 including the unknown-value edge case).
  - `TestDetailQuickActions` class (7 tests per Task 17): claim/resolve button visibility matrix across statuses, modal-include presence, Edit-button regression check.
- Tests in `tests/test_slack/test_handlers.py`:
  - **No test changes required** (per Task 19's verification-only directive). The existing three resolve-with-note tests at `test_handlers.py:1315-1376` pass unchanged after the Task 18 convergence because they verify outcomes via DB state, not by mocking service functions. An optional new mock-based convergence test is the implementer's discretion.
- `docs/technicians.md` update: add a "Quick Actions" subsection plus a mention of the Assignee filter.
- DB schema verification (no migration produced — just a verification task): confirm `repair_timeline_entries.content` column uses `utf8mb4` (4-byte Unicode) in the deployed MariaDB so emoji/non-ASCII notes round-trip correctly. If `utf8mb3`, raise as a follow-up — not a blocker for this spec since SQLite (test DB) is full Unicode and the production schema can be migrated later.

**Out of Scope:**

- **Kanban card quick actions.** Staff-only view; this issue is technician-focused. Adding quick actions there is a reasonable follow-up.
- **Backfilling claim_repair_record's missing user-exists check.** `claim_repair_record` doesn't validate the user explicitly because `update_repair_record` validates the `assignee_id` (which receives the same value). The new `resolve_repair_record` lacks that incidental coverage (no `assignee_id` change) so adds the validation directly. Backfilling claim is non-behavior-changing cleanup — out of scope.
- **Backfilling the broader codebase's `form.hidden_tag()` → raw CSRF input pattern.** Pre-existing duplicate-`id` issue affects detail-page note/photo forms today; the new spec uses the raw-input pattern to avoid amplifying it but does not retrofit the existing forms.
- **Database schema / charset migration.** If the verification task discovers `utf8mb3`, the migration is a separate ticket.
- **Concurrency: row-level locking on claim.** Two simultaneous claims produce last-write-wins on `assignee_id` with one extra timeline entry; the no-op guard in `update_repair_record` ensures only one `status_changed` notification fires when both attempts hit a `New` record. Acceptable for this makerspace. Pessimistic locking is out of scope.
- **No-op claim button when self-assigned.** UI hides the Claim button when `record.assignee_id == current_user.id`, so a no-op claim is unreachable via the queue/detail page. The service still accepts re-claim and idempotently no-ops (regression test included).
- **JavaScript framework / build pipeline.** Vanilla JS only — no React, no Vue, no esbuild. All JS lives in `esb/static/js/app.js`.
- **Bulk actions** ("claim all selected"). The issue asks for "one-button" per record.
- **Notification trigger changes.** Resolve flows through `update_repair_record`, which already queues the `resolved` Slack notification.

## Context for Development

### Codebase Patterns

- **Service-layer pattern.** Views in `esb/views/repairs.py` never call the ORM directly for business logic; they delegate to `esb/services/repair_service.py`. All validation lives in the service and raises `esb.utils.exceptions.ValidationError`. Views catch it and flash `str(e)` with category `'danger'`, then re-render or redirect. Audit-log entries and Slack notification queueing happen in the service layer. The two new routes follow this exact shape.

- **The Claim service already exists.** `repair_service.claim_repair_record(repair_record_id, claimed_by_user_id, claimed_by_username)` at `esb/services/repair_service.py:225`. Key behaviors:
  - Calls `get_repair_record(id)` (raises `ValidationError` on not-found).
  - Raises `ValidationError` if `record.status in CLOSED_STATUSES`.
  - Always sets `assignee_id = claimed_by_user_id`.
  - Promotes `status` to `'Assigned'` **only** when current status is `'New'`. For all other open statuses, it is a pure assignee swap.
  - Delegates to `update_repair_record()`, which creates timeline entries, queues notifications, and runs the no-op guard.
  - **No web view currently calls this function** — it's only invoked from Slack today (`esb/slack/handlers.py:614`). The new `/repairs/<id>/claim` route is its first web caller.
  - The user-exists check is implicit via `update_repair_record`'s validation of the `assignee_id` change (same value passed through).

- **`update_repair_record` is the single mutation entry point.** All status / assignee / ETA / note changes go through it (`esb/services/repair_service.py:375`). Behaviors:
  - Accepts `**changes` with whitelisted keys `status`, `severity`, `assignee_id`, `eta`, `specialist_description`, and a separate `note` kwarg.
  - Creates a `RepairTimelineEntry` of the appropriate `entry_type` for each changed field; the `note` kwarg appends a `note` entry in the same transaction.
  - **No-op guard:** skips notification + timeline-entry creation if the new value equals the current value. This is the safety net for concurrent claim/resolve attempts.
  - Validates `assignee_id` references an existing User (raises `ValidationError`) — but does **not** validate `author_id` symmetrically. `resolve_repair_record` therefore adds its own user-exists check on `resolved_by_user_id` (which is passed only as `author_id`, not as `assignee_id`).
  - Queues Slack notifications when `status` transitions to a `CLOSED_STATUSES` value (the `resolved` event) or to any other open status (the `status_changed` event from #34). Resolve from this spec hits the `resolved` path automatically.
  - Triggers static-page-push regeneration when `status`, `severity`, or `eta` changes.
  - The new `resolve_repair_record()` is a thin wrapper that calls `update_repair_record(status='Resolved', note=note.strip())`; all that machinery is reused for free.

- **`@role_required('technician')` decorator** (`esb/utils/decorators.py:15`) gates both new routes. Role hierarchy is `staff > technician > member`, so `staff` admits but `member` (and unauthenticated) is rejected with `abort(403)` after login.

- **Clickable rows/cards use `data-href` + JS navigation.** `esb/static/js/app.js:5-16` already implements this for `.queue-row[data-href]` and `.repair-history-row[data-href]`. The mobile-card restructure (Task 8) adopts the same pattern by adding `data-href` to `.queue-card` and extending the selector in `app.js`. This eliminates the existing anchor-wraps-card pattern, which would otherwise force a redesign for embedded action buttons.

- **Bootstrap 5 Modal pattern.** The codebase's only existing modal is `esb/templates/admin/areas.html:54-73`. That modal is a single-button confirm with NO inputs in `modal-body` — its `<form>` sits inside `modal-footer` wrapping just the submit button. **Our resolve modal cannot match that placement** because the textarea must live inside the form (otherwise the note doesn't submit) and the submit button must also live inside the form. We use a different but valid Bootstrap structure: `<form>` lives inside `modal-content`, sibling to `modal-header`, wrapping both `modal-body` and `modal-footer`:
  ```html
  <div class="modal fade" id="resolveModal">
    <div class="modal-dialog">
      <div class="modal-content">
        <div class="modal-header">...</div>
        <form method="post" action="..." id="resolveModalForm">
          <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
          <input type="hidden" name="next" value="{{ request.path }}">
          <div class="modal-body">
            <textarea name="note" required ...></textarea>
          </div>
          <div class="modal-footer">
            <button type="button" data-bs-dismiss="modal">Cancel</button>
            <button type="submit">Resolve</button>
          </div>
        </form>
      </div>
    </div>
  </div>
  ```
  **Do NOT wrap `modal-content` itself in `<form>`** — that places the form OUTSIDE the modal-dialog div and risks layout issues when Bootstrap's append-to-body / backdrop options are enabled. The pattern above keeps the form scoped inside `modal-content` and is the structure Task 9 emits. `admin/areas.html` is referenced only for the **raw `<input type="hidden" name="csrf_token" value="{{ csrf_token() }}">` pattern** (line 67) — NOT for form placement.

- **CSRF token rendering.** Codebase pattern from `admin/areas.html:67`: render raw `<input type="hidden" name="csrf_token" value="{{ csrf_token() }}">` instead of `{{ form.hidden_tag() }}`. The raw form omits the `id="csrf_token"` attribute that `hidden_tag()` emits, which would otherwise collide across multiple forms on the same page (the queue page has N+1 forms — one per queue row's Claim button plus one modal). `csrf_token()` is a Flask-WTF Jinja global. Test config disables CSRF entirely (`esb/config.py:67`).

- **Queue filtering is a hybrid pattern: server-side URL params + client-side dropdown toggle.**
  - **Server-side (existing):** `esb/views/repairs.py:62-67` reads `request.args.get('area', type=int)` and `request.args.get('status')`, passes them to `repair_service.get_repair_queue(area_id=..., status=...)` which adds SQL `WHERE` clauses at `esb/services/repair_service.py:355-367`. The queue template at `esb/templates/repairs/queue.html:21,29` renders `<option ... selected>` against `active_area` / `active_status` view kwargs so the dropdown's initial state matches the URL.
  - **Client-side (existing):** `esb/static/js/app.js:80-118`'s `applyFilters()` reads the dropdown values and toggles `style.display` on `.queue-row` and `.queue-card`. Triggered on every dropdown `change`. This refines the server-rendered set down further — it cannot widen it.
  - **New Assignee filter adopts the same hybrid pattern.** View reads `request.args.get('assignee', '')` and maps `'me'` → `assignee_id=current_user.id`, `'unassigned'` → `unassigned=True`. Service-layer kwargs `assignee_id` and `unassigned` are mutually exclusive (raise `ValidationError`). Template renders `<option ... selected>` against `active_assignee`. JS `applyFilters()` adds `assigneeVal` comparison against `dataset.assigneeId` and `dataset.unassigned`. The current user's id is embedded as `data-current-user-id` on `#queue-table-wrapper` so the JS comparison works without a re-render.
  - **Trade-off (same as existing):** the URL param is the canonical source of truth on load and reload. After load, the dropdown's `change` event applies a client-side display toggle but does NOT update the URL. So a user filtered to "Mine" then changing to "Unassigned" sees the right rows but the URL still says `?assignee=me`. Sharing or reloading reverts to the URL state. This quirk exists today for Area/Status; the new Assignee filter inherits it for consistency.

- **Service-function signature convention.** Existing helpers like `claim_repair_record` take `claimed_by_user_id: int` + `claimed_by_username: str` (separate args). `resolve_repair_record` follows the same convention: `resolved_by_user_id`, `resolved_by_username`, plus the required `note: str`. Views supply both from `current_user.id` and `current_user.username` (Flask-Login proxy).

- **Redirect-after-POST with `next` allowlist.** Both new routes accept an optional hidden form field `next`. The `_safe_next_url(next_val, record_id)` helper (2 args; fallback is constructed inside) accepts only two specific values: `url_for('repairs.queue')` (i.e., `/repairs/queue`) and `url_for('repairs.detail', id=record_id)` (i.e., `/repairs/<id>`). Any other value (including backslash variants, scheme-injected variants, URL-encoded variants) falls back to the detail URL. This is more restrictive — and far safer — than a generic "starts with `/`, not `//`" regex.

- **`request.path` (not `request.full_path`) for populating `next`.** `full_path` appends a trailing `?` when no query string is present, producing ugly URLs like `/repairs/queue?`. `path` returns the bare path. Since filters are client-side, there is no query string worth preserving across a redirect.

- **CLOSED_STATUSES as a Jinja global.** A new context processor in `esb/__init__.py` exposes `CLOSED_STATUSES` (imported from `repair_service`) to every template. Templates use `{% if record.status not in CLOSED_STATUSES %}` rather than hard-coding the list — eliminating the divergence risk if the list ever grows.

- **Existing tests.** `tests/test_views/test_repair_views.py` (~930 lines) has class-per-route structure. Follow it: `TestClaimRepairRoute`, `TestResolveRepairRoute`, plus extensions to the existing queue/detail test classes. `tests/test_services/test_repair_service.py` `TestClaimRepairRecord` at line 1357 is the reference structure for `TestResolveRepairRecord`. `tests/test_slack/test_handlers.py` uses `_register_and_capture(app)` to capture handler functions from a `MagicMock` Bolt app, then invokes them directly — the convergence test follows that exact pattern.

### Files to Reference

| File | Purpose |
| ---- | ------- |
| `esb/__init__.py` | Add a context processor exposing `CLOSED_STATUSES` to all templates. Place it near `inject_current_year` (line 73). |
| `esb/services/repair_service.py` | Add `resolve_repair_record()` immediately after `claim_repair_record` (which ends at line 272) per Task 2. Extend `get_repair_queue(area_id, status)` (line 338) with two new kwargs `assignee_id` and `unassigned` plus a mutual-exclusion `ValidationError` per Task 2b. |
| `esb/views/repairs.py` | Add `_safe_next_url(next_val, record_id)` helper after `_aging_tier` (which ends at line 27) per Task 4. Extend `queue()` (line 58) to read `?assignee=` URL param and map it to `get_repair_queue` kwargs per Task 7. Add two new route handlers `claim` and `resolve` after the `edit` route (ends at line 277) per Tasks 5 and 6. **Do NOT instantiate `RepairClaimForm`/`RepairResolveForm` in the `queue` or `detail` GET views** — forms exist only for the POST routes' `validate_on_submit()` call (templates render CSRF tokens directly via `{{ csrf_token() }}` and hard-code button markup). |
| `esb/forms/repair_forms.py` | Add `RepairClaimForm` and `RepairResolveForm` classes at the end of file. |
| `esb/slack/handlers.py` | Refactor lines 597-625 (the `resolve_with_note` branch of `repair_action_submission`) to call `repair_service.resolve_repair_record(...)` instead of `update_repair_record(status='Resolved', note=...)`. Retain the pre-validation at lines 599-603 for per-input-block error attribution. |
| `esb/static/js/app.js` | (a) Extend `.queue-row[data-href]` selector at line 5 to also include `.queue-card[data-href]`. (b) In `applyFilters()` (line 85-114), add the Assignee filter comparison and update the mobile-card branch to set `display` directly on `.queue-card` (not via `closest('a')`). (c) Add a `show.bs.modal` listener on `#resolveModal` that reads `data-repair-id`, sets the form `action`, clears the textarea, and updates the title. |
| `esb/templates/repairs/queue.html` | Add the Assignee filter `<select>`; embed `data-current-user-id` on `#queue-table-wrapper`; add the Actions column to the desktop table; restructure mobile cards (no wrapping `<a>`; `data-href` on `.queue-card`; action buttons in a sibling `card-body` div); include the resolve-modal partial at the bottom. |
| `esb/templates/repairs/detail.html` | Add Claim and Resolve buttons in the header row using `{% if record.status not in CLOSED_STATUSES %}` style guards. Include the resolve-modal partial at the bottom. |
| `esb/templates/components/_resolve_modal.html` | NEW. Modal with `<form>` inside `modal-content` wrapping body+footer, raw CSRF input, hidden `next` field defaulting to `request.path`. |
| `esb/templates/admin/areas.html` | READ-ONLY REFERENCE for the raw CSRF input pattern (line 67). Note: that file's modal-form PLACEMENT (form inside footer wrapping one button) is NOT the pattern this spec uses — our resolve modal needs a textarea inside the form, so we use a different valid Bootstrap structure. See Tech Decision "Bootstrap 5 Modal pattern". |
| `esb/models/repair_record.py` | Read-only — `REPAIR_STATUSES` constant. `CLOSED_STATUSES` lives in `repair_service.py:220`. |
| `esb/utils/decorators.py` | Read-only — `@role_required('technician')` applied to both new routes. |
| `tests/conftest.py` | Read-only — fixtures `tech_client`, `staff_client`, `tech_user`, `staff_user`, `make_area`, `make_equipment`, `make_repair_record`, helper `_create_user`. Add a new helper `member_user` fixture (or use `_create_user('member', 'memberuser')` inline) for the 403 tests. |
| `tests/test_services/test_repair_service.py` | Add `TestResolveRepairRecord` near `TestClaimRepairRecord` (line 1357). Add the reclaim-no-op regression test inside `TestClaimRepairRecord`. Add the non-ASCII round-trip test inside `TestResolveRepairRecord`. |
| `tests/test_views/test_repair_views.py` | Add `TestClaimRepairRoute` and `TestResolveRepairRoute` classes. Extend existing queue tests (around line 647) for the new filter and button-rendering assertions. Extend existing detail tests (around line 112) for the button-visibility-by-status matrix. |
| `tests/test_slack/test_handlers.py` | Update the existing `resolve_with_note` dispatcher test to assert convergence onto `resolve_repair_record`. |
| `docs/technicians.md` | Update around line 23-56 (the "Working with the Repair Queue" section) with "Quick Actions" subsection and mention the Assignee filter. |

### Technical Decisions

- **Reuse `update_repair_record` rather than duplicate.** `resolve_repair_record` is a thin wrapper, just like `claim_repair_record`. This keeps the timeline / audit / notification / static-page-regeneration machinery in one place. Resolve fires the existing `resolved` Slack notification path automatically.

- **Service vs. UI restrictions on Resolve.** The UI hides the Resolve button when status is `'New'` (technicians should triage first, not blind-resolve). The *service* `resolve_repair_record()` does NOT enforce this — Slack's existing resolve flow allows resolving any open record (including `New`), and we shouldn't break that contract. Service raises only on (a) closed record, (b) empty / whitespace-only note, (c) not-found ID, (d) not-found user_id. This split between UI policy and service invariants matches the codebase's pattern (claim's New→Assigned promotion is a service rule because both Slack and web need it; the "hide Resolve on New" is a web-UI convention only).

- **Order of validations in `resolve_repair_record`.** Check note non-empty FIRST (gives the cleanest user-facing message), then user-exists, then record-exists-and-open. This order means a typo'd ID with empty note flashes "Resolution note is required", which is the right UX even if technically the ID is also wrong.

- **Queue filter is a hybrid: server-side URL param + client-side dropdown toggle.** All three filters (Area, Status, Assignee) follow the same pattern: a URL query param drives initial server-side filtering via `get_repair_queue` kwargs, AND the dropdown's `change` event triggers client-side display-toggling via `applyFilters()` in `esb/static/js/app.js`. The URL param is the source of truth on load and reload; the dropdown can refine the rendered set further without a page reload. This matches the existing Area/Status pattern. Trade-off: dropdown-only changes do NOT update the URL, so a user filtered via dropdown sees correct rows in their session but a shared/bookmarked URL doesn't preserve that selection. (Same quirk as Area/Status today.) See the Codebase Patterns section "Queue filtering is a hybrid pattern" for the full design.

- **Embedding `current_user.id` in the DOM.** The Assignee filter's "Mine" option compares `dataset.assigneeId` on each row against `data-current-user-id` set once on the queue-scoped container (`#queue-table-wrapper`). Render via Jinja: `<div id="queue-table-wrapper" ... data-current-user-id="{{ current_user.id }}">`. The JS reads it via `container.dataset.currentUserId` (string) and compares with `===` (string equality — both sides are strings).

- **Mobile cards adopt the desktop `data-href` pattern.** Drops the `<a>` wrapper entirely. The `.queue-card` div carries `data-href`, `data-assignee-id`, `data-unassigned`, and the other existing data attributes. `app.js` extends `.queue-row[data-href], .repair-history-row[data-href]` to also include `.queue-card[data-href]`. Result: (a) eliminates the anchor-inside-anchor problem when adding embedded action buttons, (b) eliminates the `closest('a')` filter logic that would break after restructure, (c) makes the entire card click-target uniform (no whitespace-gap problem), (d) preserves keyboard navigation via the existing keydown handler on `[data-href]` rows.

- **Action buttons inside row/card don't trigger row-nav.** Inline `onclick="event.stopPropagation()"` would solve this but is banned (CSP-incompatible). Instead, the `app.js` click handler on `.queue-row[data-href], .queue-card[data-href]` checks `event.target.closest('button, a[href], form, [data-no-nav]')` and bails if any match is found. Action containers (`<td>` in desktop, action `<div>` in mobile) carry `data-no-nav` so clicks landing on container padding (where `e.target` IS the container, not a descendant button) also bail correctly. See Task 8a for the JS patch and Task 10e/10f for the `data-no-nav` attribute placement.

- **All JavaScript in `app.js` or scoped `<script>` blocks — never inline attributes.** The modal-trigger handler, the filter wiring, and the click-nav handler all live in `app.js`. This is (a) CSP-friendly (a future strict `script-src 'self'` policy would not break the app), (b) easier to test/lint, (c) consistent with the codebase pattern (kiosk-scale, QR preview, queue sort/filter all live in `app.js`).

- **Modal note textarea is cleared on `show.bs.modal`.** Two technicians' worth of stale text is a data-integrity hazard: a note typed for Repair #5 then dismissed could attach to Repair #8 if the textarea retains its value across openings. The JS handler explicitly sets `textarea.value = ''` on every show. (We also drop it on `hidden.bs.modal` for defense-in-depth, though `show` alone is sufficient.)

- **`_safe_next_url` is an explicit allowlist of exactly two paths.** Rather than regex-based filtering (which the adversarial review demonstrated can be bypassed via backslash, scheme injection, etc.), the helper compares the candidate against `url_for('repairs.queue')` and `url_for('repairs.detail', id=record_id)`. Anything else → fallback to detail. The check is straightforward equality, not pattern-matching.

- **Resolve route flashes only `note`-field errors verbatim, generic message otherwise.** Iterating `form.errors.items()` and flashing every value leaks CSRF-error strings ("The CSRF token is missing.") to end users. Instead, the resolve route flashes errors from `form.note.errors` specifically, and falls back to "Invalid resolve request — please try again." for any other failure. The claim route, having only CSRF as a possible non-success path, flashes "Invalid claim request — please try again." uniformly.

- **`CLOSED_STATUSES` exposed via context processor.** New code in `esb/__init__.py`:
  ```python
  @app.context_processor
  def inject_repair_constants():
      from esb.services.repair_service import CLOSED_STATUSES
      return {'CLOSED_STATUSES': CLOSED_STATUSES}
  ```
  Templates use `{% if record.status not in CLOSED_STATUSES %}` — one source of truth.

- **Slack convergence (F20).** The Slack `resolve_with_note` branch is changed to call `repair_service.resolve_repair_record(...)`. The Slack-side pre-validation (lines 599-603) is kept for per-input-block error attribution — without it, the service-layer empty-note error would attach to the wrong block (`action_block` instead of `note_block`). The service raise still happens (defense-in-depth) but is reached only via mis-call or race. After this change, both Slack and web use the same single source of truth for resolve invariants.

- **Concurrency: two simultaneous claims.** Tech A claims at T0, Tech B claims at T0+10ms. Both pass the closed-record guard (record was `New`). A's `update_repair_record` commits → `assignee=A, status='Assigned'`, one `assignee_change` and one `status_change` timeline entry, two notifications queued (`status_changed` plus `assignee_change` is not a separate event but the timeline entry reflects it). B's call sees the now-`Assigned` record:
  - `assignee_id` change from A to B → real change → one timeline entry, no `status_changed` notification (status was already `Assigned` so no-op guard catches it).
  - `status` change from `Assigned` to `Assigned` → no-op guard catches it.
  Net effect: data is `assignee=B, status='Assigned'`, two timeline entries (one each), one `status_changed` notification (from A's transition only). Acceptable. Documented in Notes. Regression test confirms re-claim of self-assigned record produces zero new entries.

### Files Verified (line numbers exact)

| File | Symbol | Line |
| ---- | ------ | ---- |
| `esb/services/repair_service.py` | `_aging_tier` referenced (actually in `repairs.py`) | n/a |
| `esb/services/repair_service.py` | `CLOSED_STATUSES =` | 220 |
| `esb/services/repair_service.py` | `claim_repair_record` (`def`) | 225 |
| `esb/services/repair_service.py` | end of `claim_repair_record` | 272 |
| `esb/services/repair_service.py` | `get_repair_queue` (`def`) | 338 |
| `esb/services/repair_service.py` | `update_repair_record` (`def`) | 375 |
| `esb/services/repair_service.py` | `assignee_id` validation in update | 409-412 |
| `esb/services/repair_service.py` | `resolved` notification trigger | 513-518 |
| `esb/views/repairs.py` | `_aging_tier` (`def`) | 20-27 |
| `esb/views/repairs.py` | `queue` (`def`) | 58 |
| `esb/views/repairs.py` | `detail` (`def`) | 131 |
| `esb/views/repairs.py` | `edit` (`def`) | 229 |
| `esb/views/repairs.py` | end of `edit` | 277 |
| `esb/slack/handlers.py` | `resolve_with_note` branch | 597-625 |
| `esb/templates/admin/areas.html` | modal markup (single-button confirm; NOT the pattern this spec uses for form placement) | 54-73 |
| `esb/templates/admin/areas.html` | raw CSRF input (the only pattern this spec inherits from admin/areas.html) | 67 |
| `esb/static/js/app.js` | clickable-row selector | 5 |
| `esb/static/js/app.js` | `applyFilters()` body | 85-114 |
| `esb/__init__.py` | `inject_current_year` context processor | 73 |
| `esb/config.py` | `WTF_CSRF_ENABLED = False` (TestingConfig) | 67 |
| `tests/test_services/test_repair_service.py` | `TestClaimRepairRecord` (class start) | 1357 |
| `tests/test_services/test_repair_service.py` | `TestGetRepairQueue` (class start — Task 12b extends this class) | 1453 |
| `tests/test_views/test_repair_views.py` | `TestRepairQueue` (class start) | 548 |
| `tests/test_views/test_repair_views.py` | `TestRepairQueue.test_queue_combined_area_and_status_filter` (representative existing queue-filter test) | 647 |
| `tests/test_views/test_repair_views.py` | `TestRepairRecordDetail` (class start) | 109 |
| `tests/test_views/test_repair_views.py` | `TestRepairRecordDetail` first test (`test_staff_sees_detail`) | 112 |
| `tests/test_slack/test_handlers.py` | `test_resolve_with_note_sets_resolved_and_adds_note` (start of resolve-with-note cluster) | 1315 |
| `tests/test_slack/test_handlers.py` | `test_resolve_without_note_returns_error` (end of resolve-with-note cluster — last line 1376) | 1361 |
| `tests/test_slack/test_handlers.py` | `test_closed_record_returns_error` (UNRELATED — uses `action='claim'`, not resolve; do NOT include in Task 19's verification filter) | 1378 |

## Implementation Plan

### Tasks

Tasks ordered bottom-up: constants/context → service helpers → forms → views → JS → templates → tests → docs.

**Numbering convention:** integer task numbers (`Task 1`, `Task 2`, ...) plus letter-suffixed intercalations (`Task 2b`, `Task 12b`) where later spec-revision rounds added closely-related work to an existing task. Letter-suffix tasks have full standalone task bodies (Action, File, Notes) and are NOT optional — they must be implemented in order alongside their integer-numbered siblings. Spec-linting tooling that expects strictly-integer task numbers will skip the letter-suffixed entries; manual review is the source of truth. The same convention applies to AC numbering (`AC 25a` ... `AC 25f` intercalated before `AC 26`).

- [x] **Task 1: Expose `CLOSED_STATUSES` as a Jinja context.**
  - File: `esb/__init__.py`
  - Action: Immediately after the existing `inject_current_year` context processor (around line 73-75), add:
    ```python
    @app.context_processor
    def inject_repair_constants():
        from esb.services.repair_service import CLOSED_STATUSES
        return {'CLOSED_STATUSES': CLOSED_STATUSES}
    ```
  - Notes: Local import avoids a circular import at module load (repair_service imports from extensions and models, both of which are wired up before context processors run; lazy import is the safer pattern). **Hard prerequisite for Tasks 10 and 11**: if this task is skipped or regressed, the queue and detail templates raise `jinja2.exceptions.UndefinedError` on every render (because `{% if record.status not in CLOSED_STATUSES %}` cannot operate on `Undefined`). The smoke-test coverage in Tasks 16-17 (any `200`-asserting GET against the queue/detail page) fails loudly if this is broken, so the regression cannot ship silently.

- [x] **Task 2: Add `resolve_repair_record()` service function.**
  - File: `esb/services/repair_service.py`
  - Action: Add a new function immediately after `claim_repair_record` (which ends at line 272). Signature and body:
    ```python
    def resolve_repair_record(
        repair_record_id: int,
        resolved_by_user_id: int,
        resolved_by_username: str,
        note: str,
    ) -> RepairRecord:
        """Resolve a repair record with a required note.

        Validates inputs in order: note non-empty, user exists, record
        exists and is open. Then sets status='Resolved' and appends the
        note as a timeline entry in the same transaction via
        update_repair_record. The 'resolved' Slack notification fires
        automatically via the existing trigger in update_repair_record.

        UI-level rule that 'New' records should be claimed before resolve
        is NOT enforced here -- the service contract is permissive so
        both Slack's dispatcher and the web UI can layer their own
        conventions. Resolves from 'New' are allowed.

        Args:
            repair_record_id: ID of the RepairRecord to resolve.
            resolved_by_user_id: ESB user id of the resolving user. Must
                reference an existing User.
            resolved_by_username: Username (for timeline-entry attribution).
            note: Resolution note. Required; whitespace-only is rejected.

        Returns:
            The updated RepairRecord.

        Raises:
            ValidationError: if note is empty/whitespace-only, the user
                does not exist, the record does not exist, or the record
                is already closed.
        """
        if not note or not note.strip():
            raise ValidationError('Resolution note is required')
        user = db.session.get(User, resolved_by_user_id)
        if user is None:
            raise ValidationError(f'User with id {resolved_by_user_id} not found')
        record = get_repair_record(repair_record_id)
        if record.status in CLOSED_STATUSES:
            raise ValidationError(
                f'Cannot resolve repair record {repair_record_id}: '
                f'status {record.status!r} is already closed',
            )
        return update_repair_record(
            repair_record_id=repair_record_id,
            updated_by=resolved_by_username,
            author_id=resolved_by_user_id,
            status='Resolved',
            note=note.strip(),
        )
    ```
  - Notes: The explicit `User.get` check fills the gap that `claim_repair_record` gets incidentally (claim passes user_id as `assignee_id` which `update_repair_record` validates; resolve does not change `assignee_id` so needs its own check). Error message format mirrors `update_repair_record`'s existing pattern (`f'User with id {x} not found'`).

- [x] **Task 2b: Extend `get_repair_queue()` with `assignee_id` and `unassigned` kwargs.**
  - File: `esb/services/repair_service.py`
  - Action: Modify the existing `get_repair_queue` function (signature currently `def get_repair_queue(area_id=None, status=None)` at line 338). New signature and body:
    ```python
    def get_repair_queue(
        area_id: int | None = None,
        status: str | None = None,
        assignee_id: int | None = None,
        unassigned: bool = False,
    ) -> list[RepairRecord]:
        """Get open repair records for the technician queue.

        ... (existing docstring preserved) ...

        Args:
            area_id: Optional filter by equipment's area ID.
            status: Optional filter by repair record status.
            assignee_id: Optional filter to records assigned to this user ID.
            unassigned: When True, filter to records where assignee_id IS NULL.
                Mutually exclusive with assignee_id; raises ValidationError if
                both are non-default.

        Returns:
            List of RepairRecord instances.

        Raises:
            ValidationError: if both `assignee_id` and `unassigned=True` are
                passed simultaneously (mutually exclusive filters).
        """
        if assignee_id is not None and unassigned:
            raise ValidationError(
                'Cannot filter by both assignee_id and unassigned simultaneously',
            )
        query = (
            db.select(RepairRecord)
            .join(RepairRecord.equipment)
            .join(Equipment.area)
            .options(
                joinedload(RepairRecord.equipment).joinedload(Equipment.area),
                joinedload(RepairRecord.assignee),
            )
            .filter(RepairRecord.status.notin_(CLOSED_STATUSES))
            .order_by(_SEVERITY_PRIORITY, RepairRecord.created_at.asc())
        )
        if area_id is not None:
            query = query.filter(Equipment.area_id == area_id)
        if status is not None:
            query = query.filter(RepairRecord.status == status)
        if assignee_id is not None:
            query = query.filter(RepairRecord.assignee_id == assignee_id)
        elif unassigned:
            query = query.filter(RepairRecord.assignee_id.is_(None))
        return list(
            db.session.execute(query).scalars().unique().all()
        )
    ```
  - Notes: Strictly additive — existing callers continue to work. **Caller audit (verified pre-spec):** `get_repair_queue()` is currently called from three production locations and seven test locations:
    - `esb/views/repairs.py:67` — `get_repair_queue(area_id=area_id, status=status_filter)` (Task 7 extends this call with the two new kwargs).
    - `esb/slack/handlers.py:164` — `get_repair_queue()` (no kwargs; unaffected by new behavior).
    - Tests in `tests/test_slack/test_forms.py:599,621,644,667,686,699` and `tests/test_services/test_repair_service.py:1468,1503` — all call with no kwargs or only `area_id`/`status`. None passes both new kwargs simultaneously, so none triggers the new mutual-exclusion `ValidationError`.
    The mutual-exclusion guard raises explicitly rather than silently letting one filter dominate; views must map their URL param to ONE of the two kwargs. The two new filter clauses appear AFTER the existing `area_id` and `status` filters, matching the order in the existing function body.

- [x] **Task 3: Add `RepairClaimForm` and `RepairResolveForm`.**
  - File: `esb/forms/repair_forms.py`
  - Action: At the bottom of the file (after `RepairPhotoUploadForm`), add:
    ```python
    class RepairClaimForm(FlaskForm):
        """Form for claim quick action -- CSRF only, no inputs."""

        # No fields: CSRF is auto-included by FlaskForm; submit button is
        # hard-coded in the template, so no SubmitField is needed.
        pass


    class RepairResolveForm(FlaskForm):
        """Form for resolve quick action -- requires a note."""

        note = TextAreaField(
            'Resolution Note',
            validators=[DataRequired(), Length(max=5000)],
        )
        # Submit button is hard-coded in the modal template; no SubmitField.
    ```
  - Notes: No new imports needed; `FlaskForm`, `TextAreaField`, `DataRequired`, `Length` are imported already at top of file. (`SubmitField` is also imported but no longer used by these new forms.) The forms exist so that the POST routes (Tasks 5, 6) can call `form.validate_on_submit()` and drive CSRF + `note`-required validation. CSRF tokens in templates are rendered as raw `<input>` (matches `admin/areas.html:67`) — `form.hidden_tag()` is intentionally NOT used. The forms are instantiated ONLY in the POST routes; the queue/detail GET views do not instantiate them (the templates render raw CSRF inputs and hard-code button markup).

- [x] **Task 4: Add `_safe_next_url` helper to `esb/views/repairs.py`.**
  - File: `esb/views/repairs.py`
  - Action: After the existing `_aging_tier` helper (ends at line 27), add:
    ```python
    def _safe_next_url(next_val: str | None, record_id: int) -> str:
        """Return next_val if it is one of the two allowed targets, else fallback.

        Allowlist: /repairs/queue OR /repairs/<record_id>. Any other value
        (external URL, backslash-escaped, scheme-injected, URL-encoded
        variants, /repairs/<other_id>, etc.) returns the detail-page URL
        for record_id. This explicit allowlist is more restrictive -- and
        safer -- than regex-based filtering.
        """
        queue_url = url_for('repairs.queue')
        detail_url = url_for('repairs.detail', id=record_id)
        if next_val in (queue_url, detail_url):
            return next_val
        return detail_url
    ```
  - Action: Update the imports at the top of the file (the existing import block already includes `Blueprint, abort, current_app, flash, redirect, render_template, request, send_from_directory, url_for` from flask; nothing new to add for the helper itself, but add the form imports):
    ```python
    from esb.forms.repair_forms import (
        RepairClaimForm,
        RepairNoteForm,
        RepairPhotoUploadForm,
        RepairRecordCreateForm,
        RepairRecordUpdateForm,
        RepairResolveForm,
    )
    ```
  - Notes: Two paths only. The `record_id`-specific detail URL means `/repairs/42/claim` POST with `next=/repairs/99` (a different record's detail page) falls back to `/repairs/42` rather than silently allowing cross-record navigation. Tight scope. **Trailing-slash edge case:** the route is defined as `/queue` (no trailing slash), so `url_for('repairs.queue')` returns `/repairs/queue`. The hidden `next` field is populated from `request.path`, which also returns `/repairs/queue` for that route. Both sides match exactly. A manually-typed `next=/repairs/queue/` (with trailing slash) would NOT match the allowlist and would fall back to detail — acceptable, since the hidden field never produces that value organically. If the app is ever mounted under an `APPLICATION_ROOT` or `SCRIPT_NAME` (e.g., `/esb/`), both `url_for` and `request.path` reflect the prefix consistently, so the allowlist still works.

- [x] **Task 5: Add the `claim` route.**
  - File: `esb/views/repairs.py`
  - Action: After the `edit` route (ends at line 277), add:
    ```python
    @repairs_bp.route('/<int:id>/claim', methods=['POST'])
    @role_required('technician')
    def claim(id):
        """Quick-action: claim a repair record (assignee=self, New->Assigned)."""
        form = RepairClaimForm()
        try:
            repair_service.get_repair_record(id)
        except ValidationError:
            abort(404)

        if form.validate_on_submit():
            try:
                repair_service.claim_repair_record(
                    repair_record_id=id,
                    claimed_by_user_id=current_user.id,
                    claimed_by_username=current_user.username,
                )
                flash(f'Claimed Repair #{id}.', 'success')
            except ValidationError as e:
                flash(str(e), 'danger')
        else:
            flash('Invalid claim request -- please try again.', 'danger')

        return redirect(_safe_next_url(request.form.get('next'), id))
    ```
  - Notes: 404 check comes BEFORE form validation so that a missing ID never sees a CSRF error. The single `else:` branch covers all form failures (CSRF, missing fields) with one generic message — never leaks raw WTForms strings.

- [x] **Task 6: Add the `resolve` route.**
  - File: `esb/views/repairs.py`
  - Action: Immediately below the `claim` route from Task 5, add:
    ```python
    @repairs_bp.route('/<int:id>/resolve', methods=['POST'])
    @role_required('technician')
    def resolve(id):
        """Quick-action: resolve a repair record with a required note."""
        form = RepairResolveForm()
        try:
            repair_service.get_repair_record(id)
        except ValidationError:
            abort(404)

        if form.validate_on_submit():
            try:
                repair_service.resolve_repair_record(
                    repair_record_id=id,
                    resolved_by_user_id=current_user.id,
                    resolved_by_username=current_user.username,
                    note=form.note.data,
                )
                flash(f'Resolved Repair #{id}.', 'success')
            except ValidationError as e:
                flash(str(e), 'danger')
        else:
            # Narrow leak surface: surface only note-field errors verbatim;
            # any other failure (CSRF, etc.) gets a generic message that
            # does not expose framework internals.
            if form.note.errors:
                for error in form.note.errors:
                    flash(error, 'danger')
            else:
                flash('Invalid resolve request -- please try again.', 'danger')

        return redirect(_safe_next_url(request.form.get('next'), id))
    ```
  - Notes: The `note.errors` narrowing avoids flashing "The CSRF token is missing." to end users when CSRF fails. The narrower path also makes the AC for empty-note flash deterministic ("This field is required." — the WTForms default for `DataRequired`). **Multi-flash potential:** the `for error in form.note.errors` loop emits one `flash` per error. With the current validators (`DataRequired()` + `Length(max=5000)`), at most one fires per submission — `DataRequired` triggers on empty, `Length` triggers on too-long, and they cannot both fail simultaneously (empty is shorter than 5000; full-length is non-empty). Future validators (e.g., `Regexp(...)` for content rules) could change that, producing N danger-flash cards per bad submit. Code-review checkpoint: if new validators are added, decide whether to keep per-error flashes or collapse to one generic message.

- [x] **Task 7: Extend the `queue` view to read the `?assignee=` URL param.**
  - File: `esb/views/repairs.py`
  - Action: In `queue()` (line 58), after the existing `area_id` and `status_filter` reads, add:
    ```python
    raw_assignee = request.args.get('assignee', '')
    # Canonicalize: only 'me' and 'unassigned' are recognized values; any
    # other input (empty, bogus, etc.) collapses to '' so the template's
    # dropdown still selects "All Assignees" via the {% if not active_assignee %}
    # branch. Without this canonicalization, a bogus value like 'bogus' would
    # cause no <option> to render `selected` (since none of the three options
    # match 'bogus' AND `not 'bogus'` is False).
    if raw_assignee in ('me', 'unassigned'):
        active_assignee = raw_assignee
    else:
        active_assignee = ''
    assignee_id_filter = current_user.id if active_assignee == 'me' else None
    unassigned_filter = (active_assignee == 'unassigned')
    ```
    Pass them to `get_repair_queue`:
    ```python
    records = repair_service.get_repair_queue(
        area_id=area_id,
        status=status_filter,
        assignee_id=assignee_id_filter,
        unassigned=unassigned_filter,
    )
    ```
    Add `active_assignee=active_assignee` to the `render_template(...)` kwargs (alongside the existing `active_area` and `active_status`) so the template can render the dropdown's `selected` option.
  - Action (detail view): **No code changes to `detail()`.** The detail page doesn't need a filter param.
  - Action (both views): **Do NOT instantiate `RepairClaimForm()` or `RepairResolveForm()` in the GET views.** The templates render CSRF tokens via raw `<input>` (matching `admin/areas.html:67`) and hard-code button markup. Forms are needed only by the POST routes (Tasks 5 and 6) for `validate_on_submit()`.
  - Verify: After implementing all tasks, grep `esb/views/repairs.py` to confirm `RepairClaimForm()` and `RepairResolveForm()` appear ONLY inside the `claim` and `resolve` route bodies.
  - Notes: The view canonicalizes the URL param BEFORE passing it to either the service or the template. This serves two purposes: (a) avoids the rendering quirk where `?assignee=bogus` would yield `active_assignee='bogus'`, matching neither the `me`/`unassigned` branches NOR the `{% if not active_assignee %}` "All Assignees" branch, leaving the dropdown with no selection; (b) keeps `assignee_id_filter`/`unassigned_filter` strictly typed and avoids relying on a defensive `current_user.is_authenticated` check (the route is `@role_required('technician')` so `current_user` is always authenticated at this point — the prior draft's `is_authenticated` clause was dead code). Unknown values silently collapse to "All Assignees" — the queue is a forgiving exploratory surface; bookmarked URLs with stale params still load cleanly. (Same forgiveness applies to existing `?area=` and `?status=` — a malformed `?area=foo` raises a `ValueError` from `type=int`; Flask returns 400. Our `assignee` param has no `type=int` cast, so it never raises.)

- [x] **Task 8: Update `esb/static/js/app.js` — three changes in one pass.**
  - File: `esb/static/js/app.js`
  - Action 8a: Extend the clickable-row selector at line 5. Current:
    ```javascript
    document.querySelectorAll('.queue-row[data-href], .repair-history-row[data-href]').forEach(function (row) {
    ```
    Change to:
    ```javascript
    document.querySelectorAll('.queue-row[data-href], .queue-card[data-href], .repair-history-row[data-href]').forEach(function (row) {
    ```
    AND update the handler body to (a) preserve the existing `cursor: pointer` affordance for ALL clickable surfaces (the existing line is at `app.js:6`; the new mobile-card target needs it too), and (b) skip navigation when the event originated on an interactive descendant. Both click and keydown handlers use `e.target.closest(...)` for consistency:
    ```javascript
    function isNavBlocker(el) {
      return !!(el && el.closest('button, a[href], form, [data-no-nav]'));
    }

    row.style.cursor = 'pointer';  // preserved from existing app.js:6; applies to .queue-card too

    row.addEventListener('click', function (e) {
      if (isNavBlocker(e.target)) return;
      window.location.href = row.dataset.href;
    });
    row.addEventListener('keydown', function (e) {
      if (e.key !== 'Enter' && e.key !== ' ') return;
      // e.target is the focused element when keydown fires from a child button/link,
      // OR the row itself when the row has focus. Either case is handled correctly.
      if (isNavBlocker(e.target)) return;
      e.preventDefault();
      window.location.href = row.dataset.href;
    });
    ```
    The `[data-no-nav]` selector slot is what protects "dead zones" inside the row — `<td>` padding (Task 10e), action-row `<div>` gaps in mobile cards (Task 10f). Without `data-no-nav` on those containers, a click on the padding around a button (where `e.target` is the container itself, not the button) would fall through to row-nav since `closest()` ascends from `e.target` and would not find an interactive ancestor.
  - Action 8b: In `applyFilters()` (current location lines 85-114), extend the filter logic to include Assignee comparison, and update the mobile-card path to set display on `.queue-card` directly (the wrapping `<a>` no longer exists post-Task 9 restructure). Replace the function with:
    ```javascript
    var areaFilter = document.getElementById('area-filter');
    var statusFilter = document.getElementById('status-filter');
    var assigneeFilter = document.getElementById('assignee-filter');
    var queueContainer = document.getElementById('queue-table-wrapper');
    var currentUserId = queueContainer ? queueContainer.dataset.currentUserId : '';

    if (areaFilter && statusFilter && assigneeFilter) {
      function applyFilters() {
        var areaVal = areaFilter.value;
        var statusVal = statusFilter.value;
        var assigneeVal = assigneeFilter.value;
        var visibleCount = 0;

        function matchesAssignee(el) {
          if (!assigneeVal) return true;
          if (assigneeVal === 'me') {
            // Defensive: if currentUserId is missing (queue container absent or
            // anonymous render), match nothing rather than falling through to
            // matching every row with empty assignee_id (which would silently
            // turn "Mine" into "Unassigned").
            if (!currentUserId) return false;
            return el.dataset.assigneeId === currentUserId;
          }
          if (assigneeVal === 'unassigned') return el.dataset.unassigned === 'true';
          return true;
        }

        document.querySelectorAll('.queue-row').forEach(function (row) {
          var areaMatch = !areaVal || row.dataset.areaId === areaVal;
          var statusMatch = !statusVal || row.dataset.status === statusVal;
          var assigneeMatch = matchesAssignee(row);
          var visible = areaMatch && statusMatch && assigneeMatch;
          row.style.display = visible ? '' : 'none';
          if (visible) visibleCount++;
        });

        document.querySelectorAll('.queue-card').forEach(function (card) {
          var areaMatch = !areaVal || card.dataset.areaId === areaVal;
          var statusMatch = !statusVal || card.dataset.status === statusVal;
          var assigneeMatch = matchesAssignee(card);
          card.style.display = (areaMatch && statusMatch && assigneeMatch) ? '' : 'none';
        });

        var emptyEl = document.getElementById('queue-empty');
        if (emptyEl) {
          emptyEl.classList.toggle('d-none', visibleCount > 0);
        }
      }

      areaFilter.addEventListener('change', applyFilters);
      statusFilter.addEventListener('change', applyFilters);
      assigneeFilter.addEventListener('change', applyFilters);
    }
    ```
  - Action 8c: Add the modal-trigger handler. Insert anywhere inside the `DOMContentLoaded` listener — for example, after the queue-filter block:
    ```javascript
    // --- Resolve modal: wire up dynamic action + clear stale textarea ---
    var resolveModal = document.getElementById('resolveModal');
    if (resolveModal) {
      resolveModal.addEventListener('show.bs.modal', function (event) {
        var trigger = event.relatedTarget;
        if (!trigger) return;
        var repairId = trigger.getAttribute('data-repair-id');
        var form = document.getElementById('resolveModalForm');
        var textarea = document.getElementById('resolveModalNote');
        var titleSpan = document.getElementById('resolveModalRepairId');
        if (form) form.setAttribute('action', '/repairs/' + repairId + '/resolve');
        if (textarea) textarea.value = '';
        if (titleSpan) titleSpan.textContent = '#' + repairId;
      });
    }
    ```
  - Notes: All three changes are required for the new UX to function. The `closest('button, a[href], form, [data-no-nav]')` guard in 8a is what allows action buttons inside rows/cards to NOT trigger row-nav — replaces the inline `onclick="event.stopPropagation()"` from the previous draft and is CSP-friendly. The modal handler clears the textarea on every show so dismissed notes don't carry over between repair records.

- [x] **Task 9: Create the resolve-modal partial.**
  - File: `esb/templates/components/_resolve_modal.html` (NEW)
  - Action: Write:
    ```jinja
    {# Bootstrap 5 modal -- include once per page. The form lives INSIDE
       modal-content, sibling to modal-header, wrapping body+footer. This
       differs from admin/areas.html's modal (which puts the form inside
       modal-footer wrapping one button) because we need a textarea inside
       the form. The form's action is patched at show.bs.modal time by the
       handler in app.js (Task 8c). #}
    <div class="modal fade" id="resolveModal" tabindex="-1" aria-labelledby="resolveModalLabel" aria-hidden="true">
      <div class="modal-dialog">
        <div class="modal-content">
          <div class="modal-header">
            <h5 class="modal-title" id="resolveModalLabel">
              Resolve Repair <span id="resolveModalRepairId"></span>
            </h5>
            <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
          </div>
          <form method="post" action="" id="resolveModalForm" novalidate>
            <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
            <input type="hidden" name="next" value="{{ request.path }}">
            <div class="modal-body">
              <label for="resolveModalNote" class="form-label">Resolution Note <span class="text-danger">*</span></label>
              <textarea id="resolveModalNote" name="note" class="form-control" rows="4" maxlength="5000" required></textarea>
              <div class="form-text">Describe what was done. Required.</div>
            </div>
            <div class="modal-footer">
              <button type="button" class="btn btn-outline-secondary" data-bs-dismiss="modal">Cancel</button>
              <button type="submit" class="btn btn-success">Resolve</button>
            </div>
          </form>
        </div>
      </div>
    </div>
    ```
  - Notes: No inline `<script>` — the `show.bs.modal` listener lives in `app.js` per Task 8c. The `<form>` placement wraps `modal-body` + `modal-footer` (a valid Bootstrap pattern; differs from `admin/areas.html` which has no body-level inputs and so can place the form inside the footer). Raw CSRF input (no `form.hidden_tag()`) avoids duplicate-id collisions with the page's other forms. `request.path` (not `full_path`) avoids the trailing-`?` quirk. The textarea has `maxlength="5000"` aligning with the WTForms `Length(max=5000)` validator (note: browser maxlength counts UTF-16 code units while WTForms counts Python characters — see Notes). **The hidden `next` value is fixed at template render time.** Since this partial is included ONCE per page (Task 10g for queue, Task 11 for detail), `next` evaluates to `/repairs/queue` for ALL resolve actions initiated from the queue and to `/repairs/<this-id>` for resolves from the detail page — regardless of which row's button opened the modal. The `data-bs-target="#resolveModal"`-triggered JS only patches the form's `action` (per-record) and clears the textarea; it does NOT recompute `next`. Intentional: resolves from the queue should return to the queue; resolves from a record's detail should stay on detail. Documented so future maintainers don't try to "fix" this by dynamically updating `next` in the modal-show handler. **Implicit dependency:** the partial uses `request.path`, so it MUST be rendered inside an active Flask request context. This is always the case for the queue/detail page renders. Do NOT include this partial from a CLI command, an offline static-page generator (`esb/services/static_page_service.py`), or any other code path that runs outside a request — it would raise `RuntimeError: Working outside of request context`.

- [x] **Task 10: Update `queue.html` — Actions column, restructured mobile cards, Assignee filter, modal include.**
  - File: `esb/templates/repairs/queue.html`
  - Action 10a: After the status filter `<select>` block (currently lines 25-32), add the Assignee filter. The `selected` attribute on each `<option>` matches the URL state via `active_assignee` (passed from the view per Task 7):
    ```jinja
    <div class="col-auto">
        <select id="assignee-filter" class="form-select form-select-sm" aria-label="Filter by assignee">
            <option value="" {% if not active_assignee %}selected{% endif %}>All Assignees</option>
            <option value="me" {% if active_assignee == 'me' %}selected{% endif %}>Mine</option>
            <option value="unassigned" {% if active_assignee == 'unassigned' %}selected{% endif %}>Unassigned</option>
        </select>
    </div>
    ```
    No `onchange` attribute — the JS in Task 8b wires the `change` event listener for client-side display toggling. URL navigation (e.g., share/bookmark) is handled by users typing `?assignee=...` directly; we don't auto-update the URL on dropdown change (matches the existing Area/Status pattern's behavior).
  - Action 10b: Add `data-current-user-id` to the queue table wrapper. Change the opening tag (currently line 36):
    ```jinja
    <div id="queue-table-wrapper" class="d-none d-md-block" data-current-user-id="{{ current_user.id }}">
    ```
  - Action 10c: Add an Actions column header to the desktop table. After the existing Assignee `<th>` (line 46), insert:
    ```jinja
    <th class="text-end">Actions</th>
    ```
  - Action 10d: Modify each `.queue-row` (existing `<tr>` at line 51-59) to (i) drop `role="link"` and (ii) add the assignee data attributes. The `role="link"` removal mirrors the round-2 fix for `.queue-card` — once the row contains nested interactive content (the new action `<td>` with form + buttons from Action 10e), `role="link"` is an ARIA-spec violation (interactive descendants disallowed). Keep `tabindex="0"` so keyboard nav via Enter/Space still fires the `data-href` navigation through `app.js`'s keydown handler. New opening tag:
    ```jinja
    <tr class="queue-row" tabindex="0"
        data-href="{{ url_for('repairs.detail', id=record.id) }}"
        data-equipment-name="{{ record.equipment.name }}"
        data-severity-priority="..."
        data-area-id="{{ record.equipment.area_id }}"
        data-area="{{ record.equipment.area.name }}"
        data-age-seconds="{{ (now_utc - record.created_at).total_seconds()|int }}"
        data-status="{{ record.status }}"
        data-assignee="{{ record.assignee.username if record.assignee else '' }}"
        data-assignee-id="{{ record.assignee_id or '' }}"
        data-unassigned="{{ 'true' if record.assignee_id is none else 'false' }}">
    ```
    The `role="link"` attribute is GONE; `tabindex="0"` remains. Screen readers no longer announce the row as a link (mirroring how `.queue-card` is announced — as a generic focusable element); keyboard users still navigate via Enter on a focused row, but the announcement is contents-only. The action buttons inside the row carry their own `aria-label`s and are individually focusable.
  - Action 10e: Add the action `<td>` to each row, after the existing Assignee `<td>` (currently line 76). The `data-no-nav` attribute on the `<td>` tells the row-nav handler in `app.js` to bail for ALL clicks inside the cell (including clicks landing on the padding around the buttons, not just on the buttons themselves):
    ```jinja
    <td class="text-end" data-no-nav>
        {% if record.status == 'New' and record.assignee_id != current_user.id %}
        <form method="post" action="{{ url_for('repairs.claim', id=record.id) }}" class="d-inline">
            <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
            <input type="hidden" name="next" value="{{ request.path }}">
            <button type="submit" class="btn btn-sm btn-outline-primary"
                    aria-label="Claim Repair #{{ record.id }}: {{ record.equipment.name }}">
                Claim
            </button>
        </form>
        {% endif %}
        {% if record.status != 'New' and record.status not in CLOSED_STATUSES %}
        <button type="button" class="btn btn-sm btn-outline-success"
                data-bs-toggle="modal" data-bs-target="#resolveModal"
                data-repair-id="{{ record.id }}"
                aria-label="Resolve Repair #{{ record.id }}: {{ record.equipment.name }}">
            Resolve
        </button>
        {% endif %}
    </td>
    ```
    No inline `onclick`. The `app.js` row-nav handler (Task 8a) checks `event.target.closest('button, a[href], form, [data-no-nav]')` — the `[data-no-nav]` slot is what catches dead-zone clicks (padding, gaps) inside this `<td>` and prevents accidental row-navigation.
  - Action 10f: Replace the entire mobile-cards block (currently lines 84-119). Replace with:
    ```jinja
    <div id="queue-cards-wrapper" class="d-md-none">
        {% for record in records %}
        <div class="card mb-2 queue-card text-body"
             data-href="{{ url_for('repairs.detail', id=record.id) }}"
             tabindex="0"
             data-equipment-name="{{ record.equipment.name }}"
             data-severity-priority="{{ '0' if record.severity == 'Down' else ('1' if record.severity == 'Degraded' else ('2' if record.severity == 'Not Sure' else '3')) }}"
             data-area-id="{{ record.equipment.area_id }}"
             data-area="{{ record.equipment.area.name }}"
             data-age-seconds="{{ (now_utc - record.created_at).total_seconds()|int }}"
             data-status="{{ record.status }}"
             data-assignee="{{ record.assignee.username if record.assignee else '' }}"
             data-assignee-id="{{ record.assignee_id or '' }}"
             data-unassigned="{{ 'true' if record.assignee_id is none else 'false' }}">
            <div class="card-body py-2 px-3">
                <div class="d-flex justify-content-between align-items-center">
                    <strong>{{ record.equipment.name }}</strong>
                    {% if record.severity == 'Down' %}
                    <span class="badge bg-danger">Down</span>
                    {% elif record.severity in ['Degraded', 'Not Sure'] %}
                    <span class="badge bg-warning text-dark">{{ record.severity }}</span>
                    {% elif record.severity %}
                    <span class="badge bg-secondary">{{ record.severity }}</span>
                    {% else %}
                    <span class="badge bg-secondary">None</span>
                    {% endif %}
                </div>
                <div class="small text-muted mt-1">
                    <span class="badge bg-info text-dark">{{ record.status }}</span>
                    &middot; {{ record.equipment.area.name }}
                    &middot; {{ record.created_at|relative_time }}
                    {% if record.eta %}
                    &middot; ETA: {{ record.eta|format_date }}
                    {% endif %}
                </div>
                {% if (record.status == 'New' and record.assignee_id != current_user.id) or (record.status != 'New' and record.status not in CLOSED_STATUSES) %}
                <div class="mt-2 d-flex gap-2" data-no-nav>
                    {% if record.status == 'New' and record.assignee_id != current_user.id %}
                    <form method="post" action="{{ url_for('repairs.claim', id=record.id) }}" class="d-inline">
                        <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
                        <input type="hidden" name="next" value="{{ request.path }}">
                        <button type="submit" class="btn btn-sm btn-outline-primary"
                                aria-label="Claim Repair #{{ record.id }}: {{ record.equipment.name }}">
                            Claim
                        </button>
                    </form>
                    {% endif %}
                    {% if record.status != 'New' and record.status not in CLOSED_STATUSES %}
                    <button type="button" class="btn btn-sm btn-outline-success"
                            data-bs-toggle="modal" data-bs-target="#resolveModal"
                            data-repair-id="{{ record.id }}"
                            aria-label="Resolve Repair #{{ record.id }}: {{ record.equipment.name }}">
                        Resolve
                    </button>
                    {% endif %}
                </div>
                {% endif %}
            </div>
        </div>
        {% endfor %}
    </div>
    ```
    Key structural changes:
    - `.queue-card` is now the click target (via `data-href` + the extended selector in Task 8a). The wrapping `<a>` is gone.
    - **No `role="link"` on the card div** — that ARIA role disallows nested interactive descendants (the form + buttons inside this card would violate the role's contract). The card is "clickable" via JS but does NOT claim link semantics; the action buttons inside have their own `aria-label`s and remain individually focusable. The desktop `<tr>` gets the same treatment (Action 10d also drops `role="link"`), so the desktop and mobile patterns are parallel.
    - **`text-body` class** on the card div preserves the body-text color the dropped `<a>` previously inherited from Bootstrap (no anchor-blue undertones once the wrapper is removed). No CSS change is needed in `static/css/app.css` (verified: no rule targets `.queue-card`).
    - **No `data-current-user-id` on the mobile wrapper** — only the desktop `#queue-table-wrapper` carries the attribute (Action 10b). `getElementById` finds the desktop wrapper even when CSS hides it on mobile (`d-none d-md-block`), so JS reads `currentUserId` from one source of truth. The previous draft embedded it on both wrappers; redundant.
    - Action buttons live INSIDE the same `card-body` so the entire card visual surface (including the gap between text and buttons) reads as one unit. The action-row `<div>` carries `data-no-nav` so clicks landing on its padding/gaps don't trigger row-navigation (mirrors Task 10e's `<td data-no-nav>` pattern).
  - Action 10g: At the bottom of `queue.html`, before `{% endblock %}`, include the modal:
    ```jinja
    {% include 'components/_resolve_modal.html' %}
    ```
  - Notes: The Resolve guard uses `record.status not in CLOSED_STATUSES` (the Jinja global from Task 1) — defense in depth in case a closed record ever leaks into the queue. The Claim guard reads `record.assignee_id` directly (no DB hit for `record.assignee` relationship — `assignee_id` is on the row).

- [x] **Task 11: Update `detail.html` — header Claim/Resolve buttons + modal include.**
  - File: `esb/templates/repairs/detail.html`
  - Action: Replace the header `<div>` (currently lines 13-21) with:
    ```jinja
    <div class="d-flex justify-content-between align-items-center mb-3">
        <h1>Repair #{{ record.id }}</h1>
        <div class="d-flex gap-2 align-items-center">
            {% if record.status == 'New' and record.assignee_id != current_user.id %}
            <form method="post" action="{{ url_for('repairs.claim', id=record.id) }}" class="d-inline">
                <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
                <input type="hidden" name="next" value="{{ request.path }}">
                <button type="submit" class="btn btn-outline-primary"
                        aria-label="Claim Repair #{{ record.id }}: {{ record.equipment.name }}">
                    Claim
                </button>
            </form>
            {% endif %}
            {% if record.status != 'New' and record.status not in CLOSED_STATUSES %}
            <button type="button" class="btn btn-outline-success"
                    data-bs-toggle="modal" data-bs-target="#resolveModal"
                    data-repair-id="{{ record.id }}"
                    aria-label="Resolve Repair #{{ record.id }}: {{ record.equipment.name }}">
                Resolve
            </button>
            {% endif %}
            <a href="{{ url_for('repairs.edit', id=record.id) }}" class="btn btn-primary">Edit</a>
            <span class="badge bg-{{ 'danger' if record.severity == 'Down' else ('warning text-dark' if record.severity in ['Degraded', 'Not Sure'] else 'secondary') }}">
                {{ record.severity or 'No Severity' }}
            </span>
        </div>
    </div>
    ```
  - Action: At the bottom of `detail.html`, after the Timeline `</ol>` and before `{% endblock %}`, add:
    ```jinja
    {% include 'components/_resolve_modal.html' %}
    ```
  - Notes: Uses the Jinja global `CLOSED_STATUSES` from Task 1 — no hard-coded list. Resolve hidden for `New` AND for any closed status; Claim hidden when self-assigned.

- [x] **Task 12: Add service-layer tests for `resolve_repair_record`.**
  - File: `tests/test_services/test_repair_service.py`
  - Action: Add a `TestResolveRepairRecord` class near `TestClaimRepairRecord` (which starts at line 1357). Tests:
    1. `test_resolve_open_record_sets_status_and_creates_note_entry` — start at `Assigned`; resolve with `note='Fixed'`; assert returned record has `status='Resolved'`; assert a `RepairTimelineEntry` of `entry_type='note'` with `content='Fixed'` exists; assert a `RepairTimelineEntry` of `entry_type='status_change'` with `new_value='Resolved'` exists.
    2. `test_resolve_from_new_status_is_allowed` — start at `New`; resolve; assert status becomes `Resolved` (service-layer is permissive; the triage rule is UI-only).
    3. `test_resolve_strips_whitespace_from_note` — pass `note='  Fixed  '`; assert the saved timeline entry's `content == 'Fixed'`.
    4. `test_resolve_empty_note_raises` — pass `note=''` → assert `ValidationError`; match on exact message `'Resolution note is required'`.
    5. `test_resolve_whitespace_only_note_raises` — pass `note='   '` → same assertion as #4.
    6. `test_resolve_unknown_user_raises` — pass `resolved_by_user_id=99999`; assert `ValidationError` with message containing `'User with id 99999 not found'`.
    7. `test_resolve_unknown_record_raises` — pass non-existent `repair_record_id=99999`. **Critical for catching test-author drift**: this test MUST exercise the record-not-found branch, NOT the user-not-found branch. Pass a valid non-empty `note`, AND pass a REAL `resolved_by_user_id` (e.g., `tech.id` from a fixture). If both `repair_record_id` and `resolved_by_user_id` are set to the same placeholder `99999`, the user-not-found check fires first per the documented order and the test silently exercises the wrong branch (would assert `'User with id 99999 not found'` instead of `'Repair record with id 99999 not found'`). Assert message contains `'Repair record with id 99999 not found'`.
    8. `test_resolve_closed_record_raises` — for each of `('Resolved', 'Closed - Duplicate', 'Closed - No Issue Found')`: create record, attempt resolve, assert `ValidationError` with message containing `'already closed'`, assert record was NOT mutated.
    9. `test_resolve_queues_resolved_notification` — set `notify_resolved='true'` via config; resolve a record; assert a `PendingNotification` with `notification_type='slack_message'` and `payload['event_type']=='resolved'` was enqueued.
    10. `test_resolve_does_not_queue_when_notify_resolved_false` — set `notify_resolved='false'` via config; resolve; assert no `resolved` notification was queued (sanity check — feature flag still respected).
    11. `test_resolve_with_non_ascii_note_roundtrips` — resolve with `note='Fixed! 🔧 Тест съел проблема'`; refresh the record; assert the saved timeline entry's `content` equals the input exactly (no truncation, no mojibake). **Caveat:** SQLite (the test DB) handles full Unicode natively, so this test will always pass — it does NOT exercise the production `utf8mb3` exposure. The production charset is verified separately by Task 20; if the production charset is `utf8mb3`, emoji silently truncate / raise `Incorrect string value` in production while this test stays green. Treat this test as a happy-path round-trip confirmation, NOT as production charset coverage.
    12. `test_resolve_combined_failures_uses_documented_validation_order` — POST/call with `note=''` AND `resolved_by_user_id=99999` (non-existent) AND `repair_record_id=99999` (non-existent). Per the documented order (note → user → record → closed), the empty-note check fires first; assert `ValidationError` with message `'Resolution note is required'`. This is the regression test for the order-of-validations decision — if a future refactor swaps the order (e.g., user-first), this test fails loudly. Without this test, individual single-failure tests (#4, #6, #7) would all still pass even if the order were silently inverted.
  - Notes: Use `tests.conftest._create_user`, `make_area`, `make_equipment` directly as `TestClaimRepairRecord` does. Tests #4-#7 verify each validation step in isolation; test #12 pins down the COMBINED-failure order. Construct each isolated test with all-other-fields-valid to isolate the variable under test.

- [x] **Task 12b: Add tests for `get_repair_queue()`'s new `assignee_id` and `unassigned` kwargs.**
  - File: `tests/test_services/test_repair_service.py`
  - Action: Add tests inside the existing `TestGetRepairQueue` class (starts at line 1453). Tests:
    1. `test_queue_filter_by_assignee_id` — create three records, two assigned to user A and one to user B; call `get_repair_queue(assignee_id=A.id)`; assert exactly A's two records returned (compare by `record.id` set).
    2. `test_queue_filter_unassigned` — create three records, two unassigned and one assigned; call `get_repair_queue(unassigned=True)`; assert exactly the two unassigned records returned.
    3. `test_queue_filter_assignee_id_and_unassigned_mutual_exclusion` — call `get_repair_queue(assignee_id=1, unassigned=True)`; assert `ValidationError` with message containing the substring `'assignee_id'` AND `'unassigned'` (avoids brittle exact-string matching that breaks on minor message rewording).
    4. `test_queue_no_filter_returns_all_open` — regression sanity: call `get_repair_queue()` with no kwargs; assert same result as before the signature extension (all open records, ordered by severity priority then created_at ASC).
    5. `test_queue_combined_area_and_assignee_filter` — create records across two areas, with mixed assignees; call `get_repair_queue(area_id=area1.id, assignee_id=tech.id)`; assert only records matching BOTH filters returned. Validates that the new filter composes correctly with the existing `area_id` filter.
  - Notes: These mirror the existing tests for `area_id` and `status` filters in shape. Use `make_area`, `make_equipment`, `_create_user` from `tests/conftest.py`. The mutual-exclusion test pins down the guard at the service layer so a future refactor that loosens it (e.g., "if both passed, unassigned wins") is caught.

- [x] **Task 13: Add the reclaim-no-op regression test.**
  - File: `tests/test_services/test_repair_service.py`
  - Action: Inside `TestClaimRepairRecord` (line 1357), add:
    ```python
    def test_claim_self_assigned_record_is_noop(self, app, make_area, make_equipment):
        """Re-claiming a record already assigned to self produces no new timeline entries or notifications."""
        # _db is the SQLAlchemy session used throughout this test file; existing
        # tests in TestClaimRepairRecord import it at module level. The imports
        # below are intra-test scoped for clarity — the implementer should
        # ensure `from esb.extensions import db as _db` is at module top
        # alongside other test imports (it already is in test_repair_service.py).
        from tests.conftest import _create_user
        from esb.models.pending_notification import PendingNotification

        tech = _create_user('technician', username='alice')
        area = make_area('Shop', '#shop')
        eq = make_equipment(name='Tool', area=area)
        record = RepairRecord(
            equipment_id=eq.id, description='Broken', status='Assigned', assignee_id=tech.id,
        )
        _db.session.add(record)
        _db.session.commit()

        timeline_count_before = record.timeline_entries.count()
        notification_count_before = _db.session.execute(
            _db.select(_db.func.count()).select_from(PendingNotification)
        ).scalar_one()

        repair_service.claim_repair_record(
            repair_record_id=record.id,
            claimed_by_user_id=tech.id,
            claimed_by_username=tech.username,
        )

        _db.session.refresh(record)
        # No new timeline entry (no assignee_change or status_change fired).
        assert record.timeline_entries.count() == timeline_count_before
        # No new pending notification (the status_changed/resolved triggers
        # didn't fire because audit_changes is empty post no-op guard).
        notification_count_after = _db.session.execute(
            _db.select(_db.func.count()).select_from(PendingNotification)
        ).scalar_one()
        assert notification_count_after == notification_count_before
    ```
  - Notes: Covers the concurrent-claim race scenario: a second claim by the already-assigned user is a no-op via `update_repair_record`'s value-comparison guard. Pinning this behavior — both timeline-entry count AND notification count — in a test means the next refactor can't silently break it. The notification-count check uses a COUNT(*) query for robustness across test isolation.

- [x] **Task 14: Add view tests for the claim route.**
  - File: `tests/test_views/test_repair_views.py`
  - Action: Add a `TestClaimRepairRoute` class with the following tests. For all tests, after the POST, use `_db.session.refresh(record)` and assert the resulting state; assert flash messages via `with client.session_transaction() as s: assert (b'Claimed', 'success') in [(b'Claimed Repair #{0}.'.format(id).encode(), c) for ...]` (or use `follow_redirects=True` and search `resp.data`).
    1. `test_tech_claims_new_record_promotes_to_assigned` — tech_client POST to `/repairs/<id>/claim` on a `New` record; assert 302; assert `record.status == 'Assigned'`, `record.assignee_id == tech_user.id`; assert success flash text "Claimed Repair #<id>." appears.
    2. `test_staff_claims_record` — staff_client POST works (role hierarchy).
    3. `test_tech_claims_assigned_record_swaps_assignee_keeps_status` — starting `status='Assigned'` assigned to user A, tech_client claims; assert `assignee_id == tech_user.id`, `status == 'Assigned'` (no promotion past New).
    4. `test_claim_on_closed_record_flashes_danger_and_does_not_mutate` — starting `status='Resolved'`, POST claim; assert 302; assert danger flash contains "closed"; assert record state unchanged.
    5. `test_claim_nonexistent_returns_404` — POST to `/repairs/99999/claim`; assert 404.
    6. `test_claim_unauthenticated_redirects_to_login` — POST without login; assert 302 with `/auth/login` in `resp.headers['Location']`.
    7. `test_claim_as_member_returns_403` — create a member-role user via `_create_user('member', 'memberuser')`, log in via `client.post('/auth/login', data={'username': 'memberuser', 'password': 'testpass'})`, then POST claim; assert 403.
    8. `test_claim_respects_safe_next_url_for_queue` — POST with `next=/repairs/queue`; assert 302 with `Location == /repairs/queue`. **This is the load-bearing positive control**: if the helper were broken to always return `detail_url` (the fallback), this test would fail because `/repairs/queue != /repairs/<id>`. Test #9 below is degenerate by construction (next_val happens to equal fallback) and only serves as a "smoke check" that the route doesn't 500 on a same-record `next` — the real cross-record verification is test #10.
    9. `test_claim_respects_safe_next_url_for_detail` — POST with `next=/repairs/<id>`; assert 302 with `Location == /repairs/<id>`. (Note: passes even if the helper falls back, because `next_val == detail_url == /repairs/<id>` for THIS record. It's a smoke check; #10 is the cross-record negative control that actually differentiates honored vs fallback for the detail URL.)
    10. `test_claim_rejects_other_record_detail_next` — create two records id=A and id=B; POST claim on A with `next=/repairs/<B>`; assert 302 with `Location == /repairs/<A>` (allowlist disallows cross-record next).
    11. `test_claim_rejects_protocol_relative_next` — POST with `next=//evil.example.com/`; assert 302 with `Location == /repairs/<id>` (fallback).
    12. `test_claim_rejects_scheme_next` — POST with `next=http://evil.example.com/`; assert fallback.
    13. `test_claim_rejects_backslash_next` — POST with `next=/\evil.com/path`; assert fallback (allowlist exact-match rejects this).
  - Notes: Test names assert against `url_for('repairs.claim', id=record.id).encode()` in the byte-search, not hardcoded paths. The flash-assertion pattern uses session-flashes inspection to avoid relying on follow_redirects rendering.

- [x] **Task 15: Add view tests for the resolve route.**
  - File: `tests/test_views/test_repair_views.py`
  - Action: Add a `TestResolveRepairRoute` class. Tests:
    1. `test_tech_resolves_open_record_with_note` — tech_client POST `{'note': 'Fixed'}` to `/repairs/<id>/resolve` on an `Assigned` record; assert 302; assert `record.status == 'Resolved'`; assert a `RepairTimelineEntry` with `entry_type='note', content='Fixed'` exists.
    2. `test_staff_resolves_record` — staff_client works.
    3. `test_resolve_empty_note_flashes_form_error` — POST `{'note': ''}`; assert at least one `'danger'`-category flash via `with client.session_transaction() as s: assert any(cat == 'danger' for cat, _ in s.get('_flashes', []))`; assert record NOT mutated. Do NOT assert the exact WTForms message text — Flask-WTF version drift may change the default string.
    4. `test_resolve_whitespace_only_note_flashes_service_error` — POST `{'note': '   '}`; WTForms `DataRequired` passes (whitespace truthy), but `resolve_repair_record` raises; assert danger flash contains "Resolution note is required"; assert record NOT mutated.
    5. `test_resolve_on_closed_record_flashes_danger_and_does_not_mutate` — starting `status='Resolved'`, POST resolve with valid note; assert danger flash contains "already closed"; non-mutation.
    6. `test_resolve_nonexistent_returns_404` — POST to `/repairs/99999/resolve` with note; assert 404.
    7. `test_resolve_unauthenticated_redirects_to_login`.
    8. `test_resolve_as_member_returns_403`.
    9. `test_resolve_from_new_status_allowed_via_route` — starting `status='New'`, POST resolve with note; assert status becomes `'Resolved'`.
    10. `test_resolve_respects_safe_next_url_for_queue` — POST with `next=/repairs/queue` and valid note; assert `Location == /repairs/queue`.
    11. `test_resolve_rejects_unsafe_next_url` — POST with `next=http://evil.example.com/`; assert fallback to detail.
    12. `test_resolve_with_non_ascii_note_succeeds` — POST `{'note': 'Fixed! 🔧'}`; assert 302; assert the timeline entry content is the exact bytes.
  - Notes: CSRF-failure-flashes-generic-message is hard to test cleanly because TestingConfig disables CSRF. A future expansion can test this with a separate config; for now the code path is covered by inspection of Task 6's code.

- [x] **Task 16: Add tests for queue rendering of buttons + filter + modal.**
  - File: `tests/test_views/test_repair_views.py`
  - Action: Extend the queue test cluster around line 647. Tests:
    1. `test_queue_renders_claim_button_for_new_unclaimed` — create a `New` record assigned to no one; tech_client GET queue; assert `url_for('repairs.claim', id=record.id).encode() in resp.data`; assert `b'>Claim<' in resp.data`.
    2. `test_queue_omits_claim_button_when_self_assigned` — create a `New` record assigned to `tech_user`; tech_client GET queue; assert `url_for('repairs.claim', id=record.id).encode() not in resp.data`.
    3. `test_queue_renders_resolve_button_for_assigned` — create an `Assigned` record; GET queue; assert `b'data-bs-target="#resolveModal"' in resp.data`; assert `'data-repair-id="{}"'.format(record.id).encode() in resp.data`.
    4. `test_queue_includes_resolve_modal` — GET queue; assert `b'id="resolveModal"' in resp.data`.
    5. `test_queue_embeds_current_user_id` — GET queue with at least one open record; assert `'data-current-user-id="{}"'.format(tech_user.id).encode() in resp.data`.
    5b. `test_queue_embeds_current_user_id_when_empty` — GET queue with NO open records (empty queue); assert `'data-current-user-id="{}"'.format(tech_user.id).encode() in resp.data` STILL appears. Verifies the desktop `#queue-table-wrapper` (the data-attribute carrier) is rendered even when the table body is empty — a guard against future template refactors that might omit the wrapper on empty queues, which would silently break the JS "Mine" filter (the JS reads `dataset.currentUserId` from this wrapper).
    6. `test_queue_assignee_filter_select_rendered` — GET queue; assert `b'id="assignee-filter"' in resp.data` and the three `<option>` values are present (`""`, `"me"`, `"unassigned"`).
    7. `test_queue_mobile_card_has_data_href` — GET queue; assert a `.queue-card` element exists with a `data-href` pointing at the record's detail page. Use a class-list-order-tolerant regex: `re.search(rb'<div[^>]*\bclass="[^"]*\bqueue-card\b[^"]*"[^>]*\bdata-href="/repairs/' + str(record.id).encode() + rb'"', resp.data)` MUST match. Do NOT use raw `b'class="card mb-2 queue-card"' in resp.data` substring matching — that's brittle to class-list reordering (e.g., `class="card text-body mb-2 queue-card"` is functionally identical but breaks the substring assert).
    8. `test_queue_mobile_card_has_assignee_data_attrs` — GET queue with one unassigned record and one assigned; assert `b'data-unassigned="true"'` appears for the unassigned record and `'data-assignee-id="{}"'.format(other_user.id).encode()` for the assigned one.
    9. `test_queue_row_has_assignee_data_attrs` — same as #8 but for desktop rows.
    10. `test_queue_url_param_assignee_me_filters_server_side` — given three records (two assigned to `tech_user`, one assigned to another user), GET `/repairs/queue?assignee=me` as `tech_client`; assert the two `tech_user`-owned records' UNIQUE markers appear in `resp.data` and the third record's marker does NOT. **Use a unique marker per record** — e.g., set `description='MARKER-A'`, `description='MARKER-B'`, `description='MARKER-C'` when constructing the fixtures, then assert `b'MARKER-A' in resp.data` etc. Do NOT assert against `record.id` substrings — IDs may collide with user IDs in the test fixture set, causing false positives. Verifies the server-side filter applied via the new `get_repair_queue(assignee_id=...)` kwarg.
    11. `test_queue_url_param_assignee_unassigned_filters_server_side` — given three records (two unassigned, one assigned), GET `/repairs/queue?assignee=unassigned`; use the same unique-marker pattern (`description='UNASSIGNED-A'`, etc.); assert only the two unassigned records' markers appear. Verifies the server-side filter applied via the new `unassigned=True` kwarg.
    12. `test_queue_url_param_assignee_empty_returns_all` — GET `/repairs/queue?assignee=`; assert ALL three records appear (empty value maps to no filter).
    13. `test_queue_url_param_assignee_unknown_returns_all` — GET `/repairs/queue?assignee=bogus`; assert ALL three records appear (unknown values silently no-op; do NOT 400).
    14. `test_queue_dropdown_selected_reflects_url_param` — GET `/repairs/queue?assignee=me`; parse the HTML with the response body using a regex that's permissive on whitespace and attribute order: `re.search(rb'<option[^>]*\bvalue="me"[^>]*\bselected\b[^>]*>', resp.data)` MUST match. Avoid raw `in resp.data` substring matching — Jinja's default env doesn't strip whitespace inside tags, so the literal `selected` attribute may render with surrounding spaces or in a different attribute order depending on template edits.
    15. `test_queue_dropdown_default_selected_when_no_url_param` — GET `/repairs/queue` (no `assignee` param); use the same regex form: `re.search(rb'<option[^>]*\bvalue=""[^>]*\bselected\b[^>]*>', resp.data)` MUST match (the "All Assignees" option carries `selected`).
    Plus: `test_queue_dropdown_selects_all_when_assignee_unknown` — GET `/repairs/queue?assignee=bogus`; assert "All Assignees" option (value=`""`) carries `selected` (Task 7's view canonicalizes `bogus` → `''` before passing to the template, so the dropdown gracefully reverts to the default selection rather than rendering nothing-selected). Use the same permissive regex form as T16.14/T16.15.
  - Notes: Tests #10-#13 verify the server-side filter (URL param → `get_repair_queue` kwargs → SQL filter). Tests #14-#15 verify the dropdown's initial state reflects the URL param. The client-side dropdown-change-toggles-display behavior (Task 8b) is JS-only and not covered by these view tests — filter behavior testing on the JS layer would require Selenium/Playwright; left out of scope per existing test conventions.

- [x] **Task 17: Add detail-page button-visibility tests.**
  - File: `tests/test_views/test_repair_views.py`
  - Action: Add a `TestDetailQuickActions` class around line 112 (detail-page test cluster). Tests:
    1. `test_detail_shows_claim_for_new_not_self_assigned` — create `New` record assigned to a different user; tech_client GET detail; assert claim form action URL `url_for('repairs.claim', id=record.id)` appears in `resp.data`.
    2. `test_detail_hides_claim_when_self_assigned` — `New` record assigned to tech_user; assert claim URL NOT in `resp.data`.
    3. `test_detail_shows_resolve_for_open_non_new` — `Assigned` record; assert `b'data-bs-target="#resolveModal"'` AND `'data-repair-id="{}"'.format(record.id).encode()` in `resp.data`.
    4. `test_detail_hides_resolve_for_new` — `New` record; assert NO resolve modal trigger for this record's id in `resp.data`.
    5. `test_detail_hides_both_buttons_for_closed_record` — parametrize over each value in `CLOSED_STATUSES`; for each: create record at that status, GET detail, assert neither claim URL nor resolve `data-repair-id="<id>"` appears.
    6. `test_detail_modal_included` — GET detail; assert `b'id="resolveModal"' in resp.data`.
    7. `test_detail_edit_button_still_visible` — regression test that the existing Edit button remains visible for all statuses (open AND closed).
  - Notes: Test #5 is the regression test that catches any future drift between the Jinja global `CLOSED_STATUSES` and the template's `not in CLOSED_STATUSES` check. If `CLOSED_STATUSES` grows, this test must pass without code changes (because the template uses the global).

- [x] **Task 18: Converge Slack `resolve_with_note` onto `resolve_repair_record`.**
  - File: `esb/slack/handlers.py`
  - Action: Locate the `repair_action_submission` view-submission handler (the function decorated with the action-submission registration). In the dispatch block (lines 612-625), restructure the resolve branch:
    
    Current (the relevant portion at lines 597-625). The full action-validation block is shown so the implementer does NOT accidentally delete the `else: ack(..., 'Unknown action')` guard during the diff:
    ```python
    elif action == 'resolve_with_note':
        note_val = values.get('note_block', {}).get('note', {}).get('value')
        if not note_val or not note_val.strip():
            ack(response_action='errors', errors={
                'note_block': 'Note is required when resolving.',
            })
            return
        changes['status'] = 'Resolved'
        changes['note'] = note_val.strip()
    else:
        ack(response_action='errors', errors={
            'action_block': f'Unknown action: {action}',
        })
        return

    try:
        if action == 'claim':
            repair_service.claim_repair_record(
                repair_record_id=repair_record_id,
                claimed_by_user_id=esb_user.id,
                claimed_by_username=esb_user.username,
            )
        else:
            repair_service.update_repair_record(
                repair_record_id=repair_record_id,
                updated_by=esb_user.username,
                author_id=esb_user.id,
                **changes,
            )
    except ValidationError as e:
        ack(response_action='errors', errors={'action_block': str(e)})
        return
    # ... rest of handler (ack + msg construction) unchanged.
    ```

    Updated. **Only two changes:** (1) the `resolve_with_note` action-collection branch no longer mutates `changes` (replaced with a local `resolve_note` variable); (2) the dispatch-`try` block gets a new `elif action == 'resolve_with_note':` branch. The `else: ack(... 'Unknown action')` guard at lines 606-610 is **UNCHANGED — do not delete it**. The `except ValidationError` block at lines 626-628 is also unchanged.
    ```python
    elif action == 'resolve_with_note':
        note_val = values.get('note_block', {}).get('note', {}).get('value')
        if not note_val or not note_val.strip():
            ack(response_action='errors', errors={
                'note_block': 'Note is required when resolving.',
            })
            return
        # CHANGED: do NOT add to `changes` -- the new resolve_repair_record
        # service call (below) takes the note as a kwarg.
        resolve_note = note_val.strip()
    else:
        # UNCHANGED -- keep the unknown-action guard.
        ack(response_action='errors', errors={
            'action_block': f'Unknown action: {action}',
        })
        return

    try:
        if action == 'claim':
            repair_service.claim_repair_record(
                repair_record_id=repair_record_id,
                claimed_by_user_id=esb_user.id,
                claimed_by_username=esb_user.username,
            )
        elif action == 'resolve_with_note':
            # NEW BRANCH -- routes resolve through the new service helper.
            repair_service.resolve_repair_record(
                repair_record_id=repair_record_id,
                resolved_by_user_id=esb_user.id,
                resolved_by_username=esb_user.username,
                note=resolve_note,
            )
        else:
            # UNCHANGED -- set_eta and set_status still go through update_repair_record.
            repair_service.update_repair_record(
                repair_record_id=repair_record_id,
                updated_by=esb_user.username,
                author_id=esb_user.id,
                **changes,
            )
    except ValidationError as e:
        # UNCHANGED.
        ack(response_action='errors', errors={'action_block': str(e)})
        return
    ```
  - Notes: The Slack-side pre-validation at line 599-603 is preserved — it attaches the empty-note error to the correct input block (`note_block`) for Slack UX. The service-layer raise becomes defense-in-depth (reached only if a Slack client somehow bypasses the validation, e.g., a misconfigured workflow). **Scope of convergence:** the resolve path now flows through `resolve_repair_record` from both Slack AND web. The `set_eta` and `set_status` Slack action paths still call `update_repair_record` directly (and are out of scope for this spec). So "single source of truth" applies specifically to the **resolve invariants** (closed-record guard, user-exists guard, empty-note guard, Resolved-transition + note timeline entry), NOT to all Slack-dispatched mutations.

- [x] **Task 19: Verify Slack handler tests for `resolve_with_note` pass unchanged post-convergence.**
  - File: `tests/test_slack/test_handlers.py`
  - Action: The existing resolve-with-note tests at `tests/test_slack/test_handlers.py:1315-1376` — `test_resolve_with_note_sets_resolved_and_adds_note`, `test_resolve_with_note_queues_only_resolved_notification`, `test_resolve_without_note_returns_error` — verify outcomes via `db.session.expire_all()` + DB-state inspection and `ack.call_args.kwargs` inspection. They do NOT mock service functions. Since the new `resolve_repair_record` simply calls `update_repair_record(status='Resolved', note=...)` internally, the end-state in the DB and the ack response are byte-identical to the pre-convergence behavior. **No test changes are required** — the existing three resolve-with-note tests pass unchanged after Task 18. (`test_closed_record_returns_error` at 1378-1393 uses `action='claim'`, NOT resolve — it is unaffected by Task 18 and not part of this verification.)
  - Verify: run `venv/bin/python -m pytest tests/test_slack/test_handlers.py -v -k "test_resolve_with_note_sets_resolved_and_adds_note or test_resolve_with_note_queues_only_resolved_notification or test_resolve_without_note_returns_error"` after Task 18 and confirm all three tests pass without modification. Avoid the broader `-k "resolve_with_note or closed_record"` filter — it picks up the unrelated `test_closed_record_returns_error` (a claim test) and any other class-level `closed_record` tests.
  - Optional add: a single new test `test_resolve_with_note_uses_resolve_helper` could `unittest.mock.patch('esb.slack.handlers.repair_service.resolve_repair_record')` to assert the convergence-specific call (helper invoked with the right kwargs, `update_repair_record` not called via this path). This is gilding — the four existing tests already verify the user-facing contract. Implementer's discretion.
  - Notes: A previous draft of this task prescribed a mock-based test pattern (`with patch('esb.slack.handlers.repair_service.resolve_repair_record')...`). That pattern is incompatible with the surrounding `test_handlers.py` style: existing tests verify by DB state, not by mocking. The corrected task here keeps the existing tests as-is (they cover the convergence implicitly).

- [x] **Task 20: Verify production schema's `repair_timeline_entries.content` charset.**
  - File: none (verification task).
  - Action:
    1. Connect to the production MariaDB (or the most-prod-like staging) and run:
       ```sql
       SELECT column_name, character_set_name, collation_name
       FROM information_schema.columns
       WHERE table_name = 'repair_timeline_entries' AND column_name = 'content';
       ```
    2. **Pass criterion:** `character_set_name = 'utf8mb4'` (4-byte Unicode, supports emoji).
    3. **Fail handling:** if `utf8mb3` (3-byte, no emoji): document in the PR description and file a follow-up ticket to issue an Alembic migration changing the column charset. The migration is OUT OF SCOPE for this spec — the resolve flow still works on `utf8mb3`, just with emoji silently dropped or raising `Incorrect string value`. Slack and the existing `add_repair_note` path have the same exposure today.
  - Notes: SQLite (test DB) handles full Unicode natively, so service tests pass regardless. This verification confirms production matches test expectations.

- [x] **Task 21: Update `docs/technicians.md`.**
  - File: `docs/technicians.md`
  - Action: In the "Working with the Repair Queue" section (starts at line 23), add a new subsection under "Filtering" (around line 46):
    > The **Assignee** filter has three options: **All Assignees** (default), **Mine** (records assigned to you), and **Unassigned** (records with no assignee). Filters are applied immediately client-side — no page reload.
    
    Add a new subsection "Quick Actions" after "Mobile View" (around line 56):
    > **Quick Actions.** Each row in the queue includes inline buttons for the two most common technician actions:
    > - **Claim** — appears on `New` repairs you haven't claimed. One click sets you as the assignee and moves the status to `Assigned`.
    > - **Resolve** — appears on any open repair that isn't `New`. Opens a small modal that asks for a resolution note (required), then sets the status to `Resolved` and records your note in the timeline.
    >
    > Both actions are also available from the repair detail page, next to the **Edit** button.
  - Notes: Keep docs concise — matches existing tone.

### Acceptance Criteria

Numbered for traceability. Each AC has at least one corresponding test in Tasks 12-17 and 19.

- [x] **AC 1** (Claim happy path on New): Given a `New` repair record assigned to no one OR to a user other than `current_user`, when a technician POSTs to `/repairs/<id>/claim`, then 302 response; record's `status` becomes `'Assigned'`; `assignee_id` becomes `current_user.id`; success flash `Claimed Repair #<id>.` shown. (Tests T14.1, T14.2.)

- [x] **AC 2** (Claim from later open status leaves status): Given a record at any open status other than `'New'`, when claimed, then `assignee_id` updates to `current_user.id` and `status` is unchanged. (Test T14.3.)

- [x] **AC 3** (Claim rejected on closed record): Given `status in CLOSED_STATUSES`, when POST claim, then no mutation and danger flash containing "closed" is shown. (Test T14.4.)

- [x] **AC 4** (Claim 404 / 403 / login redirect): POST to nonexistent ID returns 404. Unauthenticated POST returns 302 to `/auth/login`. Member-role POST returns 403. (Tests T14.5, T14.6, T14.7.)

- [x] **AC 5** (Claim safe next allowed for two paths): Given hidden `next` field equal to `/repairs/queue` OR `/repairs/<id>` (same record), 302 Location matches. (Tests T14.8, T14.9.)

- [x] **AC 6** (Claim unsafe next falls back): `next` value of `/repairs/<other_record_id>`, `//evil.com/`, `http://evil.com/`, or `/\evil.com/path` returns 302 to `/repairs/<id>` of the claimed record. (Tests T14.10, T14.11, T14.12, T14.13.)

- [x] **AC 7** (Reclaim is a no-op): Given a record already assigned to `current_user`, when claim is called via the service (e.g., from a concurrent race), then no new timeline entries and no new notifications are created. (Test T13.)

- [x] **AC 8** (Resolve happy path): Given an open repair record, when a technician POSTs `/repairs/<id>/resolve` with `note='Fixed'`, then 302; record's `status` is `'Resolved'`; a `RepairTimelineEntry` of `entry_type='note', content='Fixed'` exists; success flash `Resolved Repair #<id>.` shown. (Tests T15.1, T15.2.)

- [x] **AC 9** (Resolve from `New` allowed at service AND route): Service-level call to `resolve_repair_record` from `New` succeeds. Route-level POST to `/repairs/<id>/resolve` from `New` succeeds. UI hides the Resolve button on `New` records — but the route does NOT block. (Tests T12.2, T15.9.)

- [x] **AC 10** (Resolve empty note rejected at form layer): Given POST with `note=''`, WTForms `DataRequired` validation fails; the record is NOT mutated; at least one `'danger'`-category flash is set on the session. The test asserts (a) no mutation and (b) flash present with category `'danger'`, NOT an exact WTForms message string (that string is library-version-dependent and may drift across Flask-WTF releases). (Test T15.3.)

- [x] **AC 11** (Resolve whitespace-only note rejected at service layer): Given POST with `note='   '`, WTForms validates but service raises `ValidationError('Resolution note is required')`; record NOT mutated; danger flash contains exact text `'Resolution note is required'` (capital R as in source). (Test T15.4.)

- [x] **AC 12** (Resolve rejected on closed record): Given `status in CLOSED_STATUSES`, POST resolve with valid note; no mutation; danger flash contains `'already closed'`. (Test T15.5.)

- [x] **AC 13** (Resolve rejects unknown user): Service call `resolve_repair_record(resolved_by_user_id=99999, ...)` raises `ValidationError` containing `'User with id 99999 not found'`. (Test T12.6.)

- [x] **AC 14** (Resolve 404 / 403 / login redirect): same as AC 4 for the resolve route. (Tests T15.6, T15.7, T15.8.)

- [x] **AC 15** (Resolve safe next + unsafe-next fallback): same shape as AC 5/AC 6 for resolve. (Tests T15.10, T15.11.)

- [x] **AC 16** (Service-layer `resolve_repair_record` queues `resolved` notification): When `notify_resolved='true'` (default), resolving an open record queues a `PendingNotification` with `notification_type='slack_message', payload['event_type']='resolved'`. (Test T12.9.)

- [x] **AC 17** (Notification feature flag respected): When `notify_resolved='false'`, no `resolved` notification is queued on resolve. (Test T12.10.)

- [x] **AC 18** (Non-ASCII note round-trips on SQLite test DB): When a technician resolves with `note='Fixed! 🔧 Тест съел проблема'` against SQLite (test DB, full Unicode native), the saved timeline entry's `content` equals the input bytes-for-bytes after `_db.session.refresh(record)`. **Production charset coverage is NOT provided by this AC** — production runs MariaDB and the `repair_timeline_entries.content` column may be `utf8mb3` (3-byte Unicode, no emoji). If `utf8mb3`, emoji silently truncate or raise `Incorrect string value` in production while this test stays green. Task 20 verifies the production charset; if it's `utf8mb3`, file a follow-up migration. (Test T12.11 service-level; T15.12 route-level.)

- [x] **AC 19** (Whitespace stripped from note): A note with leading/trailing whitespace is saved without it. `note='  Fixed  '` → timeline entry `content='Fixed'`. (Test T12.3.)

- [x] **AC 20** (Queue template renders Claim button when applicable): GET `/repairs/queue` for a `New` record not assigned to current user contains the claim form action URL. (Test T16.1.)

- [x] **AC 21** (Queue template hides Claim when self-assigned): GET queue for a `New` record assigned to current user does NOT contain that record's claim form action URL. (Test T16.2.)

- [x] **AC 22** (Queue template renders Resolve modal trigger for open-non-New): GET queue for an `Assigned` record contains `data-bs-target="#resolveModal"` AND `data-repair-id="<id>"`. (Test T16.3.)

- [x] **AC 23** (Queue includes modal markup once): GET queue contains `id="resolveModal"`. (Test T16.4.)

- [x] **AC 24** (Queue embeds current user id): GET queue contains `data-current-user-id="<tech_user.id>"`. (Test T16.5.)

- [x] **AC 25** (Queue Assignee filter rendered): GET queue contains `id="assignee-filter"` with three options. (Test T16.6.)

- [x] **AC 25a** (Server-side filter via `?assignee=me`): GET `/repairs/queue?assignee=me` filters the rendered records to only those with `assignee_id == current_user.id`. (Test T16.10.)

- [x] **AC 25b** (Server-side filter via `?assignee=unassigned`): GET `/repairs/queue?assignee=unassigned` filters to only records with `assignee_id IS NULL`. (Test T16.11.)

- [x] **AC 25c** (Empty/unknown `?assignee` value): GET `/repairs/queue?assignee=` OR `?assignee=bogus` returns ALL open records (no 400 response, silent no-op). (Tests T16.12, T16.13.)

- [x] **AC 25d** (Dropdown reflects URL state): GET `/repairs/queue?assignee=me` renders `<option value="me" selected>` in the assignee filter dropdown; `?assignee=` (or no param) renders `<option value="" selected>` for "All Assignees". (Tests T16.14, T16.15.)

- [x] **AC 25e** (Service-layer filter contract): `get_repair_queue(assignee_id=X)` returns only records with `assignee_id == X`; `get_repair_queue(unassigned=True)` returns only records with `assignee_id IS NULL`; passing both raises `ValidationError('... mutually exclusive ...')`. (Tests T12b.1, T12b.2, T12b.3.)

- [x] **AC 25f** (Service-layer filter composition): `get_repair_queue(area_id=A, assignee_id=X)` returns only records matching BOTH filters. (Test T12b.5.)

- [x] **AC 26** (Mobile cards adopt data-href pattern): GET queue contains a `.queue-card` element with a `data-href` attribute equal to `url_for('repairs.detail', id=record.id)`. (Test T16.7.)

- [x] **AC 27** (Mobile cards have assignee data attributes): GET queue with one unassigned and one assigned record contains `data-unassigned="true"` on the former and `data-assignee-id="<other_user.id>"` on the latter. (Test T16.8.)

- [x] **AC 28** (Desktop rows have assignee data attributes): same as AC 27 for `.queue-row`. (Test T16.9.)

- [x] **AC 29** (Detail page shows Claim for New non-self-assigned): GET `/repairs/<id>` for a `New` record assigned to another user contains the claim form action URL. (Test T17.1.)

- [x] **AC 30** (Detail page hides Claim when self-assigned): GET `/repairs/<id>` for a `New` record assigned to current user does NOT contain that record's claim form action URL. (Test T17.2.)

- [x] **AC 31** (Detail page shows Resolve for open non-New): GET `/repairs/<id>` for an `Assigned` record contains the modal trigger for this record. (Test T17.3.)

- [x] **AC 32** (Detail page hides Resolve for New): GET `/repairs/<id>` for a `New` record does NOT contain its modal trigger. (Test T17.4.)

- [x] **AC 33** (Detail page hides both for every closed status): For every value `s` in `CLOSED_STATUSES`, GET `/repairs/<id>` for a record at status `s` contains neither claim form action URL nor resolve modal trigger. (Test T17.5 — parametrized.)

- [x] **AC 34** (Detail page modal included): GET `/repairs/<id>` contains `id="resolveModal"`. (Test T17.6.)

- [x] **AC 35** (Detail page Edit button preserved): GET `/repairs/<id>` for ANY status (open or closed) contains the Edit button. (Test T17.7.)

- [x] **AC 36** (Slack convergence behavior preserved): After the convergence (Task 18), the Slack `resolve_with_note` flow produces the same observable outcomes as before — a Resolved record, a single `note` timeline entry with the submitted content, exactly one queued `resolved` notification, and the same `ack(response_action='errors', errors={'note_block': ...})` for empty-note input. Verified by re-running the existing three resolve-with-note tests at `test_handlers.py:1315-1376` without modification (Task 19).

- [x] **AC 37** (Slack pre-validation preserved): Empty-note submission to the Slack action modal still ack-fails with `errors={'note_block': 'Note is required when resolving.'}` before reaching the service. (Task 19's existing test, retained.)

- [x] **AC 38** (CLOSED_STATUSES exposed to templates): Jinja `{% if 'Resolved' in CLOSED_STATUSES %}` evaluates true in any template; rendering a template referencing `CLOSED_STATUSES` does not raise `UndefinedError`. (Implicitly covered by the detail-template visibility tests in Task 17, which rely on the Jinja global.)

- [x] **AC 39** (Lint passes): `make lint` passes with no new violations.

- [x] **AC 40** (Tests pass): `make test` passes.

## Additional Context

### Dependencies

- **`claim_repair_record`** (`esb/services/repair_service.py:225`) — existing, unchanged.
- **`update_repair_record`** (`esb/services/repair_service.py:375`) — existing, unchanged. Both new helpers delegate to it.
- **Existing `resolved` notification trigger** (`esb/services/repair_service.py:513-518`) — fires automatically when status transitions into `CLOSED_STATUSES`. No new notification wiring.
- **Bootstrap 5 Modal component** — already bundled at `esb/static/js/bootstrap.bundle.min.js`.
- **Flask-WTF / WTForms** — already used throughout `esb/forms/`.
- **No DB migration.** Schema unchanged. The charset verification (Task 20) may produce a follow-up migration, but it is not produced as part of this spec.

### Testing Strategy

- **Service tests** (`tests/test_services/test_repair_service.py`):
  - `TestResolveRepairRecord`: 12 tests (Task 12, including the combined-failure order test added per F21).
  - Extension to `get_repair_queue` tests: 5 tests (Task 12b — assignee_id/unassigned filter kwargs).
  - Extension to `TestClaimRepairRecord`: 1 test (Task 13 — reclaim no-op).
  - **Total: 18 service tests.**
- **View tests** (`tests/test_views/test_repair_views.py`):
  - `TestClaimRepairRoute`: 13 tests (Task 14).
  - `TestResolveRepairRoute`: 12 tests (Task 15).
  - Extension to queue tests: 17 tests (Task 16; rendering + URL-param-based filter behavior + dropdown-selected state + unknown-value dropdown edge case + empty-queue data-attribute guard).
  - `TestDetailQuickActions`: 7 tests (Task 17).
  - **Total: 49 view tests.**
- **Slack tests** (`tests/test_slack/test_handlers.py`):
  - **No test changes required.** The existing three resolve-with-note tests at lines 1315-1376 verify outcomes via DB state + `ack` inspection, not by mocking service functions. Since `resolve_repair_record` produces identical DB state to the prior `update_repair_record(status='Resolved', note=...)` call, all three pass unchanged after the Task-18 convergence. Task 19 is a verification-only task (re-run the existing tests).
  - **Total: 0 new tests; 3 existing tests re-validated.**
- **Grand total: 67 net new tests** (18 service + 49 view) + 3 existing Slack tests re-validated.
- **Test-author note on `url_for` in test bodies.** Several test stubs construct expected URLs via `url_for(...)` outside the `client.get(...)` request context — that call would raise `RuntimeError: Working outside of request context`. Test authors should either (a) call `url_for` inside `with app.test_request_context():`, (b) use `app.url_map.bind('localhost').build('repairs.claim', {'id': record.id})` for context-free building, or (c) hardcode the path string (`f'/repairs/{record.id}/claim'`). The Flask `client` fixture pushes a request context only DURING the `client.get/post` call and tears it down before the next statement — so `url_for` called between assertions and HTTP calls needs explicit context wrapping.
- **No e2e tests added.** The existing e2e suite is minimal. Per-route unit tests + manual browser plan below cover correctness.

**Manual browser test plan (after all code changes):**
1. Start the stack: `make db-up && make migrate && make run` (and `make worker` in a second terminal if you want to see the resolved notification get processed).
2. Log in as a technician.
3. Navigate to `/repairs/queue`. Confirm the new Assignee filter dropdown appears.
4. Create or find a `New` repair. Confirm the row has a Claim button. Click it. Confirm: redirect back to queue with green flash; the row now shows `Assigned`, assignee=you, no Claim button, Resolve button visible.
5. Click Resolve. Confirm modal opens with title "Resolve Repair #<id>". Type a note, click Resolve. Confirm: redirect back to queue, success flash, record disappears from open-queue (now `Resolved`); a Slack notification is queued.
6. Open the Resolve modal on another record, type "test", close (X / Cancel), reopen for a different record. Confirm the textarea is empty (Task 8c reset).
7. Set Assignee filter to "Mine", "Unassigned", "All" — confirm filtered view in real-time, no reload, area + status filters compose.
8. Switch to mobile viewport (<768px). Repeat steps 4-7 on mobile cards. Confirm clicking on the card body (not the buttons) navigates to detail.
9. Open-redirect probe: append `?next=//evil.example.com/` and `?next=http%3A//evil.example.com/` (URL-encoded) to a queue URL or any path. Submit a Claim. Confirm redirect goes to `/repairs/<id>` (detail page fallback), not external.
10. Try a `member`-role user (create one if needed). Confirm they cannot access `/repairs/queue` at all (the nav doesn't even render the link); attempting POST to `/repairs/<id>/claim` directly returns 403.
11. Confirm the Edit button still works for ALL statuses including `Resolved` (regression — should be unchanged).
12. Test non-ASCII: resolve a record with `note='Fixed! 🔧 Тест съел проблема'`. Refresh the timeline view. Confirm exact characters rendered.

### Notes

- **Slack convergence is in scope.** The Slack `resolve_with_note` handler shares the new `resolve_repair_record` service helper, so closed-record / empty-note / unknown-user invariants all live in one place.

- **ID-existence vs CSRF check ordering (acknowledged pre-existing).** Both the `claim` and `resolve` routes call `repair_service.get_repair_record(id)` BEFORE `form.validate_on_submit()` — meaning a CSRF-less POST returns 404 for nonexistent IDs and a redirect-with-generic-flash for existent ones. An authenticated technician with a missing/stale CSRF token (e.g., third-party tooling, session-fixation probe) can enumerate which repair IDs exist via the HTTP-status differential. The existing `edit` route at `esb/views/repairs.py:229` has the same shape — this is pre-existing behavior, not a new exposure. Reordering would force a 302+flash response for legitimate missing-ID requests (worse UX). Acceptable for this makerspace; consider a defense-in-depth pass in a separate ticket if the threat model evolves.

- **Modal Esc-key destroys typed note (acknowledged trade-off).** Bootstrap 5 modals default to `data-bs-keyboard="true"`, dismissing on Esc. A technician who has typed a long note and accidentally hits Esc loses the note silently. The clear-on-show handler ensures the next open starts blank. Trade-off: stay on Bootstrap's default modal behavior (consistent with rest of codebase + user expectations) vs. preserve typed text across accidental dismissal (custom keyboard handler + dirty-tracking complexity). We accept the loss for this iteration; the same loss occurs on session expiry per the next bullet.

- **Per-row tab order increases ~3x.** Each queue row carries `tabindex="0"` plus, when applicable, a Claim form and a Resolve trigger button — three tab stops per row instead of one. For a queue of N records, tab cycles through up to 3N stops before reaching site nav. No mitigation in scope (roving tabindex, `tabindex="-1"` on rows with action buttons present, or relocating buttons to the detail page only) — all would degrade either keyboard nav-ergonomics or feature parity with the issue's "one-button" requirement. Mobile cards have the same property. Future a11y pass could revisit.

- **Slack error-attribution caveat (acknowledged pre-existing behavior).** Service-layer `ValidationError`s from `resolve_repair_record` (closed-record race, unknown-user, defensive empty-note) propagate up the Slack handler's `except ValidationError as e: ack(response_action='errors', errors={'action_block': str(e)})` block at `handlers.py:626-628`, which hard-codes attribution to `action_block` rather than the more specific `note_block`. The Slack-side pre-validation at `handlers.py:599-603` handles the empty-note case with the correct attribution (`note_block`) BEFORE the service call. For the other error paths (closed-record race, unknown-user), the user sees the error on the action block — pre-convergence behavior, unchanged by this spec. Refining attribution per-error-type is a follow-up.

- **The `New` → no-Resolve UI rule** is a convention to nudge technicians toward triage. The service does not enforce it. Both web (template `{% if %}`) and Slack (dispatcher action options) layer this restriction independently. If feedback demands one-click close of `New` records (e.g., obvious-duplicate triage), the template guard is the only place to relax.

- **Open-redirect protection.** Replaced the regex-based `_safe_next_url` with an explicit two-element allowlist. This eliminates:
  - Backslash bypass (`/\evil.com/path`),
  - Protocol-relative (`//evil.com/`),
  - Scheme-injection (`http://evil.com/`, `javascript:`, `data:`),
  - Cross-record next-leak (`/repairs/<other_id>` won't be honored from `/repairs/<this_id>`),
  - URL-encoded variants (no path-string parsing means encodings can't bypass).

- **CSP-friendly JavaScript.** All event handlers in `esb/static/js/app.js` or scoped `<script>` blocks. No `onclick`, `onchange`, or other inline JS attributes. This means a future deploy adding `Content-Security-Policy: script-src 'self'` would not break the app.

- **Form CSRF inputs use raw `<input>`, not `form.hidden_tag()`.** This avoids the duplicate `id="csrf_token"` collision that would otherwise affect the queue page (N+1 forms — one per Claim button per row, plus one modal). Existing detail-page forms (`note_form`, `photo_form`) have the same latent issue today; the new spec uses the raw-input pattern to avoid amplifying it without retrofitting the existing forms (the latent collision is pre-existing and out of scope).

- **Modal note hygiene.** The `show.bs.modal` handler clears the textarea on every open — protects against a technician typing a note for one repair, dismissing the modal, then accidentally submitting that text for a different repair.

- **Concurrent claim race.** Two technicians simultaneously claiming the same `New` record produces: (a) last-write-wins on `assignee_id` (acceptable), (b) one `status_changed` notification (from the first claim's `New`→`Assigned` transition; the second claim hits the no-op guard for status), (c) one extra `assignee_change` timeline entry for the second claim. No notification storm. Test T13 pins down the no-op guard behavior so a future refactor cannot regress it.

- **CLOSED_STATUSES single source of truth.** Templates reference the Jinja global (registered in Task 1) rather than hard-coding the list. If `CLOSED_STATUSES` grows in the future (e.g., a new `'Closed - Won't Fix'` value), templates automatically pick up the change AND the parameterized test T17.5 verifies the visibility-hiding works for every value in the list.

- **Charset / i18n.** Task 20 verifies the production `repair_timeline_entries.content` column uses `utf8mb4`. SQLite (test DB) handles full Unicode natively, so service/view tests pass regardless. Production-side, if the column is `utf8mb3`, emoji-laden notes silently truncate or raise `Incorrect string value`. This is a pre-existing exposure (also affects `add_repair_note` and `description` columns) that the new forced-note resolve flow exercises more often.

- **`maxlength` vs `Length` mismatch (acknowledged).** The modal textarea's HTML `maxlength="5000"` (Task 9) counts UTF-16 code units, while WTForms `Length(max=5000)` counts Python characters (code points). For ASCII-only input these match; for emoji or supplementary-plane characters (each is 2 UTF-16 units, 1 Python char), the browser truncates ~2x earlier than the server validator. A tech pasting 4000 emoji would see ~2500 in the textarea. This is consistent with how the rest of the codebase's `TextAreaField` + `maxlength` pairs behave; no fix here.

- **Session-expiry note loss (acknowledged).** If a tech opens the modal, types a long note, then their session times out before submit (`PERMANENT_SESSION_LIFETIME = 12 hours`), CSRF validation fails on POST, the route flashes a generic "Invalid resolve request" message and `_safe_next_url` redirects to detail. The clear-on-show modal hygiene means a fresh modal opens with no recovery of the typed note. This is acceptable given the long session window and the alternative (cross-login note preservation) introduces a separate security-of-storage problem. Documented so future UX tickets don't fix it without weighing the trade-off.

- **Claim user-validation pathway (clarification).** `claim_repair_record` does NOT add its own user-existence check, but it IS covered: `update_repair_record` validates the `assignee_id` change (`repair_service.py:409-412`), and claim passes the same user id as `assignee_id`. The user-existence check runs BEFORE the per-field no-op guard, so even a self-reclaim (where `assignee_id` is unchanged) still validates the user. `resolve_repair_record` adds its own check because it passes the user id ONLY as `author_id` (which `update_repair_record` does NOT validate symmetrically). Backfilling `update_repair_record` to also validate `author_id` is out of scope.

- **URL parameters DO drive initial filtering.** The Assignee filter mirrors the hybrid pattern of the existing Area and Status filters: `?assignee=me|unassigned` URL params drive initial server-side filtering on page load AND the dropdown's `change` event applies client-side display toggling for in-session refinement (without URL update). A bookmarkable/shareable filtered URL is supported by typing the URL directly. (Round-1 wording erroneously claimed "no URL parameters" — that was a misreading of the existing Area/Status pattern, which DOES use URL params.)

- **Future scope.**
  - Kanban cards (staff-only) could carry the same quick actions; the service helpers + modal partial built here are reusable.
  - Backfill the user-exists validation in `claim_repair_record` for symmetry.
  - Migrate the pre-existing detail-page `note_form` / `photo_form` to use raw CSRF inputs.
  - If the charset verification finds `utf8mb3`, issue a follow-up migration.

## Review Notes

- Adversarial review completed (post-implementation, round 5).
- Findings: 18 total, 18 addressed, 0 skipped (F9 and F17 were noted as spec-intentional and left as-is; all other findings produced fixes).
- Resolution approach: auto-fix.
- Implementation deviation: `RepairResolveForm.note` uses `InputRequired()` instead of the spec's `DataRequired()`. Rationale documented in the form's docstring — `DataRequired` strips whitespace and rejects at the form layer, splitting empty-note rejection across two layers with two messages. `InputRequired` lets whitespace-only POSTs flow through to `resolve_repair_record`, where the canonical "Resolution note is required" message originates. Spec test T15.4 expects exactly this routing; the deviation aligns implementation with the spec's stated test behavior.
- Test status: 1381 passing (1314 baseline + 67 net new). `make lint` clean.
- Task 20 (production schema charset verification) is a manual DB inspection that cannot be performed from the dev container; flagged as a follow-up for the implementer.
