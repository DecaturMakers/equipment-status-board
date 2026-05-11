---
title: 'Static status page export improvements'
slug: 'static-status-page-export-improvements'
created: '2026-05-11'
status: 'ready-for-dev'
stepsCompleted: [1, 2, 3, 4]
tech_stack: ['Python 3.14', 'Flask', 'Jinja2', 'pytest']
files_to_modify:
  - 'esb/services/static_page_service.py'
  - 'esb/templates/public/static_page.html'
  - 'tests/test_services/test_static_page_service.py'
code_patterns:
  - 'esb.services.status_service.get_area_status_dashboard() returns areas with computed status only — needs extension or supplementary query to expose ALL open repair records per equipment'
  - 'esb.templates.components._footer.html is the site copyright footer used on live pages; references current_year context var (injected in esb/__init__.py)'
  - 'esb.utils.filters.format_date and format_datetime are registered Jinja filters'
test_patterns:
  - 'tests/test_services/test_static_page_service.py uses make_area, make_equipment, make_repair_record fixtures; asserts on substrings in generated HTML'
---

# Tech-Spec: Static status page export improvements

**Created:** 2026-05-11

GitHub Issue: [#44](https://github.com/jantman/equipment-status-board/issues/44)

## Overview

### Problem Statement

The static status page (`esb/services/static_page_service.py` → `esb/templates/public/static_page.html`) — exported to local disk / S3 / GCS for public-facing display when the live Flask site is unavailable — has two presentation gaps:

1. **No repair detail for non-green equipment.** It lists each equipment item by area with a status dot (green/yellow/red), a label, and (for the highest-severity record only) an ETA. When equipment is Degraded or Down, the page does not enumerate the **open repair records** with their per-record status, ETA, and description, so a reader cannot see *why* equipment is impaired or *what is being done about it*.
2. **Generation metadata is inconsistent and visually weak.** A small "Generated: YYYY-MM-DD HH:MM UTC" line at the very bottom is the only branding/footer content. The live site uses a richer copyright/license footer (`esb/templates/components/_footer.html`). The static export should match the live look-and-feel, and the generation timestamp should be more prominent and in local/system timezone (not UTC).

### Solution

Update `static_page_service.generate()` to pass through (a) the open repair records per non-green equipment item and (b) a generation timestamp in the system's local timezone. Update `esb/templates/public/static_page.html` to (i) render a list of open repair records — with each record's status, ETA, and description — nested under each non-green equipment item; (ii) add a generation-time sub-heading immediately under the `<h1>Equipment Status</h1>` title, right-aligned, in local timezone; (iii) replace the bottom "Generated:" line with the site's copyright/license footer text (inlined — the static page must remain CSP-locked and have no external assets).

### Scope

**In Scope:**
- `esb/services/static_page_service.py` `generate()` — pass open repair records per equipment + local-timezone timestamp.
- `esb/templates/public/static_page.html` — repair-record list under non-green items, top sub-heading with generated time, replace bottom footer with inlined copyright text.
- Inline the copyright footer markup/text into the static template (the static page may not depend on `_footer.html` or external CSS — same self-contained / `default-src 'none'` CSP rule).
- Update `tests/test_services/test_static_page_service.py` to cover the new repair list and footer / generation-time placement.

**Out of Scope:**
- Live `public/status_dashboard.html`, kiosk views, or equipment-info pages.
- Database schema changes.
- Push delivery backends (`_push_local`, `_push_s3`, `_push_gcs`) — unchanged.
- Changes to `status_service` status derivation (color/label/severity logic stays as-is).
- Reuse of `_footer.html` via `{% include %}` — static export must remain self-contained.

## Context for Development

### Codebase Patterns

- **Self-contained static page.** `static_page.html` declares `Content-Security-Policy: default-src 'none'; style-src 'unsafe-inline'` and uses only inline `<style>`. The page must continue to render with no external `<link>` or `<script src=>` (existing test `test_produces_self_contained_html` enforces this).
- **Status derivation lives in `esb/services/status_service.py`.** `get_area_status_dashboard()` currently emits one `status` dict per equipment (computed from the highest-severity open record). The new requirement needs **all open repair records** per non-green equipment. Approach: extend `get_area_status_dashboard()` to additionally include the per-equipment list of `RepairRecord` instances in each entry (e.g., `open_records: list[RepairRecord]`). The records are already prefetched and grouped by `equipment_id` in the existing implementation (`records_by_equipment` dict), so threading the list through to the result dict is a non-disruptive add — existing callers ignoring the new key continue to work, and we avoid a near-duplicate helper. **However**, since the live dashboard uses the same call but should not show the per-record list, the template change is gated on this being the *static page* template — the live `status_dashboard.html` does not iterate `open_records`. Verify no live-page templates accidentally start rendering the new key (none do today).
- **`current_year` is injected via `app.context_processor` in `esb/__init__.py`** (`esb/__init__.py:75-76`); that processor works for `render_template()` calls so it is available to the static template without explicit kwargs.
- **Jinja filters `format_date` and `format_datetime`** (in `esb/utils/filters.py:13-32`) are registered on the app's Jinja env and usable from any template, including the static one.
- **`RepairRecord` model fields** (confirmed in `esb/models/repair_record.py`):
  - `status: str` from `REPAIR_STATUSES = ['New', 'Assigned', 'In Progress', 'Parts Needed', 'Parts Ordered', 'Parts Received', 'Needs Specialist', 'Resolved', 'Closed - No Issue Found', 'Closed - Duplicate']`. Non-closed = anything not in `CLOSED_STATUSES = ('Resolved', 'Closed - No Issue Found', 'Closed - Duplicate')`.
  - `severity: str | None` from `REPAIR_SEVERITIES = ['Down', 'Degraded', 'Not Sure']`.
  - `description: str` (Text, non-null).
  - `eta: date | None`.
  - `created_at: datetime` (UTC).
- **Severity → color map** (`status_service._SEVERITY_STATUS`): `Down`→red, `Degraded`→yellow, `Not Sure`→yellow. Use this same mapping for per-record styling in the new repair list to stay consistent.
- **Local-timezone formatting.** No existing helper. Use `datetime.now().astimezone()` (passing no `tzinfo`) — Python derives the system tz from `TZ` env / `/etc/localtime`. Format with `strftime('%Y-%m-%d %H:%M %Z')` (e.g., `2026-05-11 14:32 EDT`). If `%Z` is empty (rare; happens when `tzinfo` is a fixed offset without a name), fall back to ISO offset `%z`. Compute in the service (not Jinja) so all tz logic stays out of the template.
- **Reference precedent.** `esb/templates/public/equipment_page.html:29-46` already renders an `open_repairs` list with severity-derived `status-card-*` styling — same data shape, similar visual treatment. The static page repair list should follow the same conceptual layout (record per `<li>`, severity styling, description visible, ETA shown when set) but using *inline* CSS classes already defined in `static_page.html` (Bootstrap is unavailable in the export).

### Files to Reference

| File | Purpose |
| ---- | ------- |
| `esb/services/static_page_service.py` | Modify `generate()` to fetch repair records + local-tz timestamp. |
| `esb/services/status_service.py` | Add (or extend) a helper that returns areas with each equipment's full open-record list. |
| `esb/templates/public/static_page.html` | Render repair list, top-right generation timestamp, inline copyright footer. |
| `esb/templates/components/_footer.html` | Source of truth for the copyright/license text and link targets (used as reference; not included). |
| `esb/__init__.py` | `inject_current_year` context processor (already wired). |
| `esb/utils/filters.py` | `format_date`, `format_datetime` Jinja filters. |
| `tests/test_services/test_static_page_service.py` | Existing test class `TestGenerate`; add cases for repair list, top-right timestamp, and inline footer. |

### Technical Decisions

1. **Extend `get_area_status_dashboard()` to include an `open_records` list per equipment.** Records are already prefetched and grouped in `records_by_equipment`; threading the list through is a one-line change. Rejected the "new helper" option to avoid duplicating ~40 lines of prefetch code. Existing callers (live dashboard, kiosk) ignore the new key.
2. **Render repair records sorted by `created_at` ASC** (matches the prefetch order already used by `status_service` — `.order_by(RepairRecord.created_at, RepairRecord.id)`).
3. **Local timezone for the generation timestamp.** Use `datetime.now().astimezone()` (no `tzinfo` argument) — Python picks up the host system's TZ from `TZ` / `/etc/localtime`. The container `docker-compose.yml` / production deployment is responsible for setting `TZ`; in absence of `TZ` the default is UTC, which is acceptable. Format string: `'%Y-%m-%d %H:%M %Z'` → `2026-05-11 14:32 EDT`. If `%Z` produces an empty string (fixed-offset zones without names), fall back to `'%Y-%m-%d %H:%M %z'` → `2026-05-11 14:32 -0400`.
4. **Footer text is inlined verbatim** from `_footer.html` (copyright line + GitHub link + MIT license link) into `static_page.html`, NOT included via `{% include %}`. Reasons: (a) the static page must remain self-contained / asset-free; (b) an include couples the export to a fragment used by the live site, which is brittle if that fragment later pulls in Bootstrap classes or external icons; (c) copyright text is short and stable. Footer markup uses inline styles defined in `static_page.html` (no Bootstrap class dependency).
5. **Per-record styling**. Repair-record `<li>` items use a small inline left-border indicator color-coded by severity using the same mapping as the equipment-level dot (`Down`→red, `Degraded`/`Not Sure`→yellow, no severity → neutral gray). Display order within the record: `[status badge] [severity badge if set] description …ETA: …`.
6. **Generation sub-heading placement.** Below the `<h1>Equipment Status</h1>` block, right-aligned via `text-align: right` on a `.generated-at` div (new CSS rule). On narrow screens it remains right-aligned (CSS `text-align: right` is fine in single-column flow at any width).

## Implementation Plan

### Tasks

- [ ] **Task 1: Extend `get_area_status_dashboard()` to include per-equipment open repair records.**
  - File: `esb/services/status_service.py`
  - Action: In the loop that builds `equip_statuses` (currently lines 238-246), add `'open_records': equip_records` to the dict appended for each equipment. The list is already on hand as `records_by_equipment.get(equip.id, [])` and is ordered by `(created_at ASC, id ASC)` from the prefetch query.
  - Update the function's docstring (lines 170-186) to document the new `open_records` key — list of `RepairRecord` instances, ordered oldest-first.
  - Notes: Existing callers (live `public/status_dashboard.html`, `public/kiosk.html`, `public/kiosk_area.html`) do not iterate `open_records`, so this is additive. Do **not** change `get_single_area_status_dashboard()` for now — it is used by the per-area kiosk view; out of scope.

- [ ] **Task 2: Compute a local-timezone generation timestamp in `generate()`.**
  - File: `esb/services/static_page_service.py`
  - Action: Replace lines 22-28 (`generated_at` computation and `render_template` call) with logic that builds the timestamp using `datetime.now().astimezone()`. Try `strftime('%Y-%m-%d %H:%M %Z')`; if the resulting `%Z` portion is empty (i.e., string ends with a trailing space), fall back to `strftime('%Y-%m-%d %H:%M %z')`. Pass the string as `generated_at` to `render_template('public/static_page.html', areas=areas, generated_at=generated_at)` (template var name unchanged).
  - Notes: Keep the import inside the function (existing pattern). No new external deps.

- [ ] **Task 3: Update `static_page.html` template structure.**
  - File: `esb/templates/public/static_page.html`
  - Sub-actions:
    1. **Add top-right generation sub-heading.** Immediately after `<h1>Equipment Status</h1>` (line 28), insert `<div class="generated-at">Generated: {{ generated_at }}</div>`. Add CSS rule `.generated-at { text-align: right; font-size: 0.85rem; color: #6c757d; margin-bottom: 1rem; }` in the inline `<style>` block.
    2. **Render open-records list under non-green equipment.** Inside the `<li class="equipment-item">` loop (lines 35-40), after the existing inline status row, add a conditional block: `{% if item.status.color != 'green' and item.open_records %}<ul class="open-records-list">{% for rec in item.open_records %}<li class="open-record open-record-{{ 'red' if rec.severity == 'Down' else 'yellow' if rec.severity in ('Degraded', 'Not Sure') else 'gray' }}"><span class="record-status">{{ rec.status }}</span>{% if rec.severity %} <span class="record-severity">[{{ rec.severity }}]</span>{% endif %} <span class="record-description">{{ rec.description }}</span>{% if rec.eta %} <span class="record-eta">ETA: {{ rec.eta|format_date }}</span>{% endif %}</li>{% endfor %}</ul>{% endif %}`. Wrap the existing inline-item content in a span if needed to keep the dot/name/label on one line and push the `<ul>` to a new line — easiest: change `.equipment-item` from `flex` to `block`, wrap the dot+name+label+eta into a header `<div class="equipment-row">` with `display: flex` so the new `<ul>` lays out beneath it naturally.
    3. **Add inline CSS for the records list.**
       ```css
       .open-records-list { list-style: none; margin: 0.4rem 0 0.6rem 1.5rem; }
       .open-record { font-size: 0.85rem; padding: 0.25rem 0.4rem; margin-bottom: 0.2rem; border-left: 3px solid #6c757d; background: #fff; }
       .open-record-red { border-left-color: #dc3545; }
       .open-record-yellow { border-left-color: #ffc107; }
       .open-record-gray { border-left-color: #6c757d; }
       .record-status { font-weight: 600; }
       .record-severity { color: #6c757d; }
       .record-description { }
       .record-eta { color: #6c757d; margin-left: 0.25rem; }
       ```
    4. **Replace bottom footer.** Delete the existing `<div class="footer">Generated: {{ generated_at }}</div>` block (lines 48-50) and the corresponding `.footer` CSS rule (line 24). Insert in its place: `<footer class="site-footer" role="contentinfo">&copy; {{ current_year }} Jason Antman. <a href="https://github.com/jantman/equipment-status-board" rel="noopener noreferrer">github.com/jantman/equipment-status-board</a> <a href="https://opensource.org/license/mit" rel="noopener noreferrer">MIT licensed</a>.</footer>`. Add CSS: `.site-footer { text-align: center; margin-top: 2rem; padding-top: 1rem; border-top: 1px solid #dee2e6; font-size: 0.8rem; color: #6c757d; } .site-footer a { color: #6c757d; }` — note an `<a>` selector style is required because the document has no CSS framework reset.
  - Notes: Keep CSP unchanged (`default-src 'none'; style-src 'unsafe-inline'`). All `<a>` tags in the new footer are anchor-only (no scripts); the CSP does not need to allow `connect-src` or anything else.

- [ ] **Task 4: Add tests for the new behaviors.**
  - File: `tests/test_services/test_static_page_service.py`
  - Add the following test cases inside `class TestGenerate`:
    1. `test_generated_at_subheading_renders_above_areas` — Given an area with one equipment item, when `generate()` runs, then the HTML contains `<div class="generated-at">` and that string's index in the HTML is **less than** the index of the first `<div class="area">`.
    2. `test_generated_at_uses_local_timezone_not_hardcoded_utc` — Patch `datetime` in the service to return a fixed `datetime` whose `astimezone()` yields an EST/EDT-like tzinfo (or use `datetime.now().astimezone()` and just assert the `UTC` literal does not appear in the new subheading when system tz is non-UTC; otherwise allow `UTC`). Concretely: assert the new sub-heading does **not** end with `' UTC'` UNLESS the test's local `datetime.now().astimezone().tzname() == 'UTC'`. A simpler version: monkey-patch `static_page_service.datetime` so `datetime.now().astimezone()` returns a known timestamp with `tzname() == 'EDT'`, then assert `'2026-05-11 14:32 EDT'` (or similar) appears in the HTML.
    3. `test_open_records_listed_for_non_green_equipment` — Create equipment with one `make_repair_record(status='In Progress', severity='Down', description='Belt slipping', eta=date(2026, 6, 1))`. Assert HTML contains `'In Progress'`, `'Belt slipping'`, `'[Down]'`, and `'ETA: ' + date(2026, 6, 1).strftime('%b %d, %Y')` AND contains a `class="open-record open-record-red"` substring.
    4. `test_open_records_omitted_for_green_equipment` — Create equipment with no repair records. Assert HTML does NOT contain `class="open-records-list"`.
    5. `test_open_records_uses_yellow_class_for_degraded_and_not_sure` — Create two equipment items, one with severity `'Degraded'` and one with `'Not Sure'`. Assert both render `class="open-record open-record-yellow"`.
    6. `test_open_records_uses_gray_class_for_no_severity` — Create a repair record with `severity=None` (raw). Assert `class="open-record open-record-gray"` appears AND the equipment's color falls back per `_derive_status_from_records` (yellow Degraded). Severity badge `[…]` must NOT appear since severity is `None`.
    7. `test_open_records_omits_eta_when_unset` — Repair record with `eta=None`. Assert `record-eta` class does not appear in the rendered `<li class="open-record …">` block.
    8. `test_open_records_ordered_by_created_at_asc` — Create two records on the same equipment, the second with an earlier `created_at`. Assert the earlier record appears first in the HTML (substring index check).
    9. `test_site_footer_replaces_old_generated_line` — Assert HTML contains `'Jason Antman'`, `'github.com/jantman/equipment-status-board'`, and `'MIT licensed'`, AND does NOT contain `'<div class="footer">'` (the old class name).
    10. `test_footer_renders_current_year` — Patch `datetime.now()` in `inject_current_year` (or just assert the rendered current year matches `datetime.now(timezone.utc).year`).
    11. **Update existing `test_includes_generated_timestamp`** — it currently asserts `'UTC' in html`. Replace that assertion with `'Generated:' in html` only (timezone now depends on host); or keep `'UTC'` only if the host TZ is UTC. Safest: change to assert `'Generated:' in html`.
  - Notes: The fixtures `make_area`, `make_equipment`, `make_repair_record` accept `area`, `name`, `status`, `severity`, `description`, `eta`, etc. as kwargs (per existing tests in this same file).

- [ ] **Task 5: Run lint and full test suite.**
  - Commands: `make lint` then `make test`.
  - Expected: All green. Existing test `test_includes_generated_timestamp` was updated in Task 4.11; `test_produces_self_contained_html` continues to pass (no new `<link>` or `<script src=>`).

### Acceptance Criteria

- [ ] **AC 1 (happy path — repair list rendered):** Given a non-archived area with one equipment item whose only open repair record has `status='In Progress'`, `severity='Down'`, `description='Belt slipping'`, `eta=2026-06-01`, when `static_page_service.generate()` is called, then the returned HTML contains a `<ul class="open-records-list">` nested under that equipment's `<li class="equipment-item">` whose single `<li>` includes the substrings `In Progress`, `[Down]`, `Belt slipping`, and `ETA: Jun 01, 2026`, and has CSS class `open-record-red`.

- [ ] **AC 2 (green equipment — no list):** Given a non-archived equipment item with zero open repair records, when `generate()` is called, then the HTML for that equipment contains no `open-records-list` element.

- [ ] **AC 3 (multiple records — ordering):** Given one equipment item with two open repair records (record A `created_at = 2026-04-01`, record B `created_at = 2026-05-01`), when `generate()` is called, then the substring for record A appears before the substring for record B in the HTML (oldest first).

- [ ] **AC 4 (severity color mapping):** Given open repair records with severities `'Down'`, `'Degraded'`, `'Not Sure'`, and `None`, when `generate()` is called, then their `<li class="open-record …">` elements receive classes `open-record-red`, `open-record-yellow`, `open-record-yellow`, and `open-record-gray` respectively, and the `None`-severity record does **not** render a `[…]` severity badge.

- [ ] **AC 5 (ETA optional):** Given an open repair record with `eta=None`, when `generate()` is called, then its rendered `<li class="open-record …">` does not include a `record-eta` span and contains no `ETA:` substring.

- [ ] **AC 6 (top sub-heading present and positioned):** Given any non-empty status dashboard, when `generate()` is called, then the HTML contains exactly one element matching `<div class="generated-at">` whose position in the document is after the closing tag of `<h1>Equipment Status</h1>` and before the first `<div class="area">`. Its inner text starts with `Generated: ` followed by a `YYYY-MM-DD HH:MM ` and a non-empty timezone token.

- [ ] **AC 7 (local timezone, not UTC by default):** Given the host system's local timezone is set to `America/New_York` (`TZ=America/New_York`), when `generate()` is called, then the `<div class="generated-at">` content ends with either `EST` or `EDT` (depending on date), and does NOT contain the literal string `UTC` in the sub-heading. (Acceptance under containerized prod requires `TZ` to be set in `docker-compose.yml` / deployment — see Notes.)

- [ ] **AC 8 (timezone fallback for unnamed offsets):** Given a `datetime.astimezone()` result whose `tzname()` returns `None` or empty string (e.g., a fixed-offset zone), when `generate()` is called, then the sub-heading contains an ISO offset like `+0000` or `-0400` instead of an empty trailing space.

- [ ] **AC 9 (site footer replaces "Generated:" line):** Given any rendering, when `generate()` is called, then the HTML contains a `<footer class="site-footer">` element whose text includes `© <YEAR> Jason Antman`, an anchor to `https://github.com/jantman/equipment-status-board`, and an anchor to `https://opensource.org/license/mit` (text `MIT licensed`), AND the HTML does NOT contain the old `<div class="footer">` element.

- [ ] **AC 10 (year derives from `current_year` context):** Given the current year is 2026, when `generate()` is called, then the rendered footer contains `© 2026 Jason Antman`.

- [ ] **AC 11 (still self-contained):** When `generate()` is called, then the HTML contains no `<link …>` and no `<script src="…">`, and the meta CSP tag `default-src 'none'; style-src 'unsafe-inline'` is unchanged.

- [ ] **AC 12 (existing assertions preserved):** Existing tests in `tests/test_services/test_static_page_service.py` continue to pass after Task 4.11's adjustment of `test_includes_generated_timestamp` (assert only `'Generated:' in html`, drop the `'UTC' in html` assertion).

## Additional Context

### Dependencies

None new — uses existing `datetime`, Flask, Jinja2. No DB migration. No new packages.

### Testing Strategy

**Unit tests (pytest, SQLite in-memory per `TestingConfig`):**

All new tests live in `tests/test_services/test_static_page_service.py` inside `class TestGenerate`. Use the existing fixtures: `app`, `make_area`, `make_equipment`, `make_repair_record`. Assertions are substring / index-position checks against the rendered HTML string returned by `static_page_service.generate()`.

New test cases (one per AC group):

| Test | Covers AC |
| ---- | --------- |
| `test_open_records_listed_for_non_green_equipment` | AC 1 |
| `test_open_records_omitted_for_green_equipment` | AC 2 |
| `test_open_records_ordered_by_created_at_asc` | AC 3 |
| `test_open_records_uses_yellow_class_for_degraded_and_not_sure` | AC 4 |
| `test_open_records_uses_gray_class_for_no_severity` | AC 4 (None severity branch) |
| `test_open_records_omits_eta_when_unset` | AC 5 |
| `test_generated_at_subheading_renders_above_areas` | AC 6 |
| `test_generated_at_uses_local_timezone_not_hardcoded_utc` | AC 7 (monkey-patch system tz via `datetime` patch or `os.environ['TZ']` + `time.tzset()`) |
| `test_generated_at_falls_back_to_iso_offset_when_tzname_empty` | AC 8 |
| `test_site_footer_replaces_old_generated_line` | AC 9 |
| `test_footer_renders_current_year` | AC 10 |
| (existing) `test_produces_self_contained_html` | AC 11 (no change required; should still pass) |
| (existing, modified) `test_includes_generated_timestamp` | AC 12 (drop `'UTC' in html` assertion; keep `'Generated:' in html`) |

**Manual / smoke testing:**

1. Apply the changes locally.
2. Start the dev server (`make db-up && make migrate && make run`).
3. Create at least one Area, two Equipment items, and one open `RepairRecord` per equipment (one `Down`, one `Degraded`) via the staff UI.
4. Run `flask shell` and call `from esb.services import static_page_service; print(static_page_service.generate())` (or hit the static export path on disk via `STATIC_PAGE_PUSH_METHOD=local`).
5. Open the resulting `index.html` in a browser. Verify:
   - Top right under the title: `Generated: 2026-05-11 14:32 EDT` (or local zone).
   - Under each non-green equipment item: a bullet-less list with one row per open record, colored by severity, showing status + description + ETA.
   - Bottom: centered copyright footer with the GitHub and MIT license links.
   - View source: no `<link>`, no `<script src=...>`, CSP meta tag unchanged.

### Notes

**Production timezone configuration.** The local-timezone behavior depends on the container's `TZ` env var. The current `docker-compose.yml` does not set `TZ` on the `app` or `worker` services, so a default deployment will render `UTC`. To get a true local time, the operator must set `TZ` in the `worker` service environment (it's the `worker` that calls `generate_and_push()` via the notification handler — `app` itself doesn't invoke `generate()` on a request path). This is a deployment-config concern; document it in a follow-up but do NOT modify `docker-compose.yml` as part of this spec.

**Risk: timezone test flakiness.** Tests that assert the timezone abbreviation depend on the runner's `TZ`. The strategy in Task 4 is to monkey-patch the `datetime` object returned in the service (so test outcome is independent of the host TZ). Avoid asserting raw `EDT`/`EST` against the unpatched system clock — CI is typically UTC.

**Risk: live dashboard regression.** Task 1 adds an `open_records` key to the dict returned by `get_area_status_dashboard()`. Existing live templates (`status_dashboard.html`, `kiosk.html`, `kiosk_area.html`) iterate the dict's `equipment` list but reference only `item.equipment` and `item.status`. Verified manually during Step 2; no template change needed for the live site. Run the full test suite (`make test`) after Task 1 to confirm no regressions.

**Risk: `_derive_status_from_records` "Not Sure" mapping.** A repair record with `severity='Not Sure'` produces `color='yellow'` at the equipment level (per `_SEVERITY_STATUS`). The per-record visual treatment in the new repair list also uses yellow for `Not Sure` (Task 3.2 mapping), so the equipment dot and the record's left-border match. A record with `severity=None` is unusual (severity is nullable but the create paths set it); guard with the `gray` fallback so we never crash on a missing key.

**Future / out of scope (do not implement now):**
- Per-area kiosk static export (would require extending `get_single_area_status_dashboard()` similarly).
- Sorting open records by severity instead of `created_at` ASC.
- Showing `specialist_description` or `assignee` on the static page (privacy / clutter concerns).
- Localizing the timestamp into a non-system timezone via a config var.

GitHub issue #44 text:
> 1. The static status page currently just shows a list of equipment by area and operational/degraded/down state. For degraded or down equipment this should also include a list of the open repair records, their status, ETA if set, and description.
> 2. There is currently a small unobtrusive "Generated:" line at the bottom of the static page. Let's replace that with the copyright footer used on the live site, and add a sub-heading near the top right under "Equipment Status" that gives the generated date and time in the local/system timezone.
