"""Application timezone constants and reservation conversion helpers."""

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from esb.utils.exceptions import ValidationError


# Reservations are scheduled and displayed in the makerspace's local time.
MAKERSPACE_TIMEZONE = ZoneInfo("America/New_York")


def utc_now_naive() -> datetime:
    """Return minute-precision UTC in the database's naive storage format."""
    return datetime.now(UTC).replace(tzinfo=None, second=0, microsecond=0)


def to_utc_naive(value: datetime) -> datetime:
    """Validate a UTC-aware datetime and convert it to database format."""
    if value.tzinfo is None:
        raise ValidationError("Reservation times must be UTC-aware datetimes")
    if value.utcoffset() != timedelta(0):
        raise ValidationError("Reservation times must be UTC datetimes")
    return value.astimezone(UTC).replace(tzinfo=None)


def utc_naive_to_local(value: datetime) -> datetime:
    """Convert a database UTC-naive datetime to makerspace local time."""
    return value.replace(tzinfo=UTC).astimezone(MAKERSPACE_TIMEZONE)


def local_date_range_to_utc(starts_on: date, ends_on: date) -> tuple[datetime, datetime]:
    """Return a half-open UTC-naive interval covering inclusive local dates."""
    starts_at = datetime.combine(starts_on, time.min, tzinfo=MAKERSPACE_TIMEZONE)
    ends_at = datetime.combine(ends_on + timedelta(days=1), time.min, tzinfo=MAKERSPACE_TIMEZONE)
    return (
        starts_at.astimezone(UTC).replace(tzinfo=None),
        ends_at.astimezone(UTC).replace(tzinfo=None),
    )


def local_datetime_to_utc(start_date: date, start_time: time) -> datetime:
    """Convert makerspace wall time to UTC, rejecting DST gaps and ambiguity."""
    local_value = datetime.combine(start_date, start_time)
    candidates = []
    for fold in (0, 1):
        candidate = local_value.replace(tzinfo=MAKERSPACE_TIMEZONE, fold=fold)
        round_trip = candidate.astimezone(UTC).astimezone(MAKERSPACE_TIMEZONE)
        if round_trip.replace(tzinfo=None) == local_value:
            candidates.append(candidate)
    offsets = {candidate.utcoffset() for candidate in candidates}
    if not candidates:
        raise ValidationError("This local time does not exist because of daylight saving time.")
    if len(offsets) > 1:
        raise ValidationError("This local time is ambiguous because of daylight saving time.")
    return candidates[0].astimezone(UTC)
