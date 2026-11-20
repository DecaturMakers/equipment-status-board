"""Duration input that keeps its application-facing value in minutes."""

from wtforms import IntegerField
from wtforms.utils import unset_value


class DurationMinutesField(IntegerField):
    units = (("days", "Days", 1440), ("hours", "Hours", 60), ("minutes", "Minutes", 1))

    def process(self, formdata, data=unset_value, extra_filters=None):
        self.submitted_unit = formdata.get(f"{self.name}_unit", "minutes") if formdata is not None else None
        super().process(formdata, data, extra_filters=extra_filters)

    @property
    def unit(self):
        if self.submitted_unit is not None:
            return self.submitted_unit
        for unit, _, multiplier in self.units:
            if self.data and self.data % multiplier == 0:
                return unit
        return "minutes"

    def process_formdata(self, valuelist):
        super().process_formdata(valuelist)
        multipliers = {unit: multiplier for unit, _, multiplier in self.units}
        if self.unit not in multipliers:
            self.data = None
            raise ValueError("Select Days, Hours, or Minutes.")
        if self.data is not None:
            self.data *= multipliers[self.unit]

    def _value(self):
        if self.raw_data:
            return self.raw_data[0]
        if self.data is None:
            return ""
        multiplier = dict((unit, factor) for unit, _, factor in self.units)[self.unit]
        return str(self.data // multiplier)
