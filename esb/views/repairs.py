"""Repair record routes."""

import os
from datetime import UTC, datetime, timedelta

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, send_from_directory, url_for
from flask_login import current_user

from esb.forms.repair_forms import (
    RepairClaimForm,
    RepairNoteForm,
    RepairPhotoUploadForm,
    RepairRecordCreateForm,
    RepairRecordUpdateForm,
    RepairResolveForm,
)
from esb.models.repair_record import REPAIR_STATUSES
from esb.models.repair_timeline_entry import RepairTimelineEntry
from esb.services import equipment_service, repair_service, upload_service
from esb.services.repair_service import CLOSED_STATUSES, KANBAN_COLUMNS
from esb.utils.decorators import role_required
from esb.utils.exceptions import ValidationError

repairs_bp = Blueprint('repairs', __name__, url_prefix='/repairs')


def _aging_tier(seconds):
    """Return aging CSS class based on time-in-column seconds."""
    days = seconds / 86400
    if days >= 6:
        return 'hot'
    elif days >= 3:
        return 'warm'
    return 'default'


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


@repairs_bp.route('/')
@role_required('technician')
def index():
    """Repair records list page - redirects to queue."""
    return redirect(url_for('repairs.queue'))


@repairs_bp.route('/kanban')
@role_required('technician')
def kanban():
    """Staff Kanban board page."""
    kanban_data = repair_service.get_kanban_data()
    now_utc = datetime.now(UTC).replace(tzinfo=None)

    # Compute aging tier and entered-at datetime for each card
    for col_records in kanban_data.values():
        for record in col_records:
            record.aging_tier = _aging_tier(record.time_in_column)
            record.entered_at = now_utc - timedelta(seconds=record.time_in_column)

    return render_template(
        'repairs/kanban.html',
        kanban_data=kanban_data,
        columns=KANBAN_COLUMNS,
        now_utc=now_utc,
    )


@repairs_bp.route('/queue')
@role_required('technician')
def queue():
    """Technician repair queue page."""
    area_id = request.args.get('area', type=int)
    status_filter = request.args.get('status')

    # Canonicalize: only 'me' and 'unassigned' are recognized values; matching
    # is case-insensitive so '?assignee=Mine' from a manually-typed URL still
    # works. Any other input (empty, bogus, etc.) collapses to '' so the
    # template's dropdown still selects "All Assignees" via the
    # {% if not active_assignee %} branch.
    raw_assignee = request.args.get('assignee', '').lower()
    if raw_assignee in ('me', 'unassigned'):
        active_assignee = raw_assignee
    else:
        active_assignee = ''
    assignee_id_filter = current_user.id if active_assignee == 'me' else None
    unassigned_filter = (active_assignee == 'unassigned')

    areas = equipment_service.list_areas()
    open_statuses = [s for s in REPAIR_STATUSES if s not in CLOSED_STATUSES]
    try:
        records = repair_service.get_repair_queue(
            area_id=area_id,
            status=status_filter,
            assignee_id=assignee_id_filter,
            unassigned=unassigned_filter,
        )
    except ValidationError as e:
        # Defensive: the view's own canonicalization ensures the mutually-
        # exclusive filter guard cannot fire, but any future caller refactor
        # that lifts both into the same request should fail gracefully.
        flash(str(e), 'danger')
        records = []

    return render_template(
        'repairs/queue.html',
        records=records,
        areas=areas,
        statuses=open_statuses,
        active_area=area_id,
        active_status=status_filter,
        active_assignee=active_assignee,
        # Strip tzinfo: db.DateTime stores naive datetimes so subtraction must match
        now_utc=datetime.now(UTC).replace(tzinfo=None),
    )


@repairs_bp.route('/new', methods=['GET', 'POST'])
@role_required('technician')
def create():
    """Create a new repair record."""
    form = RepairRecordCreateForm()

    # Populate equipment choices (active only)
    equipment_list = equipment_service.list_equipment()
    form.equipment_id.choices = [(0, '-- Select Equipment --')] + [
        (e.id, f'{e.name} ({e.area.name})') for e in equipment_list
    ]

    # Populate assignee choices (all active users who are tech or staff)
    from esb.services import user_service
    users = user_service.list_users()
    form.assignee_id.choices = [(0, '-- Unassigned --')] + [
        (u.id, u.username) for u in users
    ]

    # Support pre-selected equipment from query param
    preselected_equipment_id = request.args.get('equipment_id', type=int)
    if request.method == 'GET' and preselected_equipment_id:
        form.equipment_id.data = preselected_equipment_id

    if form.validate_on_submit():
        if form.equipment_id.data == 0:
            flash('Please select an equipment item.', 'danger')
            return render_template('repairs/create.html', form=form)

        try:
            record = repair_service.create_repair_record(
                equipment_id=form.equipment_id.data,
                description=form.description.data,
                created_by=current_user.username,
                severity=form.severity.data or None,
                assignee_id=form.assignee_id.data if form.assignee_id.data != 0 else None,
                has_safety_risk=form.has_safety_risk.data,
                is_consumable=form.is_consumable.data,
                author_id=current_user.id,
            )
        except ValidationError as e:
            flash(str(e), 'danger')
            return render_template('repairs/create.html', form=form)

        flash('Repair record created successfully.', 'success')
        return redirect(url_for('repairs.detail', id=record.id))

    return render_template('repairs/create.html', form=form)


@repairs_bp.route('/<int:id>')
@role_required('technician')
def detail(id):
    """Repair record detail page with timeline."""
    try:
        record = repair_service.get_repair_record(id)
    except ValidationError:
        abort(404)

    timeline = record.timeline_entries.order_by(
        RepairTimelineEntry.created_at.desc()
    ).all()

    note_form = RepairNoteForm()
    photo_form = RepairPhotoUploadForm()
    photos = upload_service.get_documents('repair_photo', id)
    photos_by_id = {str(p.id): p for p in photos}

    return render_template(
        'repairs/detail.html',
        record=record,
        timeline=timeline,
        note_form=note_form,
        photo_form=photo_form,
        photos=photos,
        photos_by_id=photos_by_id,
    )


@repairs_bp.route('/<int:id>/notes', methods=['POST'])
@role_required('technician')
def add_note(id):
    """Add a note to a repair record."""
    try:
        repair_service.get_repair_record(id)
    except ValidationError:
        abort(404)

    form = RepairNoteForm()
    if form.validate_on_submit():
        try:
            repair_service.add_repair_note(
                repair_record_id=id,
                note=form.note.data,
                author_name=current_user.username,
                author_id=current_user.id,
            )
            flash('Note added.', 'success')
        except ValidationError as e:
            flash(str(e), 'danger')
    else:
        for field, errors in form.errors.items():
            for error in errors:
                flash(error, 'danger')
    return redirect(url_for('repairs.detail', id=id))


@repairs_bp.route('/<int:id>/photos', methods=['POST'])
@role_required('technician')
def upload_photo(id):
    """Upload a diagnostic photo to a repair record."""
    try:
        repair_service.get_repair_record(id)
    except ValidationError:
        abort(404)

    form = RepairPhotoUploadForm()
    if form.validate_on_submit():
        try:
            repair_service.add_repair_photo(
                repair_record_id=id,
                file=form.file.data,
                author_name=current_user.username,
                author_id=current_user.id,
            )
            flash('Photo uploaded.', 'success')
        except ValidationError as e:
            flash(str(e), 'danger')
    else:
        for field, errors in form.errors.items():
            for error in errors:
                flash(error, 'danger')
    return redirect(url_for('repairs.detail', id=id))


@repairs_bp.route('/<int:id>/files/<path:filename>')
@role_required('technician')
def serve_photo(id, filename):
    """Serve an uploaded repair photo file."""
    try:
        repair_service.get_repair_record(id)
    except ValidationError:
        abort(404)
    upload_path = current_app.config['UPLOAD_PATH']
    directory = os.path.join(upload_path, 'repairs', str(id))
    return send_from_directory(directory, filename)


@repairs_bp.route('/<int:id>/edit', methods=['GET', 'POST'])
@role_required('technician')
def edit(id):
    """Edit a repair record."""
    try:
        record = repair_service.get_repair_record(id)
    except ValidationError:
        abort(404)

    form = RepairRecordUpdateForm(obj=record)

    # Populate dynamic choices
    form.status.choices = [(s, s) for s in REPAIR_STATUSES]

    from esb.services import user_service
    users = user_service.list_users()
    form.assignee_id.choices = [(0, '-- Unassigned --')] + [
        (u.id, u.username) for u in users
    ]

    if request.method == 'GET':
        form.status.data = record.status
        form.severity.data = record.severity or ''
        form.assignee_id.data = record.assignee_id or 0
        form.eta.data = record.eta
        form.specialist_description.data = record.specialist_description or ''
        form.note.data = ''

    if form.validate_on_submit():
        try:
            repair_service.update_repair_record(
                repair_record_id=id,
                updated_by=current_user.username,
                author_id=current_user.id,
                status=form.status.data,
                severity=form.severity.data or None,
                assignee_id=form.assignee_id.data if form.assignee_id.data != 0 else None,
                eta=form.eta.data,
                specialist_description=form.specialist_description.data or None,
                note=form.note.data or None,
            )
        except ValidationError as e:
            flash(str(e), 'danger')
            return render_template('repairs/edit.html', form=form, record=record)

        flash('Repair record updated successfully.', 'success')
        return redirect(url_for('repairs.detail', id=id))

    return render_template('repairs/edit.html', form=form, record=record)


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
            # Capture pre-state for accurate flash wording. If the record is
            # already assigned to current_user AND has the right status, the
            # service no-ops via update_repair_record's value-equality guard;
            # we still flash a benign "already own" message instead of
            # misleading the user with "Claimed".
            try:
                pre_record = repair_service.get_repair_record(id)
                was_self_assigned = pre_record.assignee_id == current_user.id
            except ValidationError:
                was_self_assigned = False

            repair_service.claim_repair_record(
                repair_record_id=id,
                claimed_by_user_id=current_user.id,
                claimed_by_username=current_user.username,
            )
            if was_self_assigned:
                flash(f'You already own Repair #{id}.', 'info')
            else:
                flash(f'Claimed Repair #{id}.', 'success')
        except ValidationError as e:
            flash(str(e), 'danger')
    else:
        flash('Invalid claim request -- please try again.', 'danger')

    return redirect(_safe_next_url(request.form.get('next'), id))


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
        # CSRF failures get a specific reload-prompt so users with expired
        # sessions know what to do; note-field validation errors surface
        # verbatim (collapsed into a single flash to avoid stacked toasts
        # if future validators are added); anything else gets a generic
        # message that does not expose framework internals.
        csrf_errors = getattr(form.csrf_token, 'errors', None) if hasattr(form, 'csrf_token') else None
        if csrf_errors:
            flash('Your session may have expired -- please reload and try again.', 'danger')
        elif form.note.errors:
            flash('; '.join(form.note.errors), 'danger')
        else:
            flash('Invalid resolve request -- please try again.', 'danger')

    return redirect(_safe_next_url(request.form.get('next'), id))
