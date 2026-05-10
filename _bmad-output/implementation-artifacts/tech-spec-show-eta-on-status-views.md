---
title: 'Show ETA on status, kanban, kiosk, and queue views'
slug: 'show-eta-on-status-views'
created: '2026-05-10'
status: 'completed'
stepsCompleted: [1, 2, 3, 4, 5, 6]
revision: 'r4-post-third-adversarial'
tech_stack:
  - Python 3.14
  - Flask + Jinja2
  - Flask-SQLAlchemy (MariaDB in prod, SQLite in tests)
  - Bootstrap 5 (CDN) + custom CSS in esb/static/css/app.css
  - Vanilla JS (esb/static/js/app.js)
files_to_modify:
  - esb/utils/filters.py
  - esb/services/status_service.py
  - esb/services/repair_service.py
  - esb/views/public.py
  - esb/templates/public/status_dashboard.html
  - esb/templates/public/kiosk.html
  - esb/templates/public/static_page.html
  - esb/templates/public/equipment_page.html
  - esb/templates/repairs/kanban.html
  - esb/templates/repairs/queue.html
  - esb/templates/repairs/detail.html
  - esb/templates/equipment/detail.html
  - esb/templates/components/_timeline_entry.html
  - tests/test_utils/test_filters.py
  - tests/test_services/test_status_service.py
  - tests/test_services/test_static_page_service.py
  - tests/test_services/test_repair_service.py
  - tests/test_views/test_public_views.py
  - tests/test_views/test_repair_views.py
  - tests/test_views/test_equipment_views.py
code_patterns:
  - service-layer-only-business-logic
  - single-source-of-truth-status-derivation
  - highest-severity-record-selection-with-deterministic-tie-break
  - jinja-format_date-filter-accepting-date-or-iso-string
  - notification-queue-on-eta-only-changes
  - region-scoped-html-test-assertions
test_patterns:
  - pytest-class-grouping
  - factory-fixtures-make_equipment-make_area-make_repair_record
  - sqlite-in-memory-test-db
  - tech_client-staff_client-fixtures-for-rbac-views
  - flask-test-client-with-strftime-computed-expected-strings
  - pending-notification-direct-query-for-trigger-tests
github_issue: 36
---

# Tech-Spec: Show ETA on status, kanban, kiosk, and queue views

**Created:** 2026-05-10
**Revised:** 2026-05-10 r2 (addresses 15 r1 findings F1-F14, F17), r3 (addresses 16 r2 findings F18-F33), r4 (addresses 15 r3 findings F34-F48)
**GitHub Issue:** [#36](https://github.com/jantman/equipment-status-board/issues/36) — Show ETA on status and kanban

## Overview

### Problem Statement

`RepairRecord.eta` (a nullable `Date` column at `esb/models/repair_record.py:40`) is captured on repair records but is only surfaced on the QR equipment page (`esb/templates/public/equipment_page.html:15-17`) and on the per-record detail page (`esb/templates/repairs/detail.html:40-43` in `'%Y-%m-%d'`; `esb/templates/components/_timeline_entry.html:18` as a raw ISO string from `entry.new_value`). Users viewing the kanban board, public status dashboard, kiosk display, static status page export, repair queue, or equipment-detail repair-history table cannot see when a repair is expected to be complete without drilling into individual records. Issue #36 asks for ETA to be displayed everywhere repair records or equipment status is shown.

Three code-quality / consistency issues are also addressed by this spec because they would otherwise produce post-merge inconsistencies:

1. The QR page's ETA value is computed by `_build_equipment_page_context()` (`esb/views/public.py:57-79`) using a different algorithm than `_derive_status_from_records()` — it falls through severities to find the first non-null ETA, while the canonical helper returns only the highest-severity record's ETA. Without aligning these, the QR page and dashboards would display different ETAs for the same equipment.
2. The repair-detail page header and its eta_update timeline entries currently use different formats; without alignment, the same page would show "Mar 15, 2026" in the header and "2026-03-15" in the timeline.
3. `repair_service.update_repair_record()` only queues `static_page_push` regeneration on status/severity changes — once ETA is published on the static page, ETA-only edits must also trigger regeneration to avoid stale public data.

### Solution

Surface `RepairRecord.eta` everywhere a repair record or equipment status appears, using a single Jinja filter for consistent formatting, and align the QR page + timeline-entry rendering to use the same filter:

- **Per-record views** (kanban cards, repair queue table + mobile cards, equipment-detail repair-history table) — display each record's `eta` directly via the `format_date` filter.
- **Aggregate (per-equipment) views** (status dashboard, kiosk, static export) — extend `_derive_status_from_records()` in `esb/services/status_service.py` to also return `eta` (highest-severity record's ETA, with deterministic tie-break by `created_at`).
- **QR page alignment (resolves F19, F24)** — replace `_build_equipment_page_context()`'s in-line ETA-finding logic with `compute_equipment_status(equipment_id)['eta']`. **Behavior change documented:** the QR page now follows the same "highest-severity record's ETA" semantics as dashboards/Slack, instead of falling through severities. (Practical effect: rare scenario where the highest-severity open record has no ETA but a lower-severity one does — QR page used to show the lower-severity ETA; now it shows nothing, matching the dashboard.)
- **Timeline-entry alignment (resolves F18)** — extend the existing `format_date` filter to accept ISO-format date strings (in addition to `date` / `datetime` objects), then replace the raw `{{ entry.new_value }}` rendering in `_timeline_entry.html:18` with `{{ entry.new_value|format_date }}`. Same friendly format everywhere.
- **Notification trigger** — extend `update_repair_record()` to queue a `static_page_push` notification on ETA-only changes.
- **Centralized format**: use `record.eta|format_date` (`esb/utils/filters.py:10`, default `'%b %d, %Y'`). Filter is null-safe (`format_date(None) == ''`).

### Scope

**In Scope:**
- `esb/utils/filters.py` (new): extend `format_date()` to accept ISO date strings (e.g., `'2026-03-15'`) in addition to `date`/`datetime`. Resolves F18.
- `esb/services/status_service.py`: extend `_derive_status_from_records()` to compute and include `eta` (highest-severity record's ETA, with deterministic tie-break by `created_at` ASC); add `order_by(RepairRecord.created_at)` to `_get_open_records()` and the prefetch queries; simplify `get_equipment_status_detail()` to drop its now-duplicate ETA computation.
- `esb/services/repair_service.py`: extend `update_repair_record()` so that ETA-only changes also queue a `static_page_push` notification.
- `esb/views/public.py`: replace `_build_equipment_page_context()`'s in-line ETA loop with a call to `compute_equipment_status(equipment_id)['eta']`. Resolves F19.
- `esb/templates/public/status_dashboard.html`: display ETA on equipment cards when set.
- `esb/templates/public/kiosk.html`: display ETA on equipment cards when set.
- `esb/templates/public/static_page.html`: display ETA inline on each `<li>` when set; add `.eta-label` CSS rule.
- `esb/templates/public/equipment_page.html`: decouple ETA display from `issue_description`.
- `esb/templates/repairs/kanban.html`: display per-record ETA on each kanban card; include ETA in the card's `aria-label`.
- `esb/templates/repairs/queue.html`: add an ETA column to the desktop table (with `class="queue-eta-cell"` for test scoping) and an ETA line to mobile cards.
- `esb/templates/repairs/detail.html`: replace inline `strftime('%Y-%m-%d')` with the `format_date` filter for ETA display.
- `esb/templates/equipment/detail.html`: add an ETA column to the repair-history table.
- `esb/templates/components/_timeline_entry.html`: render ETA timeline entries via `format_date` filter.
- Test additions and updates for the affected services, filters, and templates.

**Out of Scope:**
- Changes to ETA capture forms or model schema.
- Slack bot output (already includes ETA via `get_equipment_status_detail()`; existing tests in `tests/test_slack/test_handlers.py` provide regression coverage). Resolves F30.
- New ETA-related logic (overdue highlighting, computed defaults, urgency colors).
- Sorting the queue table by ETA — the new ETA column is non-sortable in this spec; `data-eta-iso="..."` is added preparatorily so a follow-up only needs JS changes. Resolves F16.
- Date-format internationalization or per-locale formatting (see Notes for the locale assumption — F20).
- **Queue-storm deduplication for `static_page_push`:** Acknowledged out-of-scope risk. Each ETA edit during a long-running repair queues a fresh `static_page_push` row (no dedup), and the worker regenerates the entire page each time. Real-world impact: low (ETA edits are infrequent compared to status/severity changes), but worth a follow-up to add per-equipment debounce. Resolves F23.

## Context for Development

### Codebase Patterns

- **Service layer pattern (CLAUDE.md):** Views never query models directly. ETA aggregation for per-equipment views must live in `esb/services/status_service.py`, not in templates or views.
- **Single source of truth for status derivation:** `_derive_status_from_records()` (`esb/services/status_service.py:59`) is the canonical helper. Adding `eta` to its return dict means `get_area_status_dashboard()`, `get_single_area_status_dashboard()`, and `compute_equipment_status()` all gain ETA "for free" with no caller-side merging.
- **Existing per-equipment ETA pattern:** `get_equipment_status_detail()` (`esb/services/status_service.py:116-151`) already uses this approach: highest-severity open record via `_find_highest_severity_record()`, fall back to `open_records[0]` when no record matches the severity priority map, return `best_record.eta`. Move this into `_derive_status_from_records()` so it's shared.
- **Existing `format_date` filter:** `esb/utils/filters.py:10` defines `format_date(value, fmt='%b %d, %Y')` — null-safe (returns `''` for `None`), registered as the Jinja filter `format_date` at `esb/utils/filters.py:91`. Already used for `equipment.acquisition_date`, `equipment.warranty_expiration` (`esb/templates/equipment/detail.html:75,90`). Use this filter for ALL ETA display in this spec — do NOT inline `strftime` calls in templates.
- **`format_date` extension for ISO strings:** Add a small `isinstance(value, str)` branch that parses via `datetime.date.fromisoformat()` before applying the format. Maintains backward compatibility with existing `date`/`datetime` callers. Resolves F18.
- **Conditional display precedent:** Wrap ETA display in `{% if eta %}` (aggregate views) or `{% if record.eta %}` (per-record views) so no empty wrapper element is emitted, even though `format_date` itself is null-safe.
- **Aggregate dashboard shape:** `get_area_status_dashboard()` returns `[{area, equipment: [{equipment, status: {color, label, issue_description, severity}}]}]`. Add `eta` (a `date | None`) inside the inner `status` dict.
- **Queue table sort JS:** `esb/static/js/app.js:33-78` attaches click handlers only to `th[data-sort]` and reads `getRowSortValue()` via a switch on `data-sort` keys. The new ETA column is NOT sortable in this spec — omit `data-sort` on its `<th>`. Adding `data-eta-iso` on rows is preparatory; the JS won't process it until a future PR extends the switch.
- **Queue mobile cards:** `esb/templates/repairs/queue.html:81-115` shows mobile cards with a `small text-muted` line containing status badge + area + age. Add ETA after age in the same line.
- **Kanban card structure:** `esb/templates/repairs/kanban.html:7-34` macro `kanban_card(record)` already has a `small text-muted` line with the days-in-column display. Add a new ETA line in the same `small text-muted` style as a sibling of the days-in-column `<div>`. The macro's `aria-label` (line 11) currently lists name/area/severity/days — extend it to include ETA when set. Resolves F11.
- **Static page CSP constraint:** `esb/templates/public/static_page.html:6` sets `Content-Security-Policy: default-src 'none'; style-src 'unsafe-inline'` — no external CSS/JS. Add `.eta-label` styling inside the inline `<style>` block (lines 8-24).
- **Static-page regeneration trigger pattern:** `esb/services/repair_service.py:446-457` queues a `static_page_push` notification when `'status' in audit_changes or 'severity' in audit_changes`. Extend this conditional to also trigger on `'eta' in audit_changes`. Resolves F12.
- **Timeline-entry rendering pattern:** `esb/templates/components/_timeline_entry.html:18` currently renders ETA timeline entries as raw `entry.new_value` (an ISO date string). Update to `entry.new_value|format_date` once the filter accepts strings. Resolves F18.
- **`make_repair_record` factory + fixture (`tests/conftest.py:129-148`):** Helper `_create_repair_record()` accepts `eta=date(...)`, `created_at=datetime(...)`, etc. via `**kwargs` (`RepairRecord` constructor). Pytest fixture `make_repair_record` is a thin wrapper. Resolves F13.
- **`PendingNotification` direct-query test pattern:** Reference test `test_eta_change_queues_notification` (`tests/test_services/test_repair_service.py:409-430`) queries pending notifications via `db.session.execute(db.select(PendingNotification).filter_by(notification_type='slack_message')).scalars().all()` and asserts on `len(...)` + `payload[...]`. Use this same pattern for the new ETA-static-page-push test (NOT the `capture` fixture, which captures mutation log records). Resolves F21.
- **View routing for kanban/queue:** `esb/views/repairs.py:39-78` — both views pass full `RepairRecord` instances to templates, so `record.eta` is directly accessible — no view changes needed for per-record ETA display.

### Files to Reference

| File | Purpose |
| ---- | ------- |
| `esb/models/repair_record.py:40` | `eta = db.Column(db.Date, nullable=True)` — the source field. |
| `esb/utils/filters.py:10-19, 91` | `format_date` Jinja filter — extend to accept ISO strings. |
| `esb/services/status_service.py:22-34` | `_get_open_records()` — add `order_by(RepairRecord.created_at)` for deterministic tie-break (resolves F7). |
| `esb/services/status_service.py:37-56` | `_find_highest_severity_record()` — already returns highest-priority record. |
| `esb/services/status_service.py:59-94` | `_derive_status_from_records()` — extend to include `eta` in return dict. |
| `esb/services/status_service.py:116-151` | `get_equipment_status_detail()` — simplify by removing duplicate ETA block. |
| `esb/services/status_service.py:154-298` | `get_area_status_dashboard()` + `get_single_area_status_dashboard()` — add `order_by(RepairRecord.created_at)` to prefetch queries (lines ~199-210, ~276-285). |
| `esb/services/repair_service.py:446-457` | Existing `static_page_push` trigger — extend to also fire on `'eta' in audit_changes`. |
| `esb/views/public.py:57-79` | `_build_equipment_page_context()` — replace in-line ETA loop with `compute_equipment_status(id)['eta']`. Resolves F19. |
| `esb/templates/public/equipment_page.html:13-18` | QR page existing ETA block — decouple from `issue_description` conditional, switch to `format_date` filter. |
| `esb/templates/public/status_dashboard.html:46-65` | Equipment cards block — add ETA paragraph. |
| `esb/templates/public/kiosk.html:26-38` | Equipment cards block — add ETA paragraph. |
| `esb/templates/public/static_page.html:8-24, 33-39` | Inline `<style>` (add `.eta-label`) + equipment list item (add ETA span). |
| `esb/templates/repairs/kanban.html:7-34` | `kanban_card(record)` macro — add ETA line + extend `aria-label`. |
| `esb/templates/repairs/queue.html:36-115` | Desktop table (add `<th>ETA<span class="sort-indicator"></span></th>` between Status and Assignee + `<td class="queue-eta-cell" data-eta-iso="...">`) + mobile cards (append ETA to muted line). |
| `esb/templates/repairs/detail.html:40-43` | Switch from inline `strftime('%Y-%m-%d')` to `record.eta\|format_date`. |
| `esb/templates/equipment/detail.html:233-289` | Repair-history table — add `<th>ETA</th>` between Status and Assignee + `<td>` cells. |
| `esb/templates/components/_timeline_entry.html:18` | Replace raw `{{ entry.new_value }}` for ETA entries with `{{ entry.new_value\|format_date }}`. Resolves F18. |
| `esb/views/repairs.py:39-78` | Confirms `kanban` and `queue` views pass `RepairRecord` instances directly — no view changes. |
| `esb/views/public.py:21-54` | Confirms `status_dashboard`, `kiosk`, `kiosk_area` views pass dashboard output unchanged. |
| `esb/services/static_page_service.py:13-28` | `generate()` — picks up ETA from updated dict automatically. |
| `tests/conftest.py:129-148` | `_create_repair_record()` helper (129-142) + `make_repair_record` fixture (145-148). Helper accepts `eta`, `created_at`, etc. via `**kwargs`. Resolves F13. |
| `tests/test_utils/test_filters.py` | Existing filter tests — extend with ISO-string `format_date` cases. |
| `tests/test_services/test_status_service.py` | 4 test classes; extend with ETA assertions + tie-break test. |
| `tests/test_services/test_static_page_service.py:12` | `class TestGenerate` — extend with ETA-rendering tests. Resolves F4. |
| `tests/test_services/test_repair_service.py:409-430` | Reference pattern for the new ETA-static-page-push test (PendingNotification direct query). Resolves F21. |
| `tests/test_views/test_public_views.py:342-806` | Kiosk + status dashboard tests; add ETA-rendering tests. |
| `tests/test_views/test_repair_views.py:534-749` | Queue + kanban tests; add ETA-rendering tests. |
| `tests/test_views/test_equipment_views.py` | Equipment detail page tests; add repair-history-table ETA test (region-scoped per F22). |
| `tests/test_slack/test_handlers.py` | Existing Slack handler tests — provide F30 regression coverage; do not require changes for this spec. |

### Technical Decisions

1. **Single source of truth in service layer:** Add `eta` to the dict returned by `_derive_status_from_records()`. Three return paths:
   - Empty records → `eta=None`.
   - Highest-severity match → `eta=best_record.eta`.
   - Severity-fallback (severity is None or unknown) → `eta=records[0].eta`.

2. **Deterministic tie-break (resolves F7):** Add `order_by(RepairRecord.created_at)` to `_get_open_records()` and the prefetch queries in `get_area_status_dashboard()` / `get_single_area_status_dashboard()`. Tie-break rule: **"When multiple records share the highest severity, the oldest record (earliest `created_at`) wins."** Documented in the docstring of `_derive_status_from_records()`.

3. **Simplify `get_equipment_status_detail()`:** Drop the duplicate ETA block; return `{**status, 'assignee_name': assignee_name}`.

4. **No signature change to dashboard functions:** `status` dict gains an `eta` key.

5. **Use `format_date` filter, not inline `strftime`:** All ETA display in templates uses `{{ value|format_date }}`. Resolves F2 (format precedent inconsistency). Extend the filter to accept ISO date strings (`'2026-03-15'`) so timeline entries also render via the same filter (resolves F18). Net behavior:
   - `format_date(None)` → `''`
   - `format_date(date(2026, 3, 15))` → `'Mar 15, 2026'`
   - `format_date('2026-03-15')` → `'Mar 15, 2026'` (new branch)
   - Invalid string → fallback to returning the input as-is (defensive; logged at WARNING).

6. **Queue table — non-sortable ETA column with class for test scoping (resolves F6, F28, F32):**
   - **Position: between Status and Assignee** (uniform rule: ETA always immediately follows Status). Resolves F28 (parallel placement on equipment-detail per Decision 11).
   - `<th>` structure: `<th>ETA<span class="sort-indicator"></span></th>` — no leading whitespace before the span (resolves F32). Empty `sort-indicator` keeps cell width parity with sortable neighbors. No `data-sort`, `role="button"`, `class="sortable"`.
   - `<td>` structure: `<td class="queue-eta-cell" data-eta-iso="{{ record.eta.isoformat() if record.eta else '' }}">{{ record.eta|format_date }}</td>`. The class scopes test assertions; `data-eta-iso` is preparatory for future sort-by-ETA enhancement (resolves F16).
   - Mobile cards: append `{% if record.eta %}&middot; ETA: {{ record.eta|format_date }}{% endif %}` to the existing muted line.

7. **Kanban card — visible text + accessible label (resolves F11):**
   - Add `<div class="small text-muted">ETA: {{ record.eta|format_date }}</div>` (gated by `{% if record.eta %}`) as a sibling of the days-in-column `<div>` (`esb/templates/repairs/kanban.html:22-31`), inside the same `card-body`. Resolves F31.
   - Extend the macro's `aria-label` (line 11) to include `{% if record.eta %}, ETA {{ record.eta|format_date }}{% endif %}`.

8. **Static page inline styling:** Add `.eta-label { font-size: 0.8rem; color: #6c757d; margin-left: 0.25rem; }` to the inline `<style>`. In each `<li>`, append `{% if item.status.eta %}<span class="eta-label">ETA: {{ item.status.eta|format_date }}</span>{% endif %}` after the existing status-label span.

9. **Status dashboard + kiosk — display under issue_description, independent conditional:** Add `<p class="card-text text-muted small mt-1 mb-0">ETA: {{ item.status.eta|format_date }}</p>` (status_dashboard) / `<p class="card-text text-muted mt-1 mb-0">…</p>` (kiosk, no `small` class) gated on `{% if item.status.eta %}`. Independent of the existing `{% if color != 'green' and issue_description %}` block.

10. **QR page symmetry (resolves F8):** Decouple ETA from `issue_description` on `equipment_page.html`. Each is its own `{% if %}` guard. Switch to `format_date` filter.

11. **Equipment detail repair-history table (resolves F1, F28):** Add `<th>ETA</th>` **between Status and Assignee** (uniform rule: ETA always immediately follows Status — same as queue table per Decision 6). Add matching `<td>{{ record.eta|format_date }}</td>` in each row.

12. **Static-page regeneration on ETA-only change (resolves F12):** In `update_repair_record()` at lines 446-457, change `if 'status' in audit_changes or 'severity' in audit_changes:` to `if any(k in audit_changes for k in ('status', 'severity', 'eta')):`. Acknowledge queue-storm risk in Out-of-Scope (resolves F23) without fixing it here.

13. **Locale assumption (resolves F3, F20):** The `format_date` filter uses `'%b %d, %Y'`; `%b` is locale-dependent in general but in `C` / `POSIX` / `C.UTF-8` / `en_US.UTF-8` locales it produces English month abbreviations. The application's runtime locale is whatever `python:3.14-slim` provides by default (no `LANG`/`LC_TIME` env set in the project's Dockerfile) — empirically POSIX `C`, which produces English `%b`. Tests compute expected strings via `strftime` so assertions match the runtime locale of the test environment exactly, avoiding hard-coded English. Production deployments under non-English locales would see localized month names — out of scope.

14. **AC test-scoping strategy (resolves F5, F22, F33):**
    - Tests assert on the unique formatted-date string (`'%b %d, %Y'`) which does not collide with `format_datetime` (`'%Y-%m-%d %H:%M'`) or `data-eta-iso` (`'%Y-%m-%d'`).
    - For tests that need to verify the cell *itself* (presence/emptiness in a specific row), use the `class="queue-eta-cell"` marker. Use a **regex anchored to the test record's `data-href`** (which uniquely identifies the row) when verifying per-record cell content/emptiness, or assert `response.data.count(b'data-eta-iso=""') == N` for a single-record test.
    - For the equipment-detail repair-history-table test, scope the assertion to within `<table id="repair-history-table">…</table>` via regex (since `acquisition_date` and `warranty_expiration` use the same `format_date` filter on the same page). Resolves F22.

15. **HTML safety (informational; resolves F15):** All ETA template insertions rely on Jinja autoescape. `format_date` returns plain text; do not pass through `|safe`. `record.eta.isoformat()` returns ASCII `YYYY-MM-DD`.

16. **QR page algorithm migration (resolves F19, F24):** Replace the ETA-finding loop in `_build_equipment_page_context()` with `eta = compute_equipment_status(equipment_id)['eta']`. **Behavior change:** the current QR page falls through severities to find the first non-null ETA; after the change, it returns only the highest-severity record's ETA (or `None`). This aligns the QR page with the dashboard, kiosk, static-page, and Slack-bot semantics. Practical effect is small: the divergence only manifests when the highest-severity open record has no ETA but a lower-severity one does — uncommon in real data. Document in Notes and add a regression AC.

17. **Test fixture pattern for tie-break (resolves F25):** Pass `created_at=datetime(...)` directly to `make_repair_record(...)` — the helper forwards via `**kwargs` to the `RepairRecord` constructor. No need for post-create session mutation.

18. **Test fixture pattern for static-page push trigger (resolves F21):** Use `db.session.execute(db.select(PendingNotification).filter_by(notification_type='static_page_push')).scalars().all()` and assert on `len(...)` + `payload['changes']`. Mirror `test_eta_change_queues_notification` (`tests/test_services/test_repair_service.py:409-430`).

19. **F-finding annotations (resolves F29):** Each task and decision now lists which findings it resolves. F4 (`TestGenerate` class name) → Task 18; F6 (`<th>` whitespace + sortable header) → Decision 6; F7 (tie-break) → Decision 2; F13 (conftest fixture lines) → Codebase Patterns reference to `tests/conftest.py:129-148`.

## Implementation Plan

### Tasks

> Tasks are ordered: filter foundation, service layer, view-layer migration, per-record templates, aggregate templates, format alignment, then tests. Run `make lint` and `make test` after each major group.

#### Group A — Filter foundation

- [x] **Task A1: Extend `format_date` filter to accept ISO date strings.** *(resolves F18)*
  - File: `esb/utils/filters.py`
  - Action: Modify `format_date(value, fmt='%b %d, %Y')` (lines 10-19). Keep the existing `value is None → ''` and `value.strftime(fmt)` paths. Add a new branch: if `isinstance(value, str)`, attempt `datetime.date.fromisoformat(value).strftime(fmt)`; on `ValueError`, log a warning and return `value` unchanged (defensive — never crash a page render on a malformed string).
  - Imports: add `import logging` and `from datetime import date` if not already present; create a module-level `logger = logging.getLogger(__name__)`.
  - Notes: Backward compatible — existing `date`/`datetime` callers unaffected.

#### Group B — Service layer

- [x] **Task B1: Add deterministic ordering to `_get_open_records()` and dashboard prefetch queries.** *(resolves F7)*
  - File: `esb/services/status_service.py`
  - Action (a): In `_get_open_records()` (lines 22-34), add `.order_by(RepairRecord.created_at)` to the select.
  - Action (b): In `get_area_status_dashboard()` (around lines 199-210), add `.order_by(RepairRecord.created_at)` to the open-records prefetch.
  - Action (c): In `get_single_area_status_dashboard()` (around lines 276-285), add `.order_by(RepairRecord.created_at)` to the open-records prefetch.
  - Notes (resolves F44): The global ORDER BY in (b)/(c) is more work than strictly needed (we only require per-equipment ordering, which the bucket-grouping step rebuilds). It is acceptable here because (1) total open-record cardinality is small in practice, and (2) global ordering preserves per-equipment ordering after the `setdefault().append()` grouping. No N+1; same single query as before, just sorted.

- [x] **Task B2: Extend `_derive_status_from_records()` to include `eta` and document tie-break.**
  - File: `esb/services/status_service.py`
  - Action: Modify `_derive_status_from_records(records)` (lines 59-94). Add `eta` to all three return paths (empty → `None`; highest-severity → `best_record.eta`; severity-fallback → `records[0].eta`). Update docstring "Returns" to list `eta` and add: "When multiple records share the highest severity, the oldest record (earliest `created_at`) wins, deterministic via Task B1 ordering."

- [x] **Task B3: Simplify `get_equipment_status_detail()` to drop duplicate ETA computation.**
  - File: `esb/services/status_service.py`
  - Action: In `get_equipment_status_detail()` (lines 116-151), delete the `eta = None` initialization (line 137), the `eta = best_record.eta` assignment (line 143), and the `'eta': eta,` key in the return dict (line 149). Final return: `return {**status, 'assignee_name': assignee_name}`.

- [x] **Task B4: Extend `update_repair_record()` to queue static-page push on ETA-only change.** *(resolves F12)*
  - File: `esb/services/repair_service.py`
  - Action: At lines 446-457, change the conditional from `if 'status' in audit_changes or 'severity' in audit_changes:` to `if any(k in audit_changes for k in ('status', 'severity', 'eta')):`.

#### Group C — View migration

- [x] **Task C1: Migrate `_build_equipment_page_context()` to use `compute_equipment_status()`.** *(resolves F19, F24)*
  - **Depends on Task B2** — `compute_equipment_status()` only gains the `eta` key after Task B2's helper update. Implement Group B first. *(resolves F35)*
  - File: `esb/views/public.py`
  - Action: In `_build_equipment_page_context()` (lines 57-79), replace the ETA-finding loop (lines 69-78) with:
    ```python
    eta = status_service.compute_equipment_status(equipment_id)['eta']
    ```
  - Update the import at the top of the function if needed (status_service is already imported on line 59).
  - Notes: **Behavior change** — the QR page now returns the highest-severity record's ETA (or `None`) instead of falling through severities. Aligns with dashboard/Slack/static-page semantics. Regression AC covers this.
  - Notes (resolves F38): `compute_equipment_status()` performs an `Equipment` existence-check `db.session.get(Equipment, id)` even though the calling view at `esb/views/public.py:89` and the form-error path at `:157` both already verified existence via `equipment_service.get_equipment(id)`. This adds one redundant SELECT per QR-page render. Accepted: the cost is a single primary-key lookup on a small table per request, well within budget. If a future refactor wants to eliminate the duplicate query, the cleanest path is a lower-level helper that takes the already-fetched `Equipment` instance.

#### Group D — Per-record templates

- [x] **Task D1: Display ETA on kanban cards + extend `aria-label`.** *(resolves F11, F31)*
  - File: `esb/templates/repairs/kanban.html`
  - Action (a): In the macro `kanban_card(record)` (lines 7-34), after the closing `</div>` of the days-display block (line 31, which closes the `<div class="small text-muted mt-1">` opened on line 22), insert as a new sibling inside `<div class="card-body py-2 px-3">`:
    ```jinja
    {% if record.eta %}
    <div class="small text-muted">ETA: {{ record.eta|format_date }}</div>
    {% endif %}
    ```
  - Action (b): On line 11 (`aria-label="..."`), append before the closing quote: `{% if record.eta %}, ETA {{ record.eta|format_date }}{% endif %}`.
  - Notes (resolves F46): The macro is invoked from BOTH the desktop-columns layout (`kanban.html:59`) AND the mobile-accordion layout (`kanban.html:86`), so each record renders TWICE in `response.data`. Tests should use `in`/`not in` substring assertions, NOT exact `count() == 1` equality. The existing ACs (22, 23) already use the right form.

- [x] **Task D2: Add ETA column to repair queue desktop table.** *(resolves F6, F32; F47 covered by AC 38)*
  - File: `esb/templates/repairs/queue.html`
  - Action (a): In `<thead>` (lines 38-47), insert **between Status (line 44) and Assignee (line 45)**:
    ```jinja
    <th>ETA<span class="sort-indicator"></span></th>
    ```
    (No leading whitespace before the span; no `data-sort`, `role="button"`, or `class="sortable"`.)
  - Action (b): In each `<tr class="queue-row">` (lines 49-76), insert between the Status `<td>` (line 73) and the Assignee `<td>` (line 74):
    ```jinja
    <td class="queue-eta-cell" data-eta-iso="{{ record.eta.isoformat() if record.eta else '' }}">{{ record.eta|format_date }}</td>
    ```

- [x] **Task D3: Add ETA to repair queue mobile cards.**
  - File: `esb/templates/repairs/queue.html`
  - Action: In each mobile card's muted info line (lines 106-110), append after the relative-time span:
    ```jinja
    {% if record.eta %}
    &middot; ETA: {{ record.eta|format_date }}
    {% endif %}
    ```

- [x] **Task D4: Add ETA column to equipment-detail repair-history table.** *(resolves F1, F28)*
  - File: `esb/templates/equipment/detail.html`
  - Action (a): In `<thead>` (lines 243-249), insert `<th>ETA</th>` **between Status (line 246) and Assignee (line 247)** (uniform rule: ETA immediately follows Status, parallel to Task D2).
  - Action (b): In each row (lines 252-281), insert between the Status `<td>` (lines 270-278) and the Assignee `<td>` (line 279):
    ```jinja
    <td>{{ record.eta|format_date }}</td>
    ```

#### Group E — Format alignment

- [x] **Task E1: Convert `repairs/detail.html` ETA format to `format_date` filter.** *(resolves F2)*
  - File: `esb/templates/repairs/detail.html`
  - Action: Replace line 42 (`<dd class="col-sm-9">{{ record.eta.strftime('%Y-%m-%d') }}</dd>`) with:
    ```jinja
    <dd class="col-sm-9">{{ record.eta|format_date }}</dd>
    ```

- [x] **Task E2: Update `_timeline_entry.html` ETA timeline entries to use `format_date`.** *(resolves F18)*
  - File: `esb/templates/components/_timeline_entry.html`
  - Action: At line 18, replace:
    ```jinja
    <strong>ETA {% if entry.new_value %}set to {{ entry.new_value }}{% else %}removed{% endif %}</strong>
    ```
    with:
    ```jinja
    <strong>ETA {% if entry.new_value %}set to {{ entry.new_value|format_date }}{% else %}removed{% endif %}</strong>
    ```
  - Notes: Depends on Task A1 (the filter must accept ISO strings before this template change is safe).

#### Group F — Aggregate templates

- [x] **Task F1: Display ETA on the public status dashboard equipment cards.**
  - File: `esb/templates/public/status_dashboard.html`
  - Action: After the existing `{% if item.status.color != 'green' and item.status.issue_description %}` paragraph (lines 57-59), add an independent block:
    ```jinja
    {% if item.status.eta %}
    <p class="card-text text-muted small mt-1 mb-0">ETA: {{ item.status.eta|format_date }}</p>
    {% endif %}
    ```

- [x] **Task F2: Display ETA on kiosk equipment cards.**
  - File: `esb/templates/public/kiosk.html`
  - Action: After the existing `{% if item.status.color != 'green' and item.status.issue_description %}` paragraph (lines 34-36), add an independent block:
    ```jinja
    {% if item.status.eta %}
    <p class="card-text text-muted mt-1 mb-0">ETA: {{ item.status.eta|format_date }}</p>
    {% endif %}
    ```

- [x] **Task F3: Display ETA on the static status page export.**
  - File: `esb/templates/public/static_page.html`
  - Action (a): Inside the inline `<style>` block (lines 8-24), add:
    ```css
    .eta-label { font-size: 0.8rem; color: #6c757d; margin-left: 0.25rem; }
    ```
  - Action (b): Inside each equipment `<li>` (lines 34-38), after the existing `<span class="status-label">…</span>`, add:
    ```jinja
    {% if item.status.eta %}<span class="eta-label">ETA: {{ item.status.eta|format_date }}</span>{% endif %}
    ```

- [x] **Task F4: Decouple QR equipment-page ETA display from `issue_description` and switch to `format_date` filter.** *(resolves F8)*
  - File: `esb/templates/public/equipment_page.html`
  - Action: Replace the existing nested block (lines 13-18) with two independent conditionals:
    ```jinja
    {% if status.color != 'green' and status.issue_description %}
    <p class="mt-3 fs-5">{{ status.issue_description }}</p>
    {% endif %}
    {% if eta %}
    <p class="text-muted">ETA: {{ eta|format_date }}</p>
    {% endif %}
    ```

#### Group G — Tests

- [x] **Task G1: Test the extended `format_date` filter + locale guard.** *(resolves F18, F40)*
  - File: `tests/test_utils/test_filters.py`
  - Action: Add tests:
    - `test_format_date_accepts_date_object`: existing behavior — `format_date(date(2026, 3, 15)) == 'Mar 15, 2026'`.
    - `test_format_date_accepts_iso_string`: `format_date('2026-03-15') == 'Mar 15, 2026'`.
    - `test_format_date_returns_empty_for_none`: `format_date(None) == ''`.
    - `test_format_date_returns_input_for_invalid_string`: `format_date('not-a-date') == 'not-a-date'` (defensive — never crash).
    - `test_runtime_locale_produces_english_month_abbreviations`: Sanity guard for the F20 locale assumption — assert `date(2026, 1, 1).strftime('%b') == 'Jan'` AND `date(2026, 6, 15).strftime('%b') == 'Jun'`. If a future deployment change pins `LANG`/`LC_TIME` to a non-English locale, this test fails fast (clear root-cause signal) instead of leaking a mysterious cascade of view-test failures.
  - If the test file does not yet exist, create it with the standard pytest header.

- [x] **Task G2: Update `_derive_status_from_records()` tests.** *(resolves F4, F25)*
  - File: `tests/test_services/test_status_service.py`
  - Action: Add `assert result['eta'] is None` to existing green/empty tests. Add new tests:
    - `test_eta_returned_with_down_severity`: Down record with `eta=date(2026, 6, 1)` → `result['eta'] == date(2026, 6, 1)`.
    - `test_eta_from_highest_severity_record`: Down `eta=date(2026, 5, 1)`, Degraded `eta=date(2026, 7, 1)` → `result['eta'] == date(2026, 5, 1)`.
    - `test_eta_none_when_record_has_no_eta`: Down record with no `eta` → `result['eta'] is None`.
    - `test_eta_fallback_when_no_severity_match`: severity=None, eta set → returned.
    - `test_eta_tie_break_oldest_wins`: Two Down records, pass `created_at=datetime(2026, 1, 1)` (older with `eta=date(2026, 5, 1)`) and `created_at=datetime(2026, 2, 1)` (newer with `eta=date(2026, 8, 1)`) → `result['eta'] == date(2026, 5, 1)`. **Pass `created_at` directly as a `make_repair_record` kwarg** (forwards to the `RepairRecord` constructor).

- [x] **Task G3: Add `eta` assertions to existing dashboard tests + new green-state tests.**
  - File: `tests/test_services/test_status_service.py`
  - Action: In `TestGetAreaStatusDashboard.test_returns_areas_with_equipment_and_statuses` and `TestGetSingleAreaStatusDashboard.test_returns_area_with_equipment_and_statuses`, pass `eta=date(2026, 6, 15)` and assert `status['eta']`. Add:
    - `TestGetAreaStatusDashboard.test_eta_none_when_no_open_records`
    - `TestGetSingleAreaStatusDashboard.test_eta_present_for_degraded_equipment`

- [x] **Task G4: Add `get_equipment_status_detail()` exact-key-set tests for both seeded and operational cases.** *(resolves F17, F36)*
  - File: `tests/test_services/test_status_service.py`
  - Action: In `TestGetEquipmentStatusDetail`, add TWO tests so AC 11's "any non-error call" contract is fully exercised:
    ```python
    def test_returns_exact_key_set_with_open_record(self, app, make_equipment, make_repair_record):
        from datetime import date
        eq = make_equipment()
        make_repair_record(equipment=eq, status='New', severity='Down', description='x', eta=date(2026, 6, 15))
        result = status_service.get_equipment_status_detail(eq.id)
        assert set(result.keys()) == {
            'color', 'label', 'issue_description', 'severity', 'eta', 'assignee_name',
        }

    def test_returns_exact_key_set_when_operational(self, app, make_equipment):
        # Equipment with no open records — exercises the green/empty-records path.
        eq = make_equipment()
        result = status_service.get_equipment_status_detail(eq.id)
        assert set(result.keys()) == {
            'color', 'label', 'issue_description', 'severity', 'eta', 'assignee_name',
        }
    ```

- [x] **Task G5: Add static-page-push-on-ETA-change test using PendingNotification direct query.** *(resolves F21)*
  - File: `tests/test_services/test_repair_service.py`
  - Action: Mirror the existing `test_eta_change_queues_notification` (line 409) but assert on `static_page_push` notifications:
    ```python
    def test_eta_change_queues_static_page_push(self, app, make_area, make_equipment, staff_user):
        from datetime import date
        from esb.models.pending_notification import PendingNotification
        area = make_area(name='Woodshop')
        equip = make_equipment(name='SawStop', area=area)
        record = RepairRecord(equipment_id=equip.id, description='Test')
        _db.session.add(record)
        _db.session.commit()

        repair_service.update_repair_record(
            record.id, 'staffuser', author_id=staff_user.id, eta=date(2026, 3, 15),
        )

        notifications = _db.session.execute(
            _db.select(PendingNotification).filter_by(notification_type='static_page_push')
        ).scalars().all()
        assert len(notifications) == 1
        assert 'eta' in notifications[0].payload['changes']
    ```
  - Notes (resolves F37): Tightened to `len(notifications) == 1`. The `static_page_push` trigger is independent of `slack_channel` config (slack-message queueing is a separate code path checked at `repair_service.py:472-485`); not configuring `slack_channel` on the area means no `slack_message` is queued, but `static_page_push` still fires from the line 446-457 trigger.
  - Use the imports/style from `tests/test_services/test_repair_service.py`. Do NOT use the `capture` fixture (it captures mutation_logger records, not pending notifications).

- [x] **Task G6: Add static-page ETA-rendering tests in `TestGenerate`.** *(resolves F4)*
  - File: `tests/test_services/test_static_page_service.py` (note class is `TestGenerate`, not `Generate`)
  - Action: Add to `class TestGenerate` (line 12):
    ```python
    def test_generate_includes_eta_when_set(self, app, make_area, make_equipment, make_repair_record):
        from datetime import date
        area = make_area(name='Lab')
        eq = make_equipment(name='Microscope', area=area)
        make_repair_record(equipment=eq, status='New', severity='Down',
                           description='Broken', eta=date(2026, 6, 15))
        html = static_page_service.generate()
        expected = 'ETA: ' + date(2026, 6, 15).strftime('%b %d, %Y')
        assert expected in html
        assert 'eta-label' in html

    def test_generate_omits_eta_when_unset(self, app, make_area, make_equipment, make_repair_record):
        area = make_area(name='Lab')
        eq = make_equipment(name='Microscope', area=area)
        make_repair_record(equipment=eq, status='New', severity='Down', description='Broken')
        html = static_page_service.generate()
        assert 'ETA:' not in html
    ```

- [x] **Task G7: Add status dashboard + kiosk ETA-rendering tests including past/today/far-future.** *(resolves F9, F43)*
  - File: `tests/test_views/test_public_views.py`
  - Action: Add tests in the relevant existing test classes:
    - `test_status_dashboard_displays_eta_when_set` (eta = `date(2026, 7, 4)`).
    - `test_status_dashboard_omits_eta_when_unset`.
    - `test_kiosk_displays_eta_when_set`.
    - `test_kiosk_omits_eta_when_unset`.
    - `test_per_area_kiosk_displays_eta_when_set`.
    - `test_status_dashboard_displays_past_eta` (eta = `date(2025, 1, 1)`).
    - `test_status_dashboard_displays_eta_today` — **capture `today = date.today()` once at the top of the test**, pass `today` to the fixture AND use `today.strftime('%b %d, %Y')` in the assertion. This makes the test deterministic across midnight UTC during long CI runs (resolves F43).
    - `test_status_dashboard_displays_far_future_eta` (eta = `date(2030, 12, 31)`).
  - Compute expected via `('ETA: ' + date(...).strftime('%b %d, %Y')).encode()`.

- [x] **Task G8: Add kanban + queue ETA-rendering tests with row-scoped assertions.** *(resolves F14, F33)*
  - File: `tests/test_views/test_repair_views.py`
  - Action: Add tests:
    - `test_queue_displays_eta_column_header`: assert `b'queue-eta-cell' in response.data`.
    - `test_queue_displays_eta_value`: record with `eta=date(2026, 6, 15)` → assert `('queue-eta-cell" data-eta-iso="2026-06-15">' + date(2026, 6, 15).strftime('%b %d, %Y') + '<').encode() in response.data`.
    - `test_queue_eta_cell_blank_when_no_eta`: single record without eta → assert `response.data.count(b'data-eta-iso=""') == 1` (scoped to the one row under test).
    - `test_queue_mobile_card_displays_eta`.
    - `test_kanban_card_displays_eta_when_set`: assert formatted ETA in response AND in `aria-label` (assert `b', ETA ' + date(...).strftime('%b %d, %Y').encode() in response.data`).
    - `test_kanban_card_omits_eta_when_unset`: record without eta → assert `b'ETA:' not in response.data` AND no empty `<div class="small text-muted">ETA:` element.

- [x] **Task G9: Add equipment-detail repair-history-table ETA test with region-scoped assertion.** *(resolves F22)*
  - File: `tests/test_views/test_equipment_views.py`
  - Action: Load the equipment detail page, create a repair record with `eta=date(2026, 6, 15)`, and assert via `re.search(rb'<table[^>]*id="repair-history-table"[\s\S]*?Jun 15, 2026[\s\S]*?</table>', response.data)`. Add a complementary "no ETA" test asserting empty cell within the same scoped region.

- [x] **Task G10: Add timeline-entry ETA-format test.** *(resolves F18)*
  - File: `tests/test_views/test_repair_views.py` (or wherever timeline rendering is currently tested — search for `entry_type == 'eta_update'` test coverage; if none exists, add to the repair detail test class)
  - Action: Create a repair record, update its eta (which inserts an `eta_update` timeline entry), GET `/repairs/<id>`, and assert the response contains the `format_date`-formatted date (e.g., `b'set to Mar 15, 2026'`) and does NOT contain `b'set to 2026-03-15'`.

- [x] **Task G11: Update existing tests broken by format change AND column-position shifts.** *(resolves F48)*
  - File: across `tests/`
  - Action: After Tasks E1, E2, D2, and D4, run `make test` and update tests broken by these changes. Two specific failure sites to anticipate:
    1. **Format change (E1, E2):** Tests in `tests/test_views/test_repair_views.py` that load `/repairs/<id>` and assert on date text near "ETA" — convert from old `'%Y-%m-%d'` literal to the `format_date` output.
    2. **Column-position shifts (D2, D4):** Tests in `tests/test_views/test_repair_views.py` (queue) and `tests/test_views/test_equipment_views.py` (equipment-detail repair-history table) that assert on cell *position* in `<thead>` or row markup. Adding the new ETA column shifts subsequent columns; any test asserting on raw column-index, full `<thead>` HTML, or `<tr>` cell-count needs updating.
  - Treat this task as a search-and-update sweep: the actual list of affected tests is best identified by running `make test` after the template tasks land.

- [x] **Task G12: Add QR-page ETA regression test (post-migration), covering both GET and POST-error paths.** *(resolves F19, F39)*
  - File: `tests/test_views/test_public_views.py`
  - Action (a): Create an equipment item with two open repair records: a Down record with `eta=None` and a Degraded record with `eta=date(2026, 6, 15)`. GET `/public/equipment/<id>`. Assert the response does NOT contain `'Jun 15, 2026'` (post-migration: highest-severity record's ETA wins; Down's eta is None). Add a complementary test where the Down record HAS an ETA and confirm it's displayed.
  - Action (b) (resolves F39): `_build_equipment_page_context()` is invoked from BOTH the GET handler (`public.py:96`) AND the form-error path of `report_problem()` (`public.py:157`). The GET test in (a) exercises the shared helper, so the POST-error path inherits the same behavior — no separate test required. Document this explicitly in the test docstring: *"This test exercises `_build_equipment_page_context`, which is also called from `report_problem()` on form-validation failure; both paths share the migrated ETA computation."*

- [ ] **Task G13: Manual smoke test — kiosk auto-scale.** *(resolves F10)* — *Deferred: requires interactive browser session; not executed by AI agent.*
  - Action (manual): Start the app, populate one area with 8-12 items (several with ETAs set), visit `/public/kiosk/<area_id>` in 1920×1080 and 1366×768 viewports. Confirm legibility unchanged from baseline.

- [x] **Task G14: Run linter + full test suite.**
  - Action: `make lint && make test`.

### Acceptance Criteria

#### Filter

- [x] **AC 1:** Given `format_date(date(2026, 3, 15))`, then result is `'Mar 15, 2026'`.
- [x] **AC 2:** Given `format_date('2026-03-15')`, then result is `'Mar 15, 2026'`.
- [x] **AC 3:** Given `format_date(None)`, then result is `''`.
- [x] **AC 4:** Given `format_date('not-a-date')`, then result is `'not-a-date'` (defensive fallback; no exception).

#### Service Layer

- [x] **AC 5:** Given empty records, when `_derive_status_from_records([])` is called, then result has `eta=None`.
- [x] **AC 6:** Given a single Down-severity open record with `eta=date(2026, 6, 1)`, when `compute_equipment_status(equipment_id)` is called, then `result['eta'] == date(2026, 6, 1)`.
- [x] **AC 7:** Given two open records (Down `eta=date(2026, 5, 1)`, Degraded `eta=date(2026, 7, 1)`), when `compute_equipment_status(equipment_id)` is called, then `result['eta'] == date(2026, 5, 1)`.
- [x] **AC 8:** Given one open record with `severity=None, eta=date(2026, 8, 1)`, when `compute_equipment_status(equipment_id)` is called, then `result['eta'] == date(2026, 8, 1)`.
- [x] **AC 9:** Given a Down-severity record with `eta=None`, when `compute_equipment_status(equipment_id)` is called, then `result['eta'] is None`.
- [x] **AC 10:** Given two Down-severity records — older (`created_at=datetime(2026, 1, 1)`, `eta=date(2026, 5, 1)`) and newer (`created_at=datetime(2026, 2, 1)`, `eta=date(2026, 8, 1)`) — when `compute_equipment_status(equipment_id)` is called, then `result['eta'] == date(2026, 5, 1)` (oldest-wins).
- [x] **AC 11:** Given any non-error call to `get_equipment_status_detail(equipment_id)`, the returned dict's keys equal exactly `{color, label, issue_description, severity, eta, assignee_name}`.

#### Notification Trigger

- [x] **AC 12:** Given an existing repair record, when `update_repair_record()` is called with only an `eta` change, then querying `PendingNotification` for `notification_type='static_page_push'` returns ≥1 row whose `payload['changes']` includes `'eta'`.

#### Aggregate (per-equipment) Views

- [x] **AC 13:** Given equipment with an open repair record having `eta=date(2026, 6, 15)`, when GET `/public/` is loaded, then response.data contains `('ETA: ' + date(2026, 6, 15).strftime('%b %d, %Y')).encode()`.
- [x] **AC 14:** Given equipment with an open repair record having no `eta`, when GET `/public/` is loaded, then response.data does NOT contain `b'ETA:'`.
- [x] **AC 15:** Given equipment with an open repair record having eta set, when GET `/public/kiosk` is loaded, then the formatted ETA appears in response.data.
- [x] **AC 16:** Given equipment with an open repair record having eta set, when GET `/public/kiosk/<area_id>` is loaded for the matching area, then the formatted ETA appears in response.data.
- [x] **AC 17:** Given equipment with a Down record having `eta=date(2026, 6, 15)`, when `static_page_service.generate()` is called, then the rendered HTML contains `('ETA: ' + date(2026, 6, 15).strftime('%b %d, %Y'))` AND `'eta-label'`.
- [x] **AC 18:** Given equipment with a Down record having no `eta`, when `static_page_service.generate()` is called, then the rendered HTML does NOT contain `'ETA:'`.
- [x] **AC 19:** Given equipment with eta set to a past date (`date(2025, 1, 1)`), when GET `/public/` is loaded, then the formatted past date appears in response.data without exception.
- [x] **AC 20:** Given equipment with `eta=date.today()`, when GET `/public/` is loaded, then today's formatted date appears in response.data.
- [x] **AC 21:** Given equipment with eta set to a far-future date (`date(2030, 12, 31)`), when GET `/public/` is loaded, then the formatted far-future date appears in response.data.

#### Per-record Views

- [x] **AC 22:** Given an open repair record with `eta=date(2026, 6, 15)`, when GET `/repairs/kanban` is loaded, then response.data contains `('ETA: ' + date(2026, 6, 15).strftime('%b %d, %Y')).encode()` AND the kanban card's `aria-label` contains `(', ETA ' + date(2026, 6, 15).strftime('%b %d, %Y')).encode()`.
- [x] **AC 23:** Given an open repair record with no `eta`, when GET `/repairs/kanban` is loaded, then response.data does NOT contain `b'ETA:'` AND no empty `<div class="small text-muted">ETA:` element exists.
- [x] **AC 24:** Given GET `/repairs/queue`, response.data contains `b'queue-eta-cell'`.
- [x] **AC 25:** Given an open repair record with `eta=date(2026, 6, 15)`, when GET `/repairs/queue` is loaded, then response.data contains `('queue-eta-cell" data-eta-iso="2026-06-15">' + date(2026, 6, 15).strftime('%b %d, %Y') + '<').encode()`.
- [x] **AC 26:** Given a queue page rendered with exactly one record having no `eta` AND a non-None `severity` (e.g., `severity='Down'` so the row's severity badge does not emit literal "None"), when GET `/repairs/queue` is loaded, then a row-scoped regex match `re.search(rb'class="queue-eta-cell"[^>]*data-eta-iso=""[^>]*>\s*</td>', response.data)` succeeds (i.e., the `queue-eta-cell` exists, has `data-eta-iso=""`, and is empty between the opening `>` and closing `</td>`). This regex anchors to the new ETA cell's marker class, scoping the assertion regardless of other rows or future templates that may also use `data-eta-iso`. (Resolves F34: explicit non-None severity avoids the queue's "None" severity-badge collision; resolves F45: regex-anchored assertion replaces fragile `count()`.)
- [x] **AC 27:** Given an open repair record with `eta=date(2026, 6, 15)`, when GET `/repairs/queue` is loaded, then `response.data` contains `('ETA: ' + date(2026, 6, 15).strftime('%b %d, %Y')).encode()` (no leading-space dependency — the assertion does not rely on the `&middot;` entity terminator). The mobile-card region context is verified separately via the `queue-eta-cell` class in AC 25 (desktop) and via the `&middot;` placement in the rendered template; this AC only asserts the formatted ETA text appears at least once in the response. *(Resolves F42: removes accidental dependence on the entity terminator.)*
- [x] **AC 28:** Given a repair record with `eta=date(2026, 6, 15)` on equipment with `acquisition_date=None` and `warranty_expiration=None`, when GET `/equipment/<id>` is loaded, then `re.search(rb'<table[^>]*id="repair-history-table"[\s\S]*?Jun 15, 2026[\s\S]*?</table>', response.data)` succeeds (region-scoped assertion).
- [x] **AC 29:** Given a repair record with `eta=date(2026, 6, 15)`, when GET `/repairs/<id>` is loaded, then response.data contains both `b'ETA</dt>'` and `('Jun 15, 2026').encode()`.
- [x] **AC 30:** Given a repair record whose ETA was updated to `date(2026, 3, 15)` (creating an `eta_update` timeline entry), when GET `/repairs/<id>` is loaded, then `re.search(rb'set to\s+Mar 15, 2026\b', response.data)` succeeds AND `b'set to 2026-03-15'` does NOT appear in `response.data`. The regex tolerates whitespace and minor markup variation between `set to` and the formatted date (e.g., a future inline element wrapper), so a benign template tweak does not silently break the regression guard. *(Resolves F41.)*

#### QR Page Symmetry + Migration

- [x] **AC 31:** Given equipment with an open record having eta set but `description=''`, when GET `/public/equipment/<id>` is loaded, then ETA renders (independent of `issue_description`).
- [x] **AC 32:** Given equipment with two open records — a Down record with `eta=None` and a Degraded record with `eta=date(2026, 6, 15)` — when GET `/public/equipment/<id>` is loaded, then response.data does NOT contain the formatted Degraded-record ETA `'Jun 15, 2026'` (post-migration: highest-severity record's ETA wins; Down's eta is None).
- [x] **AC 33:** Given equipment with two open records — a Down record with `eta=date(2026, 5, 1)` and a Degraded record with `eta=date(2026, 7, 1)` — when GET `/public/equipment/<id>` is loaded, then response.data contains `('May 01, 2026').encode()` and does NOT contain `('Jul 01, 2026').encode()`.

#### Regression / Cross-cutting

- [x] **AC 34:** Given existing Slack handler tests in `tests/test_slack/test_handlers.py`, all pass after the simplification of `get_equipment_status_detail()` in Task B3 (no test changes required).
- [x] **AC 35:** Given `make lint`, exits status 0.
- [x] **AC 36:** Given `make test`, all tests pass (including any updates from Task G11 for the new `repairs/detail.html` ETA format and column-position shifts).
- [x] **AC 37:** Given the `format_date` Jinja filter is loaded in test app context, the locale guard test (`test_runtime_locale_produces_english_month_abbreviations` from Task G1) passes — `date(2026, 1, 1).strftime('%b') == 'Jan'`. *(Resolves F40: future Dockerfile/locale changes that pin a non-English `LC_TIME` will fail this test fast with a clear root-cause signal, instead of cascading into mysterious view-test failures.)*
- [x] **AC 38:** Given the queue table after Task D2's new ETA column is added, when GET `/repairs/queue` is loaded as `tech_client` with several open records of varying severity/area/age/status/assignee, then clicking each existing sortable header (Equipment Name, Severity, Area, Age, Status, Assignee) continues to sort the table — verified by inspecting that all 6 sortable `<th>` elements still carry `data-sort` attributes and that the new ETA `<th>` does NOT carry `data-sort` (so the existing `app.js:33` selector `th[data-sort]` is unchanged in cardinality and key set). This AC can be exercised by a simple HTML structural assertion: `response.data.count(b'data-sort=') == 6` (one per existing sortable column). *(Resolves F47.)*

## Additional Context

### Dependencies

- No new external libraries.
- No new model fields, migrations, or schema changes.
- Depends on the existing `format_date` Jinja filter (`esb/utils/filters.py:10`) — extended to accept ISO strings as part of this spec.
- Depends on existing fixtures in `tests/conftest.py` (`make_area`, `make_equipment`, `make_repair_record`, `tech_client`, `staff_client`, `client`).
- Depends on `_find_highest_severity_record()` helper (`esb/services/status_service.py:37`) — no changes.
- Depends on the existing `static_page_push` notification machinery.

### Testing Strategy

- **Unit tests (filter):** `tests/test_utils/test_filters.py` — add 4 cases for the extended `format_date` (date object, ISO string, None, invalid string).
- **Unit tests (service layer):** Extend `tests/test_services/test_status_service.py` to cover all four ETA paths plus tie-break (oldest-wins). Add exact-key-set test to `TestGetEquipmentStatusDetail`.
- **Unit tests (notification trigger):** Extend `tests/test_services/test_repair_service.py` with a test using direct `PendingNotification` query (mirroring `test_eta_change_queues_notification` line 409, NOT the `capture` fixture).
- **Unit tests (static page):** Extend `tests/test_services/test_static_page_service.py` `class TestGenerate` (note: `TestGenerate`, not `Generate`).
- **View/integration tests:** Extend `tests/test_views/test_public_views.py`, `test_repair_views.py`, `test_equipment_views.py`. Equipment-detail tests use a region-scoped regex (`<table id="repair-history-table">…</table>`) to avoid collision with `acquisition_date`/`warranty_expiration` fields. Queue empty-cell tests use `response.data.count()` for record-scoped assertions.
- **Format-string approach:** Compute expected formatted string in-test via `date(YYYY, M, D).strftime('%b %d, %Y')` so assertions match the runtime locale.
- **Format-conversion regression (Task G11):** After Tasks E1/E2, run `make test` to surface tests that asserted on the old `'%Y-%m-%d'` format and update them.
- **Slack regression (AC 34):** Existing Slack handler tests in `tests/test_slack/test_handlers.py` provide regression coverage for the Task B3 simplification — no new tests required.
- **Manual smoke test (Task G13):** Verify kiosk auto-scale legibility unchanged.

### Notes

- **Locale assumption (resolves F3, F20):** `format_date` uses `'%b %d, %Y'`. `%b` is locale-dependent in general, but in `C` / `POSIX` (the default Python locale; used by `python:3.14-slim` since the project's Dockerfile sets no `LANG`/`LC_TIME`/`LC_ALL`) and in any `*.UTF-8` English locale, `%b` produces English month abbreviations. Tests compute expected strings via `strftime` so assertions self-adapt. Production deployments that explicitly set non-English locales would see localized output — out of scope for this spec.
- **`%d` zero-padding:** Always 2 digits (`Jun 04`, not `Jun 4`). Matches existing behavior across the codebase.
- **HTML safety (informational, F15):** All ETA template insertions rely on Jinja autoescape. Do not pass through `|safe`. `format_date` returns plain text; `record.eta.isoformat()` returns ASCII `YYYY-MM-DD`.
- **Queue-storm risk (F23, acknowledged out-of-scope):** ETA edits during a long-running repair queue fresh `static_page_push` rows with no deduplication. Real-world impact is low (ETA edits are infrequent), but a follow-up to add per-equipment debounce in `notification_service` would be wise. Tracked separately if desired.
- **QR page behavior change (F19, F24):** Before this spec, the QR page fell through severities to find any non-null ETA on open records. After Task C1, the QR page uses the highest-severity record's ETA only (matches the dashboard, kiosk, static-page, and Slack semantics). Practical effect is small: only manifests when the highest-severity open record has no ETA but a lower-severity one does. Documented + covered by AC 32/33.
- **Future enhancement (out of scope):** Sortable queue ETA column — extend `getRowSortValue()` in `esb/static/js/app.js` with a `case 'eta':` returning `Date.parse(...)` of `data-eta-iso` (or `Infinity` for empty); add `data-sort="eta"`, `role="button"`, `class="sortable"`, and a real (non-empty) `<span class="sort-indicator">` to the new `<th>`. The `data-eta-iso` attribute added in Task D2 is preparatory for this enhancement.
- **Future enhancement (out of scope):** Highlight overdue ETAs (`eta < today`) with a warning style.
- **Future enhancement (out of scope):** Include ETA in screen-reader announcements on `status_dashboard.html`, `kiosk.html`, and `equipment/detail.html` repair-history rows.
- **Future enhancement (out of scope):** Per-equipment debounce for `static_page_push` notifications to avoid queue storms (F23 follow-up).

## Review Notes

- Adversarial review completed (post-implementation, separate-context reviewer).
- Findings: 7 total — 3 fixed, 4 acknowledged.
- Resolution approach: auto-fix (real findings).
- **Fixed:**
  - F3 → `tests/test_views/test_equipment_views.py::test_repair_history_eta_blank_when_unset`: assertion was satisfied by an empty Assignee cell; now scoped to a single empty `<td>` and the row is given an assignee.
  - F5 → `esb/templates/public/static_page.html`: added `flex-wrap: wrap` to `.equipment-item` so long ETAs wrap instead of overflowing narrow viewports (CSP-locked page has no Bootstrap responsive helpers).
  - F7 → `tests/test_views/test_repair_views.py::test_queue_existing_sortable_columns_unchanged`: replaced `count(b'data-sort=')` substring count with a `<th>`-anchored regex.
- **Acknowledged (no change):**
  - F1 — empty `.sort-indicator` span in the non-sortable ETA `<th>` is per spec Decision 6 ("keeps cell width parity with sortable neighbors"; spec resolves F32 with this exact structure).
  - F2 — `static_page_push` over-trigger on non-displayed records' ETA edits is acknowledged out-of-scope (queue-storm dedup, spec resolves F23).
  - F4 — `format_date` defensive fallback returning the raw string on `ValueError` is per spec Technical Decision 5 ("Invalid string → fallback to returning the input as-is (defensive; logged at WARNING)").
  - F6 — `_build_equipment_page_context` returns `eta` as a third tuple element duplicating `status['eta']`; preserved per spec Task C1 to minimize template churn.

## Implementation Summary

- **Files modified (esb/):** 11 (1 service, 1 view, 1 filter, 8 templates).
- **Files modified (tests/):** 6 (4 test files extended, 1 conftest reference, plus updated dashboard/single-area-dashboard tests).
- **Net diff:** +614 / −103 lines.
- **Tests:** 1223 passing (39 new); `make lint` clean.
- **Tasks:** A1, B1–B4, C1, D1–D4, E1–E2, F1–F4, G1–G12, G14 complete; G13 (manual kiosk auto-scale smoke test) intentionally deferred — requires interactive browser session, not run by AI agent.
- **Acceptance criteria:** 38/38 satisfied via automated tests.
