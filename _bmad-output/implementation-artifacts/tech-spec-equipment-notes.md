---
title: 'Notes on Equipment'
slug: 'equipment-notes'
created: '2026-07-03'
status: 'completed'
stepsCompleted: [1, 2, 3, 4]
tech_stack: [Python 3.14, Flask, Flask-SQLAlchemy, MariaDB, Alembic, Flask-WTF, Jinja2, pytest]
files_to_modify: [esb/models/equipment_note.py (new), esb/models/__init__.py, esb/services/equipment_service.py, esb/forms/equipment_forms.py, esb/views/equipment.py, esb/templates/equipment/detail.html, migrations/versions/<rev>_add_equipment_notes.py (new), tests/test_models/test_equipment_note.py (new), tests/test_services/test_equipment_service.py, tests/test_views/test_equipment_views.py]
code_patterns: [service-layer (views never query models), ExternalLink child-record CRUD, RepairTimelineEntry author_id+author_name attribution, log_mutation JSON audit, _can_edit_docs/_require_doc_edit permission gate, archived-equipment write block, Bootstrap card + list-group in detail.html (inline form, NOT collapse)]
test_patterns: [pytest class-per-feature, SQLite in-memory TestingConfig, staff_client/tech_client/make_equipment fixtures, capture fixture for mutation-log assertions, config_service.set_config for tech_doc_edit_enabled gating (technician-without-config is the canonical non-privileged case)]
---

# Tech-Spec: Notes on Equipment

**Created:** 2026-07-03

## Overview

### Problem Statement

Equipment records (GitHub issue #69) have no way to capture arbitrary free-form notes over time. Staff and technicians need to record observations, history, and context tied to a specific piece of equipment, each note carrying who wrote it and when.

### Solution

Add an `EquipmentNote` child table (foreign key to `equipment`, foreign key to `User` for the author plus a cached `author_name`, `content` text, `created_at` timestamp), a thin service layer to create and list notes, a Flask-WTF form, an add-note POST route on the equipment blueprint, and a new "Notes" section at the bottom of the equipment detail page (`equipment/detail.html`). The section shows an "Add note" textarea + button at the top (gated by the same permission as documents/links) and lists all notes newest-first below. Notes are append-only.

### Scope

**In Scope:**
- `EquipmentNote` SQLAlchemy model + Alembic migration
- `equipment_service` functions: `add_equipment_note()`, `get_equipment_notes()`
- `EquipmentNoteForm` (single textarea + submit)
- `add_note` POST route on `equipment_bp`
- New "Notes" section rendered at the bottom of `equipment/detail.html`
- Add-note permission gated by the existing `_can_edit_docs()` helper (staff always; technicians when `tech_doc_edit_enabled` config is on); blocked on archived equipment
- Author stored as FK to `User` (`author_id`) plus cached `author_name`
- Unit/view tests mirroring the external-links tests

**Out of Scope:**
- Editing or deleting notes (append-only per issue)
- Pagination (display all notes)
- Notes on any entity other than Equipment
- Slack / notification / audit-timeline integration beyond the standard `log_mutation` call
- Display of notes on public/kiosk/QR pages

## Context for Development

### Codebase Patterns

The closest existing analog is the **ExternalLink** feature (an equipment child record added and listed from the equipment detail page):
- Model `esb/models/external_link.py` — FK `equipment_id`, `created_at` default `lambda: datetime.now(UTC)`, `backref('links', lazy='dynamic')`.
- Service `esb/services/equipment_service.py` — `add_equipment_link()` / `delete_equipment_link()` / `get_equipment_links()`, each calling `log_mutation()`.
- Form `ExternalLinkForm` in `esb/forms/equipment_forms.py`.
- Routes `equipment.add_link` / `equipment.delete_link` in `esb/views/equipment.py`, gated by `_require_doc_edit()`, blocked when `eq.is_archived`.
- Template: "Links" `<div class="card mb-4">` section in `equipment/detail.html` with a collapse form + `list-group`.

Author attribution uses the **RepairTimelineEntry** pattern (`esb/models/repair_timeline_entry.py`): `author_id` FK to `users.id` (nullable) + cached `author_name` String + `content` Text + `created_at`, with `db.relationship('User', ...)`.

### Files to Reference

| File | Purpose |
| ---- | ------- |
| `esb/models/external_link.py` | Model shape for an equipment child record (FK, created_at default) |
| `esb/models/repair_timeline_entry.py` | Author FK + cached author_name + content pattern |
| `esb/services/equipment_service.py` | Where `add_equipment_note`/`get_equipment_notes` go; `log_mutation` usage; `get_equipment` |
| `esb/forms/equipment_forms.py` | Where `EquipmentNoteForm` goes; TextAreaField/validators imports |
| `esb/views/equipment.py` | `detail()` view context; `_can_edit_docs()`/`_require_doc_edit()`; add_link route as route template |
| `esb/templates/equipment/detail.html` | Links section is the exact template pattern to mirror for the Notes section |
| `esb/models/__init__.py` | Model registration (must import new model) |
| `tests/conftest.py` | Fixtures: `staff_client`, `tech_client`, `make_equipment`, `capture`; `_create_user(role, ...)` helper. Note `VALID_ROLES=('technician','staff')` — there is **no `member` role in code** (see review R2-1) |

### Technical Decisions

- **Author storage:** FK `author_id` → `users.id` (nullable, no `ondelete` — matches `RepairTimelineEntry`) plus cached `author_name` string. **Correction (review F2):** the nullable FK does **not** null-out on user deletion — with no `ondelete='SET NULL'`, MariaDB's default RESTRICT would *reject* deleting a user who has notes. It is the **cached `author_name`** — not the nullable `author_id` — that preserves attribution for display. This matches `RepairTimelineEntry` exactly and is acceptable because user deletion is not a supported flow in this app; we deliberately do not add `ondelete` behavior here. (User confirmed: foreign key to User.) **Note (review R2-5):** in *this* feature the only writer (`add_note`) always passes `current_user.id`/`.username`, so a null author is unreachable — the nullable columns and the `'unknown'`/`'Unknown'` fallbacks are defensive-only, retained purely to mirror the analog. A reasonable alternative would be `nullable=False`; we keep nullable for consistency with `RepairTimelineEntry` and to avoid a migration constraint that this feature never exercises.
- **`author_name` is a point-in-time cache (review F12):** it stores the username as of note creation and will **not** reflect later username changes (unlike a live join via the `author` relationship). This is intentional — display attribution is stable and independent of the user row. Column is `String(200)`; `User.username` is `String(80)`, so it always fits.
- **Permissions:** Adding a note reuses `_can_edit_docs()` / `_require_doc_edit()` — staff always, technicians when `tech_doc_edit_enabled`, everyone else denied. Viewing notes requires only `@login_required` (whole detail page already is). (User confirmed: same as docs/links.)
- **RBAC reality (review R2-1):** the only implemented roles are `technician` and `staff` (`user_service.VALID_ROLES`, `decorators.ROLE_HIERARCHY`). CLAUDE.md line 60 mentions a `member` role, but **no such role exists in code** and `user_service` rejects it — so the canonical "non-privileged user" for tests is a **technician with `tech_doc_edit_enabled` unset** (via `_can_edit_docs()` → `False`). Do **not** invent a `member` fixture. (Flagged discrepancy: CLAUDE.md vs. code — worth reconciling separately, out of scope here.)
- **Permission-vs-archived precedence (review F10):** the route calls `_require_doc_edit()` **before** the `is_archived` check (exactly like `add_link`). Consequently the "Cannot modify archived equipment." flash is only reachable by an already-permitted user (staff, or a technician with `tech_doc_edit_enabled`); an ungated technician POSTing to an archived item's notes route gets **403**, not the archived flash. ACs 6/7 below encode this precedence explicitly.
- **Mutability:** Append-only. No edit/delete routes, no delete button. (User confirmed.)
- **Archived equipment:** Adding notes is blocked on archived equipment (mirrors links/docs), with the "Cannot modify archived equipment." flash — for permitted users (see precedence above).
- **Ordering:** Newest-first, via `order_by(EquipmentNote.created_at.desc(), EquipmentNote.id.desc())` in the service. **Note (review F4):** the `.id.desc()` secondary sort is a deliberate improvement over `get_equipment_links` (which sorts on `created_at` alone) — it guarantees a stable, deterministic order when two notes share a `created_at` (common in fast tests and coarse-resolution timestamps), so the ordering AC/test is not flaky.
- **Timestamp display (review F7):** `created_at` is stored as naive UTC; the `format_datetime` Jinja filter (`esb/utils/filters.py`, bare `strftime('%Y-%m-%d %H:%M')`) renders it as unlabeled UTC with no timezone conversion. This is a known, accepted limitation consistent with the repair timeline's use of the same filter. **Precedent clarification (review R2-2):** no *visible* cell in this template renders `format_datetime` today — the repair row (`detail.html:259`) shows `relative_time` to the user and uses `format_datetime` only inside a `title=` tooltip; the Links/Documents lines render **date-only** via `strftime('%Y-%m-%d')`. The Notes section **deliberately diverges**: it displays a visible date **and** time (using `format_datetime`) because a note's exact time is useful. This is a conscious design choice, not a mirror of an existing visible pattern.
- **Author capture in the route:** `current_user` is a `User` instance (Flask-Login), so the route passes `author_id=current_user.id` and `author_name=current_user.username` into the service. Confirmed both attributes exist (`esb/models/user.py`).
- **Audit logging:** Call `log_mutation('equipment_note.created', author_name, {...})` — signature is `log_mutation(event, user, data)` where `user` is a username string (`esb/utils/logging.py`).
- **Content validation (review F6/R2-4):** the **service is authoritative**; the form is a friendly pre-check. The service `add_equipment_note` rejects empty/whitespace-only content with `ValidationError('Note content is required')` **and** rejects `len(content.strip()) > NOTE_MAX_LENGTH` (5000) with `ValidationError(f'Note is too long (max {NOTE_MAX_LENGTH} characters)')` (constant in the message, not a literal — review R3-6) — so no caller can persist an over-length note into the `Text` column (~65 KB). The `EquipmentNoteForm` adds `DataRequired()` + `Length(max=NOTE_MAX_LENGTH, message=...)` with the same constant-derived message (review R3-7, for a stable assertable string). **The two checks are deliberately *not* identical:** WTForms `Length` measures the **raw** field value while the service measures the **stripped** value, so a note padded with trailing whitespace past 5000 raw chars is rejected by the form but (after stripping) accepted by the service. This is intended — the service's stripped-length rule is the real constraint (it matches what actually gets stored); the form's raw-length rule is only an early UX guard. They **share the `NOTE_MAX_LENGTH` constant** (defined in the service) but are not claimed to be byte-for-byte equivalent.
- **Migration:** New `equipment_notes` table needs an Alembic migration. Per CLAUDE.md the DB runs only in Docker (port 3306 unmapped) — generate/apply via `docker compose up -d db`, inspect the container IP, then `DATABASE_URL="mysql+pymysql://root:esb_dev_password@<IP>/esb" flask db migrate/upgrade`. Model must be imported in `esb/models/__init__.py` for autogenerate to see it.
- **Model registration:** Add `EquipmentNote` import + `__all__` entry in `esb/models/__init__.py` (required for Alembic discovery and app-wide availability).

## Implementation Plan

### Tasks

- [x] **Task 1: Create the `EquipmentNote` model**
  - File: `esb/models/equipment_note.py` (new)
  - Action: Define `EquipmentNote(db.Model)` with `__tablename__ = 'equipment_notes'`. Columns:
    - `id = db.Column(db.Integer, primary_key=True)`
    - `equipment_id = db.Column(db.Integer, db.ForeignKey('equipment.id'), nullable=False, index=True)`
    - `author_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)`
    - `author_name = db.Column(db.String(200), nullable=True)`
    - `content = db.Column(db.Text, nullable=False)`
    - `created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(UTC))`
    - Relationships: `equipment = db.relationship('Equipment', backref=db.backref('notes', lazy='dynamic', order_by='EquipmentNote.created_at.desc(), EquipmentNote.id.desc()'))` and `author = db.relationship('User', backref=db.backref('equipment_notes', lazy='dynamic'))`
    - Note (review R2-10): the `order_by` on the `notes` backref matches the service's ordering so any direct `equipment.notes` access is also deterministic newest-first, consistent with `RepairTimelineEntry`'s ordered backref.
    - `__repr__` returning `f'<EquipmentNote {self.id}>'`
  - Notes: Import `from datetime import UTC, datetime` and `from esb.extensions import db`. Mirror `esb/models/external_link.py` (child FK + `created_at` default) and `esb/models/repair_timeline_entry.py` (author_id + author_name + content). `author_id` is nullable to match `RepairTimelineEntry` (no `ondelete` clause). Attribution is preserved by the cached **`author_name`**, not by the nullable FK — see Technical Decisions F2/F12: `author_name` is a point-in-time snapshot that will not reflect later username changes, and the FK does not `SET NULL` on user delete.

- [x] **Task 2: Register the model for Alembic discovery**
  - File: `esb/models/__init__.py`
  - Action: Add `from esb.models.equipment_note import EquipmentNote` **between** the `equipment` and `equipment_reservation_settings` imports (review F5: `equipment_note` sorts before `equipment_reservation_settings` because `n` < `r`) and add `'EquipmentNote'` to `__all__` in the corresponding position.
  - Notes: Required for `flask db migrate` autogenerate and app-wide import consistency.

- [x] **Task 3: Add service functions**
  - File: `esb/services/equipment_service.py`
  - Action: Define a module-level `NOTE_MAX_LENGTH = 5000` constant, then add a `# --- Equipment Notes ---` section with two functions (mirror `add_equipment_link`/`get_equipment_links`):
    - `add_equipment_note(equipment_id: int, content: str, author_id: int | None, author_name: str | None) -> EquipmentNote`:
      - Look up equipment via `db.session.get(Equipment, equipment_id)`; raise `ValidationError(f'Equipment with id {equipment_id} not found')` if `None`.
      - If `not content or not content.strip()`: raise `ValidationError('Note content is required')`.
      - Compute `stripped = content.strip()`; if `len(stripped) > NOTE_MAX_LENGTH`: raise `ValidationError(f'Note is too long (max {NOTE_MAX_LENGTH} characters)')` (review F6 — server-side length enforcement; use the constant in the message, not a `5000` literal, so it stays in sync — review R3-6).
      - Create `EquipmentNote(equipment_id=..., content=stripped, author_id=author_id, author_name=author_name)`, `db.session.add(...)`, `db.session.commit()`.
      - `log_mutation('equipment_note.created', author_name or 'unknown', {'id': note.id, 'equipment_id': note.equipment_id})`.
      - Return the note.
    - `get_equipment_notes(equipment_id: int) -> list[EquipmentNote]`: return all notes for the equipment ordered by `EquipmentNote.created_at.desc(), EquipmentNote.id.desc()` (newest-first, with a stable `id` tiebreaker — review F4).
  - Notes: Add `from esb.models.equipment_note import EquipmentNote` to the imports at the top. Import `NOTE_MAX_LENGTH` into `equipment_forms.py` (Task 4) so the form's `Length(max=...)` stays in sync with the service constant.

- [x] **Task 4: Add the note form**
  - File: `esb/forms/equipment_forms.py`
  - Action: Add `class EquipmentNoteForm(FlaskForm)` with `content = TextAreaField('Note', validators=[DataRequired(), Length(max=NOTE_MAX_LENGTH, message=f'Note is too long (max {NOTE_MAX_LENGTH} characters)')])` and `submit = SubmitField('Add Note')`. The explicit `message` (review R3-7) makes the over-length error a stable, assertable string instead of relying on WTForms' version-specific default.
  - Notes: `TextAreaField`, `DataRequired`, `Length`, `SubmitField` are already imported in this file. Import `NOTE_MAX_LENGTH` from `esb.services.equipment_service` so the form and service share the constant (review F6). **No circular import (review R2-7):** `equipment_forms.py` already imports from a service (`from esb.services.qr_service import ...`, line 18) and `equipment_service` imports only models/utils (never forms), so the graph is clean — keep the constant defined in the service, no fallback needed. Place the class near `ExternalLinkForm`.

- [x] **Task 5: Add the add-note route and wire notes into the detail view**
  - File: `esb/views/equipment.py`
  - Action:
    - Import `EquipmentNoteForm` in the `esb.forms.equipment_forms` import block.
    - In `detail()`: fetch `notes = equipment_service.get_equipment_notes(id)`, build `note_form = EquipmentNoteForm()`, and pass both to `render_template(...)`.
    - Add a new route mirroring `add_link`:
      ```python
      @equipment_bp.route('/<int:id>/notes', methods=['POST'])
      @login_required
      def add_note(id):
          try:
              eq = equipment_service.get_equipment(id)
          except ValidationError:
              abort(404)
          _require_doc_edit()
          if eq.is_archived:
              flash('Cannot modify archived equipment.', 'danger')
              return redirect(url_for('equipment.detail', id=id))
          form = EquipmentNoteForm()
          if form.validate_on_submit():
              try:
                  equipment_service.add_equipment_note(
                      equipment_id=id,
                      content=form.content.data,
                      author_id=current_user.id,
                      author_name=current_user.username,
                  )
                  flash('Note added successfully.', 'success')
              except ValidationError as e:
                  flash(str(e), 'danger')
          else:
              for field, errors in form.errors.items():
                  for error in errors:
                      flash(f'{error}', 'danger')
          return redirect(url_for('equipment.detail', id=id))
      ```
  - Notes: `_require_doc_edit()` enforces the staff/technician gate (403 for non-privileged users, i.e. ungated technicians); the archived check + validation-error flashing exactly match `add_link`.

- [x] **Task 6: Render the Notes section in the detail template**
  - File: `esb/templates/equipment/detail.html`
  - Action: Add a new `<div class="card mb-4">` "Notes" section at the bottom (after the Links section, before `{% endblock %}`). Reuse the Links card's **card + card-header + card-body + `list-group`** structure, but **NOT** its `data-bs-toggle="collapse"` toggle button — the add-note form renders **inline and always-visible** at the top of the card body per the issue (review F9: this is a deliberate divergence from the Links card, whose form is collapsed behind a header button; the Notes card-header has a plain title only, no button).
    - Card header: `<h5 class="mb-0">Notes</h5>` (no button).
    - When `can_edit_docs`, at the top of the card body render the add form:
      ```html
      <form method="post" action="{{ url_for('equipment.add_note', id=equipment.id) }}" class="mb-3">
          {{ note_form.hidden_tag() }}
          <label for="{{ note_form.content.id }}" class="form-label">Add a note</label>
          {{ note_form.content(class="form-control", rows="2", placeholder="Add a note...") }}
          {{ note_form.submit(class="btn btn-primary mt-2") }}
      </form>
      ```
      (review F8: an explicit `<label for=...>` is required — the Links form it mirrors uses real labels; a placeholder is not an accessible label.)
    - Below the form, if `notes`: a `list-group` iterating `for note in notes`; each item renders the content in an element that preserves newlines **without unescaping**, e.g. `<div style="white-space: pre-wrap;">{{ note.content }}</div>`, plus a `<small class="text-muted">` line: `{{ note.author_name or 'Unknown' }} &middot; <span title="UTC">{{ note.created_at|format_datetime }} UTC</span>`. Else show `<p class="text-muted text-center mb-0">No notes yet.</p>`.
  - Notes:
    - **Newlines / XSS (review F3):** MUST use the `white-space: pre-wrap;` CSS approach with Jinja autoescaping left **on**. Do **NOT** introduce or use an `nl2br`/`|safe`/`Markup` filter — note content is untrusted free text and any unescaping path is a stored-XSS vector. (Confirmed: no `nl2br` filter is registered — only `format_date`, `format_datetime`, `relative_time`, `category_label`, `filesize` in `esb/utils/filters.py`.)
    - **Timestamp (review F7/R2-2):** `|format_datetime` renders naive UTC as `%Y-%m-%d %H:%M` with no TZ conversion; append a literal " UTC" (and/or `title="UTC"`) so the displayed time is unambiguous. This is a deliberate visible date+time (unlike the date-only Links/Docs lines and the tooltip-only use at `detail.html:259`) — see Technical Decisions R2-2.

- [x] **Task 7: Generate and apply the Alembic migration**
  - File: `migrations/versions/<rev>_add_equipment_notes.py` (new, autogenerated)
  - Action: With the DB container running, generate the migration and apply it:
    ```bash
    docker compose up -d db
    IP=$(docker inspect equipment-status-board-db-1 --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}')
    source venv/bin/activate
    DATABASE_URL="mysql+pymysql://root:esb_dev_password@$IP/esb" flask db migrate -m "Add equipment_notes table"
    DATABASE_URL="mysql+pymysql://root:esb_dev_password@$IP/esb" flask db upgrade
    ```
  - Notes: Review the autogenerated migration to confirm it only creates `equipment_notes` (table + FKs + index on `equipment_id`) and nothing spurious. Container IP changes each restart — inspect fresh. **This manual review is the only verification of the migration (review R2-3):** the pytest suite uses SQLite `create_all()` and never runs Alembic, so nothing else catches a wrong/empty migration — review it carefully and confirm `flask db upgrade` then `downgrade` both succeed against the container.

- [x] **Task 8: Model tests**
  - File: `tests/test_models/test_equipment_note.py` (new)
  - Action: Mirror `tests/test_models/test_external_link.py`. Assert the model persists, defaults `created_at`, stores `content`/`author_id`/`author_name`, and the `equipment.notes` / `author.equipment_notes` backrefs resolve. Since the `notes` backref carries an `order_by=created_at.desc(), id.desc()` (Task 1, review R2-10), a test that adds two notes and reads `equipment.notes` should see newest-first order.

- [x] **Task 9: Service tests**
  - File: `tests/test_services/test_equipment_service.py`
  - Action: Add `TestAddEquipmentNote` and `TestGetEquipmentNotes` classes mirroring the link test classes:
    - `add_equipment_note` success (returns note, sets fields), strips whitespace, invalid equipment raises `ValidationError`, empty/whitespace content raises `ValidationError` (**call the service directly** — via the web route `DataRequired` fires first with a different message, so the service's `'Note content is required'` message is only reachable here; review R2-8), **over-length content (`'x' * (NOTE_MAX_LENGTH + 1)`) raises `ValidationError` (review F6/F11)**, logs an `equipment_note.created` mutation — assert via `entry = json.loads(r.message)` that `entry['user']` equals the passed `author_name` and `entry['data']` contains `id` + `equipment_id` (**review R3-1: `capture.records` are `LogRecord`s; parse `r.message`, do not use `record.user`/`record.data`**; mirror `test_equipment_service.py:199-208`) (use `capture` fixture).
    - `get_equipment_notes` returns notes for the equipment newest-first, excludes other equipment's notes, returns `[]` when none. **Ordering/tiebreaker test (review F4/R3-2):** because `add_equipment_note` has no `created_at` parameter (it defaults to `now(UTC)`), construct two `EquipmentNote` rows **directly** with the *same* explicit `created_at` (and add via `_db.session`), then assert `get_equipment_notes` returns the higher-`id` row first. The service API cannot force equal timestamps, so this test must bypass it.

- [x] **Task 10: View tests**
  - File: `tests/test_views/test_equipment_views.py`
  - Action: Add `TestAddNote` class mirroring `TestAddLink`/permission tests:
    - `staff_client` adds a note (200 + 'Note added successfully' + row persisted).
    - `tech_client` gets 403 when `tech_doc_edit_enabled` unset; succeeds when `config_service.set_config('tech_doc_edit_enabled', 'true', 'test')`.
    - **Non-privileged user (review R2-1/AC 6):** a `tech_client` with `tech_doc_edit_enabled` unset (the real non-privileged case — there is no `member` role) gets **403** on POST and, on a GET of the detail page, sees no add-note form (assert the form `action` URL / "Add Note" submit label is absent). This reuses the existing `tech_client` fixture; no new fixture is added.
    - 404 for nonexistent equipment; validation error for empty content ('This field is required').
    - **Over-length rejection (review F11/R3-7):** POST `'x' * (NOTE_MAX_LENGTH + 1)` and assert **no row is created** (query the count) rather than matching WTForms' default `Length` message text (which is version-fragile). If a message assertion is wanted, set an explicit `message=` on the form's `Length` validator (Task 4) and assert that pinned string.
    - **XSS-escaping (review F3/R3-3/AC 12):** POST content `<script>alert(1)</script>` as staff, then GET the detail page and assert the **escaped payload** `&lt;script&gt;alert(1)&lt;/script&gt;` is present and the **raw injected** `<script>alert(1)</script>` is not. Do **not** assert absence of the bare substring `<script` — `base.html` legitimately emits `<script src=...>` tags and that assertion would false-fail.
    - **Mutation logged (review R3-1):** parse `json.loads(r.message)` from `capture.records` and assert `entry['event'] == 'equipment_note.created'` and `entry['data']['id']` present — not `record.data`.
    - **Empty state (review R3-4/AC 3):** GET the detail page for an equipment with no notes and assert `"No notes yet."` renders.
    - **Append-only (review R3-5/AC 10):** assert no edit/delete route exists for notes — e.g. `url_for` for such an endpoint raises / the endpoint is absent from `app.url_map`, and the rendered detail page contains no delete control inside the Notes card. (Complement to the code-review check noted in AC 10.)
    - **Archived block with a *permitted* user (review F10):** use `staff_client` (or a `tech_doc_edit_enabled` `tech_client`) POSTing to an archived item → 'Cannot modify archived equipment.' Do **not** assert this message for an ungated technician, who gets 403 first because `_require_doc_edit()` runs before the archived check.

- [x] **Task 11: Lint and run the suite**
  - Action: `make lint` (ruff, 120-char) and `make test`. Fix any failures.

### Acceptance Criteria

- [x] **AC 1 (happy path — add):** Given a staff user viewing an active equipment's detail page, when they type text into the "Add note" box and submit, then the note is saved with their username as `author_name`, their id as `author_id`, the current UTC time as `created_at`, and the page reloads showing "Note added successfully." with the new note listed.
- [x] **AC 2 (display order):** Given an equipment with multiple notes, when the detail page renders, then all notes appear in a Notes section at the bottom in newest-to-oldest order (ties broken by descending `id` for a deterministic order — review F4), each showing its content, author name, and timestamp (displayed as UTC), with no pagination.
- [x] **AC 3 (empty state):** Given an equipment with no notes, when the detail page renders, then the Notes section shows "No notes yet."
- [x] **AC 4 (validation):** Given the add-note form, when submitted with empty or whitespace-only content, then no note is created and a validation error ("This field is required") is shown.
- [x] **AC 5 (permission — technician gated):** Given a technician user and `tech_doc_edit_enabled` unset/false, when they POST to `/equipment/<id>/notes`, then the response is 403 and no note is created; and when `tech_doc_edit_enabled` is 'true', the same POST succeeds.
- [x] **AC 6 (permission — non-privileged user):** Given a non-privileged user — i.e. a technician with `tech_doc_edit_enabled` unset (there is no `member` role in code; review R2-1) — when they view an equipment's detail page, then no "Add note" form is shown (`can_edit_docs` is false); and when they POST directly to `/equipment/<id>/notes`, then the response is 403 and no note is created — this holds even for an archived item, because `_require_doc_edit()` runs before the archived check (review F10).
- [x] **AC 7 (archived):** Given an archived equipment and a **permitted** user (staff, or a technician with `tech_doc_edit_enabled`), when they POST a note, then no note is created and "Cannot modify archived equipment." is flashed (review F10 — the archived flash is only reachable by permitted users).
- [x] **AC 8 (not found):** Given a nonexistent equipment id, when POSTing to its notes route, then the response is 404.
- [x] **AC 9 (audit):** Given a note is successfully added, when it is created, then an `equipment_note.created` mutation is logged as JSON where the parsed `event == 'equipment_note.created'`, the top-level `user` is the author's username, and `data` contains the note `id` and `equipment_id`. **Assertion mechanics (review R3-1):** `capture.records` are raw `logging.LogRecord`s — parse each with `json.loads(r.message)` and index the resulting dict (`entry['user']`, `entry['data']['id']`), exactly like the existing mutation-log tests (`tests/test_services/test_equipment_service.py:199-208`). Do **not** access `record.user` / `record.data` (no such attributes exist).
- [x] **AC 10 (append-only):** Given the feature as built, then there is no route, form, or UI control to edit or delete a note. *(Verified partly by test — assert no edit/delete URL is emitted and no such route resolves — and partly by code review, since "no edit/delete capability anywhere" is an absence property; review R2-9.)*
- [x] **AC 11 (length limit):** Given the add-note form or a direct service call, when content longer than `NOTE_MAX_LENGTH` (5000) characters is submitted, then no note is created and a length validation error is returned/flashed — enforced at both the form and the service layer (review F6/F11).
- [x] **AC 12 (no unescaping / XSS-safe):** Given a note whose content contains HTML/script-like text (e.g. `<script>` or `&`), when the detail page renders it, then the content is HTML-escaped (autoescape on) and newlines are preserved via `white-space: pre-wrap;`. *(The escaping/pre-wrap outcome is asserted by a view test (review F3); the stronger "no `nl2br`/`|safe`/`Markup` path is used anywhere" is an absence property enforced by code review — review R2-9.)*

## Additional Context

### Dependencies

- No new external libraries — uses existing Flask, Flask-SQLAlchemy, Flask-WTF, Alembic, pytest.
- Requires the MariaDB container running to generate/apply the migration (see Task 7); no local MySQL exists.
- Depends on existing helpers already in the codebase: `_can_edit_docs()`/`_require_doc_edit()`, `log_mutation()`, `ValidationError`, `format_datetime` Jinja filter, and the `capture`/`staff_client`/`tech_client`/`make_equipment` test fixtures.
- **No new test fixtures needed (review R2-1):** the non-privileged permission case reuses the existing `tech_client` with `tech_doc_edit_enabled` unset. There is no `member` role in code, so no member fixture is added.

### Testing Strategy

- **Model tests** (`tests/test_models/test_equipment_note.py`): persistence, `created_at` default, ordered-backref resolution — mirror `test_external_link.py`.
- **Service tests** (`tests/test_services/test_equipment_service.py`): `add_equipment_note` (success, strip, invalid equipment, empty content **called directly**, **over-length rejection**, mutation-log assertion via `json.loads(r.message)` — not `record.user`) and `get_equipment_notes` (ordering newest-first, **same-`created_at` id tiebreaker via direct-row construction**, isolation per equipment, empty list).
- **View tests** (`tests/test_views/test_equipment_views.py`): staff add success, technician 403/enabled, **ungated-technician 403 + no-form-rendered** (the non-privileged case), empty-content validation, **over-length rejection (assert no row created)**, **empty-state string**, **append-only (no edit/delete route/control)**, archived block (permitted user), 404, mutation log (`json.loads`), and an **XSS-escaping** assertion scoped to the injected payload.
- **Migration coverage gap (review R2-3):** the automated suite runs against SQLite via `create_all()` and does **not** execute the Alembic migration, so column types / FK / index in the generated MariaDB migration have no CI coverage. Mitigate by (a) carefully reviewing the autogenerated migration (Task 7) and (b) the manual smoke test below, which runs `make migrate` against the real MariaDB container.
- **Manual smoke test:** run `make db-up`, `make migrate`, `make run`; log in as staff, open an equipment detail page, add a note, confirm it appears newest-first with author + timestamp; verify the form is absent when logged in as an ungated technician (`tech_doc_edit_enabled` off).
- All automated tests use SQLite in-memory (`TestingConfig`); CSRF disabled in test config. Run via `make test` and `make lint`.

### Notes

- **Source:** GitHub issue #69 "Allow notes on Equipment" (DecaturMakers/equipment-status-board).
- **Pre-mortem / risks:**
  - *Newline rendering / XSS (F3):* note content is untrusted free text. Preserve line breaks with `white-space: pre-wrap;` and keep Jinja autoescape **on**. Do NOT add or use an `nl2br`/`|safe`/`Markup` filter — none is registered today, and adding one would create a stored-XSS vector. Covered by AC 12 + the view-layer escaping test.
  - *Author attribution vs deletion (F2/F12):* attribution is preserved by the cached `author_name`, not by the nullable `author_id` (which does not `SET NULL` on delete). `author_name` is a point-in-time snapshot; it will not follow later username changes. Template falls back to "Unknown" when `author_name` is null.
  - *Ordering determinism (F4):* `created_at` alone can tie; the service adds a `.id.desc()` tiebreaker so display/tests are deterministic.
  - *Length enforcement (F6):* the 5000-char limit is enforced in the service (authoritative) and the form (friendly message), kept in sync via `NOTE_MAX_LENGTH`.
  - *Autogenerated migration drift:* review the generated migration so it only adds `equipment_notes` (models must be imported first, or autogenerate emits an empty migration).
- **Known limitations (out of scope):** no editing/deleting, no pagination, no notifications/Slack, notes not shown on public/kiosk/QR pages.
- **CLAUDE.md vs. code discrepancy (review R2-1):** CLAUDE.md line 60 documents a `member` role, but the code implements only `technician` and `staff` (`user_service.VALID_ROLES`, `decorators.ROLE_HIERARCHY`). This spec follows the **code**. Reconciling the docs (or actually adding a `member` role) is a separate concern outside this feature — flagged here for the maintainer.
- **Migration not covered by CI (review R2-3):** see Testing Strategy — the Alembic migration is verified only by manual review + smoke test, an accepted limitation of the SQLite-based suite.
- **Future considerations:** if notes volume grows, add pagination and/or edit-delete with audit; consider surfacing notes on the public equipment page. All explicitly deferred.

## Review Notes

- Adversarial review completed (independent subagent, diff-only context).
- Findings: 6 total (all Low; no Critical/High). 2 fixed, 4 acknowledged as intentional/out-of-scope.
- Resolution approach: auto-fix of the two findings the user selected (F1, F2).
  - **F1 (fixed):** `EquipmentNoteForm` now validates *stripped* content length via a `validate_content` method (shared `NOTE_MAX_LENGTH` + message), so the form never rejects a whitespace-padded note the authoritative service would store. Supersedes the earlier "deliberately not identical" raw-vs-stripped decision.
  - **F2 (fixed):** `add_note` re-renders the detail page (via new `_render_equipment_detail` helper) on validation failure, preserving the user's typed note instead of redirecting and discarding it.
  - **F3 (acknowledged):** "member-role denied" test — invalid premise; no `member` role exists in code (R2-1). Canonical non-privileged case (ungated technician) is already tested.
  - **F4 (acknowledged):** minute-resolution timestamps — accepted per F7; ordering stays deterministic via `id DESC`.
  - **F5 (acknowledged):** notes list visible to all authenticated users — by design (viewing needs only `@login_required`, matching docs/links).
  - **F6 (acknowledged):** service re-fetches Equipment — by design, mirrors `add_equipment_link`.
- Verification: `make lint` clean; full suite 1840 passed; migration upgrade↔downgrade verified against MariaDB container.
