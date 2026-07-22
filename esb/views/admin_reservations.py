"""Administrative reservation routes and form workflows."""

from datetime import datetime, timedelta

from flask import current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from esb.forms.reservation_forms import (
    AdminReservationCancelConfirmationForm,
    AdminReservationCancelRequestForm,
    AdminReservationConfirmationForm,
    AdminReservationCreateForm,
)
from esb.models.reservation import RESERVATION_STATUS_CANCELED, RESERVATION_TYPE_MEMBER
from esb.services import equipment_service, notification_service, reservation_read_service, reservation_service, user_service
from esb.utils.decorators import role_required
from esb.utils.exceptions import ValidationError
from esb.utils.timezones import MAKERSPACE_TIMEZONE, local_datetime_to_utc, utc_naive_to_local


def register_admin_reservation_routes(admin_bp):
    """Register reservation views on the existing admin blueprint namespace."""
    admin_bp.add_url_rule("/reservations", endpoint="list_reservations", view_func=list_reservations)
    admin_bp.add_url_rule(
        "/reservations/new",
        endpoint="create_reservation",
        view_func=create_reservation,
        methods=["GET", "POST"],
    )
    admin_bp.add_url_rule(
        "/reservations/<int:id>/edit",
        endpoint="edit_reservation",
        view_func=edit_reservation,
        methods=["GET", "POST"],
    )
    admin_bp.add_url_rule(
        "/reservations/<int:id>/cancel",
        endpoint="cancel_reservation",
        view_func=cancel_reservation,
        methods=["POST"],
    )


@role_required("technician")
def list_reservations():
    """Admin reservation calendar and list view."""
    filters, warnings = reservation_read_service.parse_admin_reservation_filters(request.args)
    for warning in warnings:
        flash(warning, "warning")
    page = request.args.get("page", 1, type=int)
    if page < 1:
        flash("Ignoring invalid reservation page.", "warning")
        page = 1
    calendar_data = reservation_read_service.get_admin_calendar_data(filters=filters, page=page)
    options = reservation_read_service.get_admin_reservation_filter_options()
    query_params = filters.query_params()

    def reservation_url(**overrides):
        params = dict(query_params)
        params.update(overrides)
        return url_for("admin.list_reservations", **params)

    return render_template(
        "admin/reservations.html",
        calendar_data=calendar_data,
        filter_options=options,
        filters=filters,
        calendar_prev_url=reservation_url(calendar_date=(filters.calendar_date - timedelta(days=1)).isoformat()),
        calendar_today_url=reservation_url(calendar_date=None),
        calendar_next_url=reservation_url(calendar_date=(filters.calendar_date + timedelta(days=1)).isoformat()),
        previous_page_url=reservation_url(page=calendar_data["pagination"]["page"] - 1),
        next_page_url=reservation_url(page=calendar_data["pagination"]["page"] + 1),
        cancel_request_form=AdminReservationCancelRequestForm(),
    )


@role_required("technician")
def create_reservation():
    """Create an admin member reservation or administrative hold."""
    if request.method == "POST" and request.form.get("confirmation_token"):
        return _confirm_admin_reservation()
    return _admin_reservation_form_response()


@role_required("technician")
def edit_reservation(id):
    """Replace an active reservation while preserving its cancellation history."""
    if request.method == "POST" and request.form.get("confirmation_token"):
        return _confirm_admin_reservation(replacement_reservation_id=id)
    try:
        original = reservation_read_service.get_admin_reservation(id)
    except ValidationError:
        flash("Reservation not found.", "danger")
        return redirect(url_for("admin.list_reservations"))
    if original.status == RESERVATION_STATUS_CANCELED:
        flash("Canceled reservations cannot be edited.", "warning")
        return redirect(url_for("admin.list_reservations"))
    return _admin_reservation_form_response(original)


@role_required("technician")
def cancel_reservation(id):
    """Show and process a signed confirmation before canceling a reservation."""
    if request.form.get("confirmation_token"):
        return _confirm_admin_reservation_cancellation(id)

    form = AdminReservationCancelRequestForm()
    if not form.validate_on_submit():
        flash("Invalid cancellation request.", "danger")
        return redirect(url_for("admin.list_reservations"))
    try:
        reservation = reservation_read_service.get_admin_reservation(id)
    except ValidationError:
        flash("Reservation not found.", "danger")
        return redirect(url_for("admin.list_reservations"))
    if reservation.status == RESERVATION_STATUS_CANCELED:
        flash("Reservation is already canceled.", "warning")
        return redirect(url_for("admin.list_reservations"))

    confirmation_form = AdminReservationCancelConfirmationForm()
    confirmation_form.confirmation_token.data = _cancellation_confirmation_serializer().dumps(
        {"actor_user_id": current_user.id, "reservation_id": reservation.id}
    )
    return render_template(
        "admin/reservation_cancel_confirm.html",
        form=confirmation_form,
        reservation=reservation,
    )


def _set_admin_reservation_choices(form):
    options = reservation_read_service.get_admin_reservation_creation_options()
    form.equipment_id.choices = [(item.id, item.name) for item in options["equipment"]]
    form.owner_user_id.choices = [(0, "-- Select member --")] + [
        (user.id, user.display_name) for user in options["users"]
    ]


def _admin_reservation_command_from_form(form, starts_at_utc):
    reservation_type = form.reservation_type.data
    return {
        "equipment_id": form.equipment_id.data,
        "owner_user_id": form.owner_user_id.data if reservation_type == RESERVATION_TYPE_MEMBER else None,
        "starts_at_utc": starts_at_utc,
        "duration_minutes": form.duration_minutes.data,
        "notes": form.notes.data.strip(),
        "reservation_type": reservation_type,
    }


def _admin_reservation_command_from_payload(payload):
    owner_user_id = payload["owner_user_id"]
    return {
        "equipment_id": int(payload["equipment_id"]),
        "owner_user_id": int(owner_user_id) if owner_user_id is not None else None,
        "starts_at_utc": datetime.fromisoformat(payload["starts_at_utc"]),
        "duration_minutes": int(payload["duration_minutes"]),
        "notes": str(payload["notes"]),
        "reservation_type": str(payload["reservation_type"]),
    }


def _admin_reservation_command_payload(command):
    return {**command, "starts_at_utc": command["starts_at_utc"].isoformat()}


def _admin_reservation_form_response(original=None):
    form = AdminReservationCreateForm()
    _set_admin_reservation_choices(form)
    if request.method == "GET":
        _populate_admin_reservation_form(form, original)

    if form.validate_on_submit():
        try:
            starts_at_utc = local_datetime_to_utc(form.start_date.data, form.start_time.data)
        except ValidationError as error:
            form.start_time.errors.append(str(error))
        else:
            command = _admin_reservation_command_from_form(form, starts_at_utc)
            response = _review_or_persist_admin_reservation(command, form, original)
            if response is not None:
                return response

    title = "Edit Reservation" if original is not None else "New Reservation"
    return render_template("admin/reservation_form.html", form=form, title=title)


def _populate_admin_reservation_form(form, original=None):
    if original is None:
        starts_at = datetime.now(MAKERSPACE_TIMEZONE).replace(second=0, microsecond=0) + timedelta(hours=3)
        starts_at += timedelta(minutes=(-starts_at.minute) % 30)
        form.start_date.data = starts_at.date()
        form.start_time.data = starts_at.time()
        return

    starts_at = utc_naive_to_local(original.starts_at)
    form.reservation_type.data = original.reservation_type
    form.equipment_id.data = original.equipment_id
    form.owner_user_id.data = original.user_id or 0
    form.start_date.data = starts_at.date()
    form.start_time.data = starts_at.time()
    form.duration_minutes.data = int((original.ends_at - original.starts_at).total_seconds() // 60)
    form.notes.data = original.notes


def _review_or_persist_admin_reservation(command, form, original=None):
    replacement_id = original.id if original is not None else None
    try:
        preview = reservation_service.preview_admin_reservation(
            **command,
            actor_user_id=current_user.id,
            exclude_reservation_id=replacement_id,
        )
    except ValidationError as error:
        form.notes.errors.append(str(error))
        return None
    if preview.hard_violations:
        form.notes.errors.extend(item.message for item in preview.hard_violations)
        return None
    if preview.overridable_violations:
        return _render_admin_reservation_confirmation(
            command=command,
            violation_codes=[item.code for item in preview.overridable_violations],
            violations=preview.overridable_violations,
            replacement_reservation_id=replacement_id,
        )
    try:
        reservation, message = _persist_admin_reservation(command, replacement_id)
    except ValidationError as error:
        form.notes.errors.append(str(error))
        return None
    flash(message, "success")
    return redirect(url_for("admin.list_reservations"))


def _reservation_confirmation_serializer():
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt="admin-reservation-confirmation")


def _render_admin_reservation_confirmation(*, command, violation_codes, violations, replacement_reservation_id=None):
    equipment = equipment_service.get_equipment(command["equipment_id"])
    member_label = "No member (admin hold)"
    if command["owner_user_id"] is not None:
        member_label = user_service.get_user(command["owner_user_id"]).display_name
    payload = _admin_reservation_command_payload(command) | {
        "actor_user_id": current_user.id,
        "violation_codes": sorted(violation_codes),
        "replacement_reservation_id": replacement_reservation_id,
    }
    form = AdminReservationConfirmationForm()
    form.confirmation_token.data = _reservation_confirmation_serializer().dumps(payload)
    local_start = command["starts_at_utc"].astimezone(MAKERSPACE_TIMEZONE)
    return render_template(
        "admin/reservation_confirm.html",
        form=form,
        values=command,
        violations=violations,
        equipment_label=equipment.name,
        member_label=member_label,
        local_start_label=local_start.strftime("%Y-%m-%d %I:%M %p %Z"),
        cancel_url=_admin_reservation_form_url(replacement_reservation_id),
    )


def _admin_reservation_form_url(replacement_reservation_id=None):
    if replacement_reservation_id is not None:
        return url_for("admin.edit_reservation", id=replacement_reservation_id)
    return url_for("admin.create_reservation")


def _confirm_admin_reservation(replacement_reservation_id=None):
    form = AdminReservationConfirmationForm()
    if not form.validate_on_submit():
        flash("Invalid reservation confirmation.", "danger")
        return redirect(_admin_reservation_form_url(replacement_reservation_id))
    try:
        payload = _reservation_confirmation_serializer().loads(form.confirmation_token.data, max_age=600)
        if payload["actor_user_id"] != current_user.id:
            raise BadSignature("Confirmation belongs to another user")
        if payload.get("replacement_reservation_id") != replacement_reservation_id:
            raise BadSignature("Confirmation does not match this reservation")
        command = _admin_reservation_command_from_payload(payload)
        token_codes = set(payload["violation_codes"])
    except (BadSignature, SignatureExpired, KeyError, TypeError, ValueError):
        flash("Reservation confirmation has expired or is invalid. Please review it again.", "danger")
        return redirect(_admin_reservation_form_url(replacement_reservation_id))

    try:
        preview = reservation_service.preview_admin_reservation(
            **command,
            actor_user_id=current_user.id,
            exclude_reservation_id=replacement_reservation_id,
        )
    except ValidationError as error:
        flash(str(error), "danger")
        return redirect(_admin_reservation_form_url(replacement_reservation_id))
    if preview.hard_violations:
        flash("; ".join(item.message for item in preview.hard_violations), "danger")
        return redirect(_admin_reservation_form_url(replacement_reservation_id))

    current_codes = {item.code for item in preview.overridable_violations}
    if current_codes != token_codes:
        flash("Reservation warnings changed. Review the updated warnings before confirming.", "warning")
        return _render_admin_reservation_confirmation(
            command=command,
            violation_codes=current_codes,
            violations=preview.overridable_violations,
            replacement_reservation_id=replacement_reservation_id,
        )

    try:
        reservation, message = _persist_admin_reservation(
            command,
            replacement_reservation_id,
            overridden_policy_codes=sorted(token_codes),
        )
    except ValidationError as error:
        flash(str(error), "danger")
        return redirect(_admin_reservation_form_url(replacement_reservation_id))
    flash(message, "success")
    return redirect(url_for("admin.list_reservations"))


def _persist_admin_reservation(command, replacement_reservation_id=None, overridden_policy_codes=None):
    """Persist create/replace commands and queue their post-commit notifications."""
    if replacement_reservation_id is None:
        reservation = reservation_service.create_admin_reservation(
            **command,
            actor_user_id=current_user.id,
            overridden_policy_codes=overridden_policy_codes,
        )
        _queue_reservation_notification(reservation, "reservation_created")
        return reservation, "Reservation created successfully."

    reservation = reservation_service.replace_admin_reservation(
        reservation_id=replacement_reservation_id,
        **command,
        actor_user_id=current_user.id,
        overridden_policy_codes=overridden_policy_codes,
    )
    _queue_replacement_notifications(reservation)
    return reservation, "Reservation updated successfully."


def _cancellation_confirmation_serializer():
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt="admin-reservation-cancellation")


def _confirm_admin_reservation_cancellation(reservation_id):
    form = AdminReservationCancelConfirmationForm()
    if not form.validate_on_submit():
        flash("Invalid cancellation confirmation.", "danger")
        return redirect(url_for("admin.list_reservations"))
    try:
        payload = _cancellation_confirmation_serializer().loads(form.confirmation_token.data, max_age=600)
        if payload["actor_user_id"] != current_user.id or int(payload["reservation_id"]) != reservation_id:
            raise BadSignature("Confirmation does not match this reservation")
    except (BadSignature, SignatureExpired, KeyError, TypeError, ValueError):
        flash("Cancellation confirmation has expired or is invalid.", "danger")
        return redirect(url_for("admin.list_reservations"))
    try:
        reservation = reservation_service.cancel_reservation(reservation_id, current_user.id)
    except ValidationError as error:
        flash(str(error), "warning")
    else:
        _queue_reservation_notification(reservation, "reservation_canceled")
        flash("Reservation canceled successfully.", "success")
    return redirect(url_for("admin.list_reservations"))


def _queue_reservation_notification(reservation, event_type):
    warning = notification_service.queue_member_reservation_notification(reservation, event_type)
    if warning:
        flash(warning, "warning")


def _queue_replacement_notifications(replacement):
    original = reservation_read_service.get_admin_reservation(replacement.replaces_reservation_id)
    if original.user_id != replacement.user_id:
        _queue_reservation_notification(original, "reservation_canceled")
    _queue_reservation_notification(replacement, "reservation_updated")
