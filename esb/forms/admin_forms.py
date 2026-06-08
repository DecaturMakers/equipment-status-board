"""Admin forms for user management."""

from flask_wtf import FlaskForm
from wtforms import BooleanField, HiddenField, PasswordField, SelectField, StringField, SubmitField
from wtforms.validators import DataRequired, Email, Length, Optional


class UserCreateForm(FlaskForm):
    """Form for creating a new user account."""

    username = StringField('Username *', validators=[DataRequired(), Length(max=80)])
    email = StringField('Email *', validators=[DataRequired(), Email(), Length(max=255)])
    slack_handle = StringField('Slack Handle')
    role = SelectField(
        'Role *',
        choices=[('technician', 'Technician'), ('staff', 'Staff')],
        validators=[DataRequired()],
    )
    submit = SubmitField('Create User')


class RoleChangeForm(FlaskForm):
    """Inline form for changing a user's role on the user list."""

    user_id = HiddenField('user_id', validators=[DataRequired()])
    role = SelectField(
        'Role',
        choices=[('technician', 'Technician'), ('staff', 'Staff')],
        validators=[DataRequired()],
    )


class AppConfigForm(FlaskForm):
    """Form for application configuration settings."""

    tech_doc_edit_enabled = BooleanField('Allow Technicians to edit equipment documentation')
    notify_new_report = BooleanField('New problem report submitted')
    notify_resolved = BooleanField('Repair record resolved or closed')
    notify_severity_changed = BooleanField('Severity level changed')
    notify_status_changed = BooleanField('Repair status changed (open transitions)')
    notify_assignee_changed = BooleanField('Repair assignee changed')
    notify_eta_updated = BooleanField('ETA set or updated')
    wifi_ssid = StringField('WiFi Network Name (SSID)', validators=[Optional(), Length(max=100)])
    wifi_password = PasswordField('WiFi Password', validators=[Optional(), Length(max=100)])
    wifi_password_clear = BooleanField('Clear stored WiFi password')
    wifi_info_default = SelectField(
        'Default WiFi Info on QR Labels',
        choices=[
            ('none', 'None'),
            ('header', 'WiFi header only'),
            ('ssid', 'WiFi header + SSID'),
            ('password', 'WiFi header + SSID + Password'),
        ],
        default='none',
    )
    submit = SubmitField('Save Configuration')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Robustness: a missing wifi_info_default in POST data should be treated
        # as 'none', not None (which would fail SelectField validation and block
        # *all* config updates in that submission).
        if self.wifi_info_default.data is None:
            self.wifi_info_default.data = 'none'


class EditSlackHandleForm(FlaskForm):
    """Inline form for editing a user's Slack handle."""

    slack_handle = StringField(
        'Slack Handle',
        filters=[lambda value: value.strip() if value is not None else value],
        validators=[Length(max=80)],
    )
    submit = SubmitField('Update')


class ResetPasswordForm(FlaskForm):
    """Minimal form for resetting a user's password (CSRF only)."""
