"""Equipment registry routes."""

import io
import os

from flask import (
    Blueprint,
    Response,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    send_from_directory,
    url_for,
)
from flask_login import current_user, login_required

from esb.forms.equipment_forms import (
    DocumentUploadForm,
    EquipmentCreateForm,
    EquipmentEditForm,
    ExternalLinkForm,
    PhotoUploadForm,
    QRGenerateForm,
)
from esb.services import config_service, equipment_service, qr_service, repair_service, upload_service
from esb.utils.decorators import role_required
from esb.utils.exceptions import ValidationError
from esb.utils.text import get_normalized_base_url, slugify_filename

equipment_bp = Blueprint('equipment', __name__, url_prefix='/equipment')


@equipment_bp.route('/')
@login_required
def index():
    """Equipment registry list with optional area filter."""
    area_id = request.args.get('area_id', type=int)
    equipment = equipment_service.list_equipment(area_id=area_id)
    areas = equipment_service.list_areas()
    return render_template(
        'equipment/list.html',
        equipment=equipment,
        areas=areas,
        selected_area_id=area_id,
    )


@equipment_bp.route('/export.csv')
@login_required
def export_csv():
    """Download the equipment inventory as a CSV file."""
    area_id = request.args.get('area_id', type=int)
    include_archived = request.args.get('include_archived', default='0').lower() in ('1', 'true')
    csv_text = equipment_service.export_equipment_csv(
        username=current_user.username,
        area_id=area_id,
        include_archived=include_archived,
    )
    # Prepend UTF-8 BOM so Excel opens non-ASCII correctly; serve as UTF-8.
    body = ('\ufeff' + csv_text).encode('utf-8')
    return Response(
        body,
        content_type='text/csv; charset=utf-8',
        headers={
            'Content-Disposition': 'attachment; filename="equipment_inventory.csv"',
        },
    )


@equipment_bp.route('/new', methods=['GET', 'POST'])
@role_required('staff')
def create():
    """Equipment creation form and handler."""
    form = EquipmentCreateForm()
    areas = equipment_service.list_areas()
    form.area_id.choices = [(0, '-- Select Area --')] + [
        (a.id, a.name) for a in areas
    ]

    if form.validate_on_submit():
        if form.area_id.data == 0:
            flash('Please select an area.', 'danger')
            return render_template(
                'equipment/form.html', form=form, title='Add Equipment',
            )
        try:
            eq = equipment_service.create_equipment(
                name=form.name.data,
                manufacturer=form.manufacturer.data,
                model=form.model.data,
                area_id=form.area_id.data,
                created_by=current_user.username,
                serial_number=form.serial_number.data or None,
                acquisition_date=form.acquisition_date.data,
                acquisition_source=form.acquisition_source.data or None,
                acquisition_cost=form.acquisition_cost.data,
                warranty_expiration=form.warranty_expiration.data,
                description=form.description.data or None,
            )
        except ValidationError as e:
            flash(str(e), 'danger')
            return render_template(
                'equipment/form.html', form=form, title='Add Equipment',
            )

        flash('Equipment created successfully.', 'success')
        return redirect(url_for('equipment.detail', id=eq.id))

    return render_template(
        'equipment/form.html', form=form, title='Add Equipment',
    )


@equipment_bp.route('/<int:id>')
@login_required
def detail(id):
    """Equipment detail page."""
    try:
        eq = equipment_service.get_equipment(id)
    except ValidationError:
        abort(404)

    documents = upload_service.get_documents('equipment_doc', id)
    photos = upload_service.get_documents('equipment_photo', id)
    links = equipment_service.get_equipment_links(id)
    repair_records = repair_service.list_repair_records(
        equipment_id=id, eager_load_assignee=True,
    )
    doc_form = DocumentUploadForm()
    photo_form = PhotoUploadForm()
    link_form = ExternalLinkForm()
    can_edit_docs = _can_edit_docs() and not eq.is_archived

    return render_template(
        'equipment/detail.html',
        equipment=eq,
        documents=documents,
        photos=photos,
        links=links,
        repair_records=repair_records,
        closed_statuses=repair_service.CLOSED_STATUSES,
        doc_form=doc_form,
        photo_form=photo_form,
        link_form=link_form,
        can_edit_docs=can_edit_docs,
    )


@equipment_bp.route('/<int:id>/edit', methods=['GET', 'POST'])
@role_required('staff')
def edit(id):
    """Equipment edit form and handler."""
    try:
        eq = equipment_service.get_equipment(id)
    except ValidationError:
        abort(404)

    if eq.is_archived:
        flash('Cannot edit archived equipment.', 'danger')
        return redirect(url_for('equipment.detail', id=id))

    form = EquipmentEditForm(obj=eq)
    areas = equipment_service.list_areas()
    form.area_id.choices = [(0, '-- Select Area --')] + [
        (a.id, a.name) for a in areas
    ]

    if form.validate_on_submit():
        if form.area_id.data == 0:
            flash('Please select an area.', 'danger')
            return render_template(
                'equipment/form.html', form=form, title='Edit Equipment',
            )
        try:
            equipment_service.update_equipment(
                equipment_id=id,
                updated_by=current_user.username,
                name=form.name.data,
                manufacturer=form.manufacturer.data,
                model=form.model.data,
                area_id=form.area_id.data,
                serial_number=form.serial_number.data or None,
                acquisition_date=form.acquisition_date.data,
                acquisition_source=form.acquisition_source.data or None,
                acquisition_cost=form.acquisition_cost.data,
                warranty_expiration=form.warranty_expiration.data,
                description=form.description.data or None,
            )
        except ValidationError as e:
            flash(str(e), 'danger')
            return render_template(
                'equipment/form.html', form=form, title='Edit Equipment',
            )

        flash('Equipment updated successfully.', 'success')
        return redirect(url_for('equipment.detail', id=id))

    return render_template(
        'equipment/form.html', form=form, title='Edit Equipment',
    )


@equipment_bp.route('/<int:id>/archive', methods=['POST'])
@role_required('staff')
def archive(id):
    """Archive an equipment record (soft delete)."""
    try:
        equipment_service.archive_equipment(
            equipment_id=id,
            archived_by=current_user.username,
        )
        flash('Equipment archived successfully.', 'success')
    except ValidationError as e:
        flash(str(e), 'danger')
    return redirect(url_for('equipment.detail', id=id))


def _get_active_equipment_or_404(id):
    """Return a non-archived equipment or raise 404."""
    try:
        eq = equipment_service.get_equipment(id)
    except ValidationError:
        abort(404)
    if eq.is_archived:
        abort(404)
    return eq


def _build_wifi_choices():
    """Build WiFi dropdown choices based on current config."""
    wifi_ssid = config_service.get_config('wifi_ssid', '')
    wifi_password = config_service.get_config('wifi_password', '')
    choices = [
        ('none', 'None'),
        ('header', '\U0001f6dc Must be on WiFi'),
    ]
    if wifi_ssid:
        choices.append(('ssid', '\U0001f6dc WiFi + SSID'))
    if wifi_ssid and wifi_password:
        choices.append(('password', '\U0001f6dc WiFi + SSID + Password'))
    return choices, {'wifi_ssid': wifi_ssid, 'wifi_password': wifi_password}


def _get_wifi_default(choices):
    """Get the configured default WiFi selection, validated against available choices."""
    default = config_service.get_config('wifi_info_default', 'none')
    choice_values = {c[0] for c in choices}
    return default if default in choice_values else 'none'


_WIFI_CLAMP_ORDER = ['password', 'ssid', 'header']


def _clamp_wifi_info(wifi_info, choices):
    """Clamp wifi_info to the best available choice (graceful degradation).

    Unknown values degrade to 'none' (safe default).
    """
    choice_values = {c[0] for c in choices}
    if wifi_info in choice_values:
        return wifi_info
    if wifi_info not in _WIFI_CLAMP_ORDER:
        return 'none'
    idx = _WIFI_CLAMP_ORDER.index(wifi_info)
    for fallback in _WIFI_CLAMP_ORDER[idx + 1:]:
        if fallback in choice_values:
            return fallback
    return 'none'


@equipment_bp.route('/<int:id>/qr', methods=['GET', 'POST'])
@login_required
def qr(id):
    """QR code generation page. Read-only — no mutation logging."""
    eq = _get_active_equipment_or_404(id)
    try:
        base_url = get_normalized_base_url(current_app.config.get('ESB_BASE_URL', ''))
    except ValueError as exc:
        flash(str(exc), 'danger')
        return redirect(url_for('equipment.detail', id=id))

    choices, wifi_config = _build_wifi_choices()
    wifi_default = _get_wifi_default(choices)

    # On POST, accept any of the four known wifi_info values for validation so
    # the TOCTOU clamp logic below (rather than WTForms) handles stale selections.
    if request.method == 'POST':
        validation_choices = [('none', 'None'), ('header', 'Header'),
                              ('ssid', 'SSID'), ('password', 'Password')]
        form = QRGenerateForm(wifi_choices=validation_choices)
    else:
        form = QRGenerateForm(wifi_choices=choices)
        form.wifi_info.data = wifi_default

    def _render_form_with_real_choices():
        form.wifi_info.choices = choices
        if form.wifi_info.data not in {v for v, _ in choices}:
            form.wifi_info.data = _clamp_wifi_info(form.wifi_info.data, choices)
        return render_template('equipment/qr.html', equipment=eq, form=form)

    if form.validate_on_submit():
        wifi_info = _clamp_wifi_info(form.wifi_info.data, choices)
        if wifi_info != form.wifi_info.data:
            flash(
                f"WiFi settings changed since you loaded this page — your download was adjusted to '{wifi_info}'.",
                'info',
            )
        preset = qr_service.QR_PRESETS_BY_KEY[form.size.data]
        try:
            png_bytes = qr_service.render_qr_png(
                eq, preset,
                include_name=form.include_name.data,
                include_url=form.include_url.data,
                base_url=base_url,
                wifi_info=wifi_info,
                wifi_ssid=wifi_config['wifi_ssid'],
                wifi_password=wifi_config['wifi_password'],
            )
        except ValueError as exc:
            flash(str(exc), 'danger')
            return _render_form_with_real_choices()
        except (OSError, RuntimeError) as exc:
            current_app.logger.error('QR render failed: %s', exc)
            flash('QR code generation failed — contact an administrator.', 'danger')
            return _render_form_with_real_choices()
        current_app.logger.info(
            'QR downloaded: user=%s equipment_id=%s preset=%s include_name=%s include_url=%s wifi_info=%s',
            current_user.username, eq.id, preset.key,
            form.include_name.data, form.include_url.data, wifi_info,
        )
        filename = f'qr-{eq.id}-{slugify_filename(eq.name)}.png'
        return send_file(
            io.BytesIO(png_bytes),
            mimetype='image/png',
            as_attachment=True,
            download_name=filename,
        )
    return _render_form_with_real_choices()


@equipment_bp.route('/<int:id>/qr/preview')
@login_required
def qr_preview(id):
    """Inline PNG preview. Query params: size, include_name, include_url, wifi_info."""
    eq = _get_active_equipment_or_404(id)
    try:
        base_url = get_normalized_base_url(current_app.config.get('ESB_BASE_URL', ''))
    except ValueError:
        abort(404)

    size_key = request.args.get('size', 'sticker_2')
    preset = qr_service.QR_PRESETS_BY_KEY.get(size_key)
    if preset is None:
        abort(400)
    include_name = request.args.get('include_name') in ('1', 'true', 'on')
    include_url = request.args.get('include_url') in ('1', 'true', 'on')

    wifi_info = request.args.get('wifi_info', 'none')
    if wifi_info not in ('none', 'header', 'ssid', 'password'):
        wifi_info = 'none'
    wifi_ssid = config_service.get_config('wifi_ssid', '')
    wifi_password = config_service.get_config('wifi_password', '')
    if wifi_info == 'password' and (not wifi_password or not wifi_ssid):
        wifi_info = 'ssid'
    if wifi_info == 'ssid' and not wifi_ssid:
        wifi_info = 'header'

    try:
        png_bytes = qr_service.render_qr_png(
            eq, preset,
            include_name=include_name,
            include_url=include_url,
            base_url=base_url,
            wifi_info=wifi_info,
            wifi_ssid=wifi_ssid,
            wifi_password=wifi_password,
        )
    except ValueError:
        abort(400)
    except (OSError, RuntimeError) as exc:
        current_app.logger.error('QR preview render failed: %s', exc)
        abort(500)
    response = send_file(io.BytesIO(png_bytes), mimetype='image/png')
    response.headers['Cache-Control'] = 'private, max-age=300'
    return response


def _can_edit_docs() -> bool:
    """Check if current user can edit equipment documentation.

    Staff always can. Technicians can when tech_doc_edit_enabled is 'true'.
    """
    if current_user.role == 'staff':
        return True
    if current_user.role == 'technician':
        return config_service.get_config('tech_doc_edit_enabled', 'false').lower() == 'true'
    return False


def _require_doc_edit():
    """Abort 403 if current user cannot edit equipment documentation."""
    if not _can_edit_docs():
        abort(403)


# --- Document upload/delete ---


@equipment_bp.route('/<int:id>/documents', methods=['POST'])
@login_required
def upload_document(id):
    """Handle document upload for an equipment item."""
    try:
        eq = equipment_service.get_equipment(id)
    except ValidationError:
        abort(404)
    _require_doc_edit()

    if eq.is_archived:
        flash('Cannot modify archived equipment.', 'danger')
        return redirect(url_for('equipment.detail', id=id))

    form = DocumentUploadForm()
    if form.validate_on_submit():
        try:
            upload_service.save_upload(
                file=form.file.data,
                parent_type='equipment_doc',
                parent_id=id,
                uploaded_by=current_user.username,
                category=form.category.data,
            )
            flash('Document uploaded successfully.', 'success')
        except ValidationError as e:
            flash(str(e), 'danger')
    else:
        for field, errors in form.errors.items():
            for error in errors:
                flash(f'{error}', 'danger')
    return redirect(url_for('equipment.detail', id=id))


@equipment_bp.route('/<int:id>/documents/<int:doc_id>/delete', methods=['POST'])
@login_required
def delete_document(id, doc_id):
    """Delete a document from an equipment item."""
    try:
        eq = equipment_service.get_equipment(id)
    except ValidationError:
        abort(404)
    _require_doc_edit()

    if eq.is_archived:
        flash('Cannot modify archived equipment.', 'danger')
        return redirect(url_for('equipment.detail', id=id))

    try:
        upload_service.delete_upload(
            doc_id, current_user.username,
            parent_type='equipment_doc', parent_id=id,
        )
        flash('Document deleted.', 'success')
    except ValidationError as e:
        flash(str(e), 'danger')
    return redirect(url_for('equipment.detail', id=id))


# --- Photo upload/delete ---


@equipment_bp.route('/<int:id>/photos', methods=['POST'])
@login_required
def upload_photo(id):
    """Handle photo upload for an equipment item."""
    try:
        eq = equipment_service.get_equipment(id)
    except ValidationError:
        abort(404)
    _require_doc_edit()

    if eq.is_archived:
        flash('Cannot modify archived equipment.', 'danger')
        return redirect(url_for('equipment.detail', id=id))

    form = PhotoUploadForm()
    if form.validate_on_submit():
        try:
            upload_service.save_upload(
                file=form.file.data,
                parent_type='equipment_photo',
                parent_id=id,
                uploaded_by=current_user.username,
            )
            flash('Photo uploaded successfully.', 'success')
        except ValidationError as e:
            flash(str(e), 'danger')
    else:
        for field, errors in form.errors.items():
            for error in errors:
                flash(f'{error}', 'danger')
    return redirect(url_for('equipment.detail', id=id))


@equipment_bp.route('/<int:id>/photos/<int:photo_id>/delete', methods=['POST'])
@login_required
def delete_photo(id, photo_id):
    """Delete a photo from an equipment item."""
    try:
        eq = equipment_service.get_equipment(id)
    except ValidationError:
        abort(404)
    _require_doc_edit()

    if eq.is_archived:
        flash('Cannot modify archived equipment.', 'danger')
        return redirect(url_for('equipment.detail', id=id))

    try:
        upload_service.delete_upload(
            photo_id, current_user.username,
            parent_type='equipment_photo', parent_id=id,
        )
        flash('Photo deleted.', 'success')
    except ValidationError as e:
        flash(str(e), 'danger')
    return redirect(url_for('equipment.detail', id=id))


# --- External link add/delete ---


@equipment_bp.route('/<int:id>/links', methods=['POST'])
@login_required
def add_link(id):
    """Add an external link to an equipment item."""
    try:
        eq = equipment_service.get_equipment(id)
    except ValidationError:
        abort(404)
    _require_doc_edit()

    if eq.is_archived:
        flash('Cannot modify archived equipment.', 'danger')
        return redirect(url_for('equipment.detail', id=id))

    form = ExternalLinkForm()
    if form.validate_on_submit():
        try:
            equipment_service.add_equipment_link(
                equipment_id=id,
                title=form.title.data,
                url=form.url.data,
                created_by=current_user.username,
            )
            flash('Link added successfully.', 'success')
        except ValidationError as e:
            flash(str(e), 'danger')
    else:
        for field, errors in form.errors.items():
            for error in errors:
                flash(f'{error}', 'danger')
    return redirect(url_for('equipment.detail', id=id))


@equipment_bp.route('/<int:id>/links/<int:link_id>/delete', methods=['POST'])
@login_required
def delete_link(id, link_id):
    """Delete an external link from an equipment item."""
    try:
        eq = equipment_service.get_equipment(id)
    except ValidationError:
        abort(404)
    _require_doc_edit()

    if eq.is_archived:
        flash('Cannot modify archived equipment.', 'danger')
        return redirect(url_for('equipment.detail', id=id))

    try:
        equipment_service.delete_equipment_link(
            link_id, current_user.username, equipment_id=id,
        )
        flash('Link deleted.', 'success')
    except ValidationError as e:
        flash(str(e), 'danger')
    return redirect(url_for('equipment.detail', id=id))


# --- File serving ---


@equipment_bp.route('/<int:id>/files/docs/<path:filename>')
@login_required
def serve_document(id, filename):
    """Serve an uploaded document file."""
    try:
        equipment_service.get_equipment(id)
    except ValidationError:
        abort(404)
    upload_path = current_app.config['UPLOAD_PATH']
    directory = os.path.join(upload_path, 'equipment', str(id), 'docs')
    return send_from_directory(directory, filename)


@equipment_bp.route('/<int:id>/files/photos/<path:filename>')
@login_required
def serve_photo(id, filename):
    """Serve an uploaded photo file."""
    try:
        equipment_service.get_equipment(id)
    except ValidationError:
        abort(404)
    upload_path = current_app.config['UPLOAD_PATH']
    directory = os.path.join(upload_path, 'equipment', str(id), 'photos')
    return send_from_directory(directory, filename)
