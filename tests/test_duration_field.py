"""Duration controls preserve minute-based application values."""

import pytest
from werkzeug.datastructures import MultiDict
from wtforms import Form
from wtforms.validators import InputRequired, NumberRange

from esb.forms.duration_field import DurationMinutesField
from esb.utils.filters import format_duration


class DurationForm(Form):
    duration = DurationMinutesField("Duration", validators=[InputRequired(), NumberRange(min=1)])


@pytest.mark.parametrize("minutes,amount,unit", [
    (20160, "14", "days"), (120, "2", "hours"), (90, "90", "minutes"),
    (0, "0", "minutes"), (1501, "1501", "minutes"),
])
def test_existing_values(minutes, amount, unit):
    field = DurationForm(data={"duration": minutes}).duration
    assert field._value() == amount
    assert field.unit == unit
    assert field.data == minutes


@pytest.mark.parametrize("amount,unit,minutes", [("2", "days", 2880), ("2", "hours", 120), ("90", "minutes", 90)])
def test_submitted_values(amount, unit, minutes):
    form = DurationForm(MultiDict({"duration": amount, "duration_unit": unit}))
    assert form.validate()
    assert form.duration.data == minutes
    assert form.duration._value() == amount
    assert form.duration.unit == unit


@pytest.mark.parametrize("amount,unit", [("1.5", "hours"), ("abc", "days"), ("", "minutes"),
                                          ("-1", "hours"), ("0", "days"), ("2", "weeks")])
def test_invalid_values_preserved(amount, unit):
    form = DurationForm(MultiDict({"duration": amount, "duration_unit": unit}))
    assert not form.validate()
    assert form.duration._value() == amount
    assert form.duration.unit == unit


def test_minutes_only_submission_remains_supported():
    form = DurationForm(MultiDict({"duration": "120"}))
    assert form.validate()
    assert form.duration.data == 120


def test_value_assigned_for_rescheduling():
    field = DurationForm().duration
    field.data = 120
    assert field._value() == "2"
    assert field.unit == "hours"


@pytest.mark.parametrize("minutes,expected", [(0, "0 minutes"), (1, "1 minute"), (120, "2 hours"),
                                             (1531, "1 day 1 hour 31 minutes")])
def test_readable_duration(minutes, expected):
    assert format_duration(minutes) == expected
