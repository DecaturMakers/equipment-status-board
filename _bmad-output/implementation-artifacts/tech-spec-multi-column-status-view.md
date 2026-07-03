---
title: 'Multi-Column Kiosk Status Views'
slug: 'multi-column-status-view'
created: '2026-07-02'
status: 'Completed'
stepsCompleted: [1, 2, 3, 4]
tech_stack: ['Python 3.14', 'Flask', 'Flask blueprints', 'Jinja2', 'Bootstrap 5', 'vanilla JS', 'pytest']
files_to_modify: ['esb/views/public.py', 'esb/templates/public/kiosk_dense.html (new)', 'esb/static/css/app.css', 'esb/templates/public/status_dashboard.html', 'tests/test_views/test_public_views.py']
code_patterns: ['views delegate to status_service', 'kiosk templates extend base_kiosk.html', '#kiosk-scale-content shrink-to-fit auto-scale', 'populated_areas selectattr filter', 'dense status-dot styling from static_page.html']
test_patterns: ['pytest classes in tests/test_views/test_public_views.py', 'client/staff_client/tech_client fixtures', 'make_area/make_equipment/make_repair_record fixtures', 'assert on rendered HTML substrings']
---

# Tech-Spec: Multi-Column Kiosk Status Views

**Created:** 2026-07-02

## Overview

### Problem Statement

Feedback from the Oops Team (technician) meeting was that the current Kiosk
displays aren't information-dense enough for some use cases and that additional,
more information-dense options are needed. Technicians want additional kiosk
display options modeled on the current **concise static status page**, but with
**2-column and 3-column layouts** to optimize information density for small
screens without scrolling. (GitHub Issue #71 — "Multi-Column Status View".)

### Solution

Add two new **live Flask routes** under the `public` blueprint that render the
dense static-page-style status content using the existing **kiosk
infrastructure** (`base_kiosk.html` + the `#kiosk-scale-content` shrink-to-fit
auto-scale + 60s meta-refresh), laid out as a fixed **2- or 3-column CSS grid of
intact area blocks**. Surface both as new entries in the "Kiosk View" dropdown
on `/public/`.

### Scope

**In Scope:**
- New live route(s) for a 2-column and a 3-column dense kiosk view (public blueprint).
- New Jinja template modeled on `static_page.html`'s dense styling (status dots +
  inline open-record lines), extending `base_kiosk.html` and wrapped in
  `#kiosk-scale-content` so the existing auto-scale guarantees no scrolling.
- CSS grid layout placing N intact area blocks per row (areas as whole blocks — an
  area never splits across columns), driven by column count (2 or 3).
- Two new entries in the "Kiosk View" dropdown in `status_dashboard.html`.
- Tests for the new route(s) (SQLite in-memory, following existing public-view test patterns).

**Out of Scope:**
- Any change to the **generated/pushed static page** — `static_page_service`,
  `static_page.html`, and the GCS/S3/local export path stay exactly as-is.
- Changes to the existing all-equipment kiosk (`public.kiosk`) or per-area kiosk
  (`public.kiosk_area`) views/templates.
- Any new status/data computation — reuse `status_service.get_area_status_dashboard()`.

## Context for Development

### Codebase Patterns

- **Views delegate to services**: `public.py` routes call
  `status_service.get_area_status_dashboard()` and render a template; no direct
  model queries. New route follows the same shape as `public.kiosk` (`public.py:31`).
- **Data shape** from `get_area_status_dashboard()` (`status_service.py:186`):
  `list[ {'area': Area, 'equipment': [ {'equipment': Equipment, 'status':
  {color,label,issue_description,severity,eta,assignee_name}, 'open_records':
  [RepairRecord,...]} ]} ]`. `open_records` is the list of non-closed
  `RepairRecord` rows (sorted for display) — this is what the dense static page
  iterates. Same shape the existing kiosk consumes, plus `open_records`.
- **Kiosk no-scroll machinery**: `base_kiosk.html` loads Bootstrap + `app.css` +
  `app.js` and sets a 60s `<meta http-equiv="refresh">`. Content wrapped in an
  element with `id="kiosk-scale-content"` is measured by `app.js`
  (`applyKioskScale`, defined at `app.js:200`; the `getElementById` lookup is at
  `app.js:192`) and given `transform: scale(<=1)` to fit the
  viewport. Contract: **only `transform`** may be applied to
  `#kiosk-scale-content` (non-transform styles break the scrollWidth/Height
  measurement). Note: `applyKioskScale` only ever **shrinks** (`Math.min(1, …)`);
  it never enlarges content to fill an under-full viewport — see the sparse-board
  limitation in Notes.
- **`.kiosk-body`** sets `overflow:hidden`, so any content that would overflow is
  clipped, not scrolled — the auto-scale is what keeps everything visible.
- **Dense static styling** lives in `static_page.html` (self-contained inline
  CSS): status dots (`.status-dot` + `.status-{green|yellow|red}`), and inline
  open-record lines colored by severity (red for `Down`, yellow for
  `Degraded`/`Not Sure`, gray otherwise). The new view reproduces this *style* but
  as a `base_kiosk.html` child, so the dense CSS must be added to `app.css`.
  **Caution [F1]:** `.status-dot`/`.status-{color}` are NOT unique names —
  `components/_status_indicator.html` **would** emit `.status-dot` in its
  `minimal` variant. That variant is **currently unused** (zero call sites; the
  live includes in `status_dashboard.html`, `equipment_page.html`, `kiosk.html`
  use the `compact`/`large` variants, which do not emit `.status-dot`), so an
  unscoped rule would be harmless *today*. Still, scope the dense CSS defensively
  under `.kiosk-dense-grid` (see Task 3) so it can never bleed into that shared
  component if `minimal` is adopted later. The `.record-*` names are
  static-page-only.
- **Template globals**: `format_date` is a registered Jinja filter
  (`filters.py:101`) — globally available. `repair_severities` is **NOT** a
  context processor; it is passed explicitly to `static_page.html` by the service.
  The new route must pass `repair_severities=REPAIR_SEVERITIES` (from
  `esb.models.repair_record`) if it renders the `[severity]` badge guard.
- **Empty-state handling**: kiosk templates compute
  `populated_areas = areas | selectattr('equipment') | list` and show a
  "No equipment registered yet." message when empty. Dense view mirrors this.
- **Dropdown**: the "Kiosk View" dropdown is in `status_dashboard.html:13-33`;
  entries are Bootstrap `dropdown-item` links to `url_for(...)` routes.

### Technical Decisions (from informed discovery)

1. **Foundation = Kiosk infra + dense style.** New live route renders through
   `base_kiosk.html` and wraps content in `#kiosk-scale-content` to reuse the
   proven shrink-to-fit auto-scale + 60s refresh. (Not a standalone static-page clone.)
2. **Column layout = CSS grid, areas as blocks.** N-column CSS grid where each
   whole area-section stays intact in one grid cell (no area splitting across a
   column break). Column count is driven by a CSS custom property set inline on
   the grid (`style="--kiosk-dense-cols: {{ columns }}"`) →
   `grid-template-columns: repeat(var(--kiosk-dense-cols), 1fr)`. Column heights
   may be uneven; accepted. (Live app pages have no strict CSP, so the inline
   `style` attribute is fine — unlike the CSP-locked `static_page.html`.)
3. **Single parameterized route** `public.kiosk_dense` at
   `/public/kiosk/dense/<int:columns>`, validating `columns in (2, 3)` else
   `abort(404)`. `dense` is a string segment so it never collides with the
   existing `/public/kiosk/<int:area_id>` int route. Two dropdown entries point at
   `columns=2` and `columns=3`.
4. **Pushed static page unchanged.** Only the two live dropdown views are added;
   `static_page_service` and the exported page are untouched.

### Files to Reference

| File | Purpose |
| ---- | ------- |
| `esb/views/public.py` | Add `kiosk_dense(columns)` route; mirror `public.kiosk` (line 31). |
| `esb/services/status_service.py` | `get_area_status_dashboard()` (line 186) — data source, no change. |
| `esb/templates/public/static_page.html` | Source of dense styling (dots + inline records) to reproduce. |
| `esb/templates/public/kiosk.html` | Pattern for `base_kiosk.html` child + `#kiosk-scale-content` + populated_areas. |
| `esb/templates/base_kiosk.html` | Kiosk shell (Bootstrap/app.css/app.js, 60s refresh) the new template extends. |
| `esb/static/js/app.js` (`applyKioskScale`, line 200) | Auto-scale contract (shrink-only, `Math.min(1, …)`); no change, just relied upon. |
| `esb/static/css/app.css` (line 75+) | Add `.kiosk-dense-*` classes near existing kiosk CSS. |
| `esb/templates/public/status_dashboard.html` (lines 13-33) | Add two dropdown entries. |
| `esb/models/repair_record.py` (`REPAIR_SEVERITIES`, line 20) | Passed to template as `repair_severities`. |
| `tests/test_views/test_public_views.py` | Add tests near existing kiosk/dropdown tests. |

## Implementation Plan

### Tasks

- [x] **Task 1: Add the `kiosk_dense` route to the public blueprint.**
  - File: `esb/views/public.py`
  - Action: Add a new route right after `kiosk_area` (line 54):
    ```python
    @public_bp.route('/kiosk/dense/<int:columns>')
    def kiosk_dense(columns):
        """Multi-column dense kiosk display -- concise static-page-style
        status for wall-mounted / small displays, in a 2- or 3-column grid."""
        if columns not in (2, 3):
            abort(404)
        from esb.models.repair_record import REPAIR_SEVERITIES
        from esb.services import status_service

        areas = status_service.get_area_status_dashboard()
        return render_template(
            'public/kiosk_dense.html',
            areas=areas,
            columns=columns,
            repair_severities=REPAIR_SEVERITIES,
        )
    ```
  - Notes: `abort` and `render_template` are already imported at the top of the
    file (line 10). Validate `columns in (2, 3)` and `abort(404)` for anything
    else so only the two intended widths are reachable. The `dense` path segment
    is a string, so this never collides with the existing
    `/kiosk/<int:area_id>` route.

- [x] **Task 2: Create the dense kiosk template.**
  - File: `esb/templates/public/kiosk_dense.html` (new)
  - Action: Extend `base_kiosk.html`, wrap all content in
    `<div id="kiosk-scale-content" class="kiosk-scale-wrapper">` so the existing
    `app.js` auto-scale fits it to the viewport. Build a grid of intact area
    blocks; reproduce the dense static-page style (status dot + name + label +
    optional ETA, plus inline open-record lines for non-green items):
    ```jinja
    {% extends "base_kiosk.html" %}

    {% block title %}Equipment Status - Kiosk ({{ columns }}-Column){% endblock %}

    {% block content %}
    <h1 class="visually-hidden">Equipment Status</h1>
    <div id="kiosk-scale-content" class="kiosk-scale-wrapper">
    {% set populated_areas = areas | selectattr('equipment') | list %}
    {% if not populated_areas %}
      <div class="text-center py-5">
        <p class="fs-3 text-muted">No equipment registered yet.</p>
      </div>
    {% else %}
      <div class="kiosk-dense-grid" style="--kiosk-dense-cols: {{ columns }};">
        {% for area_data in populated_areas %}
        <section class="kiosk-dense-area">
          <h2 class="kiosk-dense-area-heading">{{ area_data.area.name }}</h2>
          <ul class="kiosk-dense-list">
            {% for item in area_data.equipment %}
            <li class="kiosk-dense-item">
              <div class="kiosk-dense-row">
                <span class="status-dot status-{{ item.status.color }}" aria-hidden="true"></span>
                <span class="kiosk-dense-name">{{ item.equipment.name }}</span>
                <span class="kiosk-dense-status">{{ item.status.label }}</span>
                {% if item.status.eta %}<span class="kiosk-dense-eta">ETA: {{ item.status.eta|format_date }}</span>{% endif %}
              </div>
              {% if item.status.color != 'green' and item.open_records %}
              <ul class="kiosk-dense-records">
                {% for rec in item.open_records %}
                <li class="kiosk-dense-record kiosk-dense-record-{{ 'red' if rec.severity == 'Down' else 'yellow' if rec.severity in ('Degraded', 'Not Sure') else 'gray' }}">
                  <span class="record-status">{{ rec.status }}</span>{% if rec.severity in repair_severities %} <span class="record-severity">[{{ rec.severity }}]</span>{% endif %} <span class="record-description">{{ rec.description }}</span>{% if rec.eta %} <span class="record-eta">ETA: {{ rec.eta|format_date }}</span>{% endif %}
                </li>
                {% endfor %}
              </ul>
              {% endif %}
            </li>
            {% endfor %}
          </ul>
        </section>
        {% endfor %}
      </div>
    {% endif %}
    </div>
    {% endblock %}
    ```
  - Notes: Column count is passed via the inline CSS custom property
    `--kiosk-dense-cols` (live app pages have no strict CSP, so an inline `style`
    attribute is allowed). The severity→color chain and the
    `rec.severity in repair_severities` badge guard are copied verbatim from
    `static_page.html:65-66` to preserve identical semantics. Do not put anything
    other than the scale wrapper on `#kiosk-scale-content`.

- [x] **Task 3: Add dense-kiosk CSS.**
  - File: `esb/static/css/app.css`
  - Action: Add the following near the existing "Kiosk display" block (after
    line 97). Status colors use Bootstrap CSS variables (`--bs-success` etc.);
    neutral greys and the record background are literal values (with Bootstrap-var
    fallbacks where a matching var exists). **Every selector is scoped under
    `.kiosk-dense-grid`** so nothing leaks to the rest of the app:
    ```css
    /* Multi-column dense kiosk (static-page style) */
    .kiosk-dense-grid {
        display: grid;
        grid-template-columns: repeat(var(--kiosk-dense-cols), 1fr);
        gap: 1rem 1.5rem;
        align-items: start;
    }
    .kiosk-dense-grid .kiosk-dense-area-heading {
        font-size: 1.5rem;
        border-bottom: 2px solid var(--bs-border-color, #dee2e6);
        padding-bottom: 0.25rem;
        margin-bottom: 0.4rem;
    }
    .kiosk-dense-grid .kiosk-dense-list { list-style: none; padding-left: 0; margin: 0; }
    .kiosk-dense-grid .kiosk-dense-item { padding: 0.15rem 0; }
    .kiosk-dense-grid .kiosk-dense-row { display: flex; flex-wrap: wrap; align-items: center; gap: 0.4rem; }
    .kiosk-dense-grid .status-dot {
        width: 12px; height: 12px; border-radius: 50%;
        display: inline-block; flex-shrink: 0;
    }
    .kiosk-dense-grid .status-dot.status-green { background-color: var(--bs-success); }
    .kiosk-dense-grid .status-dot.status-yellow { background-color: var(--bs-warning); }
    .kiosk-dense-grid .status-dot.status-red { background-color: var(--bs-danger); }
    .kiosk-dense-grid .kiosk-dense-name { font-weight: 600; overflow-wrap: anywhere; }
    .kiosk-dense-grid .kiosk-dense-status,
    .kiosk-dense-grid .kiosk-dense-eta { color: var(--bs-secondary-color, #6c757d); font-size: 0.9rem; }
    .kiosk-dense-grid .kiosk-dense-records { list-style: none; margin: 0.2rem 0 0.3rem 1.5rem; padding-left: 0; }
    .kiosk-dense-grid .kiosk-dense-record {
        font-size: 0.85rem; padding: 0.15rem 0.4rem; margin-bottom: 0.15rem;
        border-left: 3px solid var(--bs-secondary-color, #6c757d);
        background: var(--bs-body-bg, #fff);
    }
    .kiosk-dense-grid .kiosk-dense-record-red { border-left-color: var(--bs-danger); }
    .kiosk-dense-grid .kiosk-dense-record-yellow { border-left-color: var(--bs-warning); }
    .kiosk-dense-grid .kiosk-dense-record-gray { border-left-color: var(--bs-secondary-color, #6c757d); }
    .kiosk-dense-grid .kiosk-dense-record .record-status { font-weight: 600; }
    .kiosk-dense-grid .kiosk-dense-record .record-severity,
    .kiosk-dense-grid .kiosk-dense-record .record-eta { color: var(--bs-secondary-color, #6c757d); }
    .kiosk-dense-grid .kiosk-dense-record .record-description { white-space: pre-wrap; overflow-wrap: anywhere; }
    ```
  - Notes: **[F1]** `.status-dot` and `.status-{green|yellow|red}` are ALREADY
    global class names — emitted by `components/_status_indicator.html` (the
    `minimal` variant) which is included by `status_dashboard.html`,
    `equipment_page.html`, and `kiosk.html`, all of which load `app.css`.
    Therefore **every rule above is scoped under `.kiosk-dense-grid`** (a
    descendant combinator) so the new dense styling cannot alter that shared
    component or any other page. Do NOT add bare, unscoped `.status-dot` rules.
    **[F7]** `--kiosk-dense-cols` has no CSS fallback: if the inline custom
    property is ever dropped, `grid-template-columns` becomes invalid and is
    dropped, so the grid degrades to a single stacked column — an obvious visual
    break — rather than silently rendering a plausible-looking 2 columns and
    masking a broken 3-col route. The route always sets the property.
    `.kiosk-dense-name` also carries `overflow-wrap: anywhere` [R2-2] so a long
    unbroken equipment name can't overflow its `1fr` cell and force uniform
    down-scaling.

- [x] **Task 4: Add the two dropdown entries.**
  - File: `esb/templates/public/status_dashboard.html`
  - Action: Immediately after the "All Equipment" list item (line 19), add:
    ```jinja
    <li><a class="dropdown-item" href="{{ url_for('public.kiosk_dense', columns=2) }}">All Equipment (2-Column)</a></li>
    <li><a class="dropdown-item" href="{{ url_for('public.kiosk_dense', columns=3) }}">All Equipment (3-Column)</a></li>
    ```
  - Notes: Placed before the per-area divider/list so the three "All Equipment"
    variants group together. The per-area section below is unchanged.
    **[F3]** These two links sit OUTSIDE the `{% if populated_areas %}` guard, so —
    exactly like the plain "All Equipment" link — they render even when the board
    has no equipment. This is intentional and consistent with the existing link.
    It does NOT break `test_dashboard_kiosk_dropdown_only_all_equipment_when_no_areas`
    (`test_public_views.py:145`): that test's regex `href="/public/kiosk/\d+"`
    requires a digit immediately after `/kiosk/`, which `/public/kiosk/dense/2`
    does not match. Covered explicitly by the new empty-board dropdown test (AC 11).

- [x] **Task 5: Add tests for the new route and dropdown.**
  - File: `tests/test_views/test_public_views.py`
  - Action: Add tests (see Testing Strategy for the full list) covering: 2-col
    and 3-col render 200 and include equipment/area/record content; invalid
    column counts (e.g. 1, 4, 0) return 404; the dashboard dropdown links to both
    new routes. Follow existing patterns (`client`, `make_area`,
    `make_equipment`, `make_repair_record`, substring asserts on `resp.data`).

### Acceptance Criteria

- [ ] **AC 1 (happy path, 2-col):** Given areas with equipment exist, when an
  unauthenticated user requests `GET /public/kiosk/dense/2`, then the response is
  `200` and the HTML contains each area name, each equipment name, and
  `--kiosk-dense-cols: 2`.
- [ ] **AC 2 (happy path, 3-col):** Given areas with equipment exist, when a user
  requests `GET /public/kiosk/dense/3`, then the response is `200` and the HTML
  contains `--kiosk-dense-cols: 3` and the `kiosk-dense-grid` container.
- [ ] **AC 3 (dense records shown):** Given an equipment item has an open repair
  record making it non-green, when the dense view is rendered, then the record's
  **unique description text** appears inline under that equipment item.
  **[F6]** Assert on the description (a distinctive, test-controlled string), NOT
  on `rec.status` — repair statuses like "New"/"Assigned" are common substrings
  and would make the assertion pass spuriously.
- [ ] **AC 4 (green items have no records list):** Given an equipment item is
  green (no open records), when the dense view is rendered, then no
  `kiosk-dense-records` list is emitted for that item.
- [ ] **AC 5 (invalid column count → 404):** Given any request, when a user
  requests `GET /public/kiosk/dense/1`, `/public/kiosk/dense/4`, or
  `/public/kiosk/dense/0`, then the response is `404`.
- [ ] **AC 6 (non-int column count → 404):** Given a request to
  `GET /public/kiosk/dense/foo`, then the response is `404` (route int converter
  does not match), and the existing `/public/kiosk/<int:area_id>` route is
  unaffected.
- [ ] **AC 7 (empty state):** Given no areas have equipment, when the dense view
  is requested, then the response is `200` and shows "No equipment registered
  yet." with no `kiosk-dense-grid`.
- [ ] **AC 8 (auto-scale wired):** Given the dense view is rendered, then the
  `kiosk-dense-grid` content is wrapped in an element with
  `id="kiosk-scale-content"` so the existing kiosk shrink-to-fit auto-scale
  applies. **[F8] Caveat:** the shared `_footer.html` (from `base_kiosk.html:17`)
  renders OUTSIDE `#kiosk-scale-content` and is therefore unscaled; under
  `.kiosk-body { overflow:hidden }` an over-tall footer can be clipped. This is
  pre-existing kiosk behavior (identical in `kiosk.html`), not introduced here —
  so AC 8 asserts the wrapper is present, not that the footer is guaranteed visible.
- [ ] **AC 9 (dropdown entries):** Given areas with equipment exist, when the
  `/public/` dashboard is rendered, then the "Kiosk View" dropdown contains links
  to `/public/kiosk/dense/2` and `/public/kiosk/dense/3`.
- [ ] **AC 10 (pushed static page untouched):** Given this change is deployed,
  then `static_page_service.generate()` output and `static_page.html` are byte-for-byte
  unchanged (no regression in the existing static-page tests).
- [ ] **AC 11 (dense links present on empty board):** Given NO areas have
  equipment, when the `/public/` dashboard is rendered, then the "Kiosk View"
  dropdown STILL contains the `/public/kiosk/dense/2` and `/public/kiosk/dense/3`
  links (they are ungated, like the plain "All Equipment" link), and the existing
  `test_dashboard_kiosk_dropdown_only_all_equipment_when_no_areas` still passes.

## Additional Context

### Dependencies

- **No new libraries.** Uses existing Flask, Jinja2, Bootstrap 5, and the
  existing kiosk `app.js` auto-scale. No migrations, no config changes.
- **Data dependency:** `status_service.get_area_status_dashboard()` (unchanged) —
  already returns `open_records` per equipment item, which the dense view needs.
- **Template global:** `format_date` filter (already registered). `repair_severities`
  passed explicitly by the new route.

### Testing Strategy

Add to `tests/test_views/test_public_views.py`, mirroring the existing kiosk /
dropdown tests. All use SQLite in-memory (`TestingConfig`, CSRF disabled).

**Route tests (new class `TestKioskDenseView` or added to the kiosk test class):**
- `test_dense_2col_renders_200_unauthenticated` — `make_area` + `make_equipment`,
  `GET /public/kiosk/dense/2` → 200, asserts area name, equipment name, and
  `--kiosk-dense-cols: 2` in `resp.data`. (AC 1)
- `test_dense_3col_renders` — `GET /public/kiosk/dense/3` → 200, asserts
  `--kiosk-dense-cols: 3` and `kiosk-dense-grid`. (AC 2)
- `test_dense_shows_open_records` — `make_repair_record` with a `Down` severity and
  a distinctive description (e.g. `'ZZZ-broken-belt-9137'`) on an equipment, then
  assert **that description string** appears in the rendered dense HTML. Do not
  assert on `rec.status`. (AC 3, F6)
- `test_dense_green_item_has_no_records_list` — equipment with no open records →
  `kiosk-dense-records` not present for it. (AC 4)
- `test_dense_invalid_columns_404` — parametrize `[0, 1, 4, 99]` → 404. (AC 5)
- `test_dense_nonint_columns_404` — `GET /public/kiosk/dense/foo` → 404. (AC 6)
- `test_dense_empty_state` — no equipment → 200 and "No equipment registered yet."
  and `kiosk-dense-grid` absent. (AC 7)
- `test_dense_wraps_in_scale_content` — assert `id="kiosk-scale-content"` present. (AC 8)

**Dropdown tests (add near existing `test_dashboard_kiosk_dropdown_*`):**
- `test_dashboard_dropdown_contains_dense_2col_and_3col_links` — dashboard HTML
  contains `href="/public/kiosk/dense/2"` and `href="/public/kiosk/dense/3"`. (AC 9)
- `test_dashboard_dropdown_has_dense_links_when_no_equipment` — with no equipment,
  dashboard HTML still contains both dense links (they are ungated). (AC 11, F3)

**Regression:** existing `static_page` / `static_page_service` tests must still pass
unchanged (AC 10) — run the full suite (`make test`) and `make lint`.

**Manual testing:** load `/public/`, open the "Kiosk View" dropdown, click each new
entry; verify the layout fills the viewport without scrollbars at a few window
sizes (kiosk auto-scale shrinks to fit), that non-green items show their open
records, and that the 2-col vs 3-col grids differ.

### Notes

- **Out of scope (issue #71 optional idea):** making the concise static layout
  "flow better" to fill the screen without a fixed column count. Per discovery the
  fixed 2-/3-column dropdown views are the deliverable; the pushed static page is
  untouched.
- **Risk — uneven columns:** "areas as blocks" grid can leave uneven column
  heights when one area has far more equipment/records than others. Accepted per
  design decision #2; the auto-scale still guarantees no scroll.
- **Risk — auto-scale over-shrink:** with many areas the shrink-to-fit can make
  text small on large equipment counts. This is the same trade-off the existing
  kiosk already makes; not a regression.
- **Limitation — sparse boards don't fill the screen [F2]:** `applyKioskScale`
  only shrinks (`Math.min(1, …)`), never enlarges. On a board with few areas, the
  2-/3-column grid renders at scale 1 in the top-left with empty space below/right;
  nothing stretches it to "fill" the viewport. The primary win of these views is
  **information density on crowded/small screens** (the technicians' stated need),
  not filling a sparse large screen. True flow-to-fill is the Out-of-Scope idea
  from issue #71; if it becomes a requirement, revisit with a fluid/auto-fit
  layout or an enlarge-capable scale.
- **Row-major grid trade-off [F9, acknowledged]:** CSS grid places area blocks
  row-major (area1→col1, area2→col2, area3→row2col1…), so a tall area sets its
  row's height and can waste vertical space — the "uneven columns" risk above. The
  rejected `column-count` flow would balance heights but split an area across a
  column break; per decision #2 keeping areas intact was preferred.
- **Future consideration:** per-area dense variants (like the existing per-area
  kiosk entries) could be added later by parameterizing the route with an area id;
  not requested now.

## Review Notes

- Adversarial review completed (13 findings).
- Resolution approach: auto-fix "real" findings.
- Findings: 13 total, 3 fixed, 10 skipped.
  - **Fixed:**
    - **F3** (Medium/real): restored the "revisit red/yellow/gray mapping when
      `REPAIR_SEVERITIES` changes" warning comment in `kiosk_dense.html`.
    - **F5** (Medium/real): added `test_dense_null_severity_record_gray_no_badge`
      covering the null/unknown-severity branch (gray border, hidden badge,
      yellow dot).
    - **F7** (Low/real): simplified the dead guard
      `item.status.color != 'green' and item.open_records` → `item.open_records`
      (non-empty open_records always implies non-green).
  - **Skipped (real, but intentional / out-of-scope):**
    - **F1** (High/real, duplication): the only true dedup shares logic with
      `static_page.html`, which is frozen out-of-scope and byte-for-byte
      guarded by AC 10; factoring it would violate that AC. Left as-is.
    - **F8** (Low): duplicate ETA (summary line vs. top record) is intentional
      parity with `static_page.html`.
    - **F9** (Low): `.kiosk-dense-record-gray` kept for red/yellow/gray symmetry
      and to pin gray independent of the default border color.
    - **F10** (Low): generic `record-*` class names are already scoped under
      `.kiosk-dense-grid` (no runtime clash); renaming would reduce intentional
      parity with the source template.
  - **Skipped (undecided/noise or accepted trade-off already documented above):**
    F2 (over-shrink), F4 (gray-vs-yellow, now test-documented), F6 (row-major
    grid), F11 (tests framework behavior), F12 (inline-style CSP), F13
    ("Operational" label density).
