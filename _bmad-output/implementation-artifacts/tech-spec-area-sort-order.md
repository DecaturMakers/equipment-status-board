---
title: 'Configurable Sort Order for Areas'
slug: 'area-sort-order'
created: '2026-05-12'
status: 'completed'
stepsCompleted: [1, 2, 3, 4]
tech_stack:
  - Python 3.14
  - Flask
  - Flask-SQLAlchemy
  - Alembic / Flask-Migrate
  - Flask-WTF / WTForms
  - Jinja2
  - pytest
files_to_modify:
  - esb/models/area.py
  - esb/forms/equipment_forms.py
  - esb/services/equipment_service.py
  - esb/services/status_service.py
  - esb/slack/forms.py
  - esb/views/admin.py
  - esb/templates/admin/areas.html
  - esb/templates/admin/area_form.html
  - migrations/versions/<new>_add_area_sort_order.py
  - tests/conftest.py
  - tests/test_services/test_equipment_service.py
  - tests/test_services/test_status_service.py
  - tests/test_services/test_static_page_service.py
  - tests/test_views/test_admin_views.py
  - tests/test_views/test_equipment_views.py
  - tests/test_views/test_repair_views.py
  - tests/test_slack/test_forms.py
  - pyproject.toml
code_patterns:
  - Service layer: views never touch ORM; they call equipment_service / status_service.
  - log_mutation(action, actor, details_dict) is called inside service mutations.
  - Admin routes use @role_required('staff').
  - Alembic migrations use op.batch_alter_table for ALTERs (MariaDB-friendly).
  - Forms use Flask-WTF FlaskForm with explicit validators; views render via Jinja templates.
test_patterns:
  - Tests run against SQLite in-memory (TestingConfig).
  - Fixtures: app, client, db, staff_client, tech_client, make_equipment, make_area, make_repair_record (tests/conftest.py).
  - View tests use staff_client/tech_client fixtures; service tests construct via fixtures and assert ORM state.
---

# Tech-Spec: Configurable Sort Order for Areas

**Created:** 2026-05-12
**GitHub Issue:** #45 — "Sorting of areas on status pages"

## Overview

### Problem Statement

Issue #45: All multi-area views in the application — the public status dashboard, the kiosk display, the static status page export, the Areas admin table, and area dropdowns on equipment forms — currently render areas in alphabetical order by name. Staff at Decatur Makers want to control the order so that areas appear in a meaningful sequence (e.g., reflecting the physical layout or priority of the makerspace) rather than the accident of their names.

### Solution

Add a persistent integer `sort_order` column to the `areas` table (default `0`, NOT NULL). Allow staff to edit it through the existing Areas admin form. Replace the two `order_by(Area.name)` clauses in `equipment_service.list_areas()` and `status_service.get_area_status_dashboard()` with `order_by(Area.sort_order, Area.name)`. Because the status dashboard, kiosk view, static page export, and all area dropdowns funnel through one of these two service functions, every multi-area surface inherits the new ordering with no further changes.

### Scope

**In Scope:**
- Schema migration adding `areas.sort_order` (integer, NOT NULL, default 0).
- `Area.sort_order` model attribute.
- `sort_order` field on `AreaCreateForm` and `AreaEditForm`.
- Admin areas list page sorted by `(sort_order, name)` and showing the value.
- Reordering of `equipment_service.list_areas()` and `status_service.get_area_status_dashboard()` queries.
- Audit logging of `sort_order` changes through existing `log_mutation` plumbing.
- Updated tests covering the new ordering, form behavior, and migration default.

**Out of Scope:**
- Drag-and-drop reorder UI. A numeric input is sufficient for this iteration.
- Per-view custom orderings (one global order serves all surfaces).
- Reordering of equipment within an area.
- Reordering of archived areas (admin still lists active areas only; archived areas are not exposed). The `archive_area()` service function does not touch `sort_order`, so values are preserved across archive/unarchive cycles by design.
- Single-area routes that render only one area at a time: `/kiosk/<area_id>` (`esb/views/public.py:40`, `kiosk_area`) and the per-equipment public page (`esb/views/public.py:96`, `equipment_page`). These don't iterate areas, so ordering is meaningless.

**In-scope surfaces that inherit the new ordering automatically** (not requiring per-surface changes, but each needs a test): the public status dashboard, kiosk display, static page export, admin areas list, equipment registry filter dropdown, equipment create/edit area dropdowns, repair queue area filter, repair form area dropdowns, **and** the Slack `/esb-status` summary text rendered by `esb/slack/forms.py:format_status_summary` (called from `esb/slack/handlers.py:288` via `get_area_status_dashboard()`).

## Context for Development

### Codebase Patterns

- **Service layer is authoritative.** Views and templates do not touch `db.session` directly — they call functions in `esb/services/*.py`. The two area queries to update both live in services: `equipment_service.list_areas()` (esb/services/equipment_service.py:22) and `status_service.get_area_status_dashboard()` (esb/services/status_service.py:186; the `order_by(Area.name)` clause is at line 216).
- **Two service queries feed every multi-area HTML surface — but Slack `/esb-repair` does its own sort.** Public dashboard (esb/views/public.py:27), kiosk (esb/views/public.py:36), and static page export (esb/services/static_page_service.py:50) all call `status_service.get_area_status_dashboard()`. Admin areas list (esb/views/admin.py:168), equipment-form dropdowns (esb/views/equipment.py:43, :79, :167), and repair-form dropdowns (esb/views/repairs.py:115) all call `equipment_service.list_areas()`. Reordering those two queries propagates to every HTML consumer transitively. **However**, `esb/slack/forms.py:581` (`build_repair_dispatcher_modal`) does its own in-Python `for area_name in sorted(buckets):` loop over area names — this is a separate code path that the two service-query changes do NOT reach. See Task 4b for the explicit fix. The single-equipment public page (`esb/views/public.py:96`, `equipment_page`) does NOT use either query — it calls `status_service.compute_equipment_status()` for one item at a time and is unaffected by ordering changes.
- **All admin mutations go through `log_mutation()`.** `equipment_service.update_area()` (esb/services/equipment_service.py:98-137) computes a `changes` dict (per-field old→new lists) and emits `log_mutation('area.updated', updated_by, {..., 'changes': changes})` — but the emission is **guarded by `if changes:`** at line 129, so a no-op edit produces no log entry. `sort_order` joins this pattern unchanged: only append to `changes` when `area.sort_order != sort_order`. The existing test `test_no_log_when_no_changes` (`tests/test_services/test_equipment_service.py:271`) is the model for the same-value regression assertion.
- **Admin routes are staff-only.** Every route in the Area Management block in `esb/views/admin.py` is decorated with `@role_required('staff')`. No change here.
- **Form classes are minimal and duplicated.** `AreaCreateForm` and `AreaEditForm` (esb/forms/equipment_forms.py:22 and :30) intentionally share field definitions rather than inherit — keep that pattern; add the same `sort_order` field to both. Use `IntegerField` from `wtforms` and `NumberRange(min=0, max=999999)` + `Optional()` validators from `wtforms.validators`.
- **WTForms empty-string handling requires view-layer coercion.** `Optional()` makes the field tolerant of blank input (no validation error), but **does not coerce blank input to the field's `default`**. Empirically verified: with `Optional()` + `default=0`, an empty-string POST (`sort_order=''`, which is what the browser sends when the user clears the rendered field) yields `form.sort_order.data is None`; only an *absent* form key yields `data == 0` (the default). The view handler MUST therefore convert `None → 0` explicitly before calling the service: `sort_order_value = form.sort_order.data if form.sort_order.data is not None else 0`. The form-side `filters=` parameter cannot fix this because `IntegerField.process_formdata` runs `int('')` (which raises `ValueError`) before filters apply.
- **Templates iterate `areas` differently across surfaces.** All four area-rendering templates (`admin/areas.html`, `public/status_dashboard.html`, `public/kiosk.html`, `public/static_page.html`) loop over an `areas` collection produced by a service function, **but only the kiosk display filters empties with `selectattr('equipment')`** — `public/status_dashboard.html:39` and `public/static_page.html` iterate `areas` directly with no filter. The kiosk dropdown section in `status_dashboard.html:20` does use `selectattr`, but the main per-area list does not. Implication: the new ordering propagates through both the populated and empty-area paths; whichever surfaces show empty areas today will continue to, in the new sort order. Only the admin areas template needs a new display column.
- **Slack `/esb-status` is also a multi-area surface.** `esb/slack/forms.py:format_status_summary` (called from `esb/slack/handlers.py:288`) renders one Slack line per area from the same `get_area_status_dashboard()` result, so the new ordering flows through the Slack summary too. This was not flagged in the original Out-of-Scope list but is included in scope here for completeness — no Slack code changes are needed, only a regression test.
- **Migrations use Alembic batch mode.** Existing migrations (e.g., `migrations/versions/2e0d6d8be171_add_areas_table.py`) wrap schema changes in `op.batch_alter_table(...)` for MariaDB compatibility. New migration must use the same pattern when adding the column, and use `server_default='0'` so existing rows backfill before the NOT NULL constraint takes effect.

### Existing Tests Affected (Investigation Findings)

- `tests/test_services/test_equipment_service.py:18-30` (`test_returns_active_areas_ordered`) — assertion `names == ['Electronics Lab', 'Metal Shop', 'Woodshop']` still passes because all three areas keep `sort_order=0` (model default) and the secondary key is still `name`. **However**, the test now passes *for an uninteresting reason* (it never exercises the new compound ordering), so a separate new test `test_orders_by_sort_order_then_name` MUST be added with explicit mixed `sort_order` values. Also update both the service docstring at `esb/services/equipment_service.py:23` *and* the test docstring at `tests/test_services/test_equipment_service.py:19` to mention `(sort_order, name)`.
- `tests/test_services/test_equipment_service.py:207-296` (`TestUpdateArea`) — there are seven existing positional call sites to `update_area(area_id, name, slack_channel, updated_by)`: lines ~214, 223, 233, 242, 249, 258, 277. The proposed `update_area` signature change MUST be backward-compatible (see Task 5: use keyword-only `sort_order: int | None = None` argument appended after `updated_by`). With that signature, no existing test call site needs editing.
- `tests/test_services/test_equipment_service.py:271-283` (`test_no_log_when_no_changes`) — this test asserts that updating an area with the same `name`/`slack_channel`/`channel` emits no `area.updated` log entry. Model the new no-op-on-sort_order regression test on this one.
- `tests/test_services/test_status_service.py:192-272` covers `get_area_status_dashboard()`. The existing `test_multiple_areas_sorted_by_name` (`tests/test_services/test_status_service.py:266`) asserts areas are returned in alphabetical name order — **its docstring "Areas are returned sorted by name" becomes a lie after this change.** Update the docstring to mention `(sort_order, name)` and either retain it as the all-zero-sort case or supersede it with a new test that uses explicit mixed values. Then add a new test `test_orders_areas_by_sort_order_then_name` covering the compound ordering with explicit values.
- `tests/test_views/test_admin_views.py:606-714` covers `TestCreateAreaPost` and `TestEditArea` POST flows. Each existing test omits the `sort_order` form key. With `Optional()` + `default=0` (see Task 6), absent-key submissions resolve cleanly to 0, so no existing test payloads need changes. **However**, this property MUST be verified by an explicit new test (AC 10).
- `tests/test_views/test_admin_views.py:923-968` (`TestAreaMutationLogging`) — extend with two new tests: (a) editing only `sort_order` produces an `area.updated` log entry whose `changes` dict has a `sort_order` key; (b) re-saving the same `sort_order` value produces **no** `area.updated` entry (couples to the `if changes:` guard in `update_area`).
- Slack tests in `tests/test_slack/test_forms.py:408-514` consume `get_area_status_dashboard()` output but assert on per-area content, not ordering. Add a small new test that creates three areas with mixed `sort_order`, equipment in each, then renders `format_status_summary(...)` and asserts the line order matches `(sort_order, name)`.

### Files to Reference

| File | Purpose |
| ---- | ------- |
| esb/models/area.py | `Area` SQLAlchemy model — add `sort_order` column here. |
| esb/forms/equipment_forms.py | `AreaCreateForm` / `AreaEditForm` — add IntegerField with `Optional()` + `NumberRange(min=0, max=999999)`. |
| esb/services/equipment_service.py | `list_areas()`, `create_area()`, `update_area()` — accept and persist `sort_order`. |
| esb/services/status_service.py | `get_area_status_dashboard()` query reorder. |
| esb/services/static_page_service.py | Consumer of `get_area_status_dashboard()` — no code change, integration test only. |
| esb/slack/forms.py | `build_repair_dispatcher_modal` (line 554) does its own `sorted(buckets)` over area names — REQUIRES code change (Task 4b). `format_status_summary` (line 20) is a transitive consumer requiring no code change. |
| esb/slack/handlers.py | Call site for `format_status_summary` (esb/slack/handlers.py:288). |
| esb/views/admin.py | `create_area` / `edit_area` route handlers — pass `sort_order` through. |
| esb/views/equipment.py / esb/views/repairs.py | Consumers of `list_areas()` for dropdowns — no code change, ordering propagates automatically. |
| esb/templates/admin/areas.html | Admin areas table — surface `sort_order` column. |
| esb/templates/admin/area_form.html | Render new form field with HTML `type="number" min="0" max="999999" step="1"`. |
| migrations/versions/2e0d6d8be171_add_areas_table.py | Reference Alembic style for the new migration. |
| migrations/versions/2d0213647834_add_pending_notifications_table.py | Current Alembic head — the new migration's `down_revision`. |
| tests/conftest.py | `make_area` fixture / `_create_area` helper — extend in Task 10. |
| CLAUDE.md | "Database Migrations" + "Releases" sections — migration process; required version bump. |

### Technical Decisions

- **Numeric input over drag-and-drop.** A simple `IntegerField` with default `0` keeps the UI scope small and matches the surrounding admin form aesthetic. Ties are broken by `name ASC`, so leaving every area at `0` preserves today's purely-alphabetical ordering for users who don't opt in.
- **`Optional()` + `default=0` + view-layer `None → 0` coercion.** Together they solve the three input cases for `sort_order`: (a) absent form key → `data == 0` (default applies via the absent-key path); (b) empty string from cleared form → `data is None` (then view coerces to `0`); (c) explicit integer string → `data == int(value)`. `Optional()` alone does NOT coerce empty-string to the default — that is a WTForms semantic confirmed empirically. The view-layer `if data is None else 0` is therefore mandatory and cannot be removed without re-introducing the empty-string crash described under "WTForms empty-string handling" in Codebase Patterns.
- **`NumberRange(min=0, max=999999)` bounds the field.** Prevents accidental fat-finger overflow into MariaDB's signed `INT` range (max `2,147,483,647`). The choice of `999999` is intentionally far below the DB limit, leaves headroom for future use, and is enforced both by the WTForms validator (server-side) and by the HTML `max="999999"` attribute on the rendered `<input type="number">` (client-side hint).
- **`update_area` uses a keyword-only `sort_order: int | None = None` sentinel.** Preserves backward compatibility with all seven existing positional call sites in `TestUpdateArea` (which would silently break with any positional insertion). When `sort_order is None`, the function leaves the field untouched; when an int is provided, the standard `if area.sort_order != sort_order:` diff check populates `changes`. The view layer always supplies `form.sort_order.data`, so the sentinel branch is only used by test code that hasn't been extended.
- **No service-layer `int()` cast.** An earlier revision of this spec called for `int(sort_order)` at the service boundary as defense against a hypothetical future JSON caller. Per CLAUDE.md ("Don't add error handling, fallbacks, or validation for scenarios that can't happen. Trust internal code and framework guarantees."), that cast was removed in code review. The type annotations (`sort_order: int = 0` on `create_area`, `sort_order: int | None = None` on `update_area`) and the view-layer coercion at `esb/views/admin.py:178, 208` are the contract; new callers that bypass that contract must coerce their own input.
- **NOT NULL with `server_default='0'`.** Avoids three-valued sort logic and makes the Alembic migration backfill atomic — without `server_default`, the `add_column(... nullable=False)` would fail on rows that have no value at the moment the constraint takes effect. `default=0` at the ORM layer covers Python-driven inserts.
- **Compound `ORDER BY (sort_order, name)`.** Stable, deterministic, no surprises for areas that share a sort value; alphabetical remains the secondary key so today's behavior is the limit case.
- **No new index — explicit filesort trade-off.** The existing `ix_areas_name` index (created by `migrations/versions/2e0d6d8be171_add_areas_table.py:31`) covers `name` alone, so MariaDB cannot use it to satisfy `ORDER BY sort_order, name` — it will fall back to a `Using filesort`. This is acceptable here because the `areas` table is tiny (a handful of rows at Decatur Makers, with no production seed data growing it). Revisit if the table ever grows substantially; a composite index `(sort_order, name)` is the obvious mitigation.
- **`sort_order` is preserved across archive/unarchive cycles by design.** `equipment_service.archive_area()` (esb/services/equipment_service.py:140-161) only flips `is_archived`; it does not touch any other field. The new `sort_order` is left intact, so unarchiving an area restores its previous sort position automatically. This is intentional; a test in `TestArchiveArea` should pin the behavior.
- **Downgrade is structurally reversible but data-destroying.** `flask db downgrade` runs `batch_op.drop_column('sort_order')`, which removes the column and all user-set values. Re-running `upgrade` afterwards repopulates every row with `0`, not the previous values. This is acceptable for emergency rollback but should not be used as a casual "edit then revert" tool.
- **Service layer is the single ordering authority.** Touching only the two service queries propagates the new ordering to every consumer (admin list, public dashboard, kiosk, static export, equipment-form dropdowns, repair-form dropdowns, Slack `/esb-status`) without per-template changes.

## Implementation Plan

### Tasks

Tasks are ordered by dependency: schema → model → service signature/queries → forms → views → templates → tests. Within each task, the **File**, **Action**, and **Notes** fields are precise enough for a fresh agent to implement without re-reading conversation history.

- [x] **Task 1: Add `sort_order` column to the `Area` model.**
  - File: `esb/models/area.py`
  - Action: Add `sort_order = db.Column(db.Integer, nullable=False, default=0, server_default='0')` between `is_archived` and `created_at`.
  - Notes: `server_default='0'` is essential — without it, Alembic's added column will not have a default at the DB level, and existing rows on MariaDB will violate NOT NULL during the upgrade. `default=0` covers ORM-level inserts.

- [x] **Task 2: Generate the Alembic migration.**
  - File: `migrations/versions/<new_revision>_add_area_sort_order.py` (new file; revision auto-generated)
  - Action: Follow the CLAUDE.md "Database Migrations" procedure: ensure DB container is running, inspect its IP, then run `DATABASE_URL=mysql+pymysql://root:esb_dev_password@<ip>/esb flask db migrate -m "Add sort_order to areas"`. Accept the auto-generated body as-is — for `add_column` on MariaDB, plain `op.add_column('areas', sa.Column('sort_order', sa.Integer(), nullable=False, server_default='0'))` is correct and matches the project convention (the existing `2d0213647834` migration uses `op.batch_alter_table` only for `create_index`, not for column adds). Verify only:
    - `down_revision` is set to the current head (`'2d0213647834'` at the time of writing — `add_pending_notifications_table`).
    - The added column is `sa.Column('sort_order', sa.Integer(), nullable=False, server_default='0')` (the `server_default='0'` is critical — without it, the NOT NULL constraint fails on the existing rows).
    - `downgrade()` drops the column.
  - Notes: If the auto-generated migration omits `server_default='0'` (the autogenerator does not always emit defaults from model-level `default=` values), hand-edit it in. This is the only edit that may be required.

- [x] **Task 3: Reorder `equipment_service.list_areas()`.**
  - File: `esb/services/equipment_service.py:22-28`
  - Action: Change `order_by(Area.name)` to `order_by(Area.sort_order, Area.name)`. Update the docstring from "ordered by name" to "ordered by `(sort_order, name)`".
  - Notes: Do not modify the filter — archived areas remain excluded.

- [x] **Task 4: Reorder `status_service.get_area_status_dashboard()`.**
  - File: `esb/services/status_service.py` — function header at line 186; the `.order_by(Area.name)` clause at line 216 (inside the area-fetch query at lines 212-220).
  - Action: Change `.order_by(Area.name)` to `.order_by(Area.sort_order, Area.name)`. No other change to the function.
  - Notes: The dashboard's downstream consumers (public dashboard, kiosk, static page export, Slack `/esb-status` summary) all see the new order transitively.

- [x] **Task 4b: Reorder `build_repair_dispatcher_modal` area buckets.**
  - File: `esb/slack/forms.py:554-596` (`build_repair_dispatcher_modal`)
  - Action: Replace the alphabetical sort of bucket keys with one that honors `(sort_order, name)`. Build a parallel lookup of area sort keys while iterating `open_records`, then sort buckets by that lookup:
    ```python
    buckets: dict[str, list] = {}
    area_sort_keys: dict[str, tuple[int, str]] = {}
    for record in open_records:
        area = record.equipment.area
        area_name = area.name if area else 'No Area'
        sort_order = area.sort_order if area else 0
        area_sort_keys[area_name] = (sort_order, area_name)
        buckets.setdefault(area_name, []).append(record)

    option_groups = []
    for area_name in sorted(buckets, key=lambda n: area_sort_keys[n]):
        ...
    ```
    Update the function docstring at lines 561-566 to describe the new ordering rule (replace "Across area groups, areas are presented alphabetically (A-Z)." with the `(sort_order, name)` rule).
  - Notes: Without this change, `/esb-repair` would still group areas alphabetically while every other multi-area surface respects `sort_order` — a confusing inconsistency for staff. Test impact:
    - The existing test `test_option_groups_by_area_sorted_alphabetically` (`tests/test_slack/test_forms.py:609`) MUST be updated: rename to `test_option_groups_by_area_sorted_by_sort_order_then_name`. Replace the existing fixture-area names (`'Alpha'`, `'Zoo'`) with three areas using mixed `sort_order` values so the assertion meaningfully distinguishes from alphabetical (e.g., names `'A'`, `'B'`, `'C'` with sort_order `10, 5, 5` → expected order `B, C, A`). Update the test's docstring to remove the stale `"AC 31"` reference and to describe the new `(sort_order, name)` ordering instead.
    - The "No Area" sentinel bucket in the function body is defensive (`equipment.area_id` is `NOT NULL`); no test path constructs equipment without an area, so the sentinel branch is intentionally untested.

- [x] **Task 5: Extend `create_area` and `update_area` services to accept `sort_order`.**
  - File: `esb/services/equipment_service.py:71-95` (`create_area`) and `:98-137` (`update_area`)
  - Action:
    - **`create_area`**: change signature to `create_area(name, slack_channel, created_by, sort_order: int = 0)`. In the body, cast defensively (`sort_order = int(sort_order)`) before passing to the `Area(...)` constructor. Include `'sort_order': area.sort_order` in the `log_mutation('area.created', ...)` payload.
    - **`update_area`**: change signature to `update_area(area_id, name, slack_channel, updated_by, *, sort_order: int | None = None)` — keyword-only, appended after `updated_by`, sentinel default. This preserves backward compatibility with all seven existing positional call sites in `TestUpdateArea` (`tests/test_services/test_equipment_service.py` lines ~214, 223, 233, 242, 249, 258, 277), which would silently break if `sort_order` were inserted as a middle positional argument. In the body, after the existing `name` and `slack_channel` diff blocks, add:
      ```python
      if sort_order is not None:
          sort_order = int(sort_order)
          if area.sort_order != sort_order:
              changes['sort_order'] = [area.sort_order, sort_order]
              area.sort_order = sort_order
      ```
      The existing `if changes:` guard at line 129 already covers the no-op case — no separate guard needed.
  - Notes: The view layer (Task 7) always supplies `sort_order=int_value` (never `None`), so the sentinel branch in `update_area` only fires for legacy test code that omits the kwarg. This intentionally keeps the existing `TestUpdateArea` tests valid without modification.

- [x] **Task 6: Add `sort_order` field to `AreaCreateForm` and `AreaEditForm`.**
  - File: `esb/forms/equipment_forms.py:22-35`
  - Action:
    1. **Add `IntegerField` to the existing wtforms import** at line 5:
       ```python
       from wtforms import (
           BooleanField,
           DateField,
           DecimalField,
           IntegerField,    # <-- new
           SelectField,
           StringField,
           SubmitField,
           TextAreaField,
       )
       ```
       Forgetting this is the most likely silent failure mode — the form module fails to load at import time with `NameError`.
    2. **Add `NumberRange` to the existing validators import** at line 14 (which already imports `Optional`):
       ```python
       from wtforms.validators import URL, DataRequired, Length, NumberRange, Optional
       ```
    3. Add to both `AreaCreateForm` and `AreaEditForm`, placed between `slack_channel` and `submit`:
       ```python
       sort_order = IntegerField(
           'Sort Order',
           default=0,
           validators=[
               Optional(),
               NumberRange(
                   min=0,
                   max=999999,
                   message='Sort order must be between 0 and 999999.',
               ),
           ],
       )
       ```
  - Notes: **`Optional()` does NOT coerce blank input to `default=0`** — empirically verified, blank input yields `data is None`. The view handler in Task 7 must convert `None → 0` before calling the service. The `max=999999` bound prevents accidental fat-finger overflow into MariaDB's signed-INT range (`2,147,483,647`). The HTML5 `max="999999"` attribute on the rendered input (Task 8) is advisory only — server-side `NumberRange(max=...)` is authoritative; tests using `client.post` bypass HTML5 validation entirely, which is the correct integration test surface.

- [x] **Task 7: Wire `sort_order` through admin view handlers.**
  - File: `esb/views/admin.py:172-222`
  - Action: In **both** `create_area` and `edit_area`, after `form.validate_on_submit()` but before calling the service, materialize the coerced value:
    ```python
    sort_order_value = form.sort_order.data if form.sort_order.data is not None else 0
    ```
    Then pass `sort_order=sort_order_value` to `equipment_service.create_area(...)` / `equipment_service.update_area(...)`. The `AreaEditForm(obj=area)` instantiation already prefills the field from the model on GET; the explicit None coercion handles the empty-string POST case.
  - Notes: This coercion is the single fix for the WTForms empty-string-yields-None behavior. Without it, an empty-string POST would crash `create_area` (`int(None)` TypeError) and silently no-op `update_area` (sentinel branch) — see "WTForms empty-string handling" in Codebase Patterns. No changes to flash messages, redirects, or error handling.

- [x] **Task 8: Render `sort_order` in the admin area form template.**
  - File: `esb/templates/admin/area_form.html`
  - Action: After the `slack_channel` field block, add an identical block for `sort_order`:
    ```jinja
    <div class="mb-3">
        <label for="sort_order" class="form-label">Sort Order</label>
        {{ form.sort_order(class="form-control" ~ (" is-invalid" if form.sort_order.errors else ""), type="number", min="0", max="999999", step="1") }}
        <div class="form-text">Lower numbers appear first on status pages. Ties are broken alphabetically. Leave at 0 for default alphabetical ordering.</div>
        {% for error in form.sort_order.errors %}
        <div class="invalid-feedback">{{ error }}</div>
        {% endfor %}
    </div>
    ```
  - Notes: `type="number" step="1"` enables a native spinner and integer-only client validation in modern browsers; `max="999999"` mirrors the server-side `NumberRange(max=...)` bound. The label-as-not-required (no asterisk) is intentional — `Optional()` + `default=0` allow blank/missing input.

- [x] **Task 9: Surface `sort_order` in the admin areas list template.**
  - File: `esb/templates/admin/areas.html`
  - Action:
    - Desktop table (lines 14-36): add a `<th>Sort Order</th>` between `<th>Name</th>` and `<th>Slack Channel</th>`, and a corresponding `<td>{{ area.sort_order }}</td>` in the row body.
    - Mobile card section (lines 39-50): inside each card, after the slack-channel line, add `<p class="card-text text-muted mb-2 small">Sort order: {{ area.sort_order }}</p>`.
  - Notes: Areas in this template already arrive in `(sort_order, name)` order from `list_areas()` after Task 3 — no template-side sorting needed.

- [x] **Task 10: Extend the `_create_area` fixture helper to accept `sort_order`.**
  - File: `tests/conftest.py:77-88`
  - Action: Change `_create_area(name='Test Area', slack_channel='#test-area')` to `_create_area(name='Test Area', slack_channel='#test-area', sort_order=0)`. Pass `sort_order=sort_order` to the `Area(...)` constructor. The `make_area` fixture at line 86 returns the bound helper unchanged.
  - Notes: Existing `make_area(...)` call sites (hundreds across the test suite) pass `name` and/or `slack_channel` only — the new optional keyword arg is additive and won't break any of them. New tests in Tasks 11-13 use `make_area(name=..., sort_order=N)` rather than constructing `Area(...)` manually, keeping a single fixture pattern.

- [x] **Task 11: Update / extend tests for `equipment_service.list_areas()`.**
  - File: `tests/test_services/test_equipment_service.py` (around line 18-30)
  - Action:
    - In `test_returns_active_areas_ordered`, update both the test name and docstring (or just the docstring) to mention `(sort_order, name)` ordering. The existing assertion still passes because all areas have `sort_order=0` and the secondary key is `name`.
    - Add new test `test_orders_by_sort_order_then_name`: use `make_area(name='Area A', sort_order=10)`, `make_area(name='Area B', sort_order=5)`, `make_area(name='Area C', sort_order=5)`; assert `[a.name for a in list_areas()] == ['Area B', 'Area C', 'Area A']`.
  - Notes: Use the extended fixture from Task 10. Do not construct `Area(...)` manually.

- [x] **Task 12: Add ordering tests for `get_area_status_dashboard()`.**
  - File: `tests/test_services/test_status_service.py` (in `TestGetAreaStatusDashboard`, around line 266)
  - Action:
    - Update the existing `test_multiple_areas_sorted_by_name` (line 266): change its docstring to mention `(sort_order, name)` ordering. The existing assertion still passes (all areas have default `sort_order=0`) but now documents the compound rule.
    - Add new test `test_orders_areas_by_sort_order_then_name`. Use `make_area(..., sort_order=N)` for three areas with mixed values; create one piece of equipment per area via `make_equipment` (the service returns areas regardless of equipment, but matching the existing fixture pattern keeps the test idiomatic); assert `[r['area'].name for r in status_service.get_area_status_dashboard()]` is in the expected order.
  - Notes: Verify the service does NOT depend on equipment presence by reading the code — if it does (e.g., `selectattr` filter inside the service), adapt the test accordingly. Today's code returns all non-archived areas regardless.

- [x] **Task 13: Update service tests for `create_area`/`update_area` to cover `sort_order`.**
  - File: `tests/test_services/test_equipment_service.py` (TestCreateArea class starting line 138; TestUpdateArea starting around line 207)
  - Action:
    - `TestCreateArea`: add `test_creates_area_with_sort_order` that passes `sort_order=42` and asserts `area.sort_order == 42`; add `test_creates_area_with_default_sort_order` that omits the kwarg and asserts `area.sort_order == 0`; add `test_logs_sort_order_in_created_event` that uses `capture` to verify the `area.created` mutation payload includes `'sort_order': 42`.
    - `TestUpdateArea`: add `test_updates_sort_order` that mutates `sort_order` from 0 to 7 via `update_area(..., sort_order=7)` and verifies persistence and that the `log_mutation` `changes` payload contains `{'sort_order': [0, 7]}`. Add `test_no_log_when_sort_order_unchanged` (model on existing `test_no_log_when_no_changes` at line 271): set `area.sort_order = 5`, call `update_area(..., sort_order=5)`, assert no `area.updated` event is emitted (guarded by the existing `if changes:` block). Add `test_omitted_sort_order_kwarg_preserves_value`: create an area with `sort_order=5`, call the legacy `update_area(area_id, 'Same Name', '#same', 'staffuser')` (no `sort_order` kwarg), then assert `area.sort_order == 5`. This pins the keyword-only-sentinel contract — old positional calls must not clobber the field.
    - Verify all seven existing positional `update_area(area_id, name, slack_channel, updated_by)` call sites in this file still pass — they will, because Task 5 made `sort_order` keyword-only.
  - Notes: The `capture` fixture used elsewhere in the file (look around line 178 for prior usage) is the right tool for asserting on mutation events.

- [x] **Task 14: Update view tests for admin area routes.**
  - File: `tests/test_views/test_admin_views.py`
  - Action:
    - **`TestCreateAreaPost` (line 606)**:
      - Add `test_creates_area_with_sort_order`: POSTs `{'name': 'X', 'slack_channel': '#x', 'sort_order': '7'}` and asserts the persisted area has `sort_order == 7`.
      - Add `test_creates_area_with_empty_sort_order_defaults_to_zero`: POSTs `sort_order=''` (explicit empty string from the rendered form) and asserts the area is created with `sort_order == 0` — this guards against the empty-string POST regression that the view-layer `None → 0` coercion (Task 7) prevents.
      - Add `test_creates_area_rejects_negative_sort_order` (covers AC 6): POSTs `sort_order='-3'`, asserts `resp.status_code == 200` (re-render, not redirect), `b'Sort order must be between 0 and 999999.' in resp.data`, AND that no area row was inserted (count via `_db.session.execute(_db.select(Area)).all()`).
      - Add `test_creates_area_rejects_over_max_sort_order` (covers AC 6): POSTs `sort_order='1000000'`, same assertions as above.
      - Add `test_creates_area_rejects_non_integer_sort_order` (covers AC 6): POSTs `sort_order='abc'`, same assertions as above; assert that the rendered HTML contains *both* `b'Not a valid integer value.'` and `b'Sort order must be between 0 and 999999.'` (WTForms emits both).
    - **`TestEditArea` (line 659)**:
      - Add `test_updates_sort_order`: POSTs an edit with a changed `sort_order` and asserts the updated value.
      - Extend `test_renders_edit_form` (line 662) to also assert `b'Sort Order'` is present in the form HTML AND that the rendered field has the area's current value. Use a regex anchored to the field's `name` attribute to avoid matching other inputs:
        ```python
        import re
        assert b'Sort Order' in resp.data
        match = re.search(rb'<input [^>]*name="sort_order"[^>]*>', resp.data)
        assert match is not None
        assert b'value="0"' in match.group(0)  # area created via make_area defaults to 0
        ```
    - **`TestListAreas` (line 530)** (covers AC 7):
      - Add `test_table_shows_sort_order_column`: GET `/admin/areas`, assert `b'Sort Order' in resp.data` (column header) and that the rendered HTML contains the area's `sort_order` value rendered as a table cell. Use a regex anchored on the area-row structure rather than a bare substring search.
      - Add `test_areas_listed_in_sort_order_then_name`: create three areas with mixed `sort_order` (e.g., `make_area(name='Area A', sort_order=10)`, `Area B sort_order=5`, `Area C sort_order=5`), GET `/admin/areas`, then assert the byte-positions of the names: `resp.data.find(b'Area B') < resp.data.find(b'Area C') < resp.data.find(b'Area A')`. Sentinel-check first that each `find()` returns a non-negative value.
    - **`TestAreaMutationLogging` (line 923)**:
      - Add `test_sort_order_change_logged`: edits only `sort_order` and asserts the logged `data.changes` dict contains a `sort_order` key whose value is `[old, new]`.
      - Add `test_no_log_when_sort_order_unchanged`: re-saves the same value and asserts no `area.updated` log entry is emitted (the existing `if changes:` guard at `equipment_service.py:129` enforces this). Cover both the `5 → 5` and `0 → 0` cases (the latter is the more common scenario for users who never touch the field).
    - **`TestArchiveArea` (line 717)**:
      - Add `test_archive_preserves_sort_order`: create an area with explicit `sort_order=5`, call the existing `archive_area` service via POST `/admin/areas/<id>/archive`, then assert the column value via direct DB query (`_db.session.get(Area, area.id).sort_order == 5`). Do not toggle `is_archived` back via the ORM — it is not a public-API operation and there is no UI for it; the assertion on the column value is sufficient to pin "archive does not touch sort_order."
  - Notes: No changes required to existing tests because the new form field has `Optional()` + `default=0`; absent form keys resolve to 0. All new tests use the extended `make_area(..., sort_order=N)` fixture from Task 10.

- [x] **Task 14b: Add view-level ordering tests for public dashboard and kiosk (covers AC 2/3/4 at the rendered-HTML layer).**
  - File: `tests/test_views/test_public_views.py`
  - Action: Add two tests (mirror the pattern from `TestListAreas::test_areas_listed_in_sort_order_then_name`):
    - `test_status_dashboard_renders_areas_in_sort_order_then_name`: GET `/`, assert area-name byte positions in `resp.data` reflect `(sort_order, name)`. Each area needs at least one piece of equipment because the public dashboard renders area sections regardless, but kiosk filters empties.
    - `test_kiosk_renders_areas_in_sort_order_then_name`: GET `/kiosk`, same assertion pattern (with each area populated).
  - Notes: Sentinel-check `find()` results to be non-negative before the comparison chain (otherwise `-1 < N` silently passes for missing names). Pattern:
    ```python
    pos_b = resp.data.find(b'Area B')
    pos_c = resp.data.find(b'Area C')
    pos_a = resp.data.find(b'Area A')
    assert pos_b >= 0 and pos_c >= 0 and pos_a >= 0, 'one or more area names missing from response'
    assert pos_b < pos_c < pos_a
    ```

- [x] **Task 15: Add ordering regression tests for dropdown surfaces.**
  - File: `tests/test_views/test_equipment_views.py` and `tests/test_views/test_repair_views.py` (or extend existing test files that cover these views)
  - Action: Add one test per page that creates three areas with mixed `sort_order`, renders the page, and asserts area-name order in the rendered HTML:
    - Equipment registry filter dropdown at `/equipment` (rendered from `equipment_service.list_areas()` via `esb/views/equipment.py:43`).
    - Equipment create form area dropdown at `/equipment/new` (esb/views/equipment.py:80-82). Note: the choices list prepends `(0, '-- Select Area --')` as the first `<option>` — strip it before asserting on order.
    - Equipment edit form area dropdown at `/equipment/<id>/edit` (esb/views/equipment.py:167-170). Same `-- Select Area --` placeholder.
    - Repair queue area filter at `/repairs/queue` (esb/views/repairs.py:115). Note: that template prepends an `<option value="">All Areas</option>` placeholder — strip before asserting.
  - Notes: Use a minimal extraction pattern that strips placeholder rows. Example:
    ```python
    import re
    options = re.findall(r'<option[^>]*>([^<]+)</option>', resp.data.decode())
    area_options = [o for o in options if o not in ('-- Select Area --', 'All Areas')]
    assert area_options == ['Area B', 'Area C', 'Area A']
    ```
    Repeat per page. Do not import BeautifulSoup; the regex above is sufficient and the project does not depend on it.

- [x] **Task 16: Add Slack `format_status_summary` ordering test.**
  - File: `tests/test_slack/test_forms.py` (after the existing tests around line 514)
  - Action: Add `test_format_status_summary_respects_area_sort_order`. Create three areas with mixed `sort_order` plus one piece of equipment in each; call `format_status_summary(status_service.get_area_status_dashboard())`; assert area-header line order. Use string-position assertions rather than naive line splitting because the function interleaves area-count lines with non-green equipment bullet lines:
    ```python
    summary = format_status_summary(status_service.get_area_status_dashboard())
    pos_b = summary.find('Area B')
    pos_c = summary.find('Area C')
    pos_a = summary.find('Area A')
    assert pos_b >= 0 and pos_c >= 0 and pos_a >= 0, 'area names missing from summary'
    assert pos_b < pos_c < pos_a
    ```
    Do not split on `\n` — equipment bullets containing area-name substrings would match incorrectly. Sentinel-check `find()` results to defend against silent passes when a name is missing (`-1 < N` is always True).
  - Notes: For `format_status_summary` itself, no production code change is needed (it consumes whatever order `get_area_status_dashboard()` returns). The dispatcher modal IS a code change (see Task 4b).

- [x] **Task 17: Add static page export ordering integration test.**
  - File: `tests/test_services/test_static_page_service.py` (file exists; extend the existing `TestGenerate` class)
  - Action: Add `test_generate_orders_areas_by_sort_order_then_name` to the `TestGenerate` class. Create three areas with mixed `sort_order` (e.g., `make_area(name='Area A', sort_order=10)`, `make_area(name='Area B', sort_order=5)`, `make_area(name='Area C', sort_order=5)`) plus one piece of equipment in each; invoke `static_page_service.generate()`; sentinel-check that each area name appears in the HTML before asserting positions:
    ```python
    pos_b = html.find('Area B')
    pos_c = html.find('Area C')
    pos_a = html.find('Area A')
    assert pos_b >= 0 and pos_c >= 0 and pos_a >= 0, 'area names missing from rendered HTML'
    assert pos_b < pos_c < pos_a
    ```
    Without the sentinel, `find()` returning `-1` for a missing name silently passes the comparison.
  - Notes: The file already imports `app`, `make_area`, `make_equipment` fixtures via the project conftest. Use the same `make_area` / `make_equipment` pattern as the existing `test_returns_html_with_area_and_equipment` test. Do NOT create a new test module.

- [ ] **Task 18: Bump `pyproject.toml` version (DEFERRED — batched with other unreleased changes).**
  - File: `pyproject.toml`
  - Action: Intentionally deferred at the PR author's request — the maintainer has a queue of unreleased changes that will be bundled into a single future version bump rather than cutting a release per merged PR.
  - Notes: When the bundle ships, bump to whatever value the bundle warrants (likely `0.7.0` or higher depending on what else lands). Per CLAUDE.md "Releases", the release workflow auto-tags on push to `main` once the version exceeds the latest tag.

- [x] **Task 19: Run the full test suite and lint.**
  - File: (commands)
  - Action: Run `make test` and `make lint`. Address any failures before considering the task done.
  - Notes: Per CLAUDE.md, ruff is configured at 120 chars / target py3.13.

- [x] **Task 20: Verify the migration manually against MariaDB (covers AC 1).**
  - File: (commands; no source change)
  - Action: AC 1 — that the migration backfills existing rows to `sort_order=0` — has no automated test (the test fixture uses `db.create_all()` from models, not Alembic). Verify manually:
    1. Ensure the DB container is running (`docker compose up -d db`) and contains pre-existing area rows. If the DB is empty, insert two rows with the OLD schema (i.e., before applying this migration) — for example, by checking out `main`, running `make migrate`, then creating areas via `/admin/areas/new`.
    2. Switch to the issue branch and apply the new migration: `DATABASE_URL=mysql+pymysql://root:esb_dev_password@<container_ip>/esb flask db upgrade`.
    3. Connect to the DB (`docker exec -it equipment-status-board-db-1 mariadb -uroot -pesb_dev_password esb`) and run `SELECT id, name, sort_order FROM areas;`. All pre-existing rows MUST show `sort_order=0`.
    4. Run `flask db downgrade` then `flask db upgrade` again to confirm the cycle works structurally (with the documented caveat that user-set values are lost on downgrade).
  - Notes: Cannot be automated in CI without a MariaDB-backed test job. Document the verification result in the PR description.

### Acceptance Criteria

- [x] **AC 1 — Migration applies cleanly with backfill:**
  Given the database contains existing area rows from before this change, when `flask db upgrade` runs the new migration, then the `sort_order` column exists, is NOT NULL, and every pre-existing row has `sort_order = 0`.

- [x] **AC 2 — Default behavior matches today's alphabetical order:**
  Given two or more areas with `sort_order = 0` (the default), when the status dashboard, kiosk, static export, or admin areas page is rendered, then areas appear in alphabetical order by `name`.

- [x] **AC 3 — Explicit sort_order takes precedence over name:**
  Given areas `Zebra` (`sort_order=1`) and `Alpha` (`sort_order=2`), when any multi-area view is rendered, then `Zebra` appears before `Alpha`.

- [x] **AC 4 — Ties resolve alphabetically:**
  Given areas `Charlie`, `Alpha`, `Bravo` all with `sort_order = 5`, when any multi-area view is rendered, then the order is `Alpha`, `Bravo`, `Charlie`.

- [x] **AC 5 — Admin form accepts and persists sort_order:**
  Given a staff user on `/admin/areas/new` or `/admin/areas/<id>/edit`, when they submit the form with `sort_order = 7`, then the area is created/updated with `sort_order == 7` and the user is redirected back to `/admin/areas` with the success flash.

- [x] **AC 6 — Admin form validates `sort_order` bounds (server-side authoritative):**
  Given a staff user submits the create or edit form with `sort_order = -3`, when the form is processed, then the form re-renders with a validation error on the `sort_order` field and no DB change occurs. Given the same form with `sort_order = 1000000` (above the `max=999999` bound), the same validation rejection occurs. Given a non-integer like `sort_order = 'abc'`, validation fails with both `Not a valid integer value.` and `Number must be between 0 and 999999.` errors. These ACs are verified using `client.post` (the test client bypasses HTML5 input attributes), confirming the server-side `NumberRange` and `IntegerField` validators are authoritative regardless of client behavior.

- [x] **AC 7 — Admin areas list shows the value:**
  Given multiple areas exist with distinct `sort_order` values, when a staff user loads `/admin/areas`, then the rendered HTML contains each area's `sort_order` value (desktop table column and mobile card line both pass), and the areas appear in `(sort_order, name)` order.

- [x] **AC 8 — Mutation event records the change when sort_order actually changes:**
  Given an area with `sort_order = 0`, when a staff user edits it to `sort_order = 4`, then exactly one JSON-formatted log entry with `event = 'area.updated'` is emitted and its `data.changes` dict contains `sort_order: [0, 4]`. Given a staff user submits the edit form with the **same** `sort_order` value (no change), then NO `area.updated` log entry is emitted — the `if changes:` guard in `update_area` suppresses the event.

- [x] **AC 9 — Static page export reflects the new order:**
  Given areas with explicit `sort_order` values, when `static_page_service.generate()` is invoked, then the resulting HTML lists area sections in `(sort_order, name)` order.

- [x] **AC 10 — Empty-string and absent `sort_order` POST both resolve to default:**
  Given a staff user submits the create form with `sort_order=''` (the browser's representation of a cleared field), when the form is processed, then the area is created with `sort_order = 0` (via `Optional()` + `default=0`). The same holds for POSTs that omit the `sort_order` key entirely — the suite's pre-existing test POSTs to `/admin/areas/new` and `/admin/areas/<id>/edit` continue to pass with no payload changes.

- [x] **AC 11 — `area.created` audit log includes `sort_order`:**
  Given a staff user creates an area with `sort_order = 9`, when the `area.created` mutation event is emitted, then its `data` payload contains `sort_order: 9` alongside the existing `id`, `name`, and `slack_channel` fields.

- [x] **AC 12 — Slack `/esb-status` reflects the new ordering:**
  Given areas with explicit `sort_order` values and equipment in each, when `esb/slack/forms.py:format_status_summary` is invoked with the result of `get_area_status_dashboard()`, then the per-area lines in the returned summary text appear in `(sort_order, name)` order.

- [x] **AC 12b — Slack `/esb-repair` dispatcher modal area groups respect the new ordering:**
  Given multiple areas with mixed `sort_order` values and at least one open repair record per area, when `build_repair_dispatcher_modal(open_records)` is invoked, then the modal's `option_groups` array is ordered by `(sort_order, name)` rather than alphabetical-by-name. (The `'No Area'` sentinel bucket in the function body is unreachable in production because `equipment.area_id` is `NOT NULL` per `esb/models/equipment.py`; the defensive code remains for safety but is not part of any AC.)

- [x] **AC 13 — Equipment and repair-form dropdowns reflect the new ordering:**
  Given areas with explicit `sort_order` values, when a staff user loads `/equipment`, `/equipment/new`, `/equipment/<id>/edit`, or `/repairs/queue`, then the `<option>` elements in each area dropdown appear in `(sort_order, name)` order.

- [x] **AC 14 — `sort_order` is preserved through archive/unarchive cycles:**
  Given an area with `sort_order = 5`, when a staff user archives the area via POST `/admin/areas/<id>/archive`, then the `sort_order` column value in the DB is still 5. (Unarchiving is not currently exposed via a UI, but if the row is later set to `is_archived=False`, the original sort_order is intact.)

## Review Notes

- Adversarial review completed via subagent against `_bmad/core/tasks/review-adversarial-general.xml`.
- Findings: 17 total, 0 fixed, 17 skipped.
- Resolution approach: skip — every finding either restated a tech-spec design decision (e.g., `server_default='0'`, sentinel-default `sort_order` kwarg, form duplication, find()-byte-position test pattern) or pointed at explicitly-out-of-scope surfaces (archived-area reorder, equipment-within-area ordering, DB-level CheckConstraint).
- Manual MariaDB verification of AC 1 performed: created two pre-existing rows under the old schema, ran `flask db upgrade`, both rows backfilled to `sort_order=0`. Downgrade-then-upgrade cycle also verified.
- `make test` (1449 passing) and `make lint` (clean) both green at completion.

## Additional Context

### Dependencies

- No new Python packages required. `IntegerField` and `NumberRange` are already part of WTForms (already a transitive dependency via Flask-WTF).
- Docker DB container must be running locally to generate the Alembic migration (see CLAUDE.md "Database Migrations").
- Depends on the existing service-layer pattern; no upstream blockers.

### Testing Strategy

- **Unit tests (services):**
  - Ordering: explicit assertions on `list_areas()` and `get_area_status_dashboard()` ordering with mixed `sort_order` values (Tasks 11, 12).
  - Mutations: `create_area` and `update_area` persist `sort_order`; `update_area` emits `log_mutation` with `changes['sort_order'] = [old, new]` only when the value actually changes; no event on unchanged value (Task 13).
  - Defensive int coercion: `create_area(sort_order='7')` is accepted and `area.sort_order == 7` (covered by the new tests).
- **View tests (admin):**
  - POST flows for create/edit with `sort_order` set (`'7'`), empty (`''`), and omitted (Task 14).
  - Validation rejection of negative values, values above `max=999999`, and non-integer input (`'abc'`) — covers AC 6 (Task 14).
  - Admin areas list (`/admin/areas`) shows the `Sort Order` column header and renders areas in `(sort_order, name)` order — covers AC 7 (Task 14, `TestListAreas`).
  - Mutation logging round-trip including both no-op cases (`5→5` and `0→0`).
  - Form re-render shows current value via `obj=area` on edit (with regex anchored to the `name="sort_order"` attribute).
  - Archive preserves `sort_order` (`TestArchiveArea::test_archive_preserves_sort_order`).
  - Existing tests must remain green without payload changes (AC 10).
- **View tests (public dashboard / kiosk):** New ordering regression tests at the rendered-HTML layer for `/` (status dashboard) and `/kiosk` — covers AC 2/3/4 at the view layer (Task 14b).
- **View tests (dropdowns):** New regression tests for area dropdown order on `/equipment`, `/equipment/new`, `/equipment/<id>/edit`, and `/repairs/queue` (Task 15).
- **Slack tests:** New ordering test for `format_status_summary` (Task 16) in `tests/test_slack/test_forms.py`.
- **Static page tests:** New ordering integration test for `static_page_service.generate()` (Task 17) in `tests/test_services/test_static_page_service.py`.
- **Integration / manual verification:**
  - Start dev server (`make run`), log in as staff, create three areas with explicit sort orders (e.g., 10, 5, 5 with names B, A, C), confirm the public status dashboard (`/`), kiosk view, and `/admin/areas` all reflect `(5,A), (5,C), (10,B)` order.
  - Trigger a static page export and confirm the same ordering in the generated HTML.
  - Run `/esb-status` in Slack (if configured) and confirm the per-area lines respect the same ordering.
- **Migration verification:** Run `flask db upgrade` against a populated DB and confirm all pre-existing area rows have `sort_order = 0`; run `flask db downgrade` then `flask db upgrade` to confirm structural cycle (with the caveat that user-set values are lost on downgrade).

### Notes

- **Partial-POST behavior with `obj=area`.** The `edit_area` view constructs the form as `AreaEditForm(obj=area)`. WTForms preserves the obj's value if formdata does not contain the form key — meaning a POST that omits `sort_order` entirely keeps the current DB value (because `data == 0` from the absent-key/default path is then overlaid by the obj). However, real browser submissions of the rendered HTML always include the form key. The expected per-submission behavior is therefore:
  - User loads `/admin/areas/<id>/edit`: form renders with `value="<current sort_order>"`.
  - User clicks Save without changing the field: browser POSTs `sort_order=<current value>` → service sees the same int → no `area.updated` event (guarded by `if changes:`).
  - User clears the field and clicks Save: browser POSTs `sort_order=''` → `Optional()` skips `NumberRange` → `data is None` → view coerces to `0` → service updates `sort_order` to 0 (and emits `area.updated` if the prior value was non-zero).
  - User submits a non-integer like `abc`: validation fails (both `Not a valid integer value.` and `Number must be between 0 and 999999.` errors), form re-renders with all other field values preserved by WTForms.
- **Risk: forgotten migration apply.** If a developer runs the test suite (SQLite in-memory rebuilds the schema from models each time) but never applies the migration to MariaDB, the prod schema will lag the code. Mitigation: this is the standard repo workflow — the release workflow runs `flask db upgrade` on container startup.
- **Test DB does NOT exercise the migration.** The test fixture in `tests/conftest.py` calls `_db.create_all()` which builds tables from the SQLAlchemy model metadata, not from migrations. As a consequence, the migration's `server_default='0'` is never executed against SQLite during tests — the test DB relies on the ORM-level `default=0`. This means a working test suite does NOT prove the migration backfills correctly; AC 1 must be verified manually against MariaDB (per the Migration Verification step in Testing Strategy).
- **`server_default='0'` vs SQLite.** SQLite stores the DDL-level default as a string literal `'0'` for INTEGER columns, which works correctly with SQLAlchemy's `Integer` type. No special handling needed — but be aware that the DDL emitted for the test DB and prod DB differ slightly.
- **`op.batch_alter_table` is not strictly required for `add_column` on MariaDB** — it is primarily needed for SQLite ALTER limitations. The existing migration uses batch mode for its `create_index` step. We retain batch mode here for consistency with the project's pattern, but plain `op.add_column` would work too.
- **MariaDB vs SQLite collation differs on `name` secondary sort.** MariaDB's default `utf8mb4_general_ci` collation is case-insensitive, while SQLite's BINARY collation is case-sensitive (uppercase letters sort before lowercase). For mixed-case area names like `apple` and `Banana`, SQLite (tests) returns `Banana, apple` while MariaDB (prod) returns `apple, Banana`. Test fixtures use proper-case names exclusively, so this divergence won't surface in CI; flag if a real area is named in mixed case and the order looks "wrong" on the dashboard.
- **UX: cleared field re-renders blank.** If a user clears the sort_order field and submits, the value resets to 0 (per the Partial-POST behavior above), but the form re-render after a *failed* save (e.g., name conflict) will show the field as empty rather than `0`. The form-text "Leave at 0 for default" still applies but is slightly misleading after a clear-and-fail. Acceptable for an admin-only field; document if user feedback comes in.
- **Audit log contract change.** After this PR, every `area.created` event payload contains a `sort_order` key (always present, often `0`). Downstream log consumers — Loki dashboards, Splunk queries, custom log scrapers — should be updated if they enforce a strict schema. The repo currently does not have such consumers; this is informational.
- **Sort_order gaps from archives.** Archived areas keep their `sort_order` (Technical Decisions). If staff archives an area at sort_order=20 and reorders neighbors, the visible sequence may show numeric gaps (0, 5, 10, 50). This is a minor UX implication, not a bug; staff can renumber.
- **Risk: downgrade destroys user-set sort values.** `flask db downgrade` runs `batch_op.drop_column('sort_order')`, which is not a value-preserving reversal. If a downgrade is run in error and then re-upgraded, all rows reset to `0`. This is acceptable for emergency rollback only.
- **Release process** (per CLAUDE.md "Releases"): bump `pyproject.toml` `version` field as part of this work — see Task 18. The release workflow auto-tags and publishes the Docker image when the version on `main` exceeds the latest tag. No manual tagging or `CHANGELOG.md` maintenance is needed.
- **Known limitation:** No bulk-reorder UI. Staff will set values one at a time. Acceptable for the current handful of areas at Decatur Makers.
- **Future considerations (explicitly out of scope):**
  - Drag-and-drop reorder UI on `/admin/areas`.
  - Optional secondary sort for equipment within an area.
  - A composite `(sort_order, name)` index on the `areas` table if the table ever grows beyond a few dozen rows (today's filesort is fine at this scale).
