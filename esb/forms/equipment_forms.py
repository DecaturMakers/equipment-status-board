"""Equipment forms for area and equipment management."""

from flask_wtf import FlaskForm
from flask_wtf.file import FileAllowed, FileField, FileRequired
from wtforms import (
    BooleanField,
    DateField,
    DecimalField,
    IntegerField,
    SelectField,
    StringField,
    SubmitField,
    TextAreaField,
)
from wtforms.validators import URL, DataRequired, Length, NumberRange, Optional

from esb.models.document import DOCUMENT_CATEGORIES
from esb.services.qr_service import DEFAULT_DEVICE_KEY, QR_DEVICE_PRESETS, QR_SIZE_PRESETS

FORM_DOCUMENT_CATEGORIES = [('', '-- Select Category --')] + DOCUMENT_CATEGORIES


class AreaCreateForm(FlaskForm):
    """Form for creating a new area."""

    name = StringField('Name', validators=[DataRequired(), Length(max=80)])
    slack_channel = StringField('Slack Channel', validators=[DataRequired(), Length(max=80)])
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
    submit = SubmitField('Create Area')


class AreaEditForm(FlaskForm):
    """Form for editing an existing area."""

    name = StringField('Name', validators=[DataRequired(), Length(max=80)])
    slack_channel = StringField('Slack Channel', validators=[DataRequired(), Length(max=80)])
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
    submit = SubmitField('Save Changes')


class EquipmentCreateForm(FlaskForm):
    """Form for creating a new equipment record."""

    name = StringField('Name', validators=[DataRequired(), Length(max=200)])
    manufacturer = StringField('Manufacturer', validators=[DataRequired(), Length(max=200)])
    model = StringField('Model', validators=[DataRequired(), Length(max=200)])
    area_id = SelectField('Area', coerce=int, validators=[DataRequired()])
    serial_number = StringField('Serial Number', validators=[Length(max=200)])
    acquisition_date = DateField('Acquisition Date', validators=[Optional()])
    acquisition_source = StringField('Acquisition Source', validators=[Length(max=200)])
    acquisition_cost = DecimalField('Acquisition Cost', places=2, validators=[Optional()])
    warranty_expiration = DateField('Warranty Expiration', validators=[Optional()])
    description = TextAreaField('Description')
    submit = SubmitField('Create Equipment')


class EquipmentEditForm(FlaskForm):
    """Form for editing an existing equipment record."""

    name = StringField('Name', validators=[DataRequired(), Length(max=200)])
    manufacturer = StringField('Manufacturer', validators=[DataRequired(), Length(max=200)])
    model = StringField('Model', validators=[DataRequired(), Length(max=200)])
    area_id = SelectField('Area', coerce=int, validators=[DataRequired()])
    serial_number = StringField('Serial Number', validators=[Length(max=200)])
    acquisition_date = DateField('Acquisition Date', validators=[Optional()])
    acquisition_source = StringField('Acquisition Source', validators=[Length(max=200)])
    acquisition_cost = DecimalField('Acquisition Cost', places=2, validators=[Optional()])
    warranty_expiration = DateField('Warranty Expiration', validators=[Optional()])
    description = TextAreaField('Description')
    submit = SubmitField('Save Changes')


class DocumentUploadForm(FlaskForm):
    """Form for uploading a document to an equipment record."""

    file = FileField('Document', validators=[
        FileRequired('Please select a file to upload.'),
        FileAllowed(
            ['pdf', 'doc', 'docx', 'txt', 'rtf', 'odt', 'xls', 'xlsx', 'csv', 'ppt', 'pptx'],
            'Only document files are allowed.',
        ),
    ])
    category = SelectField('Category', choices=FORM_DOCUMENT_CATEGORIES, validators=[DataRequired()])
    submit = SubmitField('Upload Document')


class PhotoUploadForm(FlaskForm):
    """Form for uploading a photo/video to an equipment record."""

    file = FileField('Photo/Video', validators=[
        FileRequired('Please select a file to upload.'),
        FileAllowed(
            ['jpg', 'jpeg', 'png', 'gif', 'webp', 'mp4', 'mov', 'avi', 'webm'],
            'Only image and video files are allowed.',
        ),
    ])
    submit = SubmitField('Upload Photo')


class ExternalLinkForm(FlaskForm):
    """Form for adding an external link to an equipment record."""

    title = StringField('Title', validators=[DataRequired(), Length(max=200)])
    url = StringField('URL', validators=[DataRequired(), Length(max=2000), URL()])
    submit = SubmitField('Add Link')


class QRGenerateForm(FlaskForm):
    """Form for QR code generation options."""

    size = SelectField(
        'Size',
        choices=[(p.key, p.label) for p in QR_SIZE_PRESETS],
        validators=[DataRequired()],
        default='sticker_2',
    )
    device = SelectField(
        'Printer / device',
        choices=[(p.key, p.label) for p in QR_DEVICE_PRESETS],
        validators=[DataRequired()],
        default=DEFAULT_DEVICE_KEY,
    )
    wifi_info = SelectField('WiFi Info', default='none')
    include_name = BooleanField('Include equipment name above QR', default=False)
    include_url = BooleanField('Include URL below QR', default=False)
    submit = SubmitField('Download QR Code')

    def __init__(self, *args, wifi_choices=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.wifi_info.choices = wifi_choices or [('none', 'None')]
        # Robustness: a missing wifi_info in POST data should be treated as 'none',
        # not None (which would fail SelectField validation).
        if self.wifi_info.data is None:
            self.wifi_info.data = 'none'
