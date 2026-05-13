---
title: 'Duplicate Repair Association'
slug: 'duplicate-repair-association'
created: '2026-05-13'
status: 'ready-for-dev'
stepsCompleted: [1, 2, 3, 4]
tech_stack:
  - 'Python 3.14'
  - 'Flask + Flask-SQLAlchemy 3.x'
  - 'Alembic (via Flask-Migrate)'
  - 'Flask-WTF / WTForms'
  - 'Slack Bolt SDK (Socket Mode)'
  - 'Jinja2 + Bootstrap (server-rendered templates)'
  - 'MariaDB 12.x (prod), SQLite in-memory (tests)'
  - 'pytest + Flask test client'
files_to_modify:
  - 'esb/models/repair_record.py'
  - 'esb/services/repair_service.py'
  - 'esb/forms/repair_forms.py'
  - 'esb/views/repairs.py'
  - 'esb/templates/repairs/edit.html'
  - 'esb/templates/repairs/detail.html'
  - 'esb/slack/forms.py'
  - 'esb/slack/handlers.py'
  - 'migrations/versions/{new}_add_duplicated_repair_id.py'
  - 'tests/test_models/test_repair_record.py'
  - 'tests/test_services/test_repair_service.py'
  - 'tests/test_views/test_repair_views.py'
  - 'tests/test_slack/test_handlers.py'
  - 'tests/test_slack/test_forms.py'
code_patterns:
  - 'service-layer mutations with ValidationError + log_mutation after commit'
  - '_REPAIR_UPDATABLE_FIELDS allowlist + **changes kwargs in update_repair_record'
  - 'Flask-WTF SelectField with choices populated in view (coerce=int, 0-sentinel for None)'
  - 'Slack Block Kit static_select; all action-modal fields visible, server resolves which apply'
  - 'Audit log changes dict with [old, new] pairs; per-field timeline entries'
  - 'Alembic batch_alter_table for adding columns/FKs/indexes'
test_patterns:
  - 'pytest classes grouping by behavior; fixtures `make_equipment`, `make_repair_record`, `staff_client`, `tech_client`, `capture`'
  - 'service-layer tests assert DB state via `_db.session.get(RepairRecord, id)` after expire_all()'
  - 'Slack handler tests use _register_and_capture helper, MagicMock client, build view dicts inline'
  - 'View tests post form data with follow_redirects=False and assert 302 Location'
issue: 43
---

# Tech-Spec: Duplicate Repair Association

**Created:** 2026-05-13

**GitHub Issue:** [#43 Duplicate Repair Association](https://github.com/jantman/equipment-status-board/issues/43)

## Overview

### Problem Statement

When a repair record is closed with status `Closed - Duplicate` (via Web UI or Slack), the system only records the status string. There is no captured reference to which other repair record on the same equipment is being duplicated. This makes it impossible to query correlations (e.g. "show me all the repairs that were duplicates of repair #123") and forces staff to scan repair descriptions or timelines to figure out which prior report a duplicate refers to.

### Solution

Add a nullable `duplicated_repair_id` foreign key on `repair_records` pointing back to `repair_records.id`. Whenever a user transitions a repair to `Closed - Duplicate` — in the Web UI edit form or the Slack action modal — they are required to pick which repair on the **same equipment** the current repair duplicates. Selection uses a dropdown / `static_select` populated with the equipment's other repair records, sorted newest-first, each option labeled `#{id} [{status}] {description excerpt}`. The service layer enforces the invariant that **a status transition to `Closed - Duplicate` requires `duplicated_repair_id` to be set**, and the chosen target must belong to the same equipment and not be the record itself. The repair detail view renders the link; audit-log entries record the `duplicated_repair_id` change.

### Scope

**In Scope:**

- New nullable `duplicated_repair_id` column on `repair_records` (FK → `repair_records.id`, `ON DELETE SET NULL`, indexed).
- Alembic migration adding the column + FK + index, via `op.batch_alter_table` (MariaDB-compatible pattern used throughout this repo).
- `RepairRecord` model: add the column and a self-referential `duplicated_repair` relationship (`remote_side=[id]`).
- `repair_service.update_repair_record()`:
  - Add `'duplicated_repair_id'` to `_REPAIR_UPDATABLE_FIELDS` so it flows through the existing change-detection / timeline / audit pipeline.
  - Add validation (see **Technical Decisions §3** for the precise rule).
  - Emit a timeline entry for the change (entry_type `duplicated_repair_id_change`, old/new IDs as strings).
- `repair_service.list_duplicate_candidates(repair_record_id)` — new helper returning the equipment's other repair records (excluding the record itself), ordered `created_at DESC`.
- Web UI:
  - `RepairRecordUpdateForm` adds `duplicated_repair_id = SelectField(..., coerce=int, validators=[Optional()])`. `0` is the sentinel for "none".
  - `views/repairs.py::edit()` populates `form.duplicated_repair_id.choices` from `list_duplicate_candidates(id)` on both GET and POST, passes the chosen value (or `None` if `0`) into `update_repair_record()`.
  - `templates/repairs/edit.html`: render the new dropdown in a wrapper `<div id="duplicate-block">` that is shown iff `form.status.data == 'Closed - Duplicate'` on initial render. Add a small inline `<script>` toggling visibility when the status `<select>` changes.
  - `templates/repairs/detail.html`: render a "Marked as duplicate of #N" row in the Repair Information `<dl>` when `record.duplicated_repair_id` is set, with a link to that repair's detail page.
- Slack:
  - `build_repair_action_modal(repair_record)` adds an optional `static_select` block (`block_id='duplicate_block'`, `action_id='duplicated_repair_id'`) populated by querying `repair_service.list_duplicate_candidates(repair_record.id)`. Block label: `"Duplicate of (used when 'Set Status → Closed - Duplicate' chosen)"`. Each option text: `f'#{r.id} [{r.status}] {r.description[:60]}'` truncated to 75 chars.
  - **If the equipment has zero other repairs, remove `Closed - Duplicate` from the status dropdown options entirely** and omit the duplicate block. The user cannot mark a one-and-only repair as a duplicate.
  - `handle_repair_action_submission()`: when `action == 'set_status'` and `status_opt['value'] == 'Closed - Duplicate'`, read `duplicated_repair_id` from the same view state and pass both into `update_repair_record()`. If missing → return Slack inline error on `duplicate_block`. ValidationError from the service is surfaced on `status_block`.
- `build_repair_create_modal`: filter `Closed - Duplicate` out of the status dropdown options (a repair cannot be created already-duplicate; the create flow does not have access to a target repair).
- Audit logging: the existing `update_repair_record` audit-changes mechanism already produces an entry like `'duplicated_repair_id': [old_str, new_str]` — no extra code beyond adding the field to `_REPAIR_UPDATABLE_FIELDS`.
- Tests covering: model column + relationship, service validation (positive + each negative case), web view form rendering + submission, Slack action modal flow including zero-candidates edge case, and Slack create modal filter.

**Out of Scope:**

- Backfilling existing rows that already have `Closed - Duplicate` status — they keep `duplicated_repair_id = NULL`. Editing such legacy rows for non-status fields must remain possible (see Technical Decisions §3.c).
- A reverse-direction view ("repairs that were duplicates of *this* repair") — possible later via SQLAlchemy `backref`, but not built in this story.
- Auto-suggesting likely duplicates based on description similarity.
- Cross-equipment duplicates.
- Changing the duplicate target by editing the repair *after* the close — technically allowed by the service rules (since `duplicated_repair_id` is just a field), but no UI affordance is provided. Out of scope as a feature; the field is editable via direct DB or future admin tooling.
- A `CHECK` constraint coupling `status` and `duplicated_repair_id` at the DB layer. Enforced in service layer only (consistency with existing patterns).
- Cycle detection in duplicate chains.

## Context for Development

### Codebase Patterns

- **Service-layer business logic:** All validation and writes go through `esb/services/repair_service.py`. Views and Slack handlers never query or commit directly. Invariants raise `ValidationError` (from `esb.utils.exceptions`) — the exception type used throughout `repair_service.py` (see `update_repair_record` status validation at line 500-501). **Not** bare `ValueError`.
- **`update_repair_record` kwargs pattern:** signature is `(repair_record_id, updated_by, author_id=None, **changes)`. It validates inbound values, pops `note` (it's not a model field), then enforces an allowlist via `_REPAIR_UPDATABLE_FIELDS = ('status', 'severity', 'assignee_id', 'eta', 'specialist_description')` (line 22): any unknown keys raise `ValidationError(f'Unknown fields: ...')` (line 513-515). Adding a new updatable field requires extending this tuple. Change-detection compares `getattr(record, field) != changes[field]` and emits a per-field timeline entry inside the same transaction.
- **`create_repair_record` does NOT accept a `status` argument** (hardcodes `status='New'` at line 110). The Slack create-modal handler emulates "create with status" by calling `create_repair_record` then `update_repair_record(status=...)` (`handlers.py:244-253` with the comment "Setting non-"New" status requires a second service call"). So defense for the duplicated_repair_id invariant lives entirely in `update_repair_record`.
- **Audit logging:** `log_mutation('repair_record.updated', updated_by, {'id': ..., 'changes': audit_changes})` is called after `db.session.commit()`. `audit_changes` is a dict of `{field: [old_serialized, new_serialized]}`. Adding `'duplicated_repair_id'` to `_REPAIR_UPDATABLE_FIELDS` automatically routes it through this flow; no extra `log_mutation` calls are needed.
- **Timeline entry creation in `update_repair_record`:** the loop at line 519-560 handles `status`, `assignee_id`, and `eta` specially (with custom entry_types). For other allowlisted fields it currently emits NO timeline entry (specialist_description doesn't either). We need to add a `duplicated_repair_id_change` entry type so the change is visible in the timeline — see Tasks.
- **Form pattern:** Flask-WTF forms in `esb/forms/repair_forms.py`; `SelectField` with `coerce=int` uses `0` as the "unselected" sentinel (see `assignee_id`-from-`RepairRecordUpdateForm`, paired with `assignee_id if form.assignee_id.data != 0 else None` in views/repairs.py:324).
- **Slack modal pattern:** `esb/slack/forms.py` defines `build_*_modal()` Block Kit dict builders; `esb/slack/handlers.py` `handle_*_submission()` parses `view['state']['values']`. The action modal already follows the pattern of "show all possibly-needed inputs, server resolves which apply based on the radio choice" (see ETA / status / note blocks). The new duplicate block extends this pattern; no new modal-push is needed.
- **Slack app-context wrapper:** All handlers wrap their body with `with _ensure_app_context(app):` (defined at `handlers.py:11-27`). The new validation flow runs through `update_repair_record`, which is already wrapped by the caller.
- **Migrations:** `migrations/versions/{revisionid}_{slug}.py` using `op.batch_alter_table`. The `revisionid` is generated by Alembic via the `flask db migrate` workflow documented in CLAUDE.md — must be generated against the live MariaDB container (port 3306 not host-mapped).
- **Testing:** SQLite in-memory in `TestingConfig`; CSRF disabled. Fixtures: `make_equipment`, `make_repair_record`, `staff_client`, `tech_client`, `capture` (mutation log capture). Test class pattern: one class per behavior, e.g. `TestCreateRepairRecord`, `TestRepairActionSubmission`. View tests post form data with `follow_redirects=False` and assert `302` Location header. Service tests assert DB state via `_db.session.get(...)` after `expire_all()`.

### Files to Reference

| File | Purpose |
| ---- | ------- |
| `esb/models/repair_record.py` (lines 23-59) | Add `duplicated_repair_id` column + `duplicated_repair` self-relationship. `REPAIR_STATUSES` constant (lines 7-18) already contains `'Closed - Duplicate'` — no enum change. |
| `esb/services/repair_service.py` (line 22) | Add `'duplicated_repair_id'` to `_REPAIR_UPDATABLE_FIELDS`. |
| `esb/services/repair_service.py` (lines 470-637) | Modify `update_repair_record`: add validation block (see Technical Decisions §3), add timeline entry for the field, the rest of the existing flow handles audit/log. |
| `esb/services/repair_service.py` (after line 217) | New `list_duplicate_candidates(repair_record_id)` helper near `list_repair_records`. |
| `esb/services/repair_service.py` (line 220 `CLOSED_STATUSES`) | Reference: already includes `'Closed - Duplicate'`. |
| `esb/forms/repair_forms.py` (line 29-45 `RepairRecordUpdateForm`) | Add `duplicated_repair_id = SelectField(..., coerce=int, validators=[Optional()])`. |
| `esb/views/repairs.py` (line 288-336 `edit()`) | Populate `form.duplicated_repair_id.choices` on both GET and POST; map `0` sentinel to `None`; pass through to service. |
| `esb/views/repairs.py` (line 190-216 `detail()`) | No change needed — `record.duplicated_repair` will load lazily in the template. (Optionally eager-load for clarity.) |
| `esb/templates/repairs/edit.html` (lines 17-26 status block) | Insert wrapper `<div id="duplicate-block">` after the status block; add inline JS toggling `display` when status `<select>` changes. |
| `esb/templates/repairs/detail.html` (Repair Information `<dl>`, lines 50-80) | Add a conditional `<dt>/<dd>` pair for "Marked as duplicate of #N" with a link via `url_for('repairs.detail', id=record.duplicated_repair_id)`. |
| `esb/slack/forms.py` (lines 626-728 `build_repair_action_modal`) | Add duplicate-of block; filter `Closed - Duplicate` from status options when the equipment has no other repairs. |
| `esb/slack/forms.py` (lines 318-422 `build_repair_create_modal`) | Filter `Closed - Duplicate` from status options (always). |
| `esb/slack/handlers.py` (lines 517-677 `handle_repair_action_submission`) | In the `set_status` branch, when status is `Closed - Duplicate`, read `duplicate_block.duplicated_repair_id.selected_option`, validate-non-empty, include in `update_repair_record` call. ValidationError already surfaces as inline `action_block` error; consider surfacing on `duplicate_block` instead for clarity. |
| `migrations/versions/7bd5caedf749_add_repair_records_repair_timeline_.py` | Reference: most recent migration; pattern for `op.batch_alter_table` + indexes + foreign keys. |
| `tests/conftest.py` (lines 133-152) | Reference: `make_repair_record` factory accepts `equipment=`, `status=`, `description=`, `**kwargs` — we'll pass `duplicated_repair_id=` once the column exists. |
| `tests/test_services/test_repair_service.py` (classes around line 185+) | Reference: `TestStaticPagePush`, `TestSlackNotificationHooks` style; add a new `TestDuplicatedRepairId` class. |
| `tests/test_slack/test_handlers.py` (lines 1086+ `TestRepairActionSubmission`) | Reference: extend with duplicate-flow scenarios; uses `_build_view`, `_register_and_capture`, `MagicMock` client. |
| `tests/test_views/test_repair_views.py` (lines 183+ edit tests) | Reference: extend `TestRepairEdit` class with duplicate-of cases. |

### Technical Decisions

1. **`duplicated_repair_id` is nullable, with `ON DELETE SET NULL`.** A repair may not be a duplicate (the common case), and we don't want deletion of the target repair to cascade-delete the duplicate. `SET NULL` semantics preserve the historical "this was marked as a duplicate" status even if the original target is later deleted; staff can investigate via audit log.

2. **No status-enum change.** `Closed - Duplicate` is already in `REPAIR_STATUSES` (model line 17). We're adding a paired-field constraint, not a new status value.

3. **Validation lives in the service layer, conditionally.** Three rules in `update_repair_record`:

   **a. Status transition to `Closed - Duplicate` requires a target.**
   If `'status' in changes and changes['status'] == 'Closed - Duplicate'`:
   - `effective_dup_id = changes.get('duplicated_repair_id', record.duplicated_repair_id)`
   - `effective_dup_id` must not be `None` → else `ValidationError("'Closed - Duplicate' requires a duplicated_repair_id")`.
   - `effective_dup_id != repair_record_id` → else `ValidationError("A repair cannot be a duplicate of itself")`.
   - target = `db.session.get(RepairRecord, effective_dup_id)` must exist → else `ValidationError(f"Duplicated repair {effective_dup_id} not found")`.
   - `target.equipment_id == record.equipment_id` → else `ValidationError("Duplicated repair must be on the same equipment")`.

   **b. Explicitly setting `duplicated_repair_id` to non-None requires status to be `Closed - Duplicate`.**
   If `'duplicated_repair_id' in changes and changes['duplicated_repair_id'] is not None`:
   - `effective_status = changes.get('status', record.status)` must equal `'Closed - Duplicate'` → else `ValidationError("duplicated_repair_id may only be set when status is 'Closed - Duplicate'")`.
   - Plus same-equipment / non-self / target-exists checks as in (a).

   **c. Status moving *away* from `Closed - Duplicate` auto-clears `duplicated_repair_id`.**
   If `'status' in changes and changes['status'] != 'Closed - Duplicate'` and `record.duplicated_repair_id is not None` and `'duplicated_repair_id' not in changes`: implicitly inject `changes['duplicated_repair_id'] = None`. This is the only "silent" mutation — it audit-logs as `{'duplicated_repair_id': [old, None]}` via the normal flow.

   **Legacy-record carve-out:** Note that rule (a) only fires when `'status' in changes` — i.e., a status *transition* to `Closed - Duplicate`. A row that already has `status='Closed - Duplicate'` and `duplicated_repair_id=NULL` (legacy data) can still be edited for unrelated fields (e.g., a note, a specialist_description) without tripping validation. This is intentional.

4. **The duplicate target's status is unrestricted.** A repair can be marked as a duplicate of any other repair on the same equipment, including another `Closed - Duplicate` one or an already-resolved one. Avoids forcing users to find the "root" duplicate; staff can follow the chain if needed. **No cycle detection** — chains are operationally harmless and detection adds complexity.

5. **Slack: single-modal approach, no nested modal push.** The action modal already follows the pattern of "show all possibly-needed inputs (ETA, status, note), server resolves which apply based on the radio choice." Adding the duplicate `static_select` as another always-visible-but-optional block extends this pattern. The alternative — pushing a third modal after the user picks `Closed - Duplicate` — would require Slack's `ack(response_action='push', view=...)` from within an already-pushed modal (3-level deep stack). Single-modal is simpler, has fewer race conditions, and matches the existing UX.

6. **Slack: zero-candidates edge case.** When `list_duplicate_candidates(record.id)` returns an empty list (the equipment has only this one repair, ever), `build_repair_action_modal` **removes `'Closed - Duplicate'` from the status dropdown options** and **omits the duplicate block entirely**. The user cannot pick an unsatisfiable status. (This is preferred over showing the option and letting the server reject — better UX, less confusing.)

7. **Web UI: conditional JS show/hide on status select.** Inline `<script>` watches the status `<select>` `change` event; toggles `style.display` on the duplicate-block wrapper. Default visibility on GET matches `record.status == 'Closed - Duplicate'`. The duplicate dropdown is always rendered server-side with full candidate list (no AJAX), regardless of the current status — display is a CSS concern only. **No-JS fallback:** without JS the block is always visible (`display:block` default) — degraded but functional; users can still submit. This matches the simplicity of the existing form; the repo has no client-side framework.

8. **Description excerpt cap of 60 chars in dropdown labels.** Slack `static_select` option `text.text` has a 75-char limit. Format `#{id} [{status}] {desc[:60]}` worst-case: `#999999 [Closed - No Issue Found] ` ≈ 35 chars + 60 chars = ~95 chars. We further truncate the whole label with `[:75]` (consistent with `build_equipment_options` lines 184). Web select option text is rendered HTML — same 60-char excerpt for visual consistency.

9. **Self-referential FK with `remote_side`:** the model relationship uses `db.relationship('RepairRecord', remote_side=[id])` to disambiguate "the one I duplicate" from the implicit reverse "the ones that duplicate me." We do not add a `backref` for the reverse direction (deferred — out of scope per issue scope).

10. **`Closed - Duplicate` removed from `build_repair_create_modal` status options.** A repair cannot meaningfully be *created* already-duplicate via Slack: the create flow has no UI for the dup-target dropdown, and the follow-up `update_repair_record` would fail validation. Filter at the option-list construction site rather than surfacing a confusing error.

11. **Web UI create form is not affected.** `RepairRecordCreateForm` doesn't expose `status` (status is hardcoded to `'New'` by `create_repair_record`), so no filter is needed on the web create path.

12. **Timeline entry for duplicated_repair_id changes.** Add a new `entry_type='duplicated_repair_id_change'` with `old_value`/`new_value` as stringified IDs (or `None` for absent). Renders in the existing timeline component (`components/_timeline_entry.html`) — verify it handles unknown entry_types gracefully or extend that template if needed (small follow-up task).

## Implementation Plan

### Tasks

Tasks are ordered by dependency: schema → service → web → Slack → verification. Each phase's tests live alongside the source change so the test suite stays green between phases.

#### Phase 1: Data Layer

- [ ] **Task 1: Add `duplicated_repair_id` column + self-relationship to `RepairRecord` model.**
  - File: `esb/models/repair_record.py`
  - Action: After `specialist_description` (line 41) add `duplicated_repair_id = db.Column(db.Integer, db.ForeignKey('repair_records.id', ondelete='SET NULL'), nullable=True, index=True)`. After the existing `assignee` relationship (line 56) add `duplicated_repair = db.relationship('RepairRecord', remote_side=[id])`.
  - Notes: No `backref` (out of scope). `remote_side=[id]` is the SQLAlchemy idiom for self-referential many-to-one.

- [ ] **Task 2: Create Alembic migration for the new column.**
  - File: `migrations/versions/{auto}_add_duplicated_repair_id.py` (new file)
  - Action: Per CLAUDE.md migration workflow: `docker compose up -d db`, `docker inspect equipment-status-board-db-1 --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}'`, then `DATABASE_URL="mysql+pymysql://root:esb_dev_password@<IP>/esb" venv/bin/flask db migrate -m "Add duplicated_repair_id to repair_records"`. Inspect the generated file and ensure: `op.batch_alter_table('repair_records')` adds the column, the FK constraint includes `ondelete='SET NULL'`, and the index `ix_repair_records_duplicated_repair_id` is created. Add the index manually if Alembic missed it. Verify `downgrade()` drops index → constraint → column in reverse order. Apply with `flask db upgrade`.
  - Notes: Alembic sometimes drops `ondelete='SET NULL'` from autogen — verify and patch.

- [ ] **Task 3: Model-layer tests.**
  - File: `tests/test_models/test_repair_record.py`
  - Action: Add tests asserting (a) the new column is nullable on a fresh record, (b) setting `duplicated_repair_id` and accessing `.duplicated_repair` loads the target, (c) deleting the target via `db.session.delete(target); commit()` nulls the child's FK on refresh.
  - Notes: SQLite enforces FK ON DELETE SET NULL only when `PRAGMA foreign_keys=ON` — confirm the testing config enables this, or accept that the FK-cascade test is skipped under SQLite and add an integration smoke note instead.

#### Phase 2: Service Layer

- [ ] **Task 4: Add `list_duplicate_candidates` helper.**
  - File: `esb/services/repair_service.py`
  - Action: After `list_repair_records` (line 217), add:
    ```python
    def list_duplicate_candidates(repair_record_id: int) -> list[RepairRecord]:
        """Return same-equipment repair records (excluding self), newest first."""
        record = get_repair_record(repair_record_id)
        query = (
            db.select(RepairRecord)
            .filter(RepairRecord.equipment_id == record.equipment_id)
            .filter(RepairRecord.id != record.id)
            .order_by(RepairRecord.created_at.desc())
        )
        return list(db.session.execute(query).scalars().all())
    ```
  - Notes: `get_repair_record` raises `ValidationError` if the id is missing — propagates naturally.

- [ ] **Task 5: Extend `_REPAIR_UPDATABLE_FIELDS` and add validation + timeline entry to `update_repair_record`.**
  - File: `esb/services/repair_service.py`
  - Action:
    1. Line 22: append `'duplicated_repair_id'` to `_REPAIR_UPDATABLE_FIELDS`.
    2. In `update_repair_record` (line 470+), after the existing input validations (after line 507, before `note = changes.pop(...)`), insert the validation block per Technical Decisions §3:
       ```python
       effective_status = changes.get('status', record.status)
       effective_dup_id = changes.get('duplicated_repair_id', record.duplicated_repair_id)

       transitioning_to_closed_dup = 'status' in changes and changes['status'] == 'Closed - Duplicate'
       setting_dup_explicit = 'duplicated_repair_id' in changes and changes['duplicated_repair_id'] is not None
       transitioning_away_from_closed_dup = (
           'status' in changes and changes['status'] != 'Closed - Duplicate'
       )

       if transitioning_to_closed_dup:
           if effective_dup_id is None:
               raise ValidationError(
                   "'Closed - Duplicate' status requires a duplicated_repair_id",
               )
       if setting_dup_explicit:
           if effective_status != 'Closed - Duplicate':
               raise ValidationError(
                   "duplicated_repair_id may only be set when status is 'Closed - Duplicate'",
               )
       if transitioning_to_closed_dup or setting_dup_explicit:
           target_id = effective_dup_id
           if target_id == repair_record_id:
               raise ValidationError('A repair cannot be a duplicate of itself')
           target = db.session.get(RepairRecord, target_id)
           if target is None:
               raise ValidationError(f'Duplicated repair {target_id} not found')
           if target.equipment_id != record.equipment_id:
               raise ValidationError(
                   'Duplicated repair must be on the same equipment',
               )

       # Silent clear when status moves away from Closed - Duplicate
       if (
           transitioning_away_from_closed_dup
           and record.duplicated_repair_id is not None
           and 'duplicated_repair_id' not in changes
       ):
           changes['duplicated_repair_id'] = None
       ```
    3. In the per-field timeline-entry loop (line 519+), add an `elif field_name == 'duplicated_repair_id':` branch emitting `RepairTimelineEntry(repair_record_id=record.id, entry_type='duplicated_repair_id_change', author_id=author_id, author_name=updated_by, old_value=str(old_value) if old_value is not None else None, new_value=str(new_value) if new_value is not None else None)`.
  - Notes: `audit_changes['duplicated_repair_id']` and `log_mutation` flow through automatically because the field is now in `_REPAIR_UPDATABLE_FIELDS`. Place validation BEFORE the unknown-keys check at line 513.

- [ ] **Task 6: Service-layer tests.**
  - File: `tests/test_services/test_repair_service.py`
  - Action: Add two new test classes:
    1. `TestListDuplicateCandidates` — covers ordering newest-first, self-exclusion, equipment filtering, missing-record `ValidationError`, empty result for single-repair equipment.
    2. `TestDuplicatedRepairId` — covers the eight ACs in the Service Layer section below (AC-4 through AC-11).
  - Notes: Use `make_equipment` and `make_repair_record` factories; assert via `_db.session.get(RepairRecord, id)` after `_db.session.expire_all()`.

#### Phase 3: Web UI

- [ ] **Task 7: Add `duplicated_repair_id` field to `RepairRecordUpdateForm`.**
  - File: `esb/forms/repair_forms.py`
  - Action: After `specialist_description` (line 43) on `RepairRecordUpdateForm` add:
    ```python
    duplicated_repair_id = SelectField(
        'Duplicate of', coerce=int, validators=[Optional()],
    )
    ```
  - Notes: `0` is the unselected sentinel (consistent with `assignee_id`).

- [ ] **Task 8: Populate dropdown choices and pass through in `repairs.edit` view.**
  - File: `esb/views/repairs.py`
  - Action: In `edit()` (line 288+):
    1. After the assignee choices (around line 306), add:
       ```python
       candidates = repair_service.list_duplicate_candidates(id)
       form.duplicated_repair_id.choices = [(0, '-- Select duplicate of --')] + [
           (c.id, f'#{c.id} [{c.status}] {c.description[:60]}') for c in candidates
       ]
       ```
    2. On GET (~line 308-314) add `form.duplicated_repair_id.data = record.duplicated_repair_id or 0`.
    3. In the validated POST branch (line 316+), add to the `update_repair_record(...)` call:
       ```python
       duplicated_repair_id=(
           form.duplicated_repair_id.data if form.duplicated_repair_id.data != 0 else None
       ),
       ```
  - Notes: Service raises `ValidationError` on invalid combos → existing `flash + re-render` flow handles it.

- [ ] **Task 9: Conditional duplicate-block in `repairs/edit.html`.**
  - File: `esb/templates/repairs/edit.html`
  - Action: After the status block (after line 26), insert:
    ```html
    <div id="duplicate-block" class="mb-3"{% if form.status.data != 'Closed - Duplicate' %} style="display: none;"{% endif %}>
        <label for="duplicated_repair_id" class="form-label">Duplicate of *</label>
        {{ form.duplicated_repair_id(class="form-select" ~ (" is-invalid" if form.duplicated_repair_id.errors else "")) }}
        <div class="form-text">Required when status is "Closed - Duplicate".</div>
        {% for error in form.duplicated_repair_id.errors %}
        <div class="invalid-feedback">{{ error }}</div>
        {% endfor %}
    </div>
    ```
    Inside `{% block content %}`, after the closing `</form>` and before `{% endblock %}`, append:
    ```html
    <script>
    (function () {
        const statusSelect = document.querySelector('select[name="status"]');
        const dupBlock = document.getElementById('duplicate-block');
        if (!statusSelect || !dupBlock) return;
        const sync = () => { dupBlock.style.display = statusSelect.value === 'Closed - Duplicate' ? '' : 'none'; };
        statusSelect.addEventListener('change', sync);
    })();
    </script>
    ```
  - Notes: No-JS fallback is `display:block` (visible). Inline script is consistent with the repo's no-framework template style.

- [ ] **Task 10: Render "Marked as duplicate of" link on the detail page.**
  - File: `esb/templates/repairs/detail.html`
  - Action: In the Repair Information `<dl>` (lines 50-80), between the Status and Severity rows, add:
    ```html
    {% if record.duplicated_repair_id %}
    <dt class="col-sm-3">Marked as duplicate of</dt>
    <dd class="col-sm-9"><a href="{{ url_for('repairs.detail', id=record.duplicated_repair_id) }}">Repair #{{ record.duplicated_repair_id }}</a></dd>
    {% endif %}
    ```

- [ ] **Task 11: Add `duplicated_repair_id_change` rendering to the timeline component.**
  - File: `esb/templates/components/_timeline_entry.html`
  - Action: Add a new `{% elif entry.entry_type == 'duplicated_repair_id_change' %}` branch after the `eta_update` branch:
    ```html
    {% elif entry.entry_type == 'duplicated_repair_id_change' %}
    <span class="badge bg-secondary me-1">Duplicate</span>
    <strong>
        {% if entry.new_value %}
        Marked as duplicate of <a href="{{ url_for('repairs.detail', id=entry.new_value|int) }}">#{{ entry.new_value }}</a>
        {% else %}
        Unlinked from duplicate{% if entry.old_value %} #{{ entry.old_value }}{% endif %}
        {% endif %}
    </strong>
    ```

- [ ] **Task 12: Web view tests.**
  - File: `tests/test_views/test_repair_views.py`
  - Action: Extend `TestRepairEdit` (line 183+) with tests covering AC-14 through AC-19 (form rendering, valid submit, missing-dup-id error, status-away clearing, detail-page link).

#### Phase 4: Slack

- [ ] **Task 13: Filter `Closed - Duplicate` out of `build_repair_create_modal` status options.**
  - File: `esb/slack/forms.py`
  - Action: In `build_repair_create_modal` (line 318+, status block at ~line 396-413), change the options comprehension to `[ ... for s in REPAIR_STATUSES if s != 'Closed - Duplicate']`.

- [ ] **Task 14: Add duplicate-of block to `build_repair_action_modal`; handle zero-candidates.**
  - File: `esb/slack/forms.py`
  - Action: In `build_repair_action_modal(repair_record)` (line 626+):
    1. At the top of the function, call `from esb.services import repair_service` then `candidates = repair_service.list_duplicate_candidates(repair_record.id)`.
    2. Compute `status_options` for the status dropdown: start from the current hardcoded list (`In Progress`, `Closed - Duplicate`, `Closed - No Issue Found`); if `not candidates`, drop `Closed - Duplicate`.
    3. Use `status_options` to populate the status block (replacing the hardcoded options list at lines 698-702).
    4. After the note block, if `candidates`:
       ```python
       dup_options = [
           {
               'text': {'type': 'plain_text', 'text': f'#{r.id} [{r.status}] {r.description[:60]}'[:75]},
               'value': str(r.id),
           }
           for r in candidates
       ]
       blocks.append({
           'type': 'input',
           'block_id': 'duplicate_block',
           'optional': True,
           'element': {
               'type': 'static_select',
               'action_id': 'duplicated_repair_id',
               'placeholder': {'type': 'plain_text', 'text': 'Select duplicated repair'},
               'options': dup_options,
           },
           'label': {'type': 'plain_text', 'text': "Duplicate of (used when 'Set Status → Closed - Duplicate' chosen)"},
       })
       ```
  - Notes: `optional: True` so the modal can be submitted with action != set_status. Server-side validation enforces presence when needed.

- [ ] **Task 15: Handle duplicate selection in `handle_repair_action_submission`.**
  - File: `esb/slack/handlers.py`
  - Action: In the `elif action == 'set_status':` branch (~line 598-605), after `changes['status'] = status_opt['value']`, add:
    ```python
    if changes['status'] == 'Closed - Duplicate':
        dup_opt = (
            values.get('duplicate_block', {})
            .get('duplicated_repair_id', {})
            .get('selected_option')
        )
        if not dup_opt:
            ack(response_action='errors', errors={
                'duplicate_block': 'Selecting which repair this duplicates is required.',
            })
            return
        try:
            changes['duplicated_repair_id'] = int(dup_opt['value'])
        except (KeyError, TypeError, ValueError):
            ack(response_action='errors', errors={
                'duplicate_block': 'Invalid duplicate selection.',
            })
            return
    ```
  - Notes: Service-layer ValidationError (e.g., cross-equipment from a stale modal) still surfaces on `action_block` via the existing exception handler.

- [ ] **Task 16: Slack tests.**
  - Files: `tests/test_slack/test_handlers.py`, `tests/test_slack/test_forms.py`
  - Action:
    - `test_forms.py`: tests for AC-20 (action modal with candidates includes duplicate_block), AC-21 (zero candidates omits block + filters status option), AC-22 (create modal filters status option).
    - `test_handlers.py`: extend `TestRepairActionSubmission` with AC-23 (successful Closed-Dup submission), AC-24 (missing duplicate selection returns inline error).

#### Phase 5: Verify

- [ ] **Task 17: Run lint and full test suite.**
  - Action: `make lint && make test`. Address any ruff complaints (120-char lines, target Python 3.13). All existing tests must still pass.

### Acceptance Criteria

**Schema**

- **AC-1** Given a freshly migrated database, when introspecting `repair_records`, then a `duplicated_repair_id` column exists (nullable Integer) with a FK to `repair_records.id` (ON DELETE SET NULL) and an index `ix_repair_records_duplicated_repair_id`.

- **AC-2** Given a RepairRecord A with `duplicated_repair_id = B.id`, when B is deleted from the database, then A.duplicated_repair_id is NULL (and A is preserved).

- **AC-3** Given a RepairRecord A with `duplicated_repair_id = B.id`, when accessing `A.duplicated_repair`, then it returns the RepairRecord B instance.

**Service layer — happy path & errors**

- **AC-4** Given an open repair R1 and another open repair R2 on the same equipment, when `update_repair_record(R1.id, updated_by='u', author_id=u.id, status='Closed - Duplicate', duplicated_repair_id=R2.id)` is called, then R1.status becomes `'Closed - Duplicate'`, R1.duplicated_repair_id becomes R2.id, a timeline entry of type `duplicated_repair_id_change` is created with `new_value == str(R2.id)`, and `repair_record.updated` is emitted in the mutation log with `changes['duplicated_repair_id'] == [None, str(R2.id)]`.

- **AC-5** Given an open repair R1, when `update_repair_record(R1.id, status='Closed - Duplicate', ...)` is called WITHOUT `duplicated_repair_id`, then `ValidationError` is raised with a message containing `'Closed - Duplicate'` and `duplicated_repair_id`, and R1 is unchanged.

- **AC-6** Given an open repair R1, when `update_repair_record(R1.id, status='Closed - Duplicate', duplicated_repair_id=R1.id, ...)` is called, then `ValidationError` is raised with "cannot be a duplicate of itself".

- **AC-7** Given repair R1 on equipment E1 and repair R2 on equipment E2, when `update_repair_record(R1.id, status='Closed - Duplicate', duplicated_repair_id=R2.id, ...)` is called, then `ValidationError` is raised with "must be on the same equipment".

- **AC-8** Given an open repair R1 and a non-existent id 99999, when `update_repair_record(R1.id, status='Closed - Duplicate', duplicated_repair_id=99999, ...)` is called, then `ValidationError` is raised with "Duplicated repair 99999 not found".

- **AC-9** Given a repair R1 with `status='Resolved'`, when `update_repair_record(R1.id, duplicated_repair_id=R2.id, ...)` is called without changing status, then `ValidationError` is raised with "may only be set when status is 'Closed - Duplicate'".

- **AC-10** Given a repair R1 with `status='Closed - Duplicate'` and `duplicated_repair_id=R2.id`, when `update_repair_record(R1.id, status='In Progress', ...)` is called, then R1.duplicated_repair_id becomes NULL, `audit_changes['duplicated_repair_id'] == [str(R2.id), None]`, and a `duplicated_repair_id_change` timeline entry is created with `new_value is None`.

- **AC-11** (Legacy carve-out) Given a repair R1 with `status='Closed - Duplicate'` and `duplicated_repair_id=None` (legacy data), when `update_repair_record(R1.id, specialist_description='x', ...)` is called, then the call succeeds without raising `ValidationError` and R1.specialist_description equals `'x'`.

**Service layer — helper**

- **AC-12** Given a repair R1 on equipment E and three other repairs R2 (newest), R3, R4 (oldest) on E plus R5 on another equipment, when `list_duplicate_candidates(R1.id)` is called, then it returns `[R2, R3, R4]` in that order — R5 excluded (different equipment), R1 excluded (self).

- **AC-13** When `list_duplicate_candidates(99999)` is called with a non-existent id, then `ValidationError` is raised.

**Web UI**

- **AC-14** Given a logged-in technician fetches `/repairs/{id}/edit` for a repair whose status is `'In Progress'`, then the response HTML contains a `<div id="duplicate-block"` element with inline `style="display: none;"`.

- **AC-15** Given a logged-in technician fetches `/repairs/{id}/edit` for a repair whose status is `'Closed - Duplicate'` and `duplicated_repair_id` is set, then the duplicate-block has no `display: none` style AND the target repair's `<option>` carries `selected`.

- **AC-16** Given an open repair R1 and another repair R2 on the same equipment, when a staff client POSTs `/repairs/R1/edit` with form data `status='Closed - Duplicate'`, `duplicated_repair_id=R2.id`, then the response is `302` to `/repairs/R1`, `db.session.get(RepairRecord, R1.id).duplicated_repair_id == R2.id`, and a follow-up GET of `/repairs/R1` contains the string "Marked as duplicate of #{R2.id}".

- **AC-17** Given an open repair R1, when a staff client POSTs `/repairs/R1/edit` with `status='Closed - Duplicate'` and `duplicated_repair_id=0`, then the response is `200` (no redirect), a `flash` of category `danger` is rendered containing the service ValidationError message, and `db.session.get(RepairRecord, R1.id).status` is unchanged.

- **AC-18** Given a repair R1 with `status='Closed - Duplicate'` and `duplicated_repair_id=R2.id`, when a staff client POSTs `/repairs/R1/edit` with `status='In Progress'` (no duplicated_repair_id in the form), then the response is `302`, `R1.duplicated_repair_id` is `None`, and the detail page no longer shows the "Marked as duplicate of" row.

**Slack**

- **AC-19** Given two open repairs R1 and R2 on the same equipment, when `build_repair_action_modal(R1)` is called, then the returned view contains a block with `block_id == 'duplicate_block'` whose `static_select` options include an entry with `value == str(R2.id)` and `text.text` starting with `f'#{R2.id} [{R2.status}]'`.

- **AC-20** Given a repair R1 that is the only repair on its equipment, when `build_repair_action_modal(R1)` is called, then NO block in the returned view has `block_id == 'duplicate_block'` AND the `status_block`'s options do NOT include any option with `value == 'Closed - Duplicate'`.

- **AC-21** When `build_repair_create_modal(equipment_options, user_options)` is called, then no option in the `status_block` has `value == 'Closed - Duplicate'`.

- **AC-22** Given an open repair R1 and another R2 on the same equipment, when the registered `view:repair_action_submission` handler is invoked with `private_metadata=str(R1.id)`, action=`set_status`, status=`Closed - Duplicate`, and `duplicate_block.duplicated_repair_id.selected_option.value=str(R2.id)`, then `update_repair_record` is called with `status='Closed - Duplicate'` and `duplicated_repair_id=R2.id`, `ack()` is called with no kwargs, and an ephemeral confirmation is posted.

- **AC-23** Given an open repair R1 and another R2 on the same equipment, when the action-modal handler is invoked with `action=set_status`, status=`Closed - Duplicate`, and no `duplicate_block.duplicated_repair_id.selected_option`, then `ack` is called with `response_action='errors'` and `errors['duplicate_block']` set to the "Selecting which repair this duplicates is required." string, and `update_repair_record` is NOT called.

**Cross-cutting**

- **AC-24** `make lint` reports no new violations after all changes.
- **AC-25** `make test` passes with the new tests included.

## Additional Context

### Dependencies

- **No new third-party dependencies.** Uses existing Flask-SQLAlchemy 3.x self-referential FK support (`remote_side=[id]`), Flask-WTF `SelectField(coerce=int)`, Slack Bolt SDK `views_open` / view-submission handlers, Alembic `batch_alter_table`.
- **Service-internal dependency:** `build_repair_action_modal` becomes coupled to `repair_service.list_duplicate_candidates`. This is acceptable since `forms.py` already imports models (line 173, line 197) and the Slack layer already has a hard service dependency.
- **Database:** requires MariaDB up + migration applied before service-layer code is exercised against the real DB. SQLite-in-memory testing config picks up the column automatically via `db.create_all()`.

### Testing Strategy

- **Unit tests (model layer):** model column nullability, FK behavior, relationship loading. See Task 3.
- **Unit tests (service layer):** `TestListDuplicateCandidates` (4 cases) + `TestDuplicatedRepairId` (8 cases covering AC-4 through AC-11). See Task 6.
- **Unit tests (Slack forms):** modal-builder dict-shape assertions (AC-19, AC-20, AC-21). See Task 16a.
- **Integration tests (Slack handlers):** action-modal submission via `_register_and_capture` helper with MagicMock client (AC-22, AC-23). See Task 16b.
- **Integration tests (web views):** Flask test client POSTs with `follow_redirects=False`, asserting redirects, DB state, and rendered HTML (AC-14 through AC-18). See Task 12.
- **Manual smoke test:** after `make run` + `make worker`, exercise the full flow in a browser: create two repairs on one equipment, transition one to `Closed - Duplicate` with the other as target, verify the detail page link, verify the timeline entry. Then via Slack (if `SLACK_SOCKET_MODE_CONNECT=true`): `/esb-repair`, pick the repair, `Set Status → Closed - Duplicate`, pick the duplicate, verify ephemeral confirmation and DB state.

### Notes

- **No backfill of legacy data.** Any rows that already have `status='Closed - Duplicate'` will have `duplicated_repair_id=NULL` post-migration. Staff who want to retroactively record the link can edit those records via the web UI now that the field is exposed. The legacy carve-out (AC-11) means editing such a row for unrelated fields doesn't force a re-link.
- **No CHECK constraint.** Coupling status and `duplicated_repair_id` at the DB layer would be ideal, but MariaDB CHECK enforcement of cross-column rules has been spotty historically, and the rest of this codebase enforces invariants in the service layer. We follow that precedent.
- **No reverse-direction view.** "Which repairs are duplicates of this one?" is not in scope. A future story can add a `backref` on the relationship and a section on the detail page; the data is fully queryable as soon as this is shipped.
- **Cycle detection deferred.** Duplicate chains (R1 → R2 → R3 → R1) are operationally harmless — staff would notice while clicking through — and adding cycle detection complicates the validation logic for no real benefit.
- **Slack 3-modal-stack avoided.** The original design instinct was to push a second modal after the user selects `Closed - Duplicate`. Single-modal with always-visible-but-optional fields (matching the existing ETA/status/note pattern) is simpler, has no race window between modal pushes, and is consistent with the codebase.
- **Migration revision id:** Alembic generates this; the slug portion should be `add_duplicated_repair_id`. CLAUDE.md documents the container-IP workflow.
- **Issue tracking:** This work resolves [#43](https://github.com/jantman/equipment-status-board/issues/43). Commits must be prefixed `Issue #43:` per repo convention.
