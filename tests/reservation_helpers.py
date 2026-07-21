"""Shared factories for reservation service and view tests."""

from datetime import datetime, timedelta

from esb.extensions import db
from esb.models.equipment_reservation_settings import EquipmentReservationSettings
from esb.models.reservation import Reservation
from esb.services import reservation_read_service, reservation_service

FROZEN_NOW = datetime(2026, 6, 15, 12, 0)


def freeze_reservation_now(monkeypatch, value=FROZEN_NOW):
    monkeypatch.setattr(reservation_service, "_utc_now", lambda: value)
    monkeypatch.setattr(reservation_read_service, "_utc_now", lambda: value)


def create_reservation_settings(
    equipment,
    *,
    slug="bookable-tool",
    enabled=True,
    min_advance=0,
    max_advance=14 * 24 * 60,
    min_duration=30,
    max_duration=120,
    granularity=30,
):
    settings = EquipmentReservationSettings(
        equipment_id=equipment.id,
        reservation_slug=slug,
        reservations_enabled=enabled,
        min_advance_notice_minutes=min_advance,
        max_advance_notice_minutes=max_advance,
        min_duration_minutes=min_duration,
        max_duration_minutes=max_duration,
        slot_granularity_minutes=granularity,
    )
    db.session.add(settings)
    db.session.commit()
    return settings


def create_reservation_row(
    equipment,
    user,
    *,
    starts_at,
    ends_at=None,
    status="active",
    notes="private note",
):
    reservation = Reservation(
        equipment_id=equipment.id,
        user_id=user.id,
        starts_at=starts_at,
        ends_at=ends_at or starts_at + timedelta(hours=1),
        status=status,
        notes=notes,
        created_via="slack",
    )
    db.session.add(reservation)
    db.session.commit()
    return reservation
