"""Public routes (QR pages, kiosk, status dashboard, problem report).

The status dashboard and kiosk are publicly accessible (no login required).
"""

import os
import posixpath
from collections import OrderedDict

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, send_from_directory, url_for

from esb.models.document import DOCUMENT_CATEGORIES
from esb.utils.exceptions import AreaNotFound, ValidationError

public_bp = Blueprint('public', __name__, url_prefix='/public')

CATEGORY_DISPLAY_NAMES = dict(DOCUMENT_CATEGORIES)


@public_bp.route('/')
def status_dashboard():
    """Status dashboard showing all equipment status by area."""
    if request.args.get('kiosk') == 'true':
        return redirect(url_for('public.kiosk'))
    from esb.services import status_service

    areas = status_service.get_area_status_dashboard()
    return render_template('public/status_dashboard.html', areas=areas)


@public_bp.route('/kiosk')
def kiosk():
    """Kiosk display -- full-screen equipment status for wall-mounted displays."""
    from esb.services import status_service

    areas = status_service.get_area_status_dashboard()
    return render_template('public/kiosk.html', areas=areas)


@public_bp.route('/kiosk/<int:area_id>')
def kiosk_area(area_id):
    """Per-area kiosk display -- full-screen equipment status for one area."""
    from esb.services import status_service

    try:
        area_data = status_service.get_single_area_status_dashboard(area_id)
    except AreaNotFound:  # also catches AreaArchived (subclass)
        abort(404)

    return render_template(
        'public/kiosk.html',
        areas=[area_data],
        area_name=area_data['area'].name,
    )


def _build_equipment_page_context(equipment_id):
    """Build shared context for equipment page rendering.

    Returns a 3-tuple ``(status, open_repairs, eta)`` where ``eta`` is
    ``status['eta']``, exposed as a separate slot so the QR template can
    reference it without dotted access. ETA follows the same
    "highest-severity record's ETA" semantics as the dashboards, kiosk,
    static page, and Slack bot -- driven by ``compute_equipment_status()``.
    ``status['eta']`` (and the third tuple slot) is ``None`` when the
    highest-severity open record has no ETA, even if a lower-severity
    record does.
    """
    from esb.services import repair_service, status_service
    from esb.services.repair_service import CLOSED_STATUSES

    status = status_service.compute_equipment_status(equipment_id)

    open_repairs = [
        r for r in repair_service.list_repair_records(equipment_id=equipment_id)
        if r.status not in CLOSED_STATUSES
    ]

    return status, open_repairs, status['eta']


@public_bp.route('/equipment/<int:id>')
def equipment_page(id):
    """QR code equipment page -- public status, issues, and documentation link."""
    from esb.forms.repair_forms import ProblemReportForm
    from esb.services import equipment_service

    try:
        equipment = equipment_service.get_equipment(id)
    except ValidationError:
        abort(404)

    if equipment.is_archived:
        abort(404)

    status, open_repairs, eta = _build_equipment_page_context(id)
    form = ProblemReportForm()

    return render_template(
        'public/equipment_page.html',
        equipment=equipment,
        status=status,
        open_repairs=open_repairs,
        eta=eta,
        form=form,
    )


@public_bp.route('/equipment/<int:id>/report', methods=['POST'])
def report_problem(id):
    """Handle problem report form submission -- public, no auth required."""
    from esb.forms.repair_forms import ProblemReportForm
    from esb.services import equipment_service, repair_service, upload_service

    form = ProblemReportForm()

    # Load equipment context (needed for re-rendering on validation failure)
    try:
        equipment = equipment_service.get_equipment(id)
    except ValidationError:
        abort(404)
    if equipment.is_archived:
        abort(404)

    if form.validate_on_submit():
        try:
            record = repair_service.create_repair_record(
                equipment_id=id,
                description=form.description.data,
                created_by=form.reporter_name.data,
                severity=form.severity.data,
                reporter_name=form.reporter_name.data,
                reporter_email=form.reporter_email.data or None,
                has_safety_risk=form.has_safety_risk.data,
                is_consumable=form.is_consumable.data,
                author_id=None,
            )

            # Handle optional photo upload
            if form.photo.data and hasattr(form.photo.data, 'filename') and form.photo.data.filename:
                try:
                    upload_service.save_upload(
                        file=form.photo.data,
                        parent_type='repair_photo',
                        parent_id=record.id,
                        uploaded_by=form.reporter_name.data,
                    )
                except ValidationError as e:
                    flash(f'Report submitted but photo upload failed: {e}', 'warning')

            return redirect(url_for('public.report_confirmation', id=id, record_id=record.id))

        except ValidationError as e:
            flash(str(e), 'danger')

    # Validation failed or service error -- re-render equipment page with form errors
    status, open_repairs, eta = _build_equipment_page_context(id)

    return render_template(
        'public/equipment_page.html',
        equipment=equipment,
        status=status,
        open_repairs=open_repairs,
        eta=eta,
        form=form,
    )


@public_bp.route('/equipment/<int:id>/report-confirmation')
def report_confirmation(id):
    """Display confirmation after successful problem report submission."""
    from esb.services import equipment_service, repair_service

    try:
        equipment = equipment_service.get_equipment(id)
    except ValidationError:
        abort(404)
    if equipment.is_archived:
        abort(404)

    record = None
    record_id = request.args.get('record_id', type=int)
    if record_id:
        try:
            record = repair_service.get_repair_record(record_id)
        except ValidationError:
            pass

    return render_template(
        'public/report_confirmation.html',
        equipment=equipment,
        record=record,
    )


@public_bp.route('/equipment/<int:id>/info')
def equipment_info(id):
    """Equipment documentation page -- manuals, photos, and links."""
    from esb.services import equipment_service, upload_service

    try:
        equipment = equipment_service.get_equipment(id)
    except ValidationError:
        abort(404)

    if equipment.is_archived:
        abort(404)

    documents = upload_service.get_documents('equipment_doc', id)
    photos = upload_service.get_documents('equipment_photo', id)
    links = equipment_service.get_equipment_links(id)

    documents_by_category = OrderedDict()
    for doc in documents:
        cat_display = CATEGORY_DISPLAY_NAMES.get(doc.category, doc.category or 'Other')
        documents_by_category.setdefault(cat_display, []).append(doc)

    return render_template(
        'public/equipment_info.html',
        equipment=equipment,
        documents=documents,
        photos=photos,
        links=links,
        documents_by_category=documents_by_category,
    )


@public_bp.route('/uploads/<path:filepath>')
def serve_upload(filepath):
    """Serve uploaded equipment files (documents, photos) publicly.

    Only serves files under equipment/ subdirectories to prevent
    unauthorized access to repair photos and other upload types.
    """
    if '..' in filepath or not filepath.startswith('equipment/'):
        abort(404)
    upload_path = current_app.config['UPLOAD_PATH']
    # Use posixpath (not os.path) to split the URL-sourced filepath, so
    # platform-dependent separators can't trick os.path.join into dropping
    # the upload_path prefix.
    directory = os.path.join(upload_path, posixpath.dirname(filepath))
    filename = posixpath.basename(filepath)
    return send_from_directory(directory, filename)
