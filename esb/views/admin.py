"""Admin routes (user management, area management, app config)."""

from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from flask_login import current_user

from esb.forms.admin_forms import (
    AppConfigForm,
    EditSlackHandleForm,
    ResetPasswordForm,
    RoleChangeForm,
    UserCreateForm,
)
from esb.forms.equipment_forms import AreaCreateForm, AreaEditForm
from esb.services import equipment_service, user_service
from esb.utils.decorators import role_required
from esb.utils.exceptions import ValidationError

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')


@admin_bp.route('/')
@role_required('staff')
def index():
    """Admin dashboard -- redirects to user list."""
    return redirect(url_for('admin.list_users'))


@admin_bp.route('/users')
@role_required('staff')
def list_users():
    """User management table listing all users."""
    users = user_service.list_users()
    role_form = RoleChangeForm()
    reset_form = ResetPasswordForm()
    slack_handle_form = EditSlackHandleForm()
    return render_template(
        'admin/users.html',
        users=users,
        role_form=role_form,
        reset_form=reset_form,
        slack_handle_form=slack_handle_form,
    )


@admin_bp.route('/users/new', methods=['GET', 'POST'])
@role_required('staff')
def create_user():
    """User creation form and handler."""
    form = UserCreateForm()
    if form.validate_on_submit():
        try:
            user, temp_password, slack_delivered = user_service.create_user(
                username=form.username.data,
                email=form.email.data,
                role=form.role.data,
                slack_handle=form.slack_handle.data or None,
                created_by=current_user.username,
            )
        except ValidationError as e:
            flash(str(e), 'danger')
            return render_template('admin/user_create.html', form=form)

        if slack_delivered:
            flash('User created. Temporary password sent via Slack DM.', 'success')
            return redirect(url_for('admin.list_users'))

        # Store temp password in session for one-time display
        session['_temp_password'] = temp_password
        return redirect(url_for('admin.user_created', id=user.id))

    return render_template('admin/user_create.html', form=form)


@admin_bp.route('/users/<int:id>/created')
@role_required('staff')
def user_created(id):
    """One-time temp password display page."""
    temp_password = session.pop('_temp_password', None)
    if temp_password is None:
        flash('Temporary password is no longer available.', 'warning')
        return redirect(url_for('admin.list_users'))

    user = user_service.get_user(id)
    return render_template(
        'admin/user_created.html',
        user=user,
        temp_password=temp_password,
    )


@admin_bp.route('/users/<int:id>/role', methods=['POST'])
@role_required('staff')
def change_role(id):
    """Change a user's role."""
    form = RoleChangeForm()
    if form.validate_on_submit():
        try:
            user_service.change_role(
                user_id=id,
                new_role=form.role.data,
                changed_by=current_user.username,
            )
            flash('User role updated successfully.', 'success')
        except ValidationError as e:
            flash(str(e), 'danger')
    else:
        flash('Invalid role change request.', 'danger')
    return redirect(url_for('admin.list_users'))


@admin_bp.route('/users/<int:id>/reset-password', methods=['POST'])
@role_required('staff')
def reset_password(id):
    """Reset a user's password."""
    if id == current_user.id:
        flash('Use Change Password to change your own password.', 'danger')
        return redirect(url_for('admin.list_users'))

    form = ResetPasswordForm()
    if form.validate_on_submit():
        try:
            user, temp_password, slack_delivered = user_service.reset_password(
                user_id=id,
                reset_by=current_user.username,
            )
        except ValidationError as e:
            flash(str(e), 'danger')
            return redirect(url_for('admin.list_users'))

        if slack_delivered:
            flash('Password reset. New temporary password sent via Slack DM.', 'success')
            return redirect(url_for('admin.list_users'))

        session['_temp_password'] = temp_password
        return redirect(url_for('admin.user_created', id=user.id))

    flash('Invalid request.', 'danger')
    return redirect(url_for('admin.list_users'))


@admin_bp.route('/users/<int:id>/slack-handle', methods=['POST'])
@role_required('staff')
def edit_slack_handle(id):
    """Update a user's Slack handle."""
    form = EditSlackHandleForm()
    if form.validate_on_submit():
        try:
            user_service.update_slack_handle(
                user_id=id,
                slack_handle=form.slack_handle.data or None,
                updated_by=current_user.username,
            )
            flash("User's Slack handle updated successfully.", 'success')
        except ValidationError as e:
            flash(str(e), 'danger')
    else:
        flash('Invalid request.', 'danger')
    return redirect(url_for('admin.list_users'))


# --- Area Management Routes ---


@admin_bp.route('/areas')
@role_required('staff')
def list_areas():
    """Area management table listing all active areas."""
    areas = equipment_service.list_areas()
    return render_template('admin/areas.html', areas=areas)


@admin_bp.route('/areas/new', methods=['GET', 'POST'])
@role_required('staff')
def create_area():
    """Area creation form and handler."""
    form = AreaCreateForm()
    if form.validate_on_submit():
        sort_order_value = form.sort_order.data if form.sort_order.data is not None else 0
        try:
            equipment_service.create_area(
                name=form.name.data,
                slack_channel=form.slack_channel.data,
                created_by=current_user.username,
                sort_order=sort_order_value,
            )
        except ValidationError as e:
            flash(str(e), 'danger')
            return render_template('admin/area_form.html', form=form, title='Add Area')

        flash('Area created successfully.', 'success')
        return redirect(url_for('admin.list_areas'))

    return render_template('admin/area_form.html', form=form, title='Add Area')


@admin_bp.route('/areas/<int:id>/edit', methods=['GET', 'POST'])
@role_required('staff')
def edit_area(id):
    """Area edit form and handler."""
    try:
        area = equipment_service.get_area(id)
    except ValidationError as e:
        flash(str(e), 'danger')
        return redirect(url_for('admin.list_areas'))

    form = AreaEditForm(obj=area)
    if form.validate_on_submit():
        sort_order_value = form.sort_order.data if form.sort_order.data is not None else 0
        try:
            equipment_service.update_area(
                area_id=id,
                name=form.name.data,
                slack_channel=form.slack_channel.data,
                updated_by=current_user.username,
                sort_order=sort_order_value,
            )
        except ValidationError as e:
            flash(str(e), 'danger')
            return render_template(
                'admin/area_form.html', form=form, title='Edit Area',
            )

        flash('Area updated successfully.', 'success')
        return redirect(url_for('admin.list_areas'))

    return render_template('admin/area_form.html', form=form, title='Edit Area')


@admin_bp.route('/areas/<int:id>/archive', methods=['POST'])
@role_required('staff')
def archive_area(id):
    """Archive an area (soft delete)."""
    try:
        equipment_service.archive_area(
            area_id=id,
            archived_by=current_user.username,
        )
        flash('Area archived successfully.', 'success')
    except ValidationError as e:
        flash(str(e), 'danger')
    return redirect(url_for('admin.list_areas'))


# --- App Configuration Routes ---


@admin_bp.route('/config', methods=['GET', 'POST'])
@role_required('staff')
def app_config():
    """App configuration page."""
    from esb.services import config_service

    form = AppConfigForm()
    if request.method == 'GET':
        form.tech_doc_edit_enabled.data = (
            config_service.get_config('tech_doc_edit_enabled', 'false') == 'true'
        )
        form.notify_new_report.data = (
            config_service.get_config('notify_new_report', 'true') == 'true'
        )
        form.notify_resolved.data = (
            config_service.get_config('notify_resolved', 'true') == 'true'
        )
        form.notify_severity_changed.data = (
            config_service.get_config('notify_severity_changed', 'true') == 'true'
        )
        form.notify_status_changed.data = (
            config_service.get_config('notify_status_changed', 'true') == 'true'
        )
        form.notify_assignee_changed.data = (
            config_service.get_config('notify_assignee_changed', 'true') == 'true'
        )
        form.notify_eta_updated.data = (
            config_service.get_config('notify_eta_updated', 'true') == 'true'
        )
        form.wifi_ssid.data = config_service.get_config('wifi_ssid', '')
        form.wifi_info_default.data = config_service.get_config('wifi_info_default', 'none')

    if form.validate_on_submit():
        config_keys = [
            ('tech_doc_edit_enabled', 'false'),
            ('notify_new_report', 'true'),
            ('notify_resolved', 'true'),
            ('notify_severity_changed', 'true'),
            ('notify_status_changed', 'true'),
            ('notify_assignee_changed', 'true'),
            ('notify_eta_updated', 'true'),
        ]
        for key, default in config_keys:
            new_value = 'true' if getattr(form, key).data else 'false'
            if config_service.get_config(key, default) != new_value:
                config_service.set_config(key, new_value, changed_by=current_user.username)
        string_config_keys = [
            ('wifi_ssid', ''),
            ('wifi_info_default', 'none'),
        ]
        for key, default in string_config_keys:
            # Persist user input verbatim: SSIDs may legitimately contain leading/
            # trailing spaces, and wifi_info_default is a SelectField with fixed
            # whitespace-free choices.
            new_value = getattr(form, key).data
            if new_value is None:
                new_value = default
            if config_service.get_config(key, default) != new_value:
                config_service.set_config(key, new_value, changed_by=current_user.username)

        # wifi_password: blank submission = unchanged; checkbox = explicit clear; non-blank = set.
        # Preserve the password verbatim — spaces are valid password characters.
        submitted_pw = form.wifi_password.data or ''
        clear_pw = form.wifi_password_clear.data
        current_pw = config_service.get_config('wifi_password', '')
        if clear_pw and current_pw:
            config_service.set_config(
                'wifi_password', '', changed_by=current_user.username,
                log_old_override='***', log_new_override='',
            )
        elif submitted_pw and submitted_pw != current_pw:
            config_service.set_config(
                'wifi_password', submitted_pw, changed_by=current_user.username,
                log_old_override=('***' if current_pw else ''),
                log_new_override='***',
            )
        flash('Configuration updated successfully.', 'success')
        return redirect(url_for('admin.app_config'))

    return render_template('admin/config.html', form=form)
