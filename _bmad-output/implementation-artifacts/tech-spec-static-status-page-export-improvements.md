---
title: 'Static status page export improvements'
slug: 'static-status-page-export-improvements'
created: '2026-05-11'
status: 'Completed'
stepsCompleted: [1, 2, 3, 4, 5, 6]
tech_stack: ['Python 3.14', 'Flask', 'Jinja2', 'pytest', 'Docker (python:3.14-slim, Debian 13 trixie)']
files_to_modify:
  - 'esb/services/static_page_service.py'
  - 'esb/services/status_service.py'
  - 'esb/templates/public/static_page.html'
  - 'tests/test_services/test_static_page_service.py'
  - 'tests/test_services/test_status_service.py'
  - 'docker-compose.yml'
  - 'Dockerfile'
  - 'docs/administrators.md'
code_patterns:
  - 'esb.services.status_service.get_area_status_dashboard() returns areas with computed status only — needs extension to expose ALL open repair records per equipment'
  - 'esb.templates.components._footer.html is the site copyright footer used on live pages; references current_year context var (injected in esb/__init__.py)'
  - 'esb.utils.filters.format_date is a registered Jinja filter'
  - 'esb.slack.forms.format_status_summary and format_area_status_detail consume the dashboard dict shape'
test_patterns:
  - 'tests/test_services/test_static_page_service.py uses make_area, make_equipment, make_repair_record fixtures; asserts on substrings in generated HTML'
  - 'fixtures: make_repair_record(equipment=None, status="New", description="Test issue", **kwargs) — kwargs become RepairRecord column values (severity, eta, created_at, etc.). NOTE: if equipment is omitted, the fixture auto-creates a fresh Area+Equipment.'
revision_history:
  - '2026-05-11 — initial spec'
  - '2026-05-11 — applied 20 adversarial-review findings (R1F1–R1F20)'
  - '2026-05-11 — applied real findings from round-2 adversarial review (R2F1–R2F21: 16 applied, 5 deferred as noise)'
  - '2026-05-11 — applied real findings from round-3 adversarial review (R3F1–R3F17: all 17 applied; R3F1 invalidated the R2F1 "load-bearing tzdata" framing, recharacterized as defensive pin)'
  - '2026-05-12 — applied selected round-4 adversarial-review findings (R4F1, R4F2, R4F4, R4F10 applied; R4F3/R4F5/R4F6/R4F7 deferred as low-value polish; R4F8/R4F9 noise). Round-4 reviewer verdict: "spec is mature, ready for fresh dev agent."'
  - '2026-05-12 — implementation complete. Post-impl adversarial review returned 16 findings; 9 applied (F1, F2, F3, F4, F5, F6, F9, F11, F12), 7 skipped (F7 cosmetic test-name, F8 feature-creep, F10/F16 undecided, F13 audit-only, F14 noise, F15 spec-mandated combined-test). All 1422 tests passing; lint clean.'
---

## Review Notes

- Adversarial review completed.
- Findings: 16 total, 9 fixed, 7 skipped.
- Resolution approach: auto-fix all "real" findings; skip noise/undecided/feature-creep.
- Skipped, with rationale:
  - **F7** — Test name "archived areas and equipment" accurately reflects its two-part body; rename would not add coverage.
  - **F8** — Startup tzname log line is a feature addition, not a defect fix.
  - **F10** — Concatenation placement is exactly what the spec mandates; refactor undecided.
  - **F13** — Audit pass over substring-vs-element assertions already completed; the two real collisions (cases 7, 11) were caught at first test run.
  - **F14** — Module-level `tzinfo` import is cosmetic.
  - **F15** — Spec explicitly combined the two archived-exclusion scenarios into one test (Task 4 case 21).
  - **F16** — Live-vs-static year inconsistency note in admin docs is undecided polish.

# Tech-Spec: Static status page export improvements

**Created:** 2026-05-11
**Revised:** 2026-05-11 (post-R1 adversarial review, post-R2 adversarial review, post-R3 adversarial review)

GitHub Issue: [#44](https://github.com/jantman/equipment-status-board/issues/44)

## Overview

### Problem Statement

The static status page (`esb/services/static_page_service.py` → `esb/templates/public/static_page.html`) — exported to local disk / S3 / GCS for public-facing display when the live Flask site is unavailable — has two presentation gaps:

1. **No repair detail for non-green equipment.** It lists each equipment item by area with a status dot (green/yellow/red), a label, and (for the highest-severity record only) an ETA. When equipment is Degraded or Down, the page does not enumerate the **open repair records** with their per-record status, ETA, and description, so a reader cannot see *why* equipment is impaired or *what is being done about it*.
2. **Generation metadata is inconsistent and visually weak.** A small "Generated: YYYY-MM-DD HH:MM UTC" line at the very bottom is the only branding/footer content. The live site uses a richer copyright/license footer (`esb/templates/components/_footer.html`). The static export should match the live look-and-feel (including its accessibility attributes), and the generation timestamp should be more prominent and in local/system timezone (not UTC).

### Solution

Update `static_page_service.generate()` to pass through (a) the open repair records per non-green equipment item (sorted by severity priority, then `created_at` ASC) and (b) a generation timestamp in the system's local timezone (with seconds). Update `esb/templates/public/static_page.html` to (i) render a list of open repair records — with each record's status, severity, ETA, and description — nested under each non-green equipment item; (ii) add a generation-time sub-heading immediately under the `<h1>Equipment Status</h1>` title, right-aligned, in local timezone; (iii) replace the bottom "Generated:" line with the site's copyright/license footer text (inlined verbatim including the `aria-label` attributes and `<small>` wrapper — the static page must remain CSP-locked and have no external **sub-resources**, though anchor links to external sites are permitted). Configure the `worker` container's `TZ` env via `docker-compose.yml` and explicitly pin `tzdata` as a defensive dependency in the `Dockerfile`; document the env var in `docs/administrators.md`.

**Note on scope additions beyond issue #44's literal text:** The issue lists status, ETA, and description as required per-record fields. This spec additionally includes (a) a textual severity badge `[Down]` / `[Degraded]` / `[Not Sure]` per record — for accessibility, since color alone (the left-border indicator) is a WCAG concern; (b) sort-by-severity-priority — so the most urgent records bubble to the top at a glance, since this is the fallback view when the live site is down. These are explicitly called out as enhancements.

### Scope

**In Scope:**
- `esb/services/status_service.py` — extend `get_area_status_dashboard()` to include per-equipment `open_records` list, sorted by severity priority then `created_at` ASC. Unknown severities (and `None`) sort at "Not Sure" priority, matching the equipment-level fallback behavior.
- `esb/services/static_page_service.py` — compute local-tz generation timestamp (with seconds, with explicit tzname validation), pass local-tz year to the template.
- `esb/templates/public/static_page.html` — repair-record list under non-green items, top sub-heading with generated time, replace bottom footer with inlined copyright text + a11y attributes. Severity badge displayed only for canonical severities (Down / Degraded / Not Sure).
- Inline the copyright footer markup/text into the static template, including the live footer's `aria-label` attributes and `<small>` wrapper (the static page must have no external sub-resources — same self-contained / `default-src 'none'` CSP rule).
- `docker-compose.yml` — set `TZ=${TZ:-America/New_York}` as the default `worker`-service environment variable.
- `Dockerfile` — add `tzdata` to the `apt-get install` line as a **defensive dependency pin**. The current `python:3.14-slim` base image (Debian 13 trixie) already ships `tzdata` by default — verified via `docker run --rm python:3.14-slim dpkg -l tzdata`. The explicit install protects against a future minimal-image variant that might drop the package; it does NOT fix a current failure mode.
- `docs/administrators.md` — document the `TZ` environment variable in the Environment Variable Reference table.
- `tests/test_services/test_static_page_service.py` — cover the new repair list, footer, generation-time placement, XSS escape, CSP directive integrity, pre-wrap CSS, footer a11y attributes, entity-content escaping, archived-area exclusion, empty-dashboard rendering, cross-area name collision.
- `tests/test_services/test_status_service.py` — regression test for the new `open_records` key in `get_area_status_dashboard()`.

**Out of Scope:**
- Live `public/status_dashboard.html`, kiosk views, or equipment-info pages.
- Database schema changes.
- Push delivery backends (`_push_local`, `_push_s3`, `_push_gcs`) — unchanged.
- Changes to `status_service` status derivation (color/label/severity logic stays as-is).
- Reuse of `_footer.html` via `{% include %}` — static export must remain self-contained.
- Pagination / cap on the number of open records displayed per equipment (explicit decision — see Notes).
- `get_single_area_status_dashboard()` extension (per-area kiosk static export).

## Context for Development

### Codebase Patterns

- **Self-contained static page.** `static_page.html` declares `Content-Security-Policy: default-src 'none'; style-src 'unsafe-inline'` and uses only inline `<style>`. The page must continue to render with no external **sub-resources** — no `<link>`, no `<script src=>`, no `<img src=…>` to external hosts. Anchor links (`<a href="…">`) to external sites are user-initiated navigation, not auto-fetched sub-resources, and are permitted under this CSP. Existing test `test_produces_self_contained_html` enforces no `<link>` / `<script src=>`.
- **Status derivation lives in `esb/services/status_service.py`.** `get_area_status_dashboard()` currently emits one `status` dict per equipment (computed from the highest-severity open record). The new requirement needs **all open repair records** per non-green equipment. Approach: extend `get_area_status_dashboard()` to additionally include the per-equipment list of `RepairRecord` instances in each entry (e.g., `open_records: list[RepairRecord]`). The records are already prefetched and grouped by `equipment_id` in the existing implementation (`records_by_equipment` dict). The new key is sorted by `(severity priority ASC, created_at ASC)` using `_SEVERITY_STATUS`; the prefetch query is already ordered by `(created_at ASC, id ASC)` and Python's `list.sort()` is stable, so the `id`-ASC tiebreak is preserved naturally without being in the sort key. Existing callers ignoring the new key continue to work.
- **Consumers of `get_area_status_dashboard()` return value** (audited 2026-05-11):
  - `esb/templates/public/status_dashboard.html` — iterates `area_data.equipment[*].equipment` and `.status` only.
  - `esb/templates/public/kiosk.html` — same.
  - `esb/views/public.py` `kiosk_area()` route — passes a single-area dict (from `get_single_area_status_dashboard()`, not changed here) into `public/kiosk.html`.
  - `esb/slack/forms.py` `format_status_summary(dashboard_data)` and `format_area_status_detail(area_data)` — iterate `equipment` and `status` only.
  - `esb/slack/handlers.py` `/esb-status` command path — calls `format_status_summary()`.
  - None of the above reference `open_records`, so the additive key change does not require any caller updates. The full test suite (Task 9) is the regression net.
- **`current_year` is injected via `app.context_processor` in `esb/__init__.py`** (`inject_current_year`); that processor works for `render_template()` calls so it is available to the static template without explicit kwargs. **However**, it is derived from `datetime.now(timezone.utc).year`, which can disagree with the static page's local-tz generation timestamp for a few hours either side of midnight Dec 31. Spec passes a local-tz year as a separate template var (`generated_year`) and the footer uses that, not `current_year`, to keep the two timestamps consistent (see Decision #7).
- **Jinja filter `format_date`** (in `esb/utils/filters.py`) is registered on the app's Jinja env and usable from any template, including the static one.
- **`RepairRecord` model fields** (confirmed in `esb/models/repair_record.py`):
  - `status: str` from `REPAIR_STATUSES = ['New', 'Assigned', 'In Progress', 'Parts Needed', 'Parts Ordered', 'Parts Received', 'Needs Specialist', 'Resolved', 'Closed - No Issue Found', 'Closed - Duplicate']`. Non-closed = anything not in `CLOSED_STATUSES = ('Resolved', 'Closed - No Issue Found', 'Closed - Duplicate')`.
  - `severity: str | None` from `REPAIR_SEVERITIES = ['Down', 'Degraded', 'Not Sure']`. Column has **no DB-level CHECK constraint** — unknown strings are possible in legacy/future data.
  - `description: str` (Text, non-null). Can be multi-line and effectively unbounded.
  - `eta: date | None`.
  - `created_at: datetime` (UTC).
- **Severity → color map** (`status_service._SEVERITY_STATUS`): `Down`→red (priority 0), `Degraded`→yellow (priority 1), `Not Sure`→yellow (priority 2). For records whose severity is `None` or any *unknown* string, both the equipment-level status derivation (`status_service.py` `_derive_status_from_records`, "fall through to yellow/Degraded" branch) and the new sort key fall back to the **`Not Sure` priority (2)**. This keeps equipment-level rendering and record-list ordering consistent (Round-2 finding R2F8). **For the per-record visual:** the left border maps `Down`→red, `Degraded`/`Not Sure`→yellow, everything else (`None` and unknown strings) → gray; the severity text badge `[…]` displays **only for canonical severities** (`Down`/`Degraded`/`Not Sure`) — for unknown strings the badge is suppressed entirely (Round-3 finding R3F3), so the data-quality signal is "gray border, no badge" rather than the previous tri-state of yellow-priority + gray-border + raw-text-badge.
- **Local-timezone formatting.** No existing helper. Place the implementation in a module-level helper `_compute_generated_at()` in `static_page_service.py` (NOT inline in `generate()`) so tests can monkey-patch it directly. Format: `'%Y-%m-%d %H:%M:%S '` + `dt.tzname()` → `2026-05-11 14:32:15 EDT`. The helper **explicitly validates** that `dt.tzname()` returns a truthy non-empty string and raises `RuntimeError` otherwise — preserves a real loud-failure guarantee, vs. the silent-trailing-space degradation that a bare concatenation would allow (Round-3 finding R3F5). Under CPython 3.11+ with the system's `tzdata` package available, `datetime.now().astimezone()` reliably yields a non-empty tzname; the validation is defense in depth.
- **Reference data shape only** (not visual precedent): `esb/templates/public/equipment_page.html`'s `open_repairs` list shows the conceptual shape (one row per open record, severity-styled, description visible, ETA when set). The actual styling cannot be copied — `equipment_page.html` uses Bootstrap classes (`card`, `card-body`, `mb-2`, etc.) which are unavailable in the static export. The static page reimplements the layout in inline CSS.
- **Base image timezone behavior** (verified 2026-05-11 via `docker run --rm python:3.14-slim`): `python:3.14-slim` ships on Debian 13 trixie and pre-installs `tzdata` (`tzdata 2026a-0+deb13u1`). `/usr/share/zoneinfo/America/New_York` exists by default, and `TZ=America/New_York python -c '…tzname()'` correctly emits `EDT` out of the box. The Dockerfile change in Task 8 is a **defensive dependency pin** — making `tzdata` explicit in the install list so a future swap to a hypothetical thinner base image (or a Debian package retraction) cannot silently regress the feature. It is **not** fixing a current bug.
- **Test fixtures** (`tests/conftest.py`):
  - `make_area(name='Test Area', slack_channel='#test-area')` → `Area`.
  - `make_equipment(name='Test Equipment', manufacturer='TestCo', model='Model X', area=None, **kwargs)` → `Equipment` (extra kwargs forwarded to model constructor). If `area=None`, the fixture auto-creates a fresh area.
  - `make_repair_record(equipment=None, status='New', description='Test issue', **kwargs)` → `RepairRecord`. Extra kwargs (`severity`, `eta`, `created_at`, `assignee_id`, `reporter_name`, etc.) are forwarded to the `RepairRecord` constructor. **The fixture does NOT accept `area` or `name` kwargs.** **If `equipment` is omitted, the fixture auto-creates a fresh Area + Equipment** — always pass `equipment=…` explicitly in the new tests to avoid surprise side-effects.

### Files to Reference

| File | Purpose |
| ---- | ------- |
| `esb/services/static_page_service.py` | Modify `generate()`; add `_compute_generated_at()` module-level helper. |
| `esb/services/status_service.py` | Extend `get_area_status_dashboard()` with the new `open_records` key. |
| `esb/templates/public/static_page.html` | Render repair list, top-right generation timestamp, inline a11y-attributed copyright footer. |
| `esb/templates/components/_footer.html` | Source of truth for the copyright/license text, link targets, and a11y attributes (used as reference; not included via `{% include %}`). |
| `esb/__init__.py` | `inject_current_year` context processor (already wired; not modified — local-tz year is passed separately). |
| `esb/utils/filters.py` | `format_date` Jinja filter. |
| `esb/slack/forms.py`, `esb/slack/handlers.py` | Existing consumers of `get_area_status_dashboard()`; verified not affected by the additive `open_records` key. |
| `docker-compose.yml` | Add `TZ=${TZ:-America/New_York}` to the `worker` service. |
| `Dockerfile` | Add `tzdata` to the `apt-get install` line as a **defensive dependency pin**. The current base image already includes it; the explicit install protects against future image-content drift. |
| `docs/administrators.md` | Document the `TZ` env var in the Environment Variable Reference section. |
| `tests/test_services/test_static_page_service.py` | Existing test class `TestGenerate`; add cases for repair list, top-right timestamp, inline footer, footer-text pin, XSS escape, CSP directive integrity, pre-wrap CSS, footer a11y attributes, entity-content escape, archived exclusion, empty-dashboard, cross-area name collision, regex format check. |
| `tests/test_services/test_status_service.py` | Add regression test for `open_records` key. |
| `tests/conftest.py` | Fixture definitions (`make_area`, `make_equipment`, `make_repair_record`). |

### Technical Decisions

1. **Extend `get_area_status_dashboard()` to include an `open_records` list per equipment.** Records are already prefetched and grouped in `records_by_equipment`; threading the list through is a one-line change. Rejected the "new helper" option to avoid duplicating ~40 lines of prefetch code. Existing callers (live dashboard, kiosk, Slack formatters) ignore the new key.
2. **Sort open records by `(severity priority, created_at)` ASC.** Rationale: the static page is the fallback at-a-glance view. Sorting by severity ensures `Down` records bubble above `Degraded`/`Not Sure`/unknown within each equipment's record list. Sort-key implementation (canonical — see Task 1 for the same snippet):
   ```python
   def _open_records_sort_key(rec):
       sev_entry = _SEVERITY_STATUS.get(rec.severity)
       priority = sev_entry[2] if sev_entry else _NOT_SURE_PRIORITY
       return (priority, rec.created_at)
   ```
   **No `id` in the sort key** — Python's `list.sort()` is stable and the prefetch query order (`created_at ASC, id ASC`) is preserved on ties. **Unknown severity strings and `None` both fall back to the `Not Sure` priority (2)** — same as the equipment-level status derivation — to avoid an inversion where the equipment dot says yellow but the unknown-severity record sorts beneath Not-Sure records (R2F8). (R4F2: Decision #2 and Task 1 now share the same two-line snippet.)
3. **Local-timezone generation timestamp.** Implemented in module-level helper `_compute_generated_at()` in `static_page_service.py` (so tests can patch it). Uses `datetime.now().astimezone()` (no `tzinfo` argument) — Python picks up the host system's TZ from `TZ` env / `/etc/localtime`. Format: `'%Y-%m-%d %H:%M:%S '` + `dt.tzname()` → `2026-05-11 14:32:15 EDT`. Seconds are included for debugging value when multiple pushes happen within a minute. **Explicit tzname validation** (R3F5): the helper checks `tzname = dt.tzname(); if not tzname: raise RuntimeError(...)` — this is a real loud-failure guarantee that catches both `None` (TypeError on concatenation) AND empty-string (silent trailing space) cases. Build the string by concatenation (not `%Z`) so the trailing token is explicit.
4. **Footer text is inlined verbatim** from `_footer.html` (copyright line + GitHub link + MIT license link, INCLUDING `<small>` wrapper and all `aria-label` attributes) into `static_page.html`, NOT included via `{% include %}`. Reasons: (a) the static page must remain self-contained (no external sub-resources); (b) an include couples the export to a fragment used by the live site, which is brittle if that fragment later pulls in Bootstrap classes; (c) copyright text is short and stable. **Drift mitigation:** Task 4 case 12 adds a unit test that loads `_footer.html` through Flask's Jinja loader and asserts its **three load-bearing substrings** (`Jason Antman`, the GitHub URL, the MIT URL) appear in the rendered static page. The test is explicitly named `test_footer_text_pin` — it pins owner + URLs only, NOT year-token markup or `<small>`/aria attribute wrapping. Those are covered by their own ACs (AC 8 / AC 9).
5. **Per-record styling**. Repair-record `<li>` items use a small inline left-border indicator color-coded by severity using the same mapping as the equipment-level dot (`Down`→red, `Degraded`/`Not Sure`→yellow, everything else including `None` and unknown strings → gray). Display order within the record: `[status badge] [severity badge if canonical severity] description …ETA: …`. Severity text badge is **retained for canonical severities** (`Down`/`Degraded`/`Not Sure`) as an accessibility/redundancy feature — color alone is a WCAG concern, and the text badge gives the same information non-visually. **For non-canonical severities (R3F3)** — unknown strings AND `None` — the badge is suppressed entirely; the gray border serves as the "unrecognized data" signal. This resolves the prior tri-state inconsistency where an unknown severity produced yellow-priority sort + gray border + raw-text badge.
6. **Description wrap, not truncate.** `RepairRecord.description` is unbounded Text. Apply inline CSS `white-space: pre-wrap; overflow-wrap: anywhere;` to `.record-description` so multi-line descriptions render correctly and long un-broken strings (URLs, etc.) wrap rather than overflow the page. **No truncation** — the static page is a fallback view and full text is more useful than an ellipsis.
7. **Local-tz year for the footer.** Compute the footer year from the same `datetime` used by `_compute_generated_at()` (Python's `datetime.astimezone()` returns a `datetime` whose `.year` is the converted local-tz year, not the source UTC year — verified empirically). Pass it to the template as a separate kwarg `generated_year`. The footer renders `&copy; {{ generated_year }} Jason Antman`. The `current_year` context processor (UTC) is left alone so the live site is unaffected. This avoids the ~5-hour disagreement window around midnight Dec 31.
8. **Generation sub-heading placement.** Below the `<h1>Equipment Status</h1>` block, right-aligned via `text-align: right` on a `.generated-at` div (new CSS rule).
9. **Equipment-row layout wrapper.** Existing `.equipment-item` uses `display: flex` to lay out dot/name/label/eta on one line. Adding a nested `<ul>` for open records inside the same `<li>` would make the `<ul>` a flex sibling. Spec wraps the existing four spans into a new `<div class="equipment-row">` (with `display: flex; flex-wrap: wrap; align-items: center; gap: 0.5rem;`) and changes `.equipment-item` to `display: block`. The new `<ul class="open-records-list">` lays out beneath the row with `margin-top: 0.4rem` for visual separation. The full template diff is spelled out in Task 3.
10. **TZ default in `docker-compose.yml`** and **defensive `tzdata` pin in `Dockerfile`.** Set `TZ=${TZ:-America/New_York}` in the `worker` service `environment:` block — load-bearing change that actually controls the timestamp's timezone. Add `tzdata` to the `apt-get install` line in `Dockerfile` as a **defensive dependency pin** — the current `python:3.14-slim` base image already includes `tzdata`, so the install is currently redundant; making it explicit protects against a future minimal-image variant that might drop the package. The `app` service does not need `TZ` because it does not render the static page; the worker is the sole producer via `generate_and_push()`.
11. **Module-level datetime import in `static_page_service.py`.** Hoist `from datetime import datetime` to module top (it is currently function-scoped). This is required for the `_compute_generated_at()` helper to exist at module scope, and it lets tests patch `static_page_service.datetime` (or `_compute_generated_at` itself) directly.

## Implementation Plan

### Tasks

- [x] **Task 1: Extend `get_area_status_dashboard()` to include sorted per-equipment open repair records.**
  - File: `esb/services/status_service.py`
  - Action:
    1. Inside `get_area_status_dashboard()`, after the `records_by_equipment` grouping, add a sort: for each list in `records_by_equipment.values()`, sort in place by `(priority, created_at)`. Helper:
       ```python
       _NOT_SURE_PRIORITY = _SEVERITY_STATUS['Not Sure'][2]

       def _open_records_sort_key(rec):
           sev_entry = _SEVERITY_STATUS.get(rec.severity)
           priority = sev_entry[2] if sev_entry else _NOT_SURE_PRIORITY
           return (priority, rec.created_at)

       for records in records_by_equipment.values():
           records.sort(key=_open_records_sort_key)
       ```
       Define `_NOT_SURE_PRIORITY` and `_open_records_sort_key` at module level (right after the `_SEVERITY_STATUS` dict definition). Do **not** introduce a separate `999` sentinel — unknown severities and `None` both map to `Not Sure` priority for sort purposes, matching the equipment-level fallback (R2F7, R2F8).
    2. In the loop that builds `equip_statuses`, add `'open_records': equip_records` to the dict appended for each equipment.
    3. Update the function's docstring to document the new `open_records` key — list of `RepairRecord` instances, sorted by `(severity priority, created_at)` with unknown severities folded to `Not Sure` priority; ties on those fields preserve the prefetch query's `(created_at, id)` ASC order (stable sort).
  - Notes: Existing live-page templates (`public/status_dashboard.html`, `public/kiosk.html`) and Slack formatters (`esb/slack/forms.py`) iterate `area_data.equipment` but reference only `item.equipment` and `item.status`. The additive key is safe. `get_single_area_status_dashboard()` is **not** changed.

- [x] **Task 2: Add `_compute_generated_at()` helper and hoist `datetime` import in `static_page_service.py`.**
  - File: `esb/services/static_page_service.py`
  - Action:
    1. Move `from datetime import UTC, datetime` from inside `generate()` to the module-level imports. Remove the unused `UTC` if not referenced elsewhere.
    2. Add a module-level helper:
       ```python
       def _compute_generated_at() -> tuple[str, int]:
           """Compute the generation timestamp string and year in the system's local timezone.

           Returns:
               (timestamp_str, year) where timestamp_str is formatted like
               '2026-05-11 14:32:15 EDT'. year is the local-tz year of the
               same instant (datetime.astimezone() returns a datetime whose
               .year reflects the converted zone, not the source UTC year).

           Raises:
               RuntimeError: if the local timezone has no resolvable tzname
                   (indicates the runtime is missing tzdata, e.g. a stripped
                   Docker image). The Dockerfile pins tzdata; this guard is
                   defense-in-depth against future image-content drift.
           """
           dt = datetime.now().astimezone()
           tzname = dt.tzname()
           if not tzname:
               raise RuntimeError(
                   "Local timezone has no resolvable tzname; tzdata may be missing."
               )
           return (dt.strftime('%Y-%m-%d %H:%M:%S ') + tzname, dt.year)
       ```
       Explicit `if not tzname:` check covers both `None` and empty-string cases (R3F5). Build the string by concatenation (not `%Z`) so the trailing token is explicit.
    3. Update `generate()` — import `REPAIR_SEVERITIES` from the model and pass it as a template context kwarg so the template's badge guard isn't a hardcoded copy of the canonical list (R4F1):
       ```python
       def generate() -> str:
           from esb.models.repair_record import REPAIR_SEVERITIES
           from esb.services import status_service
           areas = status_service.get_area_status_dashboard()
           generated_at, generated_year = _compute_generated_at()
           return render_template(
               'public/static_page.html',
               areas=areas,
               generated_at=generated_at,
               generated_year=generated_year,
               repair_severities=REPAIR_SEVERITIES,
           )
       ```
  - Notes: No new external deps. Tests patch `esb.services.static_page_service._compute_generated_at` to inject deterministic timestamps regardless of host TZ.

- [x] **Task 3: Update `static_page.html` template structure.**
  - File: `esb/templates/public/static_page.html`
  - Below is the full intended template (replace the file's contents). Read the existing file first to confirm no other recent edits.

    ```html
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline';">
        <title>Equipment Status</title>
        <style>
            * { margin: 0; padding: 0; box-sizing: border-box; }
            body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; color: #212529; background: #f8f9fa; padding: 1rem; }
            h1 { font-size: 1.5rem; margin-bottom: 0.25rem; text-align: center; }
            .generated-at { text-align: right; font-size: 0.85rem; color: #6c757d; margin-bottom: 1rem; }
            .area { margin-bottom: 1.5rem; }
            .area h2 { font-size: 1.1rem; border-bottom: 2px solid #dee2e6; padding-bottom: 0.3rem; margin-bottom: 0.5rem; }
            .equipment-list { list-style: none; }
            .equipment-item { display: block; padding: 0.25rem 0; }
            .equipment-row { display: flex; flex-wrap: wrap; align-items: center; gap: 0.5rem; }
            .status-dot { width: 12px; height: 12px; border-radius: 50%; display: inline-block; flex-shrink: 0; }
            .status-green { background-color: #198754; }
            .status-yellow { background-color: #ffc107; }
            .status-red { background-color: #dc3545; }
            .equipment-name { font-size: 0.95rem; }
            .status-label { font-size: 0.8rem; color: #6c757d; }
            .eta-label { font-size: 0.8rem; color: #6c757d; margin-left: 0.25rem; }
            .no-equipment { color: #6c757d; font-size: 0.9rem; }
            .open-records-list { list-style: none; margin: 0.4rem 0 0.6rem 1.5rem; }
            .open-record { font-size: 0.85rem; padding: 0.25rem 0.4rem; margin-bottom: 0.2rem; border-left: 3px solid #6c757d; background: #fff; }
            .open-record-red { border-left-color: #dc3545; }
            .open-record-yellow { border-left-color: #ffc107; }
            .open-record-gray { border-left-color: #6c757d; }
            .record-status { font-weight: 600; }
            .record-severity { color: #6c757d; }
            .record-description { white-space: pre-wrap; overflow-wrap: anywhere; }
            .record-eta { color: #6c757d; margin-left: 0.25rem; }
            .site-footer { text-align: center; margin-top: 2rem; padding-top: 1rem; border-top: 1px solid #dee2e6; font-size: 0.8rem; color: #6c757d; word-break: break-word; }
            .site-footer a { color: #6c757d; }
        </style>
    </head>
    <body>
        <h1>Equipment Status</h1>
        <div class="generated-at">Generated: {{ generated_at }}</div>
        {% for area_data in areas %}
        <div class="area">
            <h2>{{ area_data.area.name }}</h2>
            {% if area_data.equipment %}
            <ul class="equipment-list">
                {% for item in area_data.equipment %}
                <li class="equipment-item">
                    <div class="equipment-row">
                        <span class="status-dot status-{{ item.status.color }}" aria-hidden="true"></span>
                        <span class="equipment-name">{{ item.equipment.name }}</span>
                        <span class="status-label">{{ item.status.label }}</span>
                        {% if item.status.eta %}<span class="eta-label">ETA: {{ item.status.eta|format_date }}</span>{% endif %}
                    </div>
                    {% if item.status.color != 'green' and item.open_records %}
                    <ul class="open-records-list">
                        {% for rec in item.open_records %}
                        <li class="open-record open-record-{{ 'red' if rec.severity == 'Down' else 'yellow' if rec.severity in ('Degraded', 'Not Sure') else 'gray' }}">
                            <span class="record-status">{{ rec.status }}</span>{% if rec.severity in repair_severities %} <span class="record-severity">[{{ rec.severity }}]</span>{% endif %} <span class="record-description">{{ rec.description }}</span>{% if rec.eta %} <span class="record-eta">ETA: {{ rec.eta|format_date }}</span>{% endif %}
                        </li>
                        {% endfor %}
                    </ul>
                    {% endif %}
                </li>
                {% endfor %}
            </ul>
            {% else %}
            <p class="no-equipment">No equipment in this area.</p>
            {% endif %}
        </div>
        {% endfor %}
        <footer class="site-footer" role="contentinfo" aria-label="Site copyright and license">
            <small>&copy; {{ generated_year }} Jason Antman. <a href="https://github.com/jantman/equipment-status-board" rel="noopener noreferrer" aria-label="Source code on GitHub">github.com/jantman/equipment-status-board</a> <a href="https://opensource.org/license/mit" rel="noopener noreferrer" aria-label="MIT License (opensource.org)">MIT licensed</a>.</small>
        </footer>
    </body>
    </html>
    ```

  - Key changes vs. previous template: `.equipment-item` becomes `display: block`; the existing dot/name/label/eta row is wrapped in `<div class="equipment-row">`; new `<ul class="open-records-list">` rendered only when equipment is non-green AND has open records; **severity badge guard is `{% if rec.severity in repair_severities %}`** (where `repair_severities = REPAIR_SEVERITIES` from `esb.models.repair_record`, passed via `generate()` context) so unknown/None severities suppress the badge entirely (R3F3) AND a future addition to `REPAIR_SEVERITIES` automatically picks up badge rendering without a template edit (R4F1); old `<div class="footer">Generated: …</div>` replaced by `<footer class="site-footer" role="contentinfo" aria-label="Site copyright and license">` with a `<small>` wrapper and `aria-label` on the GitHub and MIT anchors (mirrors `_footer.html`); new `.generated-at` sub-heading directly under the `<h1>`. The footer uses `generated_year` (local-tz, from `_compute_generated_at()`), NOT `current_year`. The CSP directive is unchanged. Note: the color-class chain `{{ 'red' if rec.severity == 'Down' else 'yellow' if rec.severity in ('Degraded', 'Not Sure') else 'gray' }}` intentionally keeps hardcoded membership — color is a semantic mapping per severity (not derivable from the list alone), so adding a new canonical severity also requires a deliberate color decision in this template.

- [x] **Task 4: Add tests in `tests/test_services/test_static_page_service.py`.**
  - File: `tests/test_services/test_static_page_service.py`
  - Add the following tests (inside `class TestGenerate` unless noted). Always pass `equipment=…` explicitly to `make_repair_record` to avoid the fixture auto-creating its own area/equipment.

    1. `test_generated_at_subheading_renders_above_areas` — Given an area with one equipment item, when `generate()` runs, then the HTML contains `<div class="generated-at">` and its `find()` index is greater than the index of `</h1>` and less than the index of the first `<div class="area">`.

    2. `test_generated_at_uses_local_timezone_helper` (covers AC 7a) — Monkey-patch `esb.services.static_page_service._compute_generated_at` to return `('2026-05-11 14:32:15 EDT', 2026)`. Call `generate()`. Assert HTML contains `Generated: 2026-05-11 14:32:15 EDT` and footer contains `2026`.

    3. `test_compute_generated_at_formats_tzname` (covers AC 7b, helper-level) — Use the following exact mock setup to avoid the chained-Mock ambiguity flagged in R3F4:
       ```python
       fixed_dt = datetime(2026, 7, 15, 14, 32, 15, tzinfo=ZoneInfo('America/New_York'))
       with patch.object(static_page_service, 'datetime') as mock_datetime:
           mock_datetime.now.return_value.astimezone.return_value = fixed_dt
           result = static_page_service._compute_generated_at()
       assert result == ('2026-07-15 14:32:15 EDT', 2026)
       ```
       Note: this creates a `ZoneInfo('America/New_York')` instance, which depends on tzdata being available either via the OS or the PyPI `tzdata` package. The Docker base image provides it; local pytest runs do too on standard Linux/macOS dev machines. If CI ever runs on a stripped image without tzdata, add the PyPI `tzdata` package to test/dev requirements (R3F6).

    4. `test_compute_generated_at_raises_on_empty_tzname` (covers AC 7c, R3F5 explicit-validation) — Build a minimal custom `tzinfo` subclass whose `tzname(dt)` returns `''` (empty). Patch `datetime` to make `datetime.now().astimezone()` return a `datetime` with that tzinfo. Assert `_compute_generated_at()` raises `RuntimeError` matching `"tzname"`.

    5. `test_compute_generated_at_format_matches_regex` (covers AC 6, R3F17 end-to-end regex) — Call the **unpatched** helper (no mocks). Assert the returned timestamp string matches `re.fullmatch(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} \S+', result[0])` — verifies the format end-to-end against the real codepath, including a non-empty timezone token, on the real host clock.

    6. `test_open_records_listed_for_non_green_equipment` (covers AC 1) — Create equipment with one record `make_repair_record(equipment=eq, status='In Progress', severity='Down', description='Belt slipping', eta=date(2026, 6, 1))`. Call `generate()`. Assert HTML contains `'In Progress'`, `'[Down]'`, `'Belt slipping'`, and `'ETA: ' + date(2026, 6, 1).strftime('%b %d, %Y')`, AND contains the substring `class="open-record open-record-red"`.

    7. `test_open_records_omitted_for_green_equipment` (covers AC 2) — Create equipment with no repair records. Assert HTML does NOT contain `'open-records-list'`.

    8. `test_open_records_uses_yellow_class_for_degraded_and_not_sure` (covers AC 4) — Create two equipment items in the same area, one with `severity='Degraded'`, one with `severity='Not Sure'`. Assert HTML contains at least two occurrences of `'open-record-yellow'` AND contains both `'[Degraded]'` and `'[Not Sure]'` text badges.

    9. `test_open_records_uses_gray_class_for_no_severity` (covers AC 4 None branch) — Create one equipment with one record passing `severity=None`. Assert HTML contains `'open-record-gray'` AND does NOT contain `'<span class="record-severity">'` (badge suppressed per R3F3).

    10. `test_open_records_uses_gray_class_and_suppresses_badge_for_unknown_severity` (covers AC 4 unknown branch, R3F3) — Create one equipment with one record passing `severity='Critical'` (or any unknown string). Assert HTML contains `'open-record-gray'` AND does NOT contain `'<span class="record-severity">'` AND does NOT contain `'[Critical]'`. The unknown severity sorts at Not-Sure priority (covered by Task 5) but renders with the gray-no-badge "unrecognized data" treatment.

    11. `test_open_records_omits_eta_when_unset` (covers AC 5) — In a fresh test fixture, create exactly one equipment with one record `make_repair_record(equipment=eq, severity='Down', eta=None)`. Assert HTML does NOT contain `'record-eta'`. (Scoped to a single equipment so the global assertion is safe — no substring splitting required.)

    12. `test_open_records_sorted_by_severity_priority_then_created_at` (covers AC 3) — Create one equipment with three records: `(severity='Down', created_at=datetime(2026, 5, 1, tzinfo=UTC), description='down-newer')`, `(severity='Not Sure', created_at=datetime(2026, 4, 1, tzinfo=UTC), description='notsure-older')`, `(severity='Degraded', created_at=datetime(2026, 4, 15, tzinfo=UTC), description='degraded-mid')`. Insert in mixed order. Call `generate()`. Assert `html.find('down-newer') < html.find('degraded-mid') < html.find('notsure-older')`.

    13. `test_site_footer_replaces_old_generated_line` (covers AC 8) — Call `generate()`. Assert HTML contains `'<footer class="site-footer"'`, `'role="contentinfo"'`, `'aria-label="Site copyright and license"'`, `'<small>'`, `'Jason Antman'`, `'aria-label="Source code on GitHub"'`, `'aria-label="MIT License (opensource.org)"'`, `'github.com/jantman/equipment-status-board'`, `'MIT licensed'`, AND does NOT contain `'<div class="footer">'` (the old class).

    14. `test_footer_renders_local_tz_year_as_entity` (covers AC 9) — Monkey-patch `_compute_generated_at` to return `(..., 2027)`. Assert HTML footer contains the literal substring `&copy; 2027 Jason Antman` (HTML-entity form — Jinja does NOT decode `&copy;`).

    15. `test_footer_text_pin` (covers AC 12 — footer-text pin against `_footer.html`) — Load `_footer.html` source via Flask's Jinja loader:
        ```python
        try:
            source = app.jinja_env.loader.get_source(app.jinja_env, 'components/_footer.html')[0]
        except TemplateNotFound as e:
            raise AssertionError(
                "_footer.html not found — has it been moved or renamed? "
                "Update this pin test's path."
            ) from e
        ```
        From that source, extract three load-bearing substrings: `'Jason Antman'`, `'https://github.com/jantman/equipment-status-board'`, and `'https://opensource.org/license/mit'`. Assert each appears in the rendered static page HTML. Scope: this test pins owner + URLs only (R3F13 wrapper added for clearer error message).

    16. `test_description_is_html_escaped` (covers AC 11 / XSS defense) — Create a repair record with `description='<script>alert(1)</script><img src=x onerror=y>'`. Call `generate()`. Assert HTML contains `'&lt;script&gt;'` (escaped) AND does NOT contain the literal `'<script>alert(1)</script>'`.

    17. `test_description_escapes_entity_content` (covers AC 11b, R3F11) — Create a repair record with `description='Bob & Alice broke it; price was 50%<'`. Assert HTML contains the substrings `'Bob &amp; Alice broke it'` and `'50%&lt;'` (autoescaped), AND does NOT contain a bare `'Bob & Alice'` substring (which would indicate autoescape failure).

    18. `test_csp_meta_tag_directive_unchanged` (strengthens existing `test_includes_csp_meta_tag`) — Replace the existing test (or add a sibling) that asserts only `'Content-Security-Policy' in html` with: `assert "default-src 'none'; style-src 'unsafe-inline'" in html` (verbatim directive contents).

    19. `test_equipment_row_keeps_dot_name_label_on_one_line` (covers AC 14 layout) — Assert HTML contains `<div class="equipment-row">` and within that wrapper (slice to its closing tag), the order of substrings is `status-dot`, `equipment-name`, `status-label`.

    20. `test_description_uses_prewrap_styles` (covers AC 13 wrap CSS) — Assert HTML contains the substring `.record-description { white-space: pre-wrap; overflow-wrap: anywhere; }` inside the `<style>` block.

    21. `test_archived_areas_and_equipment_are_excluded` (covers AC 17, R3F9) — Create one archived area (`is_archived=True`) named `'Archived Area'` with one piece of equipment, AND one active area named `'Active Area'` with one piece of equipment. Call `generate()`. Assert HTML contains `'Active Area'` and does NOT contain `'Archived Area'`. Then create one active area containing one active equipment named `'Visible Tool'` and one archived equipment (`is_archived=True`) named `'Retired Tool'`. Call `generate()`. Assert HTML contains `'Visible Tool'` and does NOT contain `'Retired Tool'`.

    22. `test_empty_dashboard_renders_skeleton` (covers AC 18, R3F10) — With zero non-archived areas in the DB, call `generate()`. Assert HTML contains `<h1>Equipment Status</h1>`, `<div class="generated-at">`, and `<footer class="site-footer"`, but does NOT contain `<div class="area">`.

    23. `test_two_equipment_with_same_name_in_different_areas` (covers AC 19, R3F12) — Create two areas (`'Area A'`, `'Area B'`) each with an equipment item named `'Drill Press'`, each with one `Down` open record (descriptions `'a-issue'` and `'b-issue'` respectively). Call `generate()`. Assert HTML contains both `'Area A'` and `'Area B'` AND that `html.find('Area A') < html.find('a-issue') < html.find('Area B') < html.find('b-issue')` (records appear under their correct area in document order).

    24. **Update existing `test_includes_generated_timestamp`** — Replace `assert 'UTC' in html` with `assert 'Generated:' in html`. The timezone token now depends on host TZ / patched helper.

  - Notes:
    - The fixture `make_repair_record(equipment=None, status='New', description='Test issue', **kwargs)` — pass `equipment=…` explicitly to avoid auto-create side effects; pass `severity`, `eta`, `created_at` via kwargs.
    - **Explicit imports required by the new test cases** (R4F4 — make these unambiguous for a fresh dev):
      - `from datetime import UTC, datetime` (Python 3.11+) — cases 12, 21, 22, 23 for `created_at` kwarg values.
      - `from zoneinfo import ZoneInfo` — case 3 for `ZoneInfo('America/New_York')`.
      - `from unittest.mock import patch` — cases 2, 3, 4, 14.
      - `from jinja2.exceptions import TemplateNotFound` — case 15.
      - `import re` — case 5.
      - `from esb.services import static_page_service` — cases 2, 3, 4, 5 (the cases that patch helper internals or call them directly; the broader test module already imports it).

- [x] **Task 5: Add a regression test for the new `open_records` key in `tests/test_services/test_status_service.py`.**
  - File: `tests/test_services/test_status_service.py`
  - Add (in an existing `TestGetAreaStatusDashboard` class, or create one):

    1. `test_includes_open_records_list_per_equipment` — Create one area with one equipment item and two non-closed repair records and one closed record (`status='Resolved'`). Call `get_area_status_dashboard()`. Assert `result[0]['equipment'][0]['open_records']` is a `list` of length 2; the closed record is excluded; each entry is a `RepairRecord` instance.

    2. `test_open_records_sorted_by_severity_then_created_at` — Create one equipment with five records: `(Down, 2026-05-01)`, `(Not Sure, 2026-04-01)`, `(Degraded, 2026-04-15)`, `(None, 2026-03-01)`, `('Critical', 2026-02-01)` (unknown severity, oldest). Call the dashboard. Assert the `open_records` list order is: `Down`, `Degraded`, then within priority-2 sorted by `created_at` ASC — `'Critical'` (oldest), then `None`, then `Not Sure`.

    3. `test_empty_open_records_list_for_green_equipment` — Create equipment with zero non-closed records. Assert `equipment[0]['open_records'] == []`.

  - Notes: Verify existing tests still pass — the new key is additive.

- [x] **Task 6: Configure default TZ in `docker-compose.yml` worker service.**
  - File: `docker-compose.yml`
  - Action: In the `worker:` service's `environment:` block, add a new line: `      - TZ=${TZ:-America/New_York}`. Place it adjacent to the existing `PYTHONUNBUFFERED=1` and `WORKER_HEARTBEAT_PATH=…` entries.
  - Notes: The `${TZ:-America/New_York}` syntax means "use the `TZ` env var if set in `.env` or shell, otherwise default to `America/New_York`." This matches the makerspace location (Decatur Makers) while letting other deployments override. The `app` service does **not** need TZ — only the worker calls `generate()`. This is the load-bearing change for the local-tz feature.

- [x] **Task 7: Document the `TZ` environment variable in `docs/administrators.md`.**
  - File: `docs/administrators.md`
  - Action: In the Environment Variable Reference table, add a new row:
    ```markdown
    | `TZ` | IANA timezone name for the worker container. Controls the timezone displayed in the static status page's generation timestamp (sub-heading near top of page) and the year used in the footer. Set this to your local timezone for accurate display. The `app` service does not use this variable. | No | `America/New_York` | `America/Chicago` |
    ```
  - Also add a short paragraph in the "Static Status Page Setup" section: "The static page's generation timestamp reflects the `worker` container's `TZ` environment variable. The variable resolves against the OS tzdata database (`/usr/share/zoneinfo`), which is provided by the `tzdata` system package. Both the `python:3.14-slim` base image and this image's Dockerfile install list include `tzdata`; do not remove it. To use a non-default zone, set `TZ` in `.env` before running `docker compose up`."

- [x] **Task 8: Add `tzdata` to the Dockerfile as a defensive dependency pin.**
  - File: `Dockerfile`
  - Action: In the existing `apt-get install` line, add `tzdata` alongside `gcc` and `libzbar0`:
    ```dockerfile
    RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
        libzbar0 \
        tzdata \
        && rm -rf /var/lib/apt/lists/*
    ```
  - Notes: **This is a defensive dependency pin, NOT a fix for a current bug.** The `python:3.14-slim` base image (Debian 13 trixie) already ships `tzdata` by default — verified via `docker run --rm python:3.14-slim dpkg -l tzdata` showing `tzdata 2026a-0+deb13u1`. With the base image as-is, `TZ=America/New_York` already resolves correctly. The explicit install guarantees `tzdata` remains in the image if a future base-image variant ever drops the package (or if a Debian repository retraction makes it disappear). `apt-get install -y --no-install-recommends` is fully non-interactive on Debian trixie without needing `DEBIAN_FRONTEND=noninteractive`.

- [x] **Task 9: Run lint and full test suite.**
  - Commands: `make lint` then `make test`.
  - Expected: All green. Existing test `test_includes_generated_timestamp` was updated in Task 4 case 24; `test_produces_self_contained_html` continues to pass; existing `test_includes_csp_meta_tag` is replaced/strengthened per Task 4 case 18. The full suite covers Slack formatter tests (`tests/test_slack/`) which exercise consumers of `get_area_status_dashboard()` — confirms no regression.

### Acceptance Criteria

- [ ] **AC 1 (happy path — repair list rendered):** Given a non-archived area with one equipment item whose only open repair record has `status='In Progress'`, `severity='Down'`, `description='Belt slipping'`, `eta=date(2026, 6, 1)`, when `static_page_service.generate()` is called, then the returned HTML contains a `<ul class="open-records-list">` nested under that equipment's `<li class="equipment-item">` whose single `<li>` includes the substrings `In Progress`, `[Down]`, `Belt slipping`, and `ETA: Jun 01, 2026`, and has the CSS class substring `open-record-red`.

- [ ] **AC 2 (green equipment — no list):** Given a non-archived equipment item with zero open repair records, when `generate()` is called, then the HTML for that equipment contains no `open-records-list` element.

- [ ] **AC 3 (severity-priority sort, unknown folds to Not Sure):** Given one equipment item with five open repair records — `(severity='Down', created_at=2026-05-01)`, `(severity='Degraded', created_at=2026-04-15)`, `(severity='Not Sure', created_at=2026-04-01)`, `(severity=None, created_at=2026-03-01)`, `(severity='Critical', created_at=2026-02-01)` — when `generate()` is called, then in the HTML the records appear in the order: Down, Degraded, `'Critical'` (priority-2 tie, oldest `created_at`), None (priority-2 tie), Not Sure (priority-2 tie). Unknown severities and `None` both sort at the `Not Sure` priority; ties are broken by `created_at` ASC.

- [ ] **AC 4 (severity color mapping and badge visibility):** Given open repair records with severities `'Down'`, `'Degraded'`, `'Not Sure'`, `None`, and `'Critical'` (an unknown string), when `generate()` is called, then their `<li class="open-record …">` elements receive classes `open-record-red`, `open-record-yellow`, `open-record-yellow`, `open-record-gray`, and `open-record-gray` respectively. **Severity text badges (`<span class="record-severity">[…]</span>`) appear only for canonical severities** (`Down`, `Degraded`, `Not Sure`); the `None` and `'Critical'` records render WITHOUT a badge — gray border alone signals "unrecognized data."

- [ ] **AC 5 (ETA optional):** Given an open repair record with `eta=None`, when `generate()` is called for an area containing only that record's equipment, then the rendered HTML contains no `record-eta` substring.

- [ ] **AC 6 (top sub-heading format, verified end-to-end):** Given any non-empty status dashboard, when `generate()` is called using the **unpatched** `_compute_generated_at()` helper, then the HTML contains exactly one `<div class="generated-at">` whose `find()` position is greater than the position of `</h1>` and less than the position of the first `<div class="area">`. Its inner text matches the regex `Generated: \d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} \S+` (including seconds and a non-empty timezone token).

- [ ] **AC 7a (helper-wiring):** Given `_compute_generated_at()` is patched to return `('2026-05-11 14:32:15 EDT', 2026)`, when `generate()` is called, then the rendered HTML contains the exact substring `Generated: 2026-05-11 14:32:15 EDT` inside the `<div class="generated-at">`, and the footer year is `2026`.

- [ ] **AC 7b (helper formats tzname correctly):** Given `datetime.now().astimezone()` is mocked (via the exact `mock_datetime.now.return_value.astimezone.return_value = fixed_dt` chain) to return a `datetime` with `tzinfo=ZoneInfo('America/New_York')` set to `2026-07-15 14:32:15` local time, when `_compute_generated_at()` is called, then the helper returns exactly `('2026-07-15 14:32:15 EDT', 2026)`.

- [ ] **AC 7c (helper fails loud on missing tzname):** Given `datetime.now().astimezone()` returns a `datetime` whose `tzinfo.tzname(dt)` returns `None` OR `''` (empty string), when `_compute_generated_at()` is called, then it raises `RuntimeError` with a message mentioning `tzname` or `tzdata`.

- [ ] **AC 8 (site footer with a11y attributes):** Given any rendering, when `generate()` is called, then the HTML contains a `<footer class="site-footer" role="contentinfo" aria-label="Site copyright and license">` element wrapping a `<small>` that contains: the entity sequence `&copy; <YEAR> Jason Antman`, an anchor `<a href="https://github.com/jantman/equipment-status-board" …>` with `aria-label="Source code on GitHub"`, and an anchor `<a href="https://opensource.org/license/mit" …>` with `aria-label="MIT License (opensource.org)"` and link text `MIT licensed`. The HTML does NOT contain `<div class="footer">` (the old element).

- [ ] **AC 9 (footer year matches generation timestamp year):** Given `_compute_generated_at()` is patched to return year `2027`, when `generate()` is called, then the rendered footer contains the literal substring `&copy; 2027 Jason Antman` (HTML-entity form — Jinja does NOT decode `&copy;`).

- [ ] **AC 10 (still self-contained — no external sub-resources):** When `generate()` is called, then the HTML contains no `<link …>`, no `<script src="…">`, and no `<img src="http…">` or other external sub-resource references. Anchor (`<a href="…">`) links to external sites are permitted. The meta CSP tag's full directive `default-src 'none'; style-src 'unsafe-inline'` appears verbatim.

- [ ] **AC 11 (XSS defense — description is HTML-escaped):** Given a repair record with `description='<script>alert(1)</script><img src=x onerror=y>'`, when `generate()` is called, then the HTML contains `&lt;script&gt;` (escaped) and does NOT contain the literal `<script>alert(1)</script>` as a tag.

- [ ] **AC 11b (entity-content in descriptions is HTML-escaped):** Given a repair record with `description='Bob & Alice broke it; price was 50%<'`, when `generate()` is called, then the rendered HTML contains the substrings `Bob &amp; Alice broke it` and `50%&lt;` (autoescaped), and does NOT contain a bare `Bob & Alice` substring.

- [ ] **AC 12 (footer-text pin against `_footer.html`):** Given the source of `esb/templates/components/_footer.html` loaded via Flask's Jinja loader (`app.jinja_env.loader.get_source(app.jinja_env, 'components/_footer.html')[0]`), when `generate()` is called, then the three load-bearing substrings from `_footer.html` (`Jason Antman`, `https://github.com/jantman/equipment-status-board`, `https://opensource.org/license/mit`) all appear in the rendered static page HTML. Scope clarification: this AC pins owner + URLs only. Year-token markup, `<small>` wrapping, and aria-label texts are covered by AC 8 / AC 9 — not by this AC.

- [ ] **AC 13 (description preserves newlines and wraps long text):** Given any rendering, when `generate()` is called, then the rendered HTML's `<style>` block contains the verbatim substring `.record-description { white-space: pre-wrap; overflow-wrap: anywhere; }`.

- [ ] **AC 14 (single-line equipment row preserved):** When `generate()` is called for an area with at least one equipment item, then the HTML contains a `<div class="equipment-row">` wrapper, and within that wrapper the substrings `status-dot`, `equipment-name`, and `status-label` appear in that order. The new `<ul class="open-records-list">` (when rendered) is outside this wrapper but inside the parent `<li class="equipment-item">`.

- [ ] **AC 15 (`get_area_status_dashboard()` returns `open_records`):** Given an equipment item with two non-closed repair records and one record with `status='Resolved'`, when `get_area_status_dashboard()` is called, then `result[0]['equipment'][0]['open_records']` is a `list` of exactly 2 `RepairRecord` instances (the non-closed ones), in `(severity priority ASC, created_at ASC)` order, with unknown severities folded to the `Not Sure` priority.

- [ ] **AC 16 (existing tests preserved):** Existing tests in `tests/test_services/test_static_page_service.py` continue to pass after Task 4 case 24's adjustment (drop the `'UTC' in html` assertion in `test_includes_generated_timestamp`; replace with `'Generated:' in html`).

- [ ] **AC 17 (archived areas and equipment excluded):** Given one archived area named `Archived Area` and one active area named `Active Area`, when `generate()` is called, then the HTML contains `Active Area` and does NOT contain `Archived Area`. Likewise, given an active area containing one active equipment `Visible Tool` and one archived equipment `Retired Tool`, the HTML contains `Visible Tool` and does NOT contain `Retired Tool`.

- [ ] **AC 18 (empty-dashboard renders skeleton):** Given no non-archived areas exist, when `generate()` is called, then the HTML contains `<h1>Equipment Status</h1>`, `<div class="generated-at">`, and `<footer class="site-footer"`, but contains no `<div class="area">` element.

- [ ] **AC 19 (same equipment name in different areas):** Given two areas (`Area A`, `Area B`) each containing one equipment item named `Drill Press` with one `Down` open record (descriptions `'a-issue'` and `'b-issue'` respectively), when `generate()` is called, then the HTML contains both `Area A` and `Area B`, and in document order `Area A` appears before `a-issue` which appears before `Area B` which appears before `b-issue`.

### Documentation Checklist

These items are verified by code review at PR time, not by automated tests:

- [ ] **DC 1 (`docker-compose.yml` worker has TZ default):** The `worker` service's `environment:` block contains a `TZ=${TZ:-America/New_York}` entry. **This is the load-bearing change** for the local-tz feature.
- [ ] **DC 2 (`Dockerfile` defensively pins `tzdata`):** The `apt-get install` line includes `tzdata`. Note: this is a **defensive dependency pin**, not a fix for a current bug — the `python:3.14-slim` base image already ships `tzdata`. The explicit install protects against future image-content drift. Do not remove this line as a "size optimization."
- [ ] **DC 3 (admin docs document `TZ`):** `docs/administrators.md` Environment Variable Reference table contains a row for `TZ` with description, default, and example. The Static Status Page Setup section explains the env var's effect, references the `tzdata` dependency, and warns against removing it.

## Additional Context

### Dependencies

No new Python packages. The `tzdata` system package is already provided by the `python:3.14-slim` base image; the Dockerfile change makes its presence explicit as a defensive pin. No DB migration.

**Test-time tzdata note (R3F6):** Tests that instantiate `ZoneInfo('America/New_York')` (case 3 in Task 4) require tzdata to be available at runtime — provided by the OS on Linux/macOS dev machines and the Docker test image. If CI is ever moved to a stripped image without tzdata, add the PyPI `tzdata` package to `requirements-dev.txt`.

### Testing Strategy

**Unit tests (pytest, SQLite in-memory per `TestingConfig`):**

All new tests live in `tests/test_services/test_static_page_service.py` (HTML-level) and `tests/test_services/test_status_service.py` (service-level). Use the existing fixtures: `app`, `make_area`, `make_equipment`, `make_repair_record`. The `make_repair_record(equipment=None, status='New', description='Test issue', **kwargs)` signature accepts `RepairRecord` column kwargs (`severity`, `eta`, `created_at`, etc.); it does NOT accept `area` or `name`. **Always pass `equipment=…` explicitly** to avoid the fixture's auto-create-area+equipment side effect.

Strategy for tz-sensitive tests: **never** assert on the unpatched host clock except where explicitly intended (AC 6 / case 5 is the end-to-end regex check against real output). Patching: `_compute_generated_at()` directly for `generate()`-level tests; for the helper-level format test (case 3), use the exact chained-Mock setup `mock_datetime.now.return_value.astimezone.return_value = fixed_dt` to avoid the chain-ambiguity flagged in R3F4.

| Test | Covers AC |
| ---- | --------- |
| `test_open_records_listed_for_non_green_equipment` | AC 1 |
| `test_open_records_omitted_for_green_equipment` | AC 2 |
| `test_open_records_sorted_by_severity_priority_then_created_at` | AC 3 |
| `test_open_records_uses_yellow_class_for_degraded_and_not_sure` | AC 4 (canonical branches) |
| `test_open_records_uses_gray_class_for_no_severity` | AC 4 (None branch) |
| `test_open_records_uses_gray_class_and_suppresses_badge_for_unknown_severity` | AC 4 (unknown branch) |
| `test_open_records_omits_eta_when_unset` | AC 5 |
| `test_generated_at_subheading_renders_above_areas` | AC 6 (position) |
| `test_compute_generated_at_format_matches_regex` | AC 6 (format) |
| `test_generated_at_uses_local_timezone_helper` | AC 7a |
| `test_compute_generated_at_formats_tzname` | AC 7b |
| `test_compute_generated_at_raises_on_empty_tzname` | AC 7c |
| `test_site_footer_replaces_old_generated_line` | AC 8 |
| `test_footer_renders_local_tz_year_as_entity` | AC 9 |
| (existing, modified) `test_produces_self_contained_html` + `test_csp_meta_tag_directive_unchanged` | AC 10 |
| `test_description_is_html_escaped` | AC 11 |
| `test_description_escapes_entity_content` | AC 11b |
| `test_footer_text_pin` | AC 12 |
| `test_description_uses_prewrap_styles` | AC 13 |
| `test_equipment_row_keeps_dot_name_label_on_one_line` | AC 14 |
| `test_status_service.test_includes_open_records_list_per_equipment` | AC 15 |
| `test_status_service.test_open_records_sorted_by_severity_then_created_at` | AC 15 (sort) |
| (existing, modified) `test_includes_generated_timestamp` | AC 16 |
| `test_archived_areas_and_equipment_are_excluded` | AC 17 |
| `test_empty_dashboard_renders_skeleton` | AC 18 |
| `test_two_equipment_with_same_name_in_different_areas` | AC 19 |

DC 1, DC 2, DC 3 are verified by code review at PR time.

**Manual / smoke testing:**

1. Apply the changes locally.
2. `make db-up && make migrate && make run` and create at least one Area, two Equipment items, and one open `RepairRecord` per equipment (one `Down`, one `Degraded`, one `Not Sure` or `None`) via the staff UI. Include one long-text description (200+ chars) and one multi-line description (with embedded newlines) to verify wrap behavior. Add a fourth equipment with 5+ open records on a long-named equipment to verify visual spacing under the equipment row.
3. **Local dev TZ display check (limited scope — verifies dev env only, NOT production):** Set `TZ=America/New_York` in shell before running `flask shell`, then `from esb.services import static_page_service; print(static_page_service.generate())`. Confirm the output contains a non-UTC tzname like `EDT`/`EST`. **This step verifies the dev's local Python venv resolves `TZ` correctly — it does NOT verify the worker container's behavior.** Production behavior is verified by step 5 (R3F14).
4. Open the resulting `index.html` in a browser. Verify:
   - Top right under the title: `Generated: 2026-05-11 14:32:15 EDT` (or local zone).
   - Equipment header (dot + name + label + ETA) on a single line under each area.
   - Under each non-green equipment item: a list with one row per open record, colored by severity, showing status + `[severity]` badge (only for canonical severities) + description (multi-line / long text wrapping correctly) + ETA (when set). Records sorted with `Down` records on top.
   - Bottom: centered copyright footer with `<small>` wrapper, GitHub and MIT license anchors, aria-labels present (verifiable in DevTools); year matches the generation sub-heading year.
   - View source: no `<link>`, no `<script src=...>`, no external `<img>`; CSP meta tag value is `default-src 'none'; style-src 'unsafe-inline'` verbatim; `<footer>` has `role="contentinfo"` and `aria-label="Site copyright and license"`.
5. **End-to-end Docker production smoke check:** Build the image with the Dockerfile change applied. Run the actual helper inside the worker container (R4F10 — calls the real codepath, not just `datetime.now().astimezone().tzname()`):
   ```bash
   TZ=America/New_York docker compose run --rm worker python -c "from esb.services.static_page_service import _compute_generated_at; print(_compute_generated_at())"
   ```
   Confirm output looks like `('2026-05-12 14:32:15 EDT', 2026)` — non-UTC tzname, current local-tz year. This is the authoritative production verification: it exercises `_compute_generated_at()` directly, so a future regression that breaks the helper (wrong return shape, missing `.astimezone()`, etc.) will surface here. Step 3 only covers the dev's local environment.

### Notes

**Production timezone configuration.** The `docker-compose.yml` `worker` service has `TZ=${TZ:-America/New_York}` set as the default; the `Dockerfile` defensively pins `tzdata` in the apt install line (the current `python:3.14-slim` base image already includes it — verified). Operators in other zones override via the `TZ` env var in `.env`. Documented in `docs/administrators.md`. The `app` service does not need TZ. **The load-bearing change is the `TZ` env var in compose — the `tzdata` pin is defense in depth, not a current-bug fix (R3F1, R3F15, R3F16).**

**Risk: timezone test flakiness.** Mitigated. Most tz-sensitive tests patch either `_compute_generated_at()` or the `datetime` import in `static_page_service`. The end-to-end format-regex test (case 5) deliberately runs against unpatched code on the host's real clock — it verifies the format shape, not a specific zone, so it's CI-portable.

**Risk: live dashboard / Slack regression.** Task 1 adds an `open_records` key to the dict returned by `get_area_status_dashboard()`. Audited consumers: `public/status_dashboard.html`, `public/kiosk.html`, `esb/slack/forms.py::format_status_summary`, `esb/slack/forms.py::format_area_status_detail`, `esb/slack/handlers.py` `/esb-status` path. None iterate or reference `open_records`. Task 9 runs the full suite to confirm.

**Risk: severity-priority sort change.** Spec changes the sort from "created_at ASC oldest-first" (round-1 default) to "severity priority then `created_at` ASC" with unknown severities folded to `Not Sure` priority. This matches the equipment-level status-fallback behavior, eliminating the inversion bug where a yellow-coded equipment could contain a record sorting below Not Sure (R2F8).

**Risk: footer-text pin is narrowly scoped.** AC 12 / Task 4 case 15 pins owner + URLs only — not year-token markup, `<small>`, or aria-labels. Those are covered by AC 8/9. If a future edit to `_footer.html` swaps `<small>` for `<span>`, AC 12 will NOT fire; the static page will visually diverge silently. Acceptable trade-off: the alternative (full markup pin) would require rendering `_footer.html` through Jinja with mocked context, complicating the test and over-coupling the static page to the live one. The aria-label / `<small>` invariants are pinned directly against the static page in AC 8 instead.

**Risk: `severity=None` and unknown severity strings.** Repair creation paths set severity by default, but the column is nullable AND unconstrained. Spec handles both cases consistently: (a) **sort**: both fold to `Not Sure` priority (2); (b) **template class**: both map to `open-record-gray` (the `else` branch); (c) **template badge**: both suppress the badge via `{% if rec.severity in ('Down', 'Degraded', 'Not Sure') %}`. The combined effect is "gray border, no badge" for any non-canonical severity — a clear data-quality signal. Tests cover all three branches: canonical (case 8), None (case 9), unknown string (case 10).

**Explicit non-decisions:**
- **No cap on records displayed per equipment.** Static page is the fallback view; full information takes priority over visual tidiness in the rare worst case.
- **Severity text badge retained ONLY for canonical severities.** Non-canonical (`None`, unknown strings) renders without badge — gray border alone serves as the "unrecognized data" signal.
- **No empty-tzname silent fallback in `_compute_generated_at`.** Explicit `RuntimeError` on `None`-OR-empty tzname is preferred over a silent UTC-offset fallback (which would mask a deployment regression).

**Future / out of scope (do not implement now):**
- Per-area kiosk static export (would require extending `get_single_area_status_dashboard()` similarly).
- Showing `specialist_description` or `assignee` on the static page (privacy / clutter concerns).
- Localizing the timestamp into a non-system timezone via an app-level config var (currently driven by OS `TZ`).

GitHub issue #44 text:
> 1. The static status page currently just shows a list of equipment by area and operational/degraded/down state. For degraded or down equipment this should also include a list of the open repair records, their status, ETA if set, and description.
> 2. There is currently a small unobtrusive "Generated:" line at the bottom of the static page. Let's replace that with the copyright footer used on the live site, and add a sub-heading near the top right under "Equipment Status" that gives the generated date and time in the local/system timezone.

### Adversarial Review Resolution

**Round 1 (2026-05-11):** 20 findings (R1F1–R1F20), all addressed.

**Round 2 (2026-05-11):** 21 findings (R2F1–R2F21); 16 applied, 5 deferred as noise (R2F9, R2F16, R2F18, R2F20, R2F21).

**Round 3 (2026-05-11):** 17 findings (R3F1–R3F17); all 17 applied. The most significant outcome: **R3F1 invalidated the R2F1 "load-bearing tzdata fix" framing** — direct verification (`docker run --rm python:3.14-slim`) showed the base image already includes `tzdata`. The Dockerfile change is retained as a defensive dependency pin, not as a fix for a current bug; all related framing in Decision #10, Task 8, the admin docs (Task 7), and DC 2 was rewritten accordingly.

| ID | Severity | Resolution |
| --- | --- | --- |
| R3F1 | Critical | Recharacterized Task 8 as defensive pin (not "load-bearing fix"). Updated Decision #10, Task 8 notes, Notes section, admin docs (Task 7), DC 2 to remove the false "silent UTC fallback" framing. Verified base image already includes `tzdata`. |
| R3F2 | Med | Replaced "Debian bookworm-based" with explicit "Debian trixie-based (Debian 13)" in Task 8 notes; `--no-install-recommends` plus `-y` is fully non-interactive on trixie. |
| R3F3 | Med | Template severity-badge guard changed from `{% if rec.severity %}` to `{% if rec.severity in ('Down', 'Degraded', 'Not Sure') %}`. Decision #5 / Risk section now documents the consistent "gray border + no badge for non-canonical severity" rule. AC 4 expanded to assert badge suppression for both `None` and unknown strings; new test case 10. |
| R3F4 | Med | Task 4 case 3 now spells out the exact Mock chain: `mock_datetime.now.return_value.astimezone.return_value = fixed_dt`. Removes the ambiguity that could let a wrong-semantics test pass. |
| R3F5 | Med | `_compute_generated_at` now performs explicit `if not tzname: raise RuntimeError(...)` validation (catches both `None` and empty string). New AC 7c + new test case 4 pin this behavior. Decision #3 and Notes updated. |
| R3F6 | Med | Documented test-time tzdata expectation: provided by OS on dev machines / Docker image; if CI ever moves to a stripped image, add PyPI `tzdata` to dev requirements. Added a Dependencies section note. |
| R3F7 | Low | Revision history line updated to `R2F1–R2F21 (16 applied, 5 deferred as noise)` — accurate range and counts. |
| R3F8 | Low | Round-2 narrative arithmetic corrected: "fixed 16 real findings; 5 deferred as noise" (was "15 of 21"). |
| R3F9 | Low | New AC 17 + new test case 21 covering archived-area / archived-equipment exclusion. |
| R3F10 | Low | New AC 18 + new test case 22 covering empty-dashboard (`areas == []`) skeleton rendering. |
| R3F11 | Low | New AC 11b + new test case 17 covering autoescape of entity-content descriptions (`Bob & Alice`, `50%<`). |
| R3F12 | Low | New AC 19 + new test case 23 covering two equipment with the same name in different areas. |
| R3F13 | Low | Task 4 case 15 wraps `get_source()` call in try/except with a clear error message ("update this pin test's path"). |
| R3F14 | Low | Smoke step 3 (local dev) and step 5 (Docker production) clearly distinguished: step 3 explicitly notes "this step does NOT verify the worker container's behavior — see step 5." |
| R3F15 | Low | Admin docs prose rewritten: "TZ resolves against /usr/share/zoneinfo, provided by the tzdata system package. Both python:3.14-slim's defaults and this image's Dockerfile install include tzdata; do not remove it." Replaces the misleading "without tzdata it falls back to UTC" framing. |
| R3F16 | Low | DC 2 rewritten as "defensive dependency pin (not a current-bug fix)" with explicit warning against size-optimization removal. |
| R3F17 | Low | New AC 6 regex assertion + new test case 5 (`test_compute_generated_at_format_matches_regex`) runs the **unpatched** helper and asserts the format end-to-end. |

**Round 4 (2026-05-12):** 10 findings (R4F1–R4F10); 4 applied, 4 deferred as low-value polish, 2 noise. **Reviewer's explicit verdict: "spec is mature, ready for fresh dev agent; I would ship this with fix #1 applied."**

| ID | Severity | Resolution |
| --- | --- | --- |
| R4F1 | Med | Applied. `generate()` now imports `REPAIR_SEVERITIES` from `esb.models.repair_record` and passes it as `repair_severities=` template context. Template badge guard rewritten to `{% if rec.severity in repair_severities %}`. A future addition to `REPAIR_SEVERITIES` automatically picks up badge rendering without a template edit. The color-class chain in the template intentionally retains its hardcoded membership — color is a per-severity semantic decision, not derivable from list membership alone. |
| R4F2 | Low | Applied. Decision #2 now shows the same two-line `_open_records_sort_key` snippet as Task 1, removing the prior `.get()`-with-tuple-default variant. |
| R4F4 | Low | Applied. Task 4 Notes now lists explicit imports per test case: `from datetime import UTC, datetime`, `from zoneinfo import ZoneInfo`, `from unittest.mock import patch`, `from jinja2.exceptions import TemplateNotFound`, `import re`, with case-number annotations. |
| R4F10 | Low | Applied. Smoke step 5 now calls `_compute_generated_at()` directly instead of inline `datetime.now().astimezone().tzname()` — exercises the real helper codepath. |
| R4F3 | Low | Deferred. Risk that case 5's `RuntimeError` from a tzdata-missing CI masks the test's stated intent is real but rare; failure is still red. Notes section discusses the failure mode under R3F6. |
| R4F5 | Low | Deferred. `_compute_generated_at()` returns a positional 2-tuple. Tests pin the shape; a NamedTuple is cosmetic. |
| R4F6 | Low | Deferred. Decision #11 wording is fine; both patching paths are valid, and the tests demonstrate which is canonical for each use. |
| R4F7 | Low | Deferred. AC 18's "no `<div class=\"area\">`" is brittle only to a future empty-state UI; that's a separate spec when it happens. |
| R4F8 | Noise | Not applied. Regex `\S+` is fine for all IANA TZ names on Debian trixie. |
| R4F9 | Noise | Not applied. Dockerfile layer cache + ~3MB tzdata is negligible. |

**Round 1, Round 2, Round 3 resolutions remain authoritative** — see commit history for full audit trails of those rounds' fixes.
