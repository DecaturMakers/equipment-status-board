"""Reservation policy types and validation rules."""

from dataclasses import dataclass
from datetime import datetime, timedelta

from esb.extensions import db
from esb.models.equipment import Equipment
from esb.models.equipment_reservation_settings import EquipmentReservationSettings
from esb.models.reservation import RESERVATION_STATUS_ACTIVE, Reservation
from esb.utils.exceptions import ValidationError
from esb.utils.timezones import utc_naive_to_local

RESERVATION_POLICY_OVERRIDE_ROLES = ("staff", "technician")

VIOLATION_EQUIPMENT_ARCHIVED = "equipment_archived"
VIOLATION_EQUIPMENT_NOT_RESERVABLE = "equipment_not_reservable"
VIOLATION_RESERVATIONS_DISABLED = "reservations_disabled"
VIOLATION_DURATION_NONPOSITIVE = "duration_nonpositive"
VIOLATION_DURATION_BELOW_MINIMUM = "duration_below_minimum"
VIOLATION_DURATION_ABOVE_MAXIMUM = "duration_above_maximum"
VIOLATION_DURATION_GRANULARITY = "duration_granularity"
VIOLATION_START_IN_PAST = "start_in_past"
VIOLATION_MIN_ADVANCE_NOTICE = "minimum_advance_notice"
VIOLATION_MAX_ADVANCE_NOTICE = "maximum_advance_notice"
VIOLATION_START_GRANULARITY = "start_granularity"
VIOLATION_CONFLICT = "conflict"

# Slack's legacy flow implicitly permits only these role-based overrides. The
# admin workflow separately requires explicit confirmation for every
# overridable category.
LEGACY_IMPLICIT_OVERRIDE_CODES = frozenset(
    {
        VIOLATION_DURATION_BELOW_MINIMUM,
        VIOLATION_DURATION_ABOVE_MAXIMUM,
        VIOLATION_MIN_ADVANCE_NOTICE,
        VIOLATION_MAX_ADVANCE_NOTICE,
    }
)
OVERRIDABLE_POLICY_CODES = frozenset(
    {
        VIOLATION_DURATION_BELOW_MINIMUM,
        VIOLATION_DURATION_ABOVE_MAXIMUM,
        VIOLATION_DURATION_GRANULARITY,
        VIOLATION_MIN_ADVANCE_NOTICE,
        VIOLATION_MAX_ADVANCE_NOTICE,
        VIOLATION_START_GRANULARITY,
        VIOLATION_CONFLICT,
    }
)


@dataclass(frozen=True)
class ValidatedReservation:
    """A reservation interval that passed scheduling validation."""

    equipment_id: int
    starts_at: datetime
    ends_at: datetime


@dataclass(frozen=True)
class ReservationViolation:
    """One stable, user-displayable reservation validation failure."""

    code: str
    message: str
    overridable: bool = False


@dataclass(frozen=True)
class ReservationValidationResult:
    """Validated interval and all policy failures found for a request."""

    validated: ValidatedReservation
    violations: tuple[ReservationViolation, ...]
    actor_can_override_policy: bool

    @property
    def hard_violations(self) -> tuple[ReservationViolation, ...]:
        return tuple(violation for violation in self.violations if not violation.overridable)

    @property
    def overridable_violations(self) -> tuple[ReservationViolation, ...]:
        return tuple(violation for violation in self.violations if violation.overridable)


def settings_validation_errors(
    *,
    min_advance_notice_minutes: int,
    max_advance_notice_minutes: int,
    min_duration_minutes: int,
    max_duration_minutes: int,
    slot_granularity_minutes: int,
) -> dict[str, str]:
    """Return field-specific errors for one reservation policy configuration."""
    errors = {}
    if min_advance_notice_minutes < 0:
        errors["min_advance_notice_minutes"] = "Minimum advance notice cannot be negative"
    if max_advance_notice_minutes <= 0:
        errors["max_advance_notice_minutes"] = "Maximum advance notice must be greater than 0 minutes"
    elif max_advance_notice_minutes < min_advance_notice_minutes:
        errors["max_advance_notice_minutes"] = "Maximum advance notice must be at least the minimum advance notice"
    if min_duration_minutes <= 0:
        errors["min_duration_minutes"] = "Minimum reservation duration must be greater than 0 minutes"
    if max_duration_minutes < min_duration_minutes:
        errors["max_duration_minutes"] = "Maximum reservation duration must be at least the minimum duration"
    if slot_granularity_minutes <= 0:
        errors["slot_granularity_minutes"] = "Slot granularity must be greater than 0 minutes"
    else:
        if min_duration_minutes > 0 and min_duration_minutes % slot_granularity_minutes != 0:
            errors["min_duration_minutes"] = "Minimum reservation duration must align to slot granularity"
        if max_duration_minutes > 0 and max_duration_minutes % slot_granularity_minutes != 0:
            errors["max_duration_minutes"] = "Maximum reservation duration must align to slot granularity"
    return errors


def validate_settings_values(**values) -> None:
    """Raise the first canonical validation error for policy settings."""
    errors = settings_validation_errors(**values)
    if errors:
        raise ValidationError(next(iter(errors.values())))


def validate_settings(settings: EquipmentReservationSettings) -> None:
    validate_settings_values(
        min_advance_notice_minutes=settings.min_advance_notice_minutes,
        max_advance_notice_minutes=settings.max_advance_notice_minutes,
        min_duration_minutes=settings.min_duration_minutes,
        max_duration_minutes=settings.max_duration_minutes,
        slot_granularity_minutes=settings.slot_granularity_minutes,
    )


def normalize_override_codes(values: list[str] | tuple[str, ...] | None) -> list[str]:
    if values is None:
        return []
    if not isinstance(values, (list, tuple)) or not all(isinstance(value, str) for value in values):
        raise ValidationError("Overridden policy codes must be a list of strings")
    if len(set(values)) != len(values):
        raise ValidationError("Overridden policy codes must not contain duplicates")
    invalid_codes = set(values) - OVERRIDABLE_POLICY_CODES
    if invalid_codes:
        raise ValidationError(f"Invalid overridden policy code: {sorted(invalid_codes)[0]!r}")
    return list(values)


def legacy_blocking_violations(
    result: ReservationValidationResult,
) -> tuple[ReservationViolation, ...]:
    return tuple(
        violation
        for violation in result.violations
        if not (result.actor_can_override_policy and violation.code in LEGACY_IMPLICIT_OVERRIDE_CODES)
    )


def collect_reservation_violations(
    *,
    equipment: Equipment,
    starts_at: datetime,
    ends_at: datetime,
    duration_minutes: int,
    now: datetime,
    exclude_reservation_id: int | None = None,
    lock_conflicts: bool = False,
) -> list[ReservationViolation]:
    violations = _collect_equipment_violations(equipment)
    settings = equipment.reservation_settings
    if settings is None or violations:
        return violations

    validate_settings(settings)
    violations.extend(_collect_duration_violations(duration_minutes, settings))
    violations.extend(_collect_start_time_violations(starts_at, settings, now))
    if duration_minutes <= 0:
        return violations

    conflict_query = db.select(Reservation).filter(
        Reservation.equipment_id == equipment.id,
        Reservation.status == RESERVATION_STATUS_ACTIVE,
        Reservation.starts_at < ends_at,
        Reservation.ends_at > starts_at,
    )
    if exclude_reservation_id is not None:
        conflict_query = conflict_query.filter(Reservation.id != exclude_reservation_id)
    if lock_conflicts:
        # Use a locking/current read during persistence revalidation. On
        # MariaDB's default REPEATABLE READ isolation, an ordinary SELECT could
        # otherwise reuse the earlier preview snapshot after waiting for the
        # equipment lock and miss a concurrently committed reservation.
        conflict_query = conflict_query.with_for_update()
    conflict = db.session.execute(conflict_query.order_by(Reservation.starts_at)).scalars().first()
    if conflict is not None:
        violations.append(
            ReservationViolation(
                code=VIOLATION_CONFLICT,
                message="Reservation overlaps an existing reservation",
                overridable=True,
            )
        )
    return violations


def _collect_equipment_violations(equipment: Equipment) -> list[ReservationViolation]:
    if equipment.is_archived:
        return [
            ReservationViolation(
                code=VIOLATION_EQUIPMENT_ARCHIVED,
                message=f"Equipment {equipment.name!r} is archived",
            )
        ]
    settings = equipment.reservation_settings
    if settings is None:
        return [
            ReservationViolation(
                code=VIOLATION_EQUIPMENT_NOT_RESERVABLE,
                message=f"Equipment {equipment.name!r} is not reservable",
            )
        ]
    if not settings.reservations_enabled:
        return [
            ReservationViolation(
                code=VIOLATION_RESERVATIONS_DISABLED,
                message=f"Reservations are disabled for {equipment.name!r}",
            )
        ]
    return []


def _collect_duration_violations(
    duration_minutes: int,
    settings: EquipmentReservationSettings,
) -> list[ReservationViolation]:
    if duration_minutes <= 0:
        return [
            ReservationViolation(
                code=VIOLATION_DURATION_NONPOSITIVE,
                message="Reservation duration must be greater than 0 minutes",
            )
        ]
    violations = []
    if duration_minutes < settings.min_duration_minutes:
        violations.append(
            ReservationViolation(
                VIOLATION_DURATION_BELOW_MINIMUM,
                f"Reservation must be at least {settings.min_duration_minutes} minutes",
                True,
            )
        )
    if duration_minutes > settings.max_duration_minutes:
        violations.append(
            ReservationViolation(
                VIOLATION_DURATION_ABOVE_MAXIMUM,
                f"Reservation cannot exceed {settings.max_duration_minutes} minutes",
                True,
            )
        )
    if duration_minutes % settings.slot_granularity_minutes != 0:
        violations.append(
            ReservationViolation(
                VIOLATION_DURATION_GRANULARITY,
                f"Duration must use {settings.slot_granularity_minutes}-minute increments",
                True,
            )
        )
    return violations


def _collect_start_time_violations(
    starts_at: datetime,
    settings: EquipmentReservationSettings,
    now: datetime,
) -> list[ReservationViolation]:
    violations = []
    if starts_at < now:
        violations.append(
            ReservationViolation(
                VIOLATION_START_IN_PAST,
                "Reservation cannot start in the past",
            )
        )
    if starts_at < now + timedelta(minutes=settings.min_advance_notice_minutes):
        violations.append(
            ReservationViolation(
                VIOLATION_MIN_ADVANCE_NOTICE,
                "Reservation does not meet the minimum advance notice",
                True,
            )
        )
    if starts_at > now + timedelta(minutes=settings.max_advance_notice_minutes):
        violations.append(
            ReservationViolation(
                VIOLATION_MAX_ADVANCE_NOTICE,
                "Reservation is outside the maximum advance notice",
                True,
            )
        )
    local_starts_at = utc_naive_to_local(starts_at)
    minutes_since_midnight = local_starts_at.hour * 60 + local_starts_at.minute
    if (
        minutes_since_midnight % settings.slot_granularity_minutes != 0
        or local_starts_at.second != 0
        or local_starts_at.microsecond != 0
    ):
        violations.append(
            ReservationViolation(
                VIOLATION_START_GRANULARITY,
                f"Start time must use {settings.slot_granularity_minutes}-minute increments",
                True,
            )
        )
    return violations
