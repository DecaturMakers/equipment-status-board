"""Reservation scheduling service."""

from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import joinedload

from esb.extensions import db
from esb.models.equipment import Equipment
from esb.models.equipment_reservation_settings import EquipmentReservationSettings
from esb.models.reservation import RESERVATION_CREATED_VIA, Reservation
from esb.models.user import User
from esb.utils.exceptions import ValidationError

ACTIVE_STATUS = "active"
CANCELED_STATUS = "canceled"
RESERVATION_POLICY_OVERRIDE_ROLES = ("staff", "technician")


def list_reservable_equipment() -> list[Equipment]:
    """Return non-archived equipment with enabled reservation settings."""
    return list(
        db.session.execute(
            db.select(Equipment)
            .join(EquipmentReservationSettings)
            .options(joinedload(Equipment.reservation_settings))
            .filter(
                Equipment.is_archived.is_(False),
                EquipmentReservationSettings.reservations_enabled.is_(True),
            )
            .order_by(Equipment.name)
        )
        .scalars()
        .all()
    )


def get_public_availability(now=None) -> dict:
    """Build a privacy-safe reservation availability read model."""
    now_utc = _to_utc_naive(now) if now is not None else _utc_now()
    equipment_items = []

    for equipment in list_reservable_equipment():
        settings = equipment.reservation_settings
        window_end = now_utc + timedelta(minutes=settings.max_advance_notice_minutes)
        reservations = _active_reservations_for_window(
            equipment.id,
            now_utc,
            window_end,
        )
        equipment_items.append(
            {
                "id": equipment.id,
                "name": equipment.name,
                "reservation_slug": settings.reservation_slug,
                "reservations_enabled": settings.reservations_enabled,
                "min_advance_notice_minutes": settings.min_advance_notice_minutes,
                "max_advance_notice_minutes": settings.max_advance_notice_minutes,
                "min_duration_minutes": settings.min_duration_minutes,
                "max_duration_minutes": settings.max_duration_minutes,
                "slot_granularity_minutes": settings.slot_granularity_minutes,
                "reservations": [
                    {
                        "label": "Reserved",
                        "starts_at": reservation.starts_at.replace(tzinfo=UTC).isoformat(),
                        "ends_at": reservation.ends_at.replace(tzinfo=UTC).isoformat(),
                    }
                    for reservation in reservations
                ],
            }
        )

    return {
        "equipment": equipment_items,
    }


def get_public_calendar_data(now=None) -> dict:
    """Build public reservation calendar data with reserver and note details."""
    now_utc = _to_utc_naive(now) if now is not None else _utc_now()
    local_now = now_utc.replace(tzinfo=UTC).astimezone()

    columns = []
    events = []
    for equipment in list_reservable_equipment():
        settings = equipment.reservation_settings
        window_end = now_utc + timedelta(minutes=settings.max_advance_notice_minutes)
        reservations = _active_reservations_for_window(
            equipment.id,
            now_utc,
            window_end,
            include_user=True,
        )
        resource_id = str(equipment.id)
        columns.append({
            "id": resource_id,
            "name": equipment.name,
        })
        for reservation in reservations:
            starts_at = reservation.starts_at.replace(tzinfo=UTC).astimezone().replace(tzinfo=None)
            ends_at = reservation.ends_at.replace(tzinfo=UTC).astimezone().replace(tzinfo=None)
            reserved_by = reservation.user.display_name if reservation.user else "Unknown"
            note = _truncate_calendar_note(reservation.notes)
            text = reserved_by if not note else f"{reserved_by}: {note}"
            events.append({
                "id": str(reservation.id),
                "resource": resource_id,
                "start": starts_at.isoformat(timespec="seconds"),
                "end": ends_at.isoformat(timespec="seconds"),
                "text": text,
                "reservedBy": reserved_by,
                "note": note,
                "backColor": "#2f6f73",
                "barColor": "#164e52",
                "fontColor": "#ffffff",
            })

    return {
        "startDate": local_now.date().isoformat(),
        "columns": columns,
        "events": events,
    }


def _truncate_calendar_note(note: str | None, max_length: int = 80) -> str:
    text = " ".join((note or "").split())
    if len(text) <= max_length:
        return text
    return f"{text[:max_length - 3].rstrip()}..."


def create_reservation(
    equipment_id: int,
    user_id: int,
    starts_at_utc: datetime,
    duration_minutes: int,
    notes: str | None,
    created_via: str,
) -> Reservation:
    """Create an active reservation after applying scheduling rules."""
    if created_via not in RESERVATION_CREATED_VIA:
        raise ValidationError(f"Invalid reservation source: {created_via!r}")

    user = db.session.get(User, user_id)
    if user is None:
        raise ValidationError(f"User with id {user_id} not found")

    can_override_policy = user.role in RESERVATION_POLICY_OVERRIDE_ROLES
    equipment = _get_equipment_for_update(equipment_id)
    starts_at, ends_at = _validate_reservation_request(
        equipment,
        starts_at_utc,
        duration_minutes,
        can_override_policy=can_override_policy,
    )

    reservation = Reservation(
        equipment_id=equipment.id,
        user_id=user.id,
        starts_at=starts_at,
        ends_at=ends_at,
        notes=(notes or "").strip() or None,
        created_via=created_via,
    )
    db.session.add(reservation)
    db.session.commit()
    return reservation


def cancel_reservation(reservation_id: int, actor_user_id: int) -> Reservation:
    """Cancel an active reservation while preserving history."""
    reservation = db.session.get(Reservation, reservation_id)
    if reservation is None:
        raise ValidationError(f"Reservation with id {reservation_id} not found")

    actor = db.session.get(User, actor_user_id)
    if actor is None:
        raise ValidationError(f"User with id {actor_user_id} not found")

    if reservation.status == CANCELED_STATUS:
        raise ValidationError("Reservation is already canceled")

    reservation.status = CANCELED_STATUS
    reservation.canceled_at = _utc_now()
    reservation.canceled_by_user_id = actor.id
    db.session.commit()
    return reservation


def list_user_upcoming_reservations(user_id: int) -> list[Reservation]:
    """Return a user's active reservations that have not ended yet."""
    return list(
        db.session.execute(
            db.select(Reservation)
            .filter(
                Reservation.user_id == user_id,
                Reservation.status == ACTIVE_STATUS,
                Reservation.ends_at > _utc_now(),
            )
            .order_by(Reservation.starts_at)
        )
        .scalars()
        .all()
    )


def _get_equipment_for_update(equipment_id: int) -> Equipment:
    equipment = db.session.execute(
        db.select(Equipment)
        .options(joinedload(Equipment.reservation_settings))
        .filter(Equipment.id == equipment_id)
        .with_for_update()
    ).scalar_one_or_none()
    if equipment is None:
        raise ValidationError(f"Equipment with id {equipment_id} not found")
    return equipment


def _validate_reservation_request(
    equipment: Equipment,
    starts_at_utc: datetime,
    duration_minutes: int,
    *,
    can_override_policy: bool = False,
) -> tuple[datetime, datetime]:
    settings = _validate_reservable_equipment(equipment)
    _validate_duration(
        duration_minutes,
        settings,
        can_override_policy=can_override_policy,
    )
    starts_at = _to_utc_naive(starts_at_utc)
    _validate_start_time(
        starts_at,
        settings,
        can_override_policy=can_override_policy,
    )
    ends_at = starts_at + timedelta(minutes=duration_minutes)
    conflict = (
        db.session.execute(
            db.select(Reservation)
            .filter(
                Reservation.equipment_id == equipment.id,
                Reservation.status == ACTIVE_STATUS,
                Reservation.starts_at < ends_at,
                Reservation.ends_at > starts_at,
            )
            .order_by(Reservation.starts_at)
        )
        .scalars()
        .first()
    )
    if conflict is not None:
        raise ValidationError("Reservation overlaps an existing reservation")
    return starts_at, ends_at


def _validate_reservable_equipment(
    equipment: Equipment,
) -> EquipmentReservationSettings:
    if equipment.is_archived:
        raise ValidationError(f"Equipment {equipment.name!r} is archived")

    settings = equipment.reservation_settings
    if settings is None:
        raise ValidationError(f"Equipment {equipment.name!r} is not reservable")

    if not settings.reservations_enabled:
        raise ValidationError(f"Reservations are disabled for {equipment.name!r}")

    _validate_settings_policy(settings)
    return settings


def _validate_settings_policy(settings: EquipmentReservationSettings) -> None:
    if settings.min_advance_notice_minutes < 0:
        raise ValidationError("Minimum advance notice cannot be negative")
    if settings.max_advance_notice_minutes <= 0:
        raise ValidationError("Maximum advance notice must be greater than 0 minutes")
    if settings.max_advance_notice_minutes < settings.min_advance_notice_minutes:
        raise ValidationError("Maximum advance notice must be at least the minimum advance notice")
    if settings.min_duration_minutes <= 0:
        raise ValidationError("Minimum reservation duration must be greater than 0 minutes")
    if settings.max_duration_minutes < settings.min_duration_minutes:
        raise ValidationError("Maximum reservation duration must be at least the minimum duration")
    if settings.slot_granularity_minutes <= 0:
        raise ValidationError("Slot granularity must be greater than 0 minutes")
    if settings.min_duration_minutes % settings.slot_granularity_minutes != 0:
        raise ValidationError("Minimum reservation duration must align to slot granularity")
    if settings.max_duration_minutes % settings.slot_granularity_minutes != 0:
        raise ValidationError("Maximum reservation duration must align to slot granularity")


def _validate_duration(
    duration_minutes: int,
    settings: EquipmentReservationSettings,
    *,
    can_override_policy: bool = False,
) -> None:
    if duration_minutes <= 0:
        raise ValidationError("Reservation duration must be greater than 0 minutes")
    if not can_override_policy and duration_minutes < settings.min_duration_minutes:
        raise ValidationError(f"Reservation must be at least {settings.min_duration_minutes} minutes")
    if not can_override_policy and duration_minutes > settings.max_duration_minutes:
        raise ValidationError(f"Reservation cannot exceed {settings.max_duration_minutes} minutes")
    if duration_minutes % settings.slot_granularity_minutes != 0:
        raise ValidationError(f"Duration must use {settings.slot_granularity_minutes}-minute increments")


def _validate_start_time(
    starts_at: datetime,
    settings: EquipmentReservationSettings,
    *,
    can_override_policy: bool = False,
) -> None:
    now = _utc_now()
    if starts_at < now:
        raise ValidationError("Reservation cannot start in the past")

    if not can_override_policy:
        earliest_start = now + timedelta(minutes=settings.min_advance_notice_minutes)
        if starts_at < earliest_start:
            raise ValidationError("Reservation does not meet the minimum advance notice")

        latest_start = now + timedelta(minutes=settings.max_advance_notice_minutes)
        if starts_at > latest_start:
            raise ValidationError("Reservation is outside the maximum advance notice")

    minutes_since_midnight = starts_at.hour * 60 + starts_at.minute
    if (
        minutes_since_midnight % settings.slot_granularity_minutes != 0
        or starts_at.second != 0
        or starts_at.microsecond != 0
    ):
        raise ValidationError(f"Start time must use {settings.slot_granularity_minutes}-minute increments")


def _active_reservations_for_window(
    equipment_id: int,
    starts_at: datetime,
    ends_at: datetime,
    *,
    include_user: bool = False,
) -> list[Reservation]:
    query = db.select(Reservation)
    if include_user:
        query = query.options(joinedload(Reservation.user))

    return list(
        db.session.execute(
            query
            .filter(
                Reservation.equipment_id == equipment_id,
                Reservation.status == ACTIVE_STATUS,
                Reservation.starts_at < ends_at,
                Reservation.ends_at > starts_at,
            )
            .order_by(Reservation.starts_at)
        )
        .scalars()
        .all()
    )


def _to_utc_naive(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValidationError("Reservation times must be UTC-aware datetimes")
    if value.utcoffset() != timedelta(0):
        raise ValidationError("Reservation times must be UTC datetimes")
    return value.astimezone(UTC).replace(tzinfo=None)


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None, second=0, microsecond=0)
