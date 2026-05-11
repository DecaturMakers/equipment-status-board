"""Repair record forms."""

from flask_wtf import FlaskForm
from flask_wtf.file import FileAllowed, FileField, FileRequired
from wtforms import BooleanField, DateField, SelectField, StringField, SubmitField, TextAreaField
from wtforms.validators import DataRequired, Email, InputRequired, Length, Optional

from esb.models.repair_record import REPAIR_SEVERITIES


class RepairRecordCreateForm(FlaskForm):
    """Form for creating a new repair record."""

    equipment_id = SelectField('Equipment *', coerce=int)
    description = TextAreaField(
        'Description *', validators=[DataRequired(), Length(max=5000)],
    )
    severity = SelectField(
        'Severity',
        choices=[('', '-- Select Severity --')] + [(s, s) for s in REPAIR_SEVERITIES],
        validators=[Optional()],
    )
    assignee_id = SelectField('Assignee', coerce=int, validators=[Optional()])
    has_safety_risk = BooleanField('Safety Risk')
    is_consumable = BooleanField('Consumable Issue')
    submit = SubmitField('Create Repair Record')


class RepairRecordUpdateForm(FlaskForm):
    """Form for updating a repair record."""

    status = SelectField('Status *', validators=[DataRequired()])
    severity = SelectField(
        'Severity',
        choices=[('', '-- No Severity --')] + [(s, s) for s in REPAIR_SEVERITIES],
        validators=[Optional()],
    )
    assignee_id = SelectField('Assignee', coerce=int, validators=[Optional()])
    eta = DateField('ETA', validators=[Optional()])
    specialist_description = TextAreaField(
        'Specialist Description',
        validators=[Optional(), Length(max=5000)],
    )
    note = TextAreaField('Add Note', validators=[Optional(), Length(max=5000)])
    submit = SubmitField('Save Changes')


class RepairNoteForm(FlaskForm):
    """Form for adding a note to a repair record."""

    note = TextAreaField('Note', validators=[DataRequired(), Length(max=5000)])
    submit = SubmitField('Add Note')


class ProblemReportForm(FlaskForm):
    """Public problem report form -- no authentication required."""

    reporter_name = StringField('Your Name', validators=[
        DataRequired(message='Name is required'),
        Length(max=200),
    ])
    description = TextAreaField('Description', validators=[
        DataRequired(message='Description is required'),
        Length(max=5000),
    ])
    severity = SelectField('Severity', choices=[
        ('Not Sure', 'Not Sure'),
        ('Degraded', 'Degraded'),
        ('Down', 'Down'),
    ], default='Not Sure')
    has_safety_risk = BooleanField('This is a safety risk')
    is_consumable = BooleanField('This is a consumable item (e.g., filament, sandpaper)')
    reporter_email = StringField('Email (optional)', validators=[
        Optional(),
        Email(message='Please enter a valid email address'),
        Length(max=255),
    ])
    photo = FileField('Photo (optional)')
    submit = SubmitField('Submit Report')


class RepairPhotoUploadForm(FlaskForm):
    """Form for uploading a diagnostic photo/video to a repair record."""

    file = FileField('Photo/Video', validators=[
        FileRequired('Please select a file to upload.'),
        FileAllowed(
            ['jpg', 'jpeg', 'png', 'gif', 'webp', 'mp4', 'mov', 'avi', 'webm'],
            'Only image and video files are allowed.',
        ),
    ])
    submit = SubmitField('Upload Photo')


class RepairClaimForm(FlaskForm):
    """Form for claim quick action -- CSRF only, no inputs."""

    # No fields: CSRF is auto-included by FlaskForm; submit button is
    # hard-coded in the template, so no SubmitField is needed.
    pass


class RepairResolveForm(FlaskForm):
    """Form for resolve quick action -- requires a note.

    Uses InputRequired (not DataRequired) so whitespace-only input passes
    the form layer and the service-layer resolve_repair_record helper
    catches it with the canonical 'Resolution note is required' message.
    DataRequired would strip whitespace and reject at the form layer,
    splitting the empty-note rejection across two layers with inconsistent
    messages.
    """

    note = TextAreaField(
        'Resolution Note',
        validators=[InputRequired(), Length(max=5000)],
    )
    # Submit button is hard-coded in the modal template; no SubmitField.
