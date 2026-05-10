---
title: 'Kiosk Display Scaling and Per-Area Kiosks'
slug: 'kiosk-scaling-and-per-area'
created: '2026-05-09'
revised: '2026-05-09 (post-adversarial-review pass 2)'
status: 'ready-for-dev'
stepsCompleted: [1, 2, 3, 4]
tech_stack:
  - Python 3.14 (ruff target py313)
  - Flask + Flask-SQLAlchemy
  - Jinja2 templates
  - Bootstrap 5 (bundled local CSS/JS — confirmed loaded via base_public.html:17 and base.html:74)
  - Vanilla JS (no framework, single esb/static/js/app.js)
files_to_modify:
  - esb/utils/exceptions.py
  - esb/views/public.py
  - esb/services/status_service.py
  - esb/templates/base_kiosk.html
  - esb/templates/public/kiosk.html
  - esb/templates/public/status_dashboard.html
  - esb/static/css/app.css
  - esb/static/js/app.js
  - tests/test_views/test_public_views.py
  - tests/test_services/test_status_service.py
code_patterns:
  - Service-layer pattern; views call services, services return dicts/lists
  - Local imports inside view functions to avoid circular imports
  - Single CSS/JS files (no per-page assets)
  - snake_case template names; underscore-prefix for partials
  - db.session.get(Model, id) for PK lookups; db.session.execute(db.select(...)) for queries
  - flask.abort(404) for missing/archived resources on public pages
  - Vanilla JS pattern: DOMContentLoaded handler with early-return guards (e.g., `if (!el) return;`)
  - Domain exceptions all inherit from ESBError (esb/utils/exceptions.py)
test_patterns:
  - pytest, SQLite in-memory test DB, CSRF disabled in TestingConfig
  - Class-based test grouping (e.g., TestKioskView in tests/test_views/test_public_views.py)
  - Fixtures: `client` (unauthenticated), `staff_client`, `tech_client`, `make_area`, `make_equipment`, `make_repair_record`
  - Assert HTML substrings via `response.data` (bytes) or `response.data.decode()` (str)
  - For redirects: `response.status_code == 302` + `response.headers['Location']`
issue: 33
---

# Tech-Spec: Kiosk Display Scaling and Per-Area Kiosks

**Created:** 2026-05-09
**Revised:** 2026-05-09 (after two adversarial-review passes — see "Revision History" at end)
**Issue:** [#33](https://github.com/jantman/equipment-status-board/issues/33) — Kiosk Display Scaling and Per-Area Kiosks

## Overview

### Problem Statement

The kiosk display (`/public/kiosk`) is intended for wall-mounted, non-interactive screens, so users cannot scroll. When the makerspace has many areas/equipment, content overflows the viewport and becomes invisible. Additionally, individual areas (e.g., woodshop, metalshop) want their own dedicated kiosk view that focuses on just that area's equipment.

### Solution

1. Add JS-driven **shrink-to-fit scaling** to the kiosk template: after render, measure the content vs. the viewport and apply a CSS `transform: scale()` ≤ 1.0 so content always fits without scrolling. Content is never up-scaled beyond its natural size. Re-measure on resize, after web-fonts load, and on the existing 60s meta-refresh.
2. Add a new per-area kiosk route `/public/kiosk/<int:area_id>` that renders the same kiosk layout but scoped to a single area, with the area's name as the heading. Both kiosk views use the same scaling JS.

### Scope

**In Scope:**

- New route `/public/kiosk/<int:area_id>` in `esb/views/public.py` that renders the same kiosk template scoped to a single area.
- Returns 404 when the area is missing, archived, or `area_id` is not a valid Area.
- New service function `status_service.get_single_area_status_dashboard(area_id)` returning the same shape as one entry from `get_area_status_dashboard()`; raises `AreaNotFound` for missing areas and `AreaArchived` (subclass of `AreaNotFound`) for archived areas.
- New `AreaNotFound(ESBError)` and `AreaArchived(AreaNotFound)` exceptions in `esb/utils/exceptions.py`.
- Reuses existing archived-equipment filtering (same behavior as `/public/kiosk`).
- JS-based shrink-to-fit scaling applied to both kiosk views (all-areas and per-area), implemented in `esb/static/js/app.js`.
- CSS scaffolding (a wrapper element + `transform-origin` rule + `.kiosk-body { overflow: hidden }`) in `esb/static/css/app.css`.
- One-token edit in `esb/templates/base_kiosk.html`: `<main class="container-fluid p-3">` → `<main class="container-fluid p-0">` (so the scaling wrapper has full viewport area to work with — see Technical Decision #5 below).
- Empty-per-area state: an area with no non-archived equipment renders "No equipment in this area yet." copy.
- Discoverability: a Bootstrap dropdown on the public status dashboard listing the all-areas kiosk plus one entry per non-archived area **that has at least one non-archived equipment item**.
- Tests for the new route, service function, exception hierarchy, scaling DOM hooks, and discoverability dropdown (including filtering of empty areas).

**Out of Scope:**

- Up-scaling content beyond its natural size when the viewport is much larger than needed.
- Adding a `slug` field to the `Area` model (route uses integer id).
- Changes to the 60s auto-refresh interval, status colors, or `_status_indicator.html` component.
- Authentication changes (kiosks remain unauthenticated).
- Changes to GCS static-status page generation.
- A "rotating" or "carousel" kiosk that cycles through areas.
- Refactoring the existing `equipment_service.get_area` use of `ValidationError` for missing-area lookups (separate cleanup).

## Context for Development

### Codebase Patterns

- **Service layer pattern** (MANDATORY): all business logic lives in `esb/services/`. Views are thin: parse input → call service → render template. Models are accessed only by services.
- **Dependency flow:** `views → services → models`. Never reversed.
- **Local service imports** inside view functions (e.g., `from esb.services import status_service` inside the route body), per the existing pattern in `esb/views/public.py`. Avoids circular imports.
- **Single asset files:** all custom CSS in `esb/static/css/app.css`; all custom JS in `esb/static/js/app.js`. NO per-page CSS/JS files.
- **Template naming:** snake_case (`kiosk.html`); underscore-prefix for partials (`_status_indicator.html`).
- **No raw SQL:** all queries via SQLAlchemy ORM (`db.session.execute(db.select(...))`, `db.session.get(Model, id)`).
- **404 pattern:** `flask.abort(404)` for missing/archived public resources (see `equipment_page` at `esb/views/public.py:65` for the existing pattern). The `abort` symbol is already imported at the top of `esb/views/public.py` (line 10).
- **Domain exception hierarchy:** all exceptions inherit from `ESBError` (verified `esb/utils/exceptions.py:7`). Existing classes: `EquipmentNotFound(ESBError)`, `RepairRecordNotFound(ESBError)`, `UnauthorizedAction(ESBError)`, `ValidationError(ESBError)`. Mirror this structure for `AreaNotFound`.
- **Vanilla-JS pattern in `app.js`:** `document.addEventListener('DOMContentLoaded', function () { ... })` containing per-feature blocks; each feature uses an early-return guard like `var el = document.getElementById('foo'); if (!el) return;` so the same script is safely loaded on every page.
- **Test class grouping:** `tests/test_views/test_public_views.py` contains `TestStatusDashboardView`, `TestKioskView`, `TestEquipmentPageView`, etc. New test class follows the same structure.

### Files to Reference

| File | Purpose |
| ---- | ------- |
| `esb/utils/exceptions.py` (lines 7-25) | Add new `AreaNotFound(ESBError)` and `AreaArchived(AreaNotFound)`, mirroring `EquipmentNotFound`. |
| `esb/views/public.py` (line 31) | Existing `/kiosk` route. Add new `/kiosk/<int:area_id>` route adjacent to it. `abort` is already imported (line 10) — no new imports needed in the route body. |
| `esb/services/status_service.py` (line 154) | `get_area_status_dashboard()` returns a list-of-dicts shape. Add `get_single_area_status_dashboard(area_id)` returning the same dict shape (single entry) and raising `AreaNotFound` / `AreaArchived` distinctly. |
| `esb/templates/base_kiosk.html` (line 13) | Change `<main class="container-fluid p-3">` to `<main class="container-fluid p-0">` so the scaling wrapper measures against the full viewport (no padding-induced gap). |
| `esb/templates/public/kiosk.html` | Refactor to wrap content in `<div id="kiosk-scale-content" class="kiosk-scale-wrapper">…</div>`. Add explicit empty-per-area branch. Update visually-hidden `<h1>` to include the area name when in per-area mode. |
| `esb/templates/public/status_dashboard.html` (line 13) | Replace single "Kiosk View" link with a Bootstrap dropdown listing "All Equipment" plus one entry per non-archived area **that has equipment**. |
| `esb/templates/base.html` (line 74 — verified) and `esb/templates/base_public.html` (line 17 — verified) | Both already load `js/bootstrap.bundle.min.js` (Popper included). Status dashboard inherits whichever based on auth state. **No changes.** |
| `esb/templates/components/_status_indicator.html` | Status indicator partial (compact variant). **No changes.** |
| `esb/static/css/app.css` (lines 4-6, 55-66) | Extend `.kiosk-body` rule to add `overflow: hidden;`. Add new `.kiosk-scale-wrapper { transform-origin: top left; }` rule. |
| `esb/static/js/app.js` | Add a feature block following the existing `DOMContentLoaded` pattern. Bind scaling computation to `DOMContentLoaded`, `window.load`, `document.fonts.ready`, and debounced `resize`. |
| `esb/models/area.py` | `Area` has `id`, `name`, `slack_channel`, `is_archived`, timestamps. No slug. Route uses integer `id`. |
| `tests/test_views/test_public_views.py` (line 226) | `TestKioskView` is the model. Add new `TestPerAreaKioskView` class. Add scaling-DOM tests to `TestKioskView`. Add discoverability tests to `TestStatusDashboardView`. **Modify** existing `test_dashboard_shows_kiosk_link` (line 53) and `test_kiosk_has_visually_hidden_h1` (line 418) to account for new dropdown / area_name behavior — see Tasks 11 & 12. |
| `tests/test_services/test_status_service.py` | Add tests for `get_single_area_status_dashboard()` (success, missing, archived, archived-equipment-excluded, distinct exception classes). |
| `tests/conftest.py` | Fixtures available: `client`, `staff_client`, `tech_client`, `make_area`, `make_equipment`, `make_repair_record`. Archived-area pattern: see `test_kiosk_excludes_archived_areas` at line 402. |

### Technical Decisions

1. **Scaling is JS-driven, shrink-only — vertical-dominant in practice:** Apply `transform: scale(s)` with `s = Math.min(1, viewportW/contentW, viewportH/contentH)` and `transform-origin: top left`. Clamping to ≤ 1.0 means small content stays at natural size (no awkward up-scaling). `transform: scale()` does not affect layout per CSS spec — `scrollWidth`/`scrollHeight` already report the natural unscaled dimensions, so no reset is needed before measurement. **Note:** because the kiosk grid uses CSS Grid `auto-fill, minmax(280px, 1fr)`, the grid reflows to fit available width and rarely produces horizontal overflow — so `viewportW/contentW ≈ 1` in normal use. The vertical axis (`viewportH/contentH`) is the dominant constraint in practice. The horizontal term remains in the formula as a defensive belt-and-suspenders for edge cases (e.g., a single very long equipment name in a single-column layout) and for future layout changes.

2. **Recomputation triggers:** `DOMContentLoaded` (first paint), `window.load` (after images), `document.fonts.ready` (after web-fonts settle to avoid FOUT-induced miscalibration), and debounced `resize` (150ms — matches the existing `qr-form` debounce in `app.js:140`). The 60s meta-refresh causes a full reload, which re-fires all of these.

3. **Scrollbar flash mitigation:** Set `.kiosk-body { overflow: hidden; }` so the unscaled content never produces a scrollbar before the JS runs. The `.kiosk-body` class is only applied to `<body>` via `base_kiosk.html`, so this rule is scoped to kiosk pages. **Constraint:** because the body has `overflow: hidden`, any future Bootstrap modal/dropdown/popover added to a kiosk page would be silently clipped if it overflows the viewport. This is acceptable today (kiosks are non-interactive read-only displays) but should be re-evaluated if interactivity is ever added.

4. **No-JS fallback (known limitation):** With JavaScript disabled, oversize content is clipped (because of `.kiosk-body { overflow: hidden }`) rather than scrollable. Considered acceptable: kiosks are dedicated displays where JS will be enabled.

5. **Eliminate `<main>` padding for kiosk pages:** `base_kiosk.html` currently sets `<main class="container-fluid p-3">`, contributing 1rem padding on all sides. This causes (a) the wrapper's natural width to be smaller than the viewport (false-positive horizontal scaling threshold) and (b) the bottom 1rem of vertical content to be clipped silently when scaled to viewport height. Solution: change the class to `p-0`. The wrapper itself controls its own internal spacing if needed.

6. **Wrapper layout — `display: block` (default):** No special `display` or `min-width` rules on `.kiosk-scale-wrapper`. As a default block element, it fills the parent's content-box width. Combined with the `p-0` change above, this means the wrapper's natural width = viewport width, and the kiosk grid's `auto-fill, minmax(280px, 1fr)` flows naturally. Avoids the inline-block/baseline-gap quirks and the `min-width: 100%` confusion present in the v1 spec.

7. **URL shape:** `/public/kiosk/<int:area_id>` — Flask's `int` converter automatically returns 404 on non-integer values. Per-area kiosk URL is `url_for('public.kiosk_area', area_id=area.id)`.

8. **View-name choice:** New route function `kiosk_area(area_id)` (endpoint `public.kiosk_area`). The all-areas kiosk endpoint stays as `public.kiosk`.

9. **Per-area heading:** Per-area kiosk shows the area's `name` as the existing `<h2 class="kiosk-area-heading">` (template loops; with one area there's one heading). Visually-hidden `<h1>` becomes `Equipment Status - {area_name}` when an `area_name` value is passed (the all-areas kiosk does not pass it; the template handles absence).

10. **404 for archived/missing area, with internal observability:** `get_single_area_status_dashboard()` raises `AreaNotFound` for "no such id" and `AreaArchived` for archived. Since `AreaArchived` is a subclass of `AreaNotFound`, the view's `except AreaNotFound:` catches both and `abort(404)`s. Future callers can catch the more specific class for distinct handling. No leaking of "exists but archived" vs. "doesn't exist" to the public.

11. **Empty per-area state has its own copy:** A non-archived area with zero non-archived equipment renders "No equipment in this area yet." (distinct from the all-areas empty-state "No equipment registered yet."). Determined in the template by checking `areas|length == 1 and not areas[0].equipment`.

12. **Discoverability dropdown filters empty areas:** The dropdown lists only non-archived areas with at least one non-archived equipment item. Avoids users navigating to dead-end empty kiosks via the dropdown. Direct URL access still works (with the empty-per-area copy).

13. **Discoverability link UX:** Replace single "Kiosk View" button (`status_dashboard.html:13`) with a Bootstrap dropdown labeled `Kiosk View ▾`. Items: "All Equipment" (existing route) + one item per qualifying area.

14. **Re-use vs. parameterize service:** Add a dedicated `get_single_area_status_dashboard(area_id)` rather than filtering `get_area_status_dashboard()` in the view — keeps business logic in the service and avoids over-fetching.

15. **LTR-only assumption:** `transform-origin: top left` pins scaling to the top-left corner. App is currently LTR-only; if RTL is added later, switch to `transform-origin: top right` for `dir="rtl"` (out of scope).

16. **CSS selector form:** Keep the existing `.kiosk-body` (single-class) selector — do NOT change to `body.kiosk-body`. The class is only ever applied to `<body>` in `base_kiosk.html:12`, so the body-prefix would be a gratuitous specificity bump (0,0,1,0 → 0,0,1,1) with no functional benefit. A CSS comment (`/* applied to <body> via base_kiosk.html */`) documents the scope without affecting cascade. Spec narrative may reference the rule descriptively as "the kiosk-body rule" or `body.kiosk-body` for documentation clarity, but the actual stylesheet uses `.kiosk-body`.

17. **JS measurement contract:** Code added to `#kiosk-scale-content` MUST only use `transform` styles. Per-CSS spec, `transform` does not affect layout, so `scrollWidth`/`scrollHeight` correctly report the natural unscaled dimensions. If a future change introduces a non-transform style on the wrapper that DOES affect layout (e.g., viewport-relative `font-size`, `width`, `padding`), the measurement assumption breaks. Inline JS comment in Task 7 codifies this.

## Implementation Plan

### Tasks

Tasks are ordered by dependency (lowest level first).

- [ ] **Task 1: Add `AreaNotFound` and `AreaArchived` exceptions**
  - File: `esb/utils/exceptions.py`
  - Action: Append to the file (after the existing `ValidationError` at line 23):
    ```python
    class AreaNotFound(ESBError):
        """Raised when an area lookup fails (does not exist)."""


    class AreaArchived(AreaNotFound):
        """Raised when an area exists but is archived.

        Subclass of AreaNotFound so callers that don't need the distinction
        can catch the parent and treat both as 'unavailable'.
        """
    ```
  - Notes: `EquipmentNotFound` (line 11) extends `ESBError` directly — confirmed by reading the file. Do NOT subclass from `ValidationError`. Do not add to any `__init__.py` re-exports (existing exceptions are imported directly from `esb.utils.exceptions`).

- [ ] **Task 2: Add `get_single_area_status_dashboard()` service function**
  - File: `esb/services/status_service.py`
  - Action: Insert a new function at line 234 (immediately after `get_area_status_dashboard()` ends at line 233):
    ```python
    def get_single_area_status_dashboard(area_id: int) -> dict:
        """Get a single non-archived area's equipment with computed statuses.

        Returns the same shape as one entry from get_area_status_dashboard():
            {
                'area': Area instance,
                'equipment': [
                    {'equipment': Equipment, 'status': {color, label, issue_description, severity}},
                    ...
                ],
            }

        Raises:
            AreaNotFound: if the area does not exist.
            AreaArchived: if the area exists but is archived.
                          (Subclass of AreaNotFound — catch the parent if the
                           caller treats both cases identically, e.g. a 404 view.)
        """
        from esb.utils.exceptions import AreaArchived, AreaNotFound

        area = db.session.get(Area, area_id)
        if area is None:
            raise AreaNotFound(f'Area with id {area_id} not found')
        if area.is_archived:
            raise AreaArchived(f'Area with id {area_id} is archived')

        equipment_list = (
            db.session.execute(
                db.select(Equipment)
                .filter(Equipment.area_id == area_id, Equipment.is_archived.is_(False))
                .order_by(Equipment.name)
            )
            .scalars()
            .all()
        )

        equip_ids = [e.id for e in equipment_list]
        records_by_equipment: dict[int, list[RepairRecord]] = {}
        if equip_ids:
            # Skip the IN-clause query when there's no equipment, purely as
            # a roundtrip-saving optimization. (SQLAlchemy 1.4+ handles
            # empty IN clauses gracefully — this is not a correctness guard.)
            open_records = (
                db.session.execute(
                    db.select(RepairRecord)
                    .filter(
                        RepairRecord.equipment_id.in_(equip_ids),
                        RepairRecord.status.notin_(CLOSED_STATUSES),
                    )
                )
                .scalars()
                .all()
            )
            for record in open_records:
                records_by_equipment.setdefault(record.equipment_id, []).append(record)

        equip_statuses = []
        for equip in equipment_list:
            equip_records = records_by_equipment.get(equip.id, [])
            equip_statuses.append({
                'equipment': equip,
                'status': _derive_status_from_records(equip_records),
            })

        return {'area': area, 'equipment': equip_statuses}
    ```
  - Notes: Reuses `_derive_status_from_records()` and `CLOSED_STATUSES` already imported at the top of `status_service.py`. Distinct exceptions for missing vs archived preserve internal observability while the view collapses both into 404.

- [ ] **Task 3: Add `/public/kiosk/<int:area_id>` route**
  - File: `esb/views/public.py`
  - Action: Add a new route after the existing `kiosk()` function (line 31):
    ```python
    @public_bp.route('/kiosk/<int:area_id>')
    def kiosk_area(area_id):
        """Per-area kiosk display -- full-screen equipment status for one area."""
        from esb.services import status_service
        from esb.utils.exceptions import AreaNotFound

        try:
            area_data = status_service.get_single_area_status_dashboard(area_id)
        except AreaNotFound:  # also catches AreaArchived (subclass)
            abort(404)

        return render_template(
            'public/kiosk.html',
            areas=[area_data],
            area_name=area_data['area'].name,
        )
    ```
  - Notes: Uses the existing `abort` import at `esb/views/public.py:10`. Catching `AreaNotFound` (the parent) also catches `AreaArchived` due to inheritance. Passes a single-element `areas` list so the existing template iteration logic just works. Passes `area_name` separately so the visually-hidden `<h1>` and `<title>` can include the area name. The all-areas `kiosk()` view does NOT pass `area_name`; the template treats absence as "all areas".

- [ ] **Task 4: Drop `<main>` padding in `base_kiosk.html`**
  - File: `esb/templates/base_kiosk.html`
  - Action: On line 13, change `<main class="container-fluid p-3">` to `<main class="container-fluid p-0">`.
  - Notes: This single-token change ensures the scaling wrapper measures against the full viewport (no Bootstrap padding gap). Does not affect any other consumer because `base_kiosk.html` is only used by `kiosk.html`. See Technical Decision #5.

- [ ] **Task 5: Refactor `kiosk.html` to add scaling wrapper, per-area H1, and explicit empty-per-area branch**
  - File: `esb/templates/public/kiosk.html`
  - Action: Replace the entire content of the file with:
    ```jinja2
    {% extends "base_kiosk.html" %}

    {% block title %}Equipment Status{% if area_name %} - {{ area_name }}{% endif %} - Kiosk{% endblock %}

    {% block content %}
    <h1 class="visually-hidden">Equipment Status{% if area_name %} - {{ area_name }}{% endif %}</h1>
    <div id="kiosk-scale-content" class="kiosk-scale-wrapper">
    {% if not areas %}
    <div class="text-center py-5">
      <p class="fs-3 text-muted">No equipment registered yet.</p>
    </div>
    {% elif areas|length == 1 and not areas[0].get('equipment') %}
    <div class="text-center py-5">
      <p class="fs-3 text-muted">No equipment in this area yet.</p>
    </div>
    {% else %}
      {% for area_data in areas %}
      {% if area_data.equipment %}
      <section class="mb-4">
        <h2 class="kiosk-area-heading mb-3">{{ area_data.area.name }}</h2>
        <div class="kiosk-equipment-grid">
          {% for item in area_data.equipment %}
          <div class="card h-100 status-card status-card-{{ item.status.color }}">
            <div class="card-body">
              <div class="d-flex justify-content-between align-items-start">
                <h3 class="kiosk-equipment-name fw-bold mb-0">{{ item.equipment.name }}</h3>
                {% set status = item.status %}
                {% set variant = 'compact' %}
                {% include 'components/_status_indicator.html' %}
              </div>
              {% if item.status.color != 'green' and item.status.issue_description %}
              <p class="card-text text-muted mt-2 mb-0">{{ item.status.issue_description }}</p>
              {% endif %}
            </div>
          </div>
          {% endfor %}
        </div>
      </section>
      {% endif %}
      {% endfor %}
    {% endif %}
    </div>
    {% endblock %}
    ```
  - Notes: Three render branches now: (1) all-areas with no areas at all → "No equipment registered yet."; (2) per-area mode where the single area has no equipment → "No equipment in this area yet."; (3) at least one area-with-equipment → loop normally. The `<h1>` and `<title>` include the area name only when `area_name` is truthy (`{% if area_name %}` correctly handles `None`, empty string, and missing context). The empty-per-area branch uses `.get('equipment')` (not attribute access) to defensively handle hypothetical future callers that pass `areas=[{'area': X}]` without the `equipment` key — although the current service contract guarantees the key is always present.

- [ ] **Task 6: Add scaling CSS**
  - File: `esb/static/css/app.css`
  - Action:
    1. Update the existing `.kiosk-body` rule (lines 4-6). Keep the single-class selector (do NOT change to `body.kiosk-body` — Tech Decision #16); add a scope-documenting comment and `overflow: hidden`:
       ```css
       /* Kiosk layout. Class is only applied to <body> in base_kiosk.html, so
          this rule is effectively body-scoped. overflow:hidden prevents any
          pre-JS scrollbars or post-JS clipping artifacts.

          Constraint: any future Bootstrap modal/dropdown/popover added to a
          kiosk page would be silently clipped if it overflows the viewport.
          See Tech Decision #3. */
       .kiosk-body {
           font-size: 1.25rem;
           overflow: hidden;
       }
       ```
    2. Append a new rule below the existing kiosk display block (after line 66):
       ```css
       /* Scaling wrapper for kiosk shrink-to-fit. JS measures scrollWidth/Height
          and applies a transform: scale(s≤1) to fit the wrapper inside the viewport.
          transform-origin pins the scaled content to the top-left of the viewport.
          IMPORTANT: do NOT add non-transform styles that affect layout (font-size,
          width, padding, etc.) to this class — the JS measurement assumes only
          transforms are applied. See Tech Decision #17.
          Note: LTR-only — for RTL support switch to `top right`. */
       .kiosk-scale-wrapper {
           transform-origin: top left;
       }
       ```
  - Notes: No `display: inline-block`, no `min-width: 100%`. The wrapper inherits the default `display: block` and naturally fills its parent's content-box width (which, post-Task 4, equals the viewport width).

- [ ] **Task 7: Add JS shrink-to-fit scaling**
  - File: `esb/static/js/app.js`
  - Action: Insert a new feature block at line 118 (before the closing `});` of the `DOMContentLoaded` handler — line 119 is the closing `});` itself):
    ```javascript
      // --- Kiosk shrink-to-fit scaling ---
      // Contract: only `transform` styles may be applied to #kiosk-scale-content.
      // Any non-transform style that affects layout (font-size, width, padding,
      // etc.) breaks the scrollWidth/scrollHeight measurement assumption.
      // See Tech Decision #17 in the spec.
      var kioskScale = document.getElementById('kiosk-scale-content');
      if (kioskScale) {
        var KIOSK_RESIZE_DEBOUNCE_MS = 150;
        var resizeTimer = null;
        function applyKioskScale() {
          // scrollWidth/scrollHeight report natural unscaled dimensions per
          // CSS spec — transforms do not affect layout.
          var contentW = kioskScale.scrollWidth;
          var contentH = kioskScale.scrollHeight;
          var viewportW = document.documentElement.clientWidth;
          var viewportH = document.documentElement.clientHeight;
          if (viewportW <= 0 || viewportH <= 0) return;  // hidden tab / boot
          if (contentW <= 0 || contentH <= 0) {
            // Layout transiently zero (e.g., during font swap). Retry on the
            // next animation frame so we don't get stuck with no transform.
            requestAnimationFrame(applyKioskScale);
            return;
          }
          var scale = Math.min(1, viewportW / contentW, viewportH / contentH);
          kioskScale.style.transform = 'scale(' + scale + ')';
        }
        applyKioskScale();
        // Re-run after images, web-fonts, etc. settle to avoid FOUT-induced miscalibration.
        window.addEventListener('load', applyKioskScale);
        if (document.fonts && document.fonts.ready && typeof document.fonts.ready.then === 'function') {
          document.fonts.ready.then(applyKioskScale);
        }
        window.addEventListener('resize', function () {
          if (resizeTimer) clearTimeout(resizeTimer);
          resizeTimer = setTimeout(applyKioskScale, KIOSK_RESIZE_DEBOUNCE_MS);
        });
      }
    ```
  - Notes: No `transform = 'none'` reset before measurement — `scrollWidth` is unaffected by transform per CSS spec, and the reset would cause a brief unscaled flash on resize. The viewport-zero guard handles background-tab and boot edge cases. The zero-content `requestAnimationFrame` retry recovers from transient zero-size states (e.g., during web-font swap when text dimensions are momentarily undefined) without waiting for the next user interaction or 60s refresh. `KIOSK_RESIZE_DEBOUNCE_MS = 150` is a deliberate choice (not coupled to `qr-form`'s implementation), happens to match it.

- [ ] **Task 8: Update status dashboard with kiosk dropdown (filtered)**
  - File: `esb/templates/public/status_dashboard.html`
  - Action: Replace lines 12-14 (the existing `<div class="text-end mb-3">...</div>` block) with a Bootstrap dropdown that filters empty areas:
    ```jinja2
    <div class="text-end mb-3">
      <div class="dropdown d-inline-block">
        <button class="btn btn-sm btn-outline-secondary dropdown-toggle" type="button"
                id="kioskDropdown" data-bs-toggle="dropdown" aria-expanded="false">
          Kiosk View
        </button>
        <ul class="dropdown-menu dropdown-menu-end" aria-labelledby="kioskDropdown">
          <li><a class="dropdown-item" href="{{ url_for('public.kiosk') }}">All Equipment</a></li>
          {% set populated_areas = areas | selectattr('equipment') | list %}
          {% if populated_areas %}
          <li><hr class="dropdown-divider"></li>
          {% for area_data in populated_areas %}
          <li>
            <a class="dropdown-item"
               href="{{ url_for('public.kiosk_area', area_id=area_data.area.id) }}">
              {{ area_data.area.name }}
            </a>
          </li>
          {% endfor %}
          {% endif %}
        </ul>
      </div>
    </div>
    ```
  - Notes: `selectattr('equipment')` filters to entries where `equipment` is truthy (non-empty list). `areas` is already in the template context (from the `status_dashboard()` view) and already filtered to non-archived areas by the existing service call. Bootstrap's bundled JS (Popper-included) is loaded in both `base.html:74` and `base_public.html:17` — verified.

- [ ] **Task 9: Add service tests for `get_single_area_status_dashboard()`**
  - File: `tests/test_services/test_status_service.py`
  - Action: Add a new test class `TestGetSingleAreaStatusDashboard` with these tests:
    - `test_returns_area_with_equipment_and_statuses`
    - `test_raises_area_not_found_for_missing_id` — use `with pytest.raises(AreaNotFound) as exc_info: ...; assert type(exc_info.value) is AreaNotFound` (exact-class check, NOT `isinstance` — keeps the missing-vs-archived distinction explicit)
    - `test_raises_area_archived_for_archived_area` — assert `type(exc_info.value) is AreaArchived`; separately verify it is also catchable as `AreaNotFound` via `with pytest.raises(AreaNotFound):` (subclass relationship)
    - `test_excludes_archived_equipment_in_area`
    - `test_returns_empty_equipment_list_when_no_equipment`
    - `test_status_derivation_matches_repair_records` — happy paths for green / yellow / red
  - Notes: Use existing `make_area`, `make_equipment`, `make_repair_record` fixtures. For archived-area test, set `area.is_archived = True; db.session.commit()` after creation.

- [ ] **Task 10: Add view tests for per-area kiosk route**
  - File: `tests/test_views/test_public_views.py`
  - Action: Add new class `TestPerAreaKioskView` after `TestKioskView` (current line ~436). Tests:
    - `test_per_area_kiosk_renders_unauthenticated` — `client.get(f'/public/kiosk/{area.id}')` returns 200
    - `test_per_area_kiosk_shows_only_that_areas_equipment` — equipment from other areas not present
    - `test_per_area_kiosk_shows_area_name_in_h1` — assert `Equipment Status - {area_name}` in `<h1>`
    - `test_per_area_kiosk_shows_area_name_in_h2_heading`
    - `test_per_area_kiosk_shows_area_name_in_title`
    - `test_per_area_kiosk_404_for_missing_area` — `client.get('/public/kiosk/999999')` returns 404
    - `test_per_area_kiosk_404_for_archived_area` — set `is_archived=True`, expect 404
    - `test_per_area_kiosk_404_for_non_integer` — `client.get('/public/kiosk/abc')` returns 404 (Flask `int` converter)
    - `test_per_area_kiosk_excludes_archived_equipment`
    - `test_per_area_kiosk_shows_status_indicators`
    - `test_per_area_kiosk_shows_issue_descriptions`
    - `test_per_area_kiosk_meta_refresh_present`
    - `test_per_area_kiosk_no_navbar`
    - `test_per_area_kiosk_empty_area_shows_per_area_empty_copy` — area with no equipment renders `'No equipment in this area yet.'`
    - `test_per_area_kiosk_has_scale_wrapper_div` — assert `id="kiosk-scale-content"` and `class="kiosk-scale-wrapper"` in HTML
  - Notes: Mirror the patterns in `TestKioskView` for consistency. Use simple alphanumeric area names to avoid HTML-escape complications in assertions (e.g., `'Wood Shop'`, not `'Tools & Stuff'`).

- [ ] **Task 11: Update `TestKioskView` and add scaling-DOM hook + dropdown tests**
  - File: `tests/test_views/test_public_views.py`
  - Action:
    1. **Modify** the existing `test_kiosk_has_visually_hidden_h1` (currently asserts exact bytes `<h1 class="visually-hidden">Equipment Status</h1>`). Loosen to allow optional area-name suffix. Replace assertion with:
       ```python
       assert 'class="visually-hidden"' in html
       assert 'Equipment Status' in html
       # For all-areas kiosk, no area name should be appended:
       assert 'Equipment Status</h1>' in html or 'Equipment Status </h1>' in html
       ```
    2. **Add** to `TestKioskView`:
       - `test_kiosk_has_scale_wrapper_div` — assert `id="kiosk-scale-content"` and `class="kiosk-scale-wrapper"` in HTML
    3. **Modify** the existing `test_dashboard_shows_kiosk_link` (line 53). Currently `assert b'/public/kiosk' in response.data` — passes vacuously under the new dropdown. Tighten to:
       ```python
       html = response.data.decode()
       # Must contain the All Equipment dropdown item linking to /public/kiosk (not just any kiosk URL)
       assert 'href="/public/kiosk"' in html
       assert 'All Equipment' in html
       ```
    4. **Add** to `TestStatusDashboardView`:
       - `test_dashboard_kiosk_dropdown_contains_all_equipment_link` — assert `href="/public/kiosk"` and `All Equipment` present, plus `data-bs-toggle="dropdown"` to confirm the dropdown structure
       - `test_dashboard_kiosk_dropdown_contains_per_area_links_for_populated_areas` — create two areas WITH equipment, assert both `/public/kiosk/{id}` URLs appear
       - `test_dashboard_kiosk_dropdown_excludes_empty_areas` — create one area with equipment, one area without; assert only the populated area's URL appears
       - `test_dashboard_kiosk_dropdown_excludes_archived_areas` — archive one area, assert its URL/name does NOT appear
       - `test_dashboard_kiosk_dropdown_only_all_equipment_when_no_areas` — empty database; assert dropdown contains "All Equipment" link, does NOT contain `<hr class="dropdown-divider">`, and contains no `/public/kiosk/<int>` URLs
       - `test_dashboard_loads_bootstrap_bundle_js` — assert `'bootstrap.bundle.min.js' in html` (sanity check that the dropdown's JS dependency is actually loaded)
    5. **Add** automated `<main>` padding tests (mirrors the existing `test_kanban_uses_container_fluid` at `tests/test_views/test_repair_views.py:820` — reuse or replicate the `_main_element_classes` helper at `tests/test_views/test_repair_views.py:15`):
       - In `TestKioskView`: `test_kiosk_main_has_no_padding` — assert `'p-0' in classes` AND `'p-3' not in classes` for the all-areas kiosk
       - In `TestPerAreaKioskView`: `test_per_area_kiosk_main_has_no_padding` — same for `/public/kiosk/<id>`
       - Either import `_main_element_classes` from the kanban test module, or duplicate the helper at the top of `test_public_views.py`. Importing across test modules is acceptable — pytest doesn't restrict it — but a small duplication keeps test files self-contained.
    6. **Add** automated CSS-content tests for AC #13 (kiosk overflow):
       - `test_app_css_kiosk_body_has_overflow_hidden` — read `esb/static/css/app.css`, assert that within ~500 chars of the `.kiosk-body` rule there is `overflow: hidden;`. Implementation:
         ```python
         from pathlib import Path

         def test_app_css_kiosk_body_has_overflow_hidden(self):
             css = Path('esb/static/css/app.css').read_text()
             assert '.kiosk-body' in css
             # Find the .kiosk-body rule and assert overflow: hidden is in its block
             idx = css.index('.kiosk-body')
             block_end = css.index('}', idx)
             block = css[idx:block_end]
             assert 'overflow: hidden' in block
         ```
       - Lives in `TestKioskView` (or a new `TestKioskCss` if preferred). This test does not require a Flask app/client.
  - Notes: All assertions use simple ASCII to avoid HTML-escape edge cases. The CSS-content test (`test_app_css_kiosk_body_has_overflow_hidden`) intentionally couples to file content to catch reverts/refactors that lose the rule — accepting that mild brittleness as the cost of guarding the no-JS fallback (Tech Decision #4).

- [ ] **Task 12: Run lint and tests; spot-check existing tests**
  - Action: Run `make lint` and `make test`. All existing tests must pass; new tests must pass; no new ruff errors.
  - Notes: Spot-check these existing tests for surprises:
    - `test_kiosk_no_navbar` (line 327) — asserts `'navbar' not in html` and `'<nav' not in html`. The new wrapper and h1 do not introduce either substring; should remain green.
    - `test_kiosk_has_visually_hidden_h1` (line 418) — covered by Task 11 modification above.
    - `test_dashboard_shows_kiosk_link` (line 53) — covered by Task 11 modification above.
    - `test_kiosk_meta_refresh_tag` — meta refresh remains in `base_kiosk.html`; should remain green.

### Acceptance Criteria

- [ ] **AC 1** — **Per-area route happy path:** Given a non-archived area with id `X` exists with at least one non-archived equipment item, when an unauthenticated user GETs `/public/kiosk/X`, then the response is 200 and the page shows the area's name as the kiosk heading and lists only that area's non-archived equipment.

- [ ] **AC 2** — **Per-area scoping:** Given two areas A and B each with their own equipment, when the user GETs `/public/kiosk/<A.id>`, then the response body contains A's equipment names and does NOT contain any of B's equipment names.

- [ ] **AC 3** — **404 for missing area:** Given no area exists with id 999999, when the user GETs `/public/kiosk/999999`, then the response status is 404.

- [ ] **AC 4** — **404 for archived area:** Given an area with `is_archived=True`, when the user GETs `/public/kiosk/<area.id>`, then the response status is 404 (no leakage of "exists but archived").

- [ ] **AC 5** — **404 for non-integer area_id:** Given the URL `/public/kiosk/abc`, when the user GETs it, then the response status is 404 (handled by Flask's `int` URL converter).

- [ ] **AC 6** — **Per-area excludes archived equipment:** Given an area contains both archived and non-archived equipment, when the user GETs the per-area kiosk, then only non-archived equipment names appear in the response.

- [ ] **AC 7** — **Both kiosk views include scaling DOM hook:** Given the user GETs either `/public/kiosk` or `/public/kiosk/<id>`, when the page is rendered, then the response HTML contains an element with `id="kiosk-scale-content"` and class `kiosk-scale-wrapper`.

- [ ] **AC 8** — **Shrink-to-fit scaling applied via JS:** Given the kiosk page is loaded in a browser and the natural content size exceeds the viewport, when the JS runs (on `DOMContentLoaded`, `load`, or `fonts.ready`), then the `#kiosk-scale-content` element has a `transform: scale(s)` style applied where `0 < s ≤ 1`. (Manual test — not unit-testable without a real browser.)

- [ ] **AC 9** — **No up-scaling:** Given the kiosk page is loaded with content smaller than the viewport, when the JS runs, then `s = 1` (content remains at natural size, no stretch). (Manual test.)

- [ ] **AC 10** — **Scaling re-runs on resize:** Given the kiosk page is loaded and visible, when the browser window is resized, then the scale factor is recomputed within ~150ms (debounce window). (Manual test.)

- [ ] **AC 11** — **Scaling re-runs after fonts load:** Given the kiosk page initially renders with system fonts and web-fonts swap in afterwards, when `document.fonts.ready` resolves, then the scale factor is recomputed against the post-FOUT layout. (Manual test.)

- [ ] **AC 12** — **No scrollbars on kiosk pages (automated CSS check):** Given `esb/static/css/app.css` is read, when the `.kiosk-body` rule is parsed, then the rule body contains `overflow: hidden`. Verified by `test_app_css_kiosk_body_has_overflow_hidden` (Task 11.6). (Browser-level visual confirmation also recommended in manual testing step 4.)

- [ ] **AC 12b** — **Kiosk `<main>` has no padding (automated):** Given the kiosk page is rendered, when the `<main>` element's classes are extracted, then the class list contains `p-0` and does NOT contain `p-3`. Covered by `test_kiosk_main_has_no_padding` and `test_per_area_kiosk_main_has_no_padding` (Task 11.5).

- [ ] **AC 13** — **Discoverability dropdown — all-equipment link:** Given the public status dashboard is loaded, when the user clicks the "Kiosk View" dropdown, then it contains an "All Equipment" item linking to `/public/kiosk`.

- [ ] **AC 14** — **Discoverability dropdown — per-area links for populated areas:** Given two non-archived areas with equipment exist, when the dashboard renders, then the kiosk dropdown contains a link to `/public/kiosk/<area_id>` for each, labeled with the area name.

- [ ] **AC 15** — **Discoverability dropdown excludes archived areas:** Given an archived area exists (with or without equipment), when the dashboard renders, then the kiosk dropdown does NOT contain a link to that area's per-area kiosk.

- [ ] **AC 16** — **Discoverability dropdown excludes empty areas:** Given a non-archived area with zero non-archived equipment exists, when the dashboard renders, then the kiosk dropdown does NOT contain a link to that area's per-area kiosk.

- [ ] **AC 17** — **Empty per-area state has its own copy:** Given the user navigates directly to `/public/kiosk/<id>` for a non-archived area with no equipment, when the page renders, then it shows "No equipment in this area yet." (not the all-areas "No equipment registered yet." copy).

- [ ] **AC 18** — **Per-area heading and title:** Given the user loads `/public/kiosk/<id>` for an area named "Wood Shop", when the page renders, then the `<h1 class="visually-hidden">` contains `Equipment Status - Wood Shop` and the `<title>` contains `Wood Shop`.

- [ ] **AC 19** — **Service raises distinct exceptions:** Given `status_service.get_single_area_status_dashboard(id)` is called with a missing id, then it raises `AreaNotFound` (and not `AreaArchived`). Given an archived area's id, then it raises `AreaArchived`, which is a subclass of `AreaNotFound`. Given a valid non-archived id, then it returns a dict with `'area'` and `'equipment'` keys.

- [ ] **AC 20** — **All existing kiosk + dashboard tests still pass:** Given the existing test suite (`TestKioskView`, `TestStatusDashboardView`), when CI runs after this change, then all tests pass — with the documented modifications to `test_dashboard_shows_kiosk_link` (line 53) and `test_kiosk_has_visually_hidden_h1` (line 418) per Task 11.

- [ ] **AC 21** — **Bootstrap bundle loaded on dashboard:** Given the public status dashboard is rendered (authenticated or unauthenticated), when the response is inspected, then `bootstrap.bundle.min.js` is in the HTML (the dropdown's JS dependency).

## Additional Context

### Dependencies

- **No new Python packages.** Uses existing Flask, Flask-SQLAlchemy.
- **No new JS libraries.** Bootstrap (already bundled at `static/js/bootstrap.bundle.min.js`) provides the dropdown component. Confirmed loaded via both `base.html:74` and `base_public.html:17`.
- **No DB migration.** Uses existing `Area` and `Equipment` columns.
- **No infra change.** Routes are unauthenticated public, like the existing kiosk.
- Internally depends on:
  - `_derive_status_from_records()` (private helper in `status_service.py`)
  - `CLOSED_STATUSES` (imported at top of `status_service.py`)
  - `Area`, `Equipment`, `RepairRecord` models
  - `ESBError` base class in `esb/utils/exceptions.py:7`
  - The `_status_indicator.html` partial (compact variant)
  - The existing `.kiosk-body`, `.kiosk-area-heading`, `.kiosk-equipment-name`, `.kiosk-equipment-grid` CSS classes
  - Browser support: `document.fonts.ready` is defensively guarded with a feature check; if unavailable, scaling still works via `DOMContentLoaded` + `load` + `resize`.

### Testing Strategy

- **Unit tests (service layer):** `tests/test_services/test_status_service.py` — new `TestGetSingleAreaStatusDashboard` class covering happy path, missing id, archived area (distinct exception), archived equipment exclusion, empty area, and status derivation. Use existing `make_area`/`make_equipment`/`make_repair_record` fixtures.
- **Integration tests (view layer):** `tests/test_views/test_public_views.py` — new `TestPerAreaKioskView` covering 200 response, scoping, three 404 cases (missing/archived/non-int), archived equipment exclusion, status indicators, meta refresh, no navbar, empty-area copy, and scaling-DOM hook. Add scaling-DOM-hook test to `TestKioskView`. Add four discoverability dropdown tests + bootstrap-bundle-loaded test to `TestStatusDashboardView`. Modify two existing tests per Task 11.
- **Manual tests (browser):** required for the JS scaling behavior (ACs 8–12) since pytest tests don't render JS:
  1. Load `/public/kiosk` in a browser with many areas/equipment — confirm content fits without scrollbars.
  2. Resize the browser window — confirm content rescales within ~150ms.
  3. Load with a small amount of content — confirm content stays at natural size (not stretched).
  4. Inspect element on `body` — confirm `overflow: hidden` is set.
  5. Inspect element on `<main>` — confirm class is `container-fluid p-0` (no padding).
  6. Load with fonts that take time to swap — confirm scale recomputes after FOUT (visible jiggle once, then stable).
  7. Load `/public/kiosk/<area_id>` — confirm only that area is shown, scaling works.
  8. Load `/public/kiosk/<empty_area_id>` — confirm "No equipment in this area yet." copy appears.
  9. Load `/public/kiosk/999999` — confirm 404.
  10. Load `/public/kiosk/abc` — confirm 404.
  11. From the status dashboard, open "Kiosk View" dropdown — confirm "All Equipment" + per-area links present, archived/empty areas excluded.
- **Lint:** `make lint` (ruff) — no new errors.
- **Suite:** `make test` — all 660+ existing tests still pass; new tests pass.

### Notes

**Known limitations:**
- **No-JS fallback:** With JavaScript disabled, oversize content is clipped (because of `.kiosk-body { overflow: hidden }`) rather than scrollable. Considered acceptable: kiosks are dedicated displays where JS will be enabled.
- **Very wide aspect ratios:** Shrink-to-fit uses the more constraining of `viewportW/contentW` and `viewportH/contentH`, so on very wide or very tall viewports there will be empty space along one axis. Acceptable — alternative (stretching) was explicitly out of scope.
- **First-paint flash:** Between the initial paint and JS execution, oversize content is briefly clipped. On a LAN this gap is essentially imperceptible. If observed in practice as objectionable, a future iteration could apply `visibility: hidden` on the wrapper until JS sets it visible after measuring.
- **LTR-only:** `transform-origin: top left` assumes left-to-right reading order. If RTL support is added later, switch to `top right` for `dir="rtl"` pages. Not applicable today (app is LTR-only).
- **HTML-escape edge cases in tests:** Test area names should be alphanumeric-only (e.g., `'Wood Shop'`) to avoid Jinja autoescape interfering with substring assertions. Names with `&`, `<`, `>`, `"` would be encoded in the HTML and fail naive `'X' in html` checks.
- **Tall narrow viewports with many items:** Because horizontal overflow rarely occurs (the responsive grid reflows), shrink-to-fit is dominated by the vertical axis. On extremely tall narrow viewports (e.g., a 480×1920 portrait kiosk display) with many equipment items, the resulting scale factor can render text very small (< 0.5rem). Recommended kiosk hardware: 1080p+ landscape displays. Documented but not enforced.
- **`get_area_status_dashboard()` and `get_single_area_status_dashboard()` return shape:** Both must return a `list[dict]` / `dict` (not a generator). The Jinja templates use `areas|length` and `selectattr|list` which materialize iterables — repeated iteration is required. Type hints on the service functions document this contract.

**Risk items / pre-mortem:**
- **`test_kiosk_no_navbar` (line 327)** asserts `'navbar' not in html` and `'<nav' not in html`. The new wrapper and h1 do not introduce either substring — should remain green. Verified by inspection.
- **Bootstrap dropdown JS** depends on `bootstrap.bundle.min.js` being loaded on the status dashboard. It is, via `base.html:74` (authenticated) and `base_public.html:17` (unauthenticated). New test `test_dashboard_loads_bootstrap_bundle_js` (Task 11) asserts this explicitly.
- **Resize event flooding:** The 150ms `setTimeout` debounce prevents this. Pattern matches the existing `qr-form` implementation (`app.js:140`).
- **Archived-vs-missing observability:** `AreaNotFound`/`AreaArchived` distinction preserves callers' ability to log the difference; the public 404 path remains uniform.
- **Browser `document.fonts.ready` support:** All modern browsers support it (Chrome 35+, Firefox 41+, Safari 10+). The JS guards with a feature check just in case.
- **Concurrent meta-refresh + resize race:** If a resize is queued via `setTimeout` at exactly the moment of the 60s meta-refresh, the timer is GC'd with the page. No real bug, just noting it for completeness.
- **`equipment_service.get_area` uses `ValidationError`** for missing-area lookups — inconsistent with the new `AreaNotFound` introduced here. Out of scope for this spec; consider as future cleanup.
- **`equipment_service.get_area` callers** are unaffected by this change (we add new exceptions, don't modify existing ones).

**Future considerations (out of scope):**
- Per-area kiosks could optionally show a header banner with area name in much larger type. Current spec uses the existing 2.5rem `kiosk-area-heading`, consistent with the all-areas view.
- Could add `?refresh=N` URL parameter to override the 60s default. Not requested.
- A "rotating" kiosk that cycles through areas at intervals — explicitly out of scope per Step 1.
- A QR code on the kiosk that links to the per-area kiosk URL for easy mobile-device kiosk setup.
- Refactor `equipment_service.get_area` to raise `AreaNotFound` (the new exception) instead of `ValidationError`, for consistency.

## Revision History

- **2026-05-09 v1** — Initial spec produced via `/bmad-bmm-quick-spec`.
- **2026-05-09 v2** — Adversarial review (22 findings). All real findings addressed:
  - **F1 (Critical):** Task 1 now definitively states `class AreaNotFound(ESBError):`. Removed misleading `ValidationError` hedge.
  - **F2 (Critical):** Task 5 (template) adds an explicit `{% elif areas|length == 1 and not areas[0].equipment %}` branch with "No equipment in this area yet." copy. New AC #17.
  - **F3 (High):** Task 1 introduces `AreaArchived(AreaNotFound)`. Service raises distinct classes; view catches the parent. New AC #19.
  - **F4 (High):** Task 7 removes the `transform = 'none'` reset (CSS spec: `transform` doesn't affect layout / `scrollWidth`).
  - **F5 + F12 + F17 (High/Medium/Low):** Task 6 drops `display: inline-block; min-width: 100%` in favor of default `display: block`. Task 4 (new) sets `<main>` to `p-0` so wrapper width = viewport.
  - **F6 (High):** Task 8 dropdown filters with `selectattr('equipment')`. New AC #16.
  - **F7 (High):** Task 7 binds scaling to `window.load` and `document.fonts.ready` in addition to `DOMContentLoaded`. New AC #11.
  - **F9 (Medium):** Task 7 adds `console.warn` on empty-content case.
  - **F10 (Medium):** Task 11 modifies `test_dashboard_shows_kiosk_link` to a tighter assertion.
  - **F11 (Medium):** Task 11 adds `test_dashboard_loads_bootstrap_bundle_js`. New AC #21.
  - **F13 (Medium):** Spec uses `body.kiosk-body` form consistently.
  - **F14 (Medium):** Task 11 modifies `test_kiosk_has_visually_hidden_h1` to looser assertion.
  - **F15 (Low):** LTR assumption documented in Technical Decision #15 and Notes.
  - **F16 (Low):** Debounce updated to 150ms to actually mirror `qr-form`.
  - **F18 (Low):** Task 7 adds viewport-zero guard.
  - **F19 (Low):** Task 2 comment updated to clarify the IN-clause guard is a roundtrip-saving optimization, not a SQL-error guard.
  - **F20 (Low):** Notes mention HTML-escape test brittleness; Task 10 explicitly recommends alphanumeric area names.
  - **F21 (Low):** Task 3 explicitly notes that `abort` is already imported at `public.py:10`.
  - **F22 (Low):** Pre-mortem mentions the harmless meta-refresh/resize race.
  - **F8 (Medium, undecided):** No code change; documented browser-support note in Dependencies.

- **2026-05-09 v3** — Second adversarial review (23 findings, no Criticals). Real findings addressed:
  - **F1 (High):** Bootstrap line number corrected from `base.html:75` to `base.html:74` in 5 places.
  - **F3 (High):** Task 11 adds `test_kiosk_main_has_no_padding` and `test_per_area_kiosk_main_has_no_padding` automated tests, mirroring existing `test_kanban_uses_container_fluid` at `tests/test_views/test_repair_views.py:820`. New AC #12b.
  - **F4 (High):** AC #12 changed from manual to automated; Task 11 adds `test_app_css_kiosk_body_has_overflow_hidden` reading `app.css` directly.
  - **F5 (High):** Task 7 JS now uses `requestAnimationFrame(applyKioskScale)` retry on the zero-content branch instead of silently giving up.
  - **F6 (High):** Task 9 test pattern changed from `assert not isinstance(...)` to `assert type(exc_info.value) is AreaNotFound` for clarity.
  - **F7 (Medium):** Tech Decision #3 now documents the no-popover-on-kiosk constraint of `overflow: hidden`.
  - **F8 (Medium):** Tech Decision #16 reverted: keep `.kiosk-body` selector (no specificity bump), document scope via CSS comment instead.
  - **F9 (Medium):** Tech Decision #1 clarifies that vertical scaling dominates because the responsive grid rarely produces horizontal overflow.
  - **F11 (Medium):** Task 7 removes the dead `console.warn` (replaced by rAF retry per F5).
  - **F12 (Medium):** New Tech Decision #17 + inline JS comment: only `transform` styles allowed on `#kiosk-scale-content`.
  - **F14 (Low):** Note added in Known Limitations about return-shape contract (must be list, not generator).
  - **F15 (Low):** Note added in Task 5 that `{% if area_name %}` correctly handles None/empty/missing.
  - **F16 (Low):** Template uses `not areas[0].get('equipment')` instead of attribute access for defensive missing-key handling.
  - **F19 (Low):** Task 7 extracts `KIOSK_RESIZE_DEBOUNCE_MS = 150` constant; comment no longer couples to qr-form's implementation.
  - **F20 (Low):** Task 11 adds `test_dashboard_kiosk_dropdown_only_all_equipment_when_no_areas` for the empty-database case.
  - **F21 (Low):** Task 7 wording corrected: "Insert at line 118, before the closing `});` of the DOMContentLoaded handler".
  - **F22 (Low):** Known Limitations adds note about tall narrow viewports producing illegibly small text on cheap kiosks.
  - **F23 (Low):** Task 2 specifies insertion at line 234 of `status_service.py`.
  - **F2 (High, borderline noise):** Skipped — reviewer's own analysis judged it borderline.
  - **F10 (Medium):** Skipped — would require jsdom/headless test infrastructure not justified by the risk.
  - **F13 (Medium):** Skipped — script-tag-position assertion would couple to template internals; covered indirectly by manual testing.
  - **F17 (Low):** Skipped — already noted as harmless.
  - **F18 (Low, noise):** No change — sanity check passed.
