"""Administrative reservation workflow forms."""

from flask_wtf import FlaskForm
from wtforms import (
    DateField,
    HiddenField,
    IntegerField,
    SelectField,
    SubmitField,
    TextAreaField,
    TimeField,
)
from wtforms.validators import DataRequired, InputRequired, Length, NumberRange, Optional, ValidationError

from esb.models.reservation import RESERVATION_TYPE_ADMIN_HOLD, RESERVATION_TYPE_MEMBER


class AdminReservationCreateForm(FlaskForm):
    reservation_type = SelectField(
        "Reservation type",
        choices=[
            (RESERVATION_TYPE_MEMBER, "Member reservation"),
            (RESERVATION_TYPE_ADMIN_HOLD, "Admin hold"),
        ],
        validators=[DataRequired()],
    )
    equipment_id = SelectField("Equipment", coerce=int, validators=[InputRequired()])
    owner_user_id = SelectField("Member", coerce=int, validators=[Optional()])
    start_date = DateField("Start date", validators=[DataRequired()], format="%Y-%m-%d")
    start_time = TimeField("Start time", validators=[DataRequired()], format="%H:%M")
    duration_minutes = IntegerField(
        "Duration (minutes)",
        validators=[InputRequired(), NumberRange(min=1)],
    )
    notes = TextAreaField("Note", validators=[DataRequired(), Length(max=5000)])
    submit = SubmitField("Review reservation")

    def validate_owner_user_id(self, field):
        if self.reservation_type.data == RESERVATION_TYPE_MEMBER and not field.data:
            raise ValidationError("Select an active member for this reservation.")


class AdminReservationConfirmationForm(FlaskForm):
    confirmation_token = HiddenField(validators=[DataRequired()])
    submit = SubmitField("Create reservation")


class AdminReservationCancelRequestForm(FlaskForm):
    submit = SubmitField("Cancel reservation")


class AdminReservationCancelConfirmationForm(FlaskForm):
    confirmation_token = HiddenField(validators=[DataRequired()])
    submit = SubmitField("Cancel reservation")
