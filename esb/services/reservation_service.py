"""Reservation scheduling service."""

from datetime import datetime, timedelta

from sqlalchemy.orm import joinedload

from esb.extensions import db
from esb.models.equipment import Equipment
from esb.models.reservation import (
    RESERVATION_CREATED_VIA,
    RESERVATION_STATUS_ACTIVE,
    RESERVATION_STATUS_CANCELED,
    RESERVATION_TYPE_ADMIN_HOLD,
    RESERVATION_TYPE_MEMBER,
    RESERVATION_TYPES,
    Reservation,
)
from esb.models.user import User
from esb.services import reservation_policy
from esb.utils.exceptions import ValidationError
from esb.utils.logging import log_mutation
from esb.utils.timezones import to_utc_naive, utc_now_naive

ACTIVE_STATUS = RESERVATION_STATUS_ACTIVE
CANCELED_STATUS = RESERVATION_STATUS_CANCELED


def create_reservation(
    equipment_id: int,
    owner_user_id: int | None,
    starts_at_utc: datetime,
    duration_minutes: int,
    notes: str | None,
    created_via: str,
    *,
    actor_user_id: int | None = None,
    reservation_type: str = RESERVATION_TYPE_MEMBER,
    overridden_policy_codes: list[str] | tuple[str, ...] | None = None,
    commit: bool = True,
) -> Reservation:
    """Validate and persist a reservation.

    ``actor_user_id`` controls policy privileges; ``owner_user_id`` is the
    member the reservation belongs to. Callers creating a larger transaction
    can pass ``commit=False`` and commit or roll back the session themselves.
    """
    if created_via not in RESERVATION_CREATED_VIA:
        raise ValidationError(f"Invalid reservation source: {created_via!r}")

    _validate_reservation_shape(
        reservation_type=reservation_type,
        owner_user_id=owner_user_id,
        starts_at=None,
        ends_at=None,
    )
    owner = _get_user(owner_user_id, label="owner") if owner_user_id is not None else None
    if actor_user_id is None:
        if owner is None:
            raise ValidationError("Reservation actor is required for an admin hold")
        actor_user_id = owner.id
    validated = validate_reservation_request(
        equipment_id=equipment_id,
        starts_at_utc=starts_at_utc,
        duration_minutes=duration_minutes,
        actor_user_id=actor_user_id,
    )
    reservation = persist_reservation(
        validated=validated,
        owner_user_id=owner.id if owner is not None else None,
        notes=notes,
        created_via=created_via,
        reservation_type=reservation_type,
        created_by_user_id=actor_user_id,
        overridden_policy_codes=overridden_policy_codes,
        commit=commit,
    )
    if commit:
        _log_reservation_created(reservation, _get_user(actor_user_id, label="actor"))
    return reservation


def preview_admin_reservation(
    *,
    equipment_id: int,
    owner_user_id: int | None,
    starts_at_utc: datetime,
    duration_minutes: int,
    notes: str,
    actor_user_id: int,
    reservation_type: str,
    exclude_reservation_id: int | None = None,
) -> reservation_policy.ReservationValidationResult:
    """Validate an admin form without taking a lock or writing a reservation."""
    _validate_admin_reservation_request(
        owner_user_id=owner_user_id,
        notes=notes,
        reservation_type=reservation_type,
    )
    result = evaluate_reservation_request(
        equipment_id=equipment_id,
        starts_at_utc=starts_at_utc,
        duration_minutes=duration_minutes,
        actor_user_id=actor_user_id,
        exclude_reservation_id=exclude_reservation_id,
    )
    _require_admin_reservation_actor(result)
    return result


def create_admin_reservation(
    *,
    equipment_id: int,
    owner_user_id: int | None,
    starts_at_utc: datetime,
    duration_minutes: int,
    notes: str,
    actor_user_id: int,
    reservation_type: str,
    overridden_policy_codes: list[str] | tuple[str, ...] | None = None,
) -> Reservation:
    """Create a reviewed admin reservation, revalidating under an equipment lock.

    The ``SELECT ... FOR UPDATE`` performed by evaluation serializes conflict
    checks with inserts for an equipment item on MariaDB until this commit.
    """
    return _persist_admin_reservation(
        equipment_id=equipment_id,
        owner_user_id=owner_user_id,
        starts_at_utc=starts_at_utc,
        duration_minutes=duration_minutes,
        notes=notes,
        actor_user_id=actor_user_id,
        reservation_type=reservation_type,
        overridden_policy_codes=overridden_policy_codes,
    )


def replace_admin_reservation(
    *,
    reservation_id: int,
    equipment_id: int,
    owner_user_id: int | None,
    starts_at_utc: datetime,
    duration_minutes: int,
    notes: str,
    actor_user_id: int,
    reservation_type: str,
    overridden_policy_codes: list[str] | tuple[str, ...] | None = None,
) -> Reservation:
    """Create a replacement and cancel the original in one transaction."""
    return _persist_admin_reservation(
        replacement_reservation_id=reservation_id,
        equipment_id=equipment_id,
        owner_user_id=owner_user_id,
        starts_at_utc=starts_at_utc,
        duration_minutes=duration_minutes,
        notes=notes,
        actor_user_id=actor_user_id,
        reservation_type=reservation_type,
        overridden_policy_codes=overridden_policy_codes,
    )


def _persist_admin_reservation(
    *,
    equipment_id: int,
    owner_user_id: int | None,
    starts_at_utc: datetime,
    duration_minutes: int,
    notes: str,
    actor_user_id: int,
    reservation_type: str,
    overridden_policy_codes: list[str] | tuple[str, ...] | None,
    replacement_reservation_id: int | None = None,
) -> Reservation:
    """Revalidate and persist an admin create or replacement transaction."""
    original = None
    if replacement_reservation_id is not None:
        original = _get_reservation(replacement_reservation_id, for_update=True)
        if original.status == CANCELED_STATUS:
            raise ValidationError("Reservation is already canceled")

    _validate_admin_reservation_request(
        owner_user_id=owner_user_id,
        notes=notes,
        reservation_type=reservation_type,
    )
    result = evaluate_reservation_request(
        equipment_id=equipment_id,
        starts_at_utc=starts_at_utc,
        duration_minutes=duration_minutes,
        actor_user_id=actor_user_id,
        lock_equipment=True,
        exclude_reservation_id=original.id if original is not None else None,
    )
    _require_admin_reservation_actor(result)
    if result.hard_violations:
        raise ValidationError("; ".join(item.message for item in result.hard_violations))

    expected_codes = {item.code for item in result.overridable_violations}
    supplied_codes = set(reservation_policy.normalize_override_codes(overridden_policy_codes))
    if supplied_codes != expected_codes:
        raise ValidationError("Reservation policy warnings changed; review and confirm the reservation again")

    reservation = persist_reservation(
        validated=result.validated,
        owner_user_id=owner_user_id,
        notes=notes,
        created_via="admin",
        reservation_type=reservation_type,
        created_by_user_id=actor_user_id,
        overridden_policy_codes=sorted(supplied_codes),
        commit=False,
    )
    actor = _get_user(actor_user_id, label="actor")
    if original is not None:
        reservation.replaces_reservation_id = original.id
        original.status = CANCELED_STATUS
        original.canceled_at = _utc_now()
        original.canceled_by_user_id = actor.id
    db.session.commit()

    if original is None:
        _log_reservation_created(reservation, actor)
        return reservation

    log_mutation(
        "reservation.updated",
        actor.username,
        {
            "reservation_id": original.id,
            "replacement_reservation_id": reservation.id,
            "equipment_id": reservation.equipment_id,
            "owner_user_id": reservation.user_id,
            "reservation_type": reservation.reservation_type,
            "overridden_policy_codes": reservation.overridden_policy_codes or [],
        },
    )
    return reservation


def validate_reservation_request(
    *,
    equipment_id: int,
    starts_at_utc: datetime,
    duration_minutes: int,
    actor_user_id: int,
) -> reservation_policy.ValidatedReservation:
    """Validate a proposed reservation without persisting one.

    The actor's role, rather than the reservation owner's role, determines
    whether policy bounds may be overridden. Equipment is locked while the
    conflict check runs so a caller can persist the returned interval in the
    same transaction.
    """
    result = evaluate_reservation_request(
        equipment_id=equipment_id,
        starts_at_utc=starts_at_utc,
        duration_minutes=duration_minutes,
        actor_user_id=actor_user_id,
        lock_equipment=True,
    )
    blocking = reservation_policy.legacy_blocking_violations(result)
    if blocking:
        raise ValidationError("; ".join(violation.message for violation in blocking))
    return result.validated


def evaluate_reservation_request(
    *,
    equipment_id: int,
    starts_at_utc: datetime,
    duration_minutes: int,
    actor_user_id: int,
    lock_equipment: bool = False,
    exclude_reservation_id: int | None = None,
) -> reservation_policy.ReservationValidationResult:
    """Evaluate a request and return all policy violations without persisting.

    Callers can use the stable violation codes to render admin warnings. This
    function does not grant an override or mutate the database. Preview callers
    should use the default unlocked query; persistence callers should request a
    lock and revalidate in the transaction that writes the reservation.
    """
    actor = _get_user(actor_user_id, label="actor")
    can_override_policy = actor.role in reservation_policy.RESERVATION_POLICY_OVERRIDE_ROLES
    equipment = _get_equipment(equipment_id, for_update=lock_equipment)
    starts_at = to_utc_naive(starts_at_utc)
    ends_at = starts_at + timedelta(minutes=duration_minutes)
    validated = reservation_policy.ValidatedReservation(
        equipment_id=equipment.id,
        starts_at=starts_at,
        ends_at=ends_at,
    )
    violations = reservation_policy.collect_reservation_violations(
        equipment=equipment,
        starts_at=starts_at,
        ends_at=ends_at,
        duration_minutes=duration_minutes,
        now=_utc_now(),
        exclude_reservation_id=exclude_reservation_id,
        lock_conflicts=lock_equipment,
    )
    return reservation_policy.ReservationValidationResult(
        validated=validated,
        violations=tuple(violations),
        actor_can_override_policy=can_override_policy,
    )


def persist_reservation(
    *,
    validated: reservation_policy.ValidatedReservation,
    owner_user_id: int | None,
    notes: str | None,
    created_via: str,
    reservation_type: str = RESERVATION_TYPE_MEMBER,
    created_by_user_id: int | None = None,
    overridden_policy_codes: list[str] | tuple[str, ...] | None = None,
    commit: bool = True,
) -> Reservation:
    """Persist a previously validated reservation interval.

    This intentionally does not repeat policy validation. Callers must obtain
    ``validated`` from :func:`validate_reservation_request` in the current
    transaction before calling this function.
    """
    if created_via not in RESERVATION_CREATED_VIA:
        raise ValidationError(f"Invalid reservation source: {created_via!r}")

    _validate_reservation_shape(
        reservation_type=reservation_type,
        owner_user_id=owner_user_id,
        starts_at=validated.starts_at,
        ends_at=validated.ends_at,
    )
    owner = _get_user(owner_user_id, label="owner") if owner_user_id is not None else None
    if created_by_user_id is not None:
        _get_user(created_by_user_id, label="creator")
    override_codes = reservation_policy.normalize_override_codes(overridden_policy_codes)
    if override_codes and created_via != "admin":
        raise ValidationError("Only admin reservations may record policy overrides")

    reservation = Reservation(
        equipment_id=validated.equipment_id,
        user_id=owner.id if owner is not None else None,
        starts_at=validated.starts_at,
        ends_at=validated.ends_at,
        notes=(notes or "").strip() or None,
        created_via=created_via,
        reservation_type=reservation_type,
        created_by_user_id=created_by_user_id,
        overridden_policy_codes=override_codes,
    )
    db.session.add(reservation)
    if commit:
        db.session.commit()
    else:
        db.session.flush()
    return reservation


def cancel_reservation(
    reservation_id: int,
    actor_user_id: int,
    *,
    commit: bool = True,
) -> Reservation:
    """Cancel an active reservation while preserving history.

    Pass ``commit=False`` to compose cancellation with other reservation work
    in one transaction.
    """
    reservation = _get_reservation(reservation_id, for_update=True)

    actor = _get_user(actor_user_id, label="actor")

    if reservation.status == CANCELED_STATUS:
        raise ValidationError("Reservation is already canceled")

    reservation.status = CANCELED_STATUS
    reservation.canceled_at = _utc_now()
    reservation.canceled_by_user_id = actor.id
    if commit:
        db.session.commit()
        log_mutation(
            "reservation.status_changed",
            actor.username,
            {
                "reservation_id": reservation.id,
                "equipment_id": reservation.equipment_id,
                "old_status": ACTIVE_STATUS,
                "new_status": CANCELED_STATUS,
            },
        )
    else:
        db.session.flush()
    return reservation


def _get_equipment(equipment_id: int, *, for_update: bool) -> Equipment:
    query = (
        db.select(Equipment).options(joinedload(Equipment.reservation_settings)).filter(Equipment.id == equipment_id)
    )
    if for_update:
        query = query.with_for_update()
    equipment = db.session.execute(query).scalar_one_or_none()
    if equipment is None:
        raise ValidationError(f"Equipment with id {equipment_id} not found")
    return equipment


def _get_reservation(reservation_id: int, *, for_update: bool) -> Reservation:
    query = (
        db.select(Reservation)
        .options(
            joinedload(Reservation.equipment),
            joinedload(Reservation.user),
        )
        .filter(Reservation.id == reservation_id)
    )
    if for_update:
        query = query.with_for_update()
    reservation = db.session.execute(query).scalar_one_or_none()
    if reservation is None:
        raise ValidationError(f"Reservation with id {reservation_id} not found")
    return reservation


def _get_user(user_id: int, *, label: str) -> User:
    user = db.session.get(User, user_id)
    if user is None:
        raise ValidationError(f"Reservation {label} with id {user_id} not found")
    return user


def _validate_admin_reservation_request(
    *,
    owner_user_id: int | None,
    notes: str,
    reservation_type: str,
) -> None:
    """Apply admin-only ownership and audit-note requirements."""
    _validate_reservation_shape(
        reservation_type=reservation_type,
        owner_user_id=owner_user_id,
        starts_at=None,
        ends_at=None,
    )
    if not (notes or "").strip():
        raise ValidationError("A note is required for admin reservations and holds")
    if owner_user_id is not None:
        owner = _get_user(owner_user_id, label="owner")
        if not owner.is_active:
            raise ValidationError("Member reservations require an active owner")


def _require_admin_reservation_actor(result: reservation_policy.ReservationValidationResult) -> None:
    """Require the service-level actor privilege used by admin mutations."""
    if not result.actor_can_override_policy:
        raise ValidationError("Admin reservations require a staff or technician actor")


def _log_reservation_created(reservation: Reservation, actor: User) -> None:
    """Write a privacy-conscious structured log after a committed creation."""
    log_mutation(
        "reservation.created",
        actor.username,
        {
            "reservation_id": reservation.id,
            "equipment_id": reservation.equipment_id,
            "owner_user_id": reservation.user_id,
            "reservation_type": reservation.reservation_type,
            "created_via": reservation.created_via,
            "overridden_policy_codes": reservation.overridden_policy_codes or [],
        },
    )


def _validate_reservation_shape(
    *,
    reservation_type: str,
    owner_user_id: int | None,
    starts_at: datetime | None,
    ends_at: datetime | None,
) -> None:
    if reservation_type not in RESERVATION_TYPES:
        raise ValidationError(f"Invalid reservation type: {reservation_type!r}")
    if reservation_type == RESERVATION_TYPE_MEMBER and owner_user_id is None:
        raise ValidationError("Member reservations require an owner")
    if reservation_type == RESERVATION_TYPE_ADMIN_HOLD and owner_user_id is not None:
        raise ValidationError("Admin holds cannot have an owner")
    if starts_at is not None and ends_at is not None and ends_at <= starts_at:
        raise ValidationError("Reservation end must be after start")


def _utc_now() -> datetime:
    """Compatibility seam for deterministic service tests."""
    return utc_now_naive()
