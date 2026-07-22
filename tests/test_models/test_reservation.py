"""Tests for reservation-related models."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.exc import IntegrityError

from esb.extensions import db as _db
from esb.models.equipment_reservation_settings import EquipmentReservationSettings
from esb.models.reservation import (
    RESERVATION_TYPE_ADMIN_HOLD,
    RESERVATION_TYPE_MEMBER,
    Reservation,
)


def _settings(equipment, slug='stub-equipment'):
    return EquipmentReservationSettings(
        equipment_id=equipment.id,
        reservation_slug=slug,
        reservations_enabled=True,
        min_advance_notice_minutes=2 * 60,
        max_advance_notice_minutes=14 * 24 * 60,
        min_duration_minutes=30,
        max_duration_minutes=120,
        slot_granularity_minutes=30,
    )


class TestEquipmentReservationSettings:
    """Tests for equipment reservation settings."""

    def test_create_settings_for_equipment(self, app, make_equipment):
        """Settings row links one-to-one with equipment."""
        equipment = make_equipment(name='Reservable Tool')
        settings = _settings(equipment)

        _db.session.add(settings)
        _db.session.commit()

        assert settings.id is not None
        assert settings.equipment == equipment
        assert equipment.reservation_settings == settings
        assert settings.reservations_enabled is True

    def test_equipment_without_settings_is_allowed(self, app, make_equipment):
        """Equipment does not need a settings row."""
        equipment = make_equipment(name='Regular Tool')

        assert equipment.reservation_settings is None

    def test_only_one_settings_row_per_equipment(self, app, make_equipment):
        """equipment_id is unique in settings."""
        equipment = make_equipment(name='Unique Settings Tool')
        _db.session.add(_settings(equipment, slug='unique-settings-tool'))
        _db.session.commit()

        _db.session.add(_settings(equipment, slug='duplicate-settings-tool'))
        with pytest.raises(IntegrityError):
            _db.session.commit()
        _db.session.rollback()

    def test_reservation_slug_required_and_unique(self, app, make_area, make_equipment):
        """reservation_slug rejects NULL and duplicates."""
        area = make_area(name='Reservation Slug Area')
        first = make_equipment(name='First Reservable', area=area)
        second = make_equipment(name='Second Reservable', area=area)
        _db.session.add(_settings(first, slug='same-slug'))
        _db.session.commit()

        _db.session.add(_settings(second, slug='same-slug'))
        with pytest.raises(IntegrityError):
            _db.session.commit()
        _db.session.rollback()

        third = make_equipment(name='Third Reservable', area=area)
        settings = _settings(third, slug='third-reservable')
        settings.reservation_slug = None
        _db.session.add(settings)
        with pytest.raises(IntegrityError):
            _db.session.commit()
        _db.session.rollback()

    def test_required_duration_fields_reject_null(self, app, make_equipment):
        """Reservation duration policy fields are non-null once settings exist."""
        equipment = make_equipment(name='Policy Tool')
        settings = _settings(equipment, slug='policy-tool')
        settings.min_duration_minutes = None

        _db.session.add(settings)
        with pytest.raises(IntegrityError):
            _db.session.commit()
        _db.session.rollback()


class TestReservation:
    """Tests for reservation model relationships and constraints."""

    def test_create_active_reservation(self, app, make_equipment, staff_user):
        """Reservation links equipment and user."""
        equipment = make_equipment(name='Bookable Tool')
        starts_at = datetime(2026, 6, 15, 14, 0, tzinfo=UTC)
        reservation = Reservation(
            equipment_id=equipment.id,
            user_id=staff_user.id,
            starts_at=starts_at,
            ends_at=starts_at + timedelta(hours=1),
            created_via='slack',
            notes='Bring safety glasses',
        )

        _db.session.add(reservation)
        _db.session.commit()

        assert reservation.id is not None
        assert reservation.status == 'active'
        assert reservation.equipment == equipment
        assert reservation.user == staff_user
        assert equipment.reservations.count() == 1
        assert staff_user.reservations.count() == 1
        assert reservation.canceled_at is None
        assert reservation.canceled_by_user is None
        assert reservation.reservation_type == RESERVATION_TYPE_MEMBER
        assert reservation.overridden_policy_codes == []

    def test_admin_hold_has_no_member_and_tracks_creator(
        self, app, make_equipment, staff_user,
    ):
        equipment = make_equipment(name='Held Tool')
        reservation = Reservation(
            equipment_id=equipment.id,
            starts_at=datetime(2026, 6, 15, 14, 0, tzinfo=UTC),
            ends_at=datetime(2026, 6, 15, 15, 0, tzinfo=UTC),
            created_via='admin',
            reservation_type=RESERVATION_TYPE_ADMIN_HOLD,
            created_by_user_id=staff_user.id,
            overridden_policy_codes=['conflict'],
        )

        _db.session.add(reservation)
        _db.session.commit()

        assert reservation.user is None
        assert reservation.is_admin_hold is True
        assert reservation.created_by_user == staff_user
        assert staff_user.created_reservations.count() == 1
        assert reservation.overridden_policy_codes == ['conflict']

    def test_replacement_lineage_is_navigable(self, app, make_equipment, staff_user):
        equipment = make_equipment(name='Replacement Tool')
        original = Reservation(
            equipment_id=equipment.id,
            user_id=staff_user.id,
            starts_at=datetime(2026, 6, 15, 14, 0, tzinfo=UTC),
            ends_at=datetime(2026, 6, 15, 15, 0, tzinfo=UTC),
            created_via='admin',
        )
        _db.session.add(original)
        _db.session.commit()
        replacement = Reservation(
            equipment_id=equipment.id,
            user_id=staff_user.id,
            starts_at=datetime(2026, 6, 15, 15, 0, tzinfo=UTC),
            ends_at=datetime(2026, 6, 15, 16, 0, tzinfo=UTC),
            created_via='admin',
            replaces_reservation_id=original.id,
        )
        _db.session.add(replacement)
        _db.session.commit()

        assert replacement.replaces_reservation == original
        assert original.replacement_reservations.all() == [replacement]

    def test_canceled_reservation_links_canceling_user(self, app, make_equipment, staff_user, tech_user):
        """Canceled reservation can track who canceled it."""
        equipment = make_equipment(name='Cancelable Tool')
        starts_at = datetime(2026, 6, 15, 16, 0, tzinfo=UTC)
        canceled_at = datetime(2026, 6, 14, 12, 0, tzinfo=UTC)
        reservation = Reservation(
            equipment_id=equipment.id,
            user_id=tech_user.id,
            starts_at=starts_at,
            ends_at=starts_at + timedelta(hours=2),
            status='canceled',
            created_via='admin',
            canceled_at=canceled_at,
            canceled_by_user_id=staff_user.id,
        )

        _db.session.add(reservation)
        _db.session.commit()

        assert reservation.canceled_by_user == staff_user
        assert staff_user.canceled_reservations.count() == 1

    def test_required_reservation_fields_reject_null(self, app, make_equipment):
        """Reservation requires equipment, user, times, and created_via."""
        equipment = make_equipment(name='Incomplete Reservation Tool')
        reservation = Reservation(
            equipment_id=equipment.id,
            starts_at=datetime(2026, 6, 15, 14, 0, tzinfo=UTC),
            ends_at=datetime(2026, 6, 15, 15, 0, tzinfo=UTC),
            created_via='slack',
        )

        _db.session.add(reservation)
        with pytest.raises(IntegrityError):
            _db.session.commit()
        _db.session.rollback()

    def test_member_and_hold_owner_constraints_are_enforced(
        self, app, make_equipment, staff_user,
    ):
        equipment = make_equipment(name='Type Constraint Tool')
        member_without_owner = Reservation(
            equipment_id=equipment.id,
            starts_at=datetime(2026, 6, 15, 14, 0, tzinfo=UTC),
            ends_at=datetime(2026, 6, 15, 15, 0, tzinfo=UTC),
            created_via='admin',
            reservation_type=RESERVATION_TYPE_MEMBER,
        )
        _db.session.add(member_without_owner)
        with pytest.raises(IntegrityError):
            _db.session.commit()
        _db.session.rollback()

    def test_interval_constraint_is_enforced(self, app, make_equipment, staff_user):
        equipment = make_equipment(name='Interval Constraint Tool')
        invalid_interval = Reservation(
            equipment_id=equipment.id,
            user_id=staff_user.id,
            starts_at=datetime(2026, 6, 15, 15, 0, tzinfo=UTC),
            ends_at=datetime(2026, 6, 15, 14, 0, tzinfo=UTC),
            created_via='admin',
        )
        _db.session.add(invalid_interval)

        with pytest.raises(IntegrityError):
            _db.session.commit()
        _db.session.rollback()

        hold_with_owner = Reservation(
            equipment_id=equipment.id,
            user_id=staff_user.id,
            starts_at=datetime(2026, 6, 15, 14, 0, tzinfo=UTC),
            ends_at=datetime(2026, 6, 15, 15, 0, tzinfo=UTC),
            created_via='admin',
            reservation_type=RESERVATION_TYPE_ADMIN_HOLD,
        )
        _db.session.add(hold_with_owner)
        with pytest.raises(IntegrityError):
            _db.session.commit()
        _db.session.rollback()

    def test_notes_are_nullable(self, app, make_equipment, staff_user):
        """Reservation notes are optional."""
        equipment = make_equipment(name='No Notes Tool')
        starts_at = datetime(2026, 6, 15, 18, 0, tzinfo=UTC)
        reservation = Reservation(
            equipment_id=equipment.id,
            user_id=staff_user.id,
            starts_at=starts_at,
            ends_at=starts_at + timedelta(minutes=30),
            created_via='slack',
        )

        _db.session.add(reservation)
        _db.session.commit()

        assert reservation.notes is None
