"""Tests for reservation service scheduling rules."""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from esb.extensions import db as _db
from esb.models.equipment_reservation_settings import EquipmentReservationSettings
from esb.models.reservation import Reservation
from esb.services import reservation_service
from esb.utils.exceptions import ValidationError
from tests.conftest import _create_user


FROZEN_NOW = datetime(2026, 6, 15, 12, 0)


def _freeze_now(monkeypatch, value=FROZEN_NOW):
    monkeypatch.setattr(reservation_service, '_utc_now', lambda: value)


def _settings(
    equipment,
    *,
    slug='bookable-tool',
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
    _db.session.add(settings)
    _db.session.commit()
    return settings


def _reservation(
    equipment,
    user,
    *,
    starts_at,
    ends_at=None,
    status='active',
    notes='private note',
):
    reservation = Reservation(
        equipment_id=equipment.id,
        user_id=user.id,
        starts_at=starts_at,
        ends_at=ends_at or starts_at + timedelta(hours=1),
        status=status,
        notes=notes,
        created_via='slack',
    )
    _db.session.add(reservation)
    _db.session.commit()
    return reservation


class TestListReservableEquipment:
    def test_lists_non_archived_equipment_with_enabled_settings(self, app, make_area, make_equipment):
        area = make_area(name='Scheduling Area')
        enabled = make_equipment(name='Enabled Tool', area=area)
        disabled = make_equipment(name='Disabled Tool', area=area)
        ordinary = make_equipment(name='Ordinary Tool', area=area)
        archived = make_equipment(name='Archived Tool', area=area, is_archived=True)
        _settings(enabled, slug='enabled-tool')
        _settings(disabled, slug='disabled-tool', enabled=False)
        _settings(archived, slug='archived-tool')

        equipment = reservation_service.list_reservable_equipment()

        assert [item.name for item in equipment] == ['Enabled Tool']
        assert disabled not in equipment
        assert ordinary not in equipment
        assert archived not in equipment


class TestCreateReservation:
    def test_creates_reservation_and_stores_utc_naive_time(
        self, app, make_equipment, staff_user, monkeypatch,
    ):
        _freeze_now(monkeypatch)
        equipment = make_equipment(name='Laser Cutter')
        _settings(equipment)
        starts_at_utc = datetime(2026, 6, 15, 15, 0, tzinfo=UTC)

        reservation = reservation_service.create_reservation(
            equipment.id,
            staff_user.id,
            starts_at_utc,
            60,
            '  setup job  ',
            'slack',
        )

        assert reservation.id is not None
        assert reservation.starts_at == datetime(2026, 6, 15, 15, 0)
        assert reservation.ends_at == datetime(2026, 6, 15, 16, 0)
        assert reservation.notes == 'setup job'
        assert reservation.status == 'active'
        assert reservation.created_via == 'slack'

    def test_rejects_non_utc_reservation_start(
        self, app, make_equipment, staff_user, monkeypatch,
    ):
        _freeze_now(monkeypatch)
        equipment = make_equipment(name='UTC Boundary Tool')
        _settings(equipment)

        with pytest.raises(ValidationError, match='UTC-aware'):
            reservation_service.create_reservation(
                equipment.id,
                staff_user.id,
                datetime(2026, 6, 15, 13, 0),
                60,
                None,
                'slack',
            )

        with pytest.raises(ValidationError, match='UTC datetimes'):
            reservation_service.create_reservation(
                equipment.id,
                staff_user.id,
                datetime(2026, 6, 15, 10, 0, tzinfo=ZoneInfo('America/Chicago')),
                60,
                None,
                'slack',
            )

    def test_rejects_archived_non_reservable_and_disabled_equipment(
        self, app, make_area, make_equipment, staff_user, monkeypatch,
    ):
        _freeze_now(monkeypatch)
        area = make_area(name='Validation Area')
        archived = make_equipment(name='Archived', area=area, is_archived=True)
        ordinary = make_equipment(name='Ordinary', area=area)
        disabled = make_equipment(name='Disabled', area=area)
        _settings(archived, slug='archived')
        _settings(disabled, slug='disabled', enabled=False)
        starts_at = datetime(2026, 6, 15, 13, 0, tzinfo=UTC)

        with pytest.raises(ValidationError, match='archived'):
            reservation_service.create_reservation(
                archived.id, staff_user.id, starts_at, 60, None, 'slack'
            )
        with pytest.raises(ValidationError, match='not reservable'):
            reservation_service.create_reservation(
                ordinary.id, staff_user.id, starts_at, 60, None, 'slack'
            )
        with pytest.raises(ValidationError, match='disabled'):
            reservation_service.create_reservation(
                disabled.id, staff_user.id, starts_at, 60, None, 'slack'
            )

    @pytest.mark.parametrize(
        ('duration', 'message'),
        [
            (15, 'at least'),
            (150, 'cannot exceed'),
            (45, 'increments'),
        ],
    )
    def test_enforces_duration_rules(
        self, app, make_equipment, monkeypatch, duration, message,
    ):
        _freeze_now(monkeypatch)
        member_user = _create_user('member', username=f'member_duration_{duration}')
        equipment = make_equipment(name='Duration Tool')
        _settings(equipment, min_duration=30, max_duration=120, granularity=30)

        with pytest.raises(ValidationError, match=message):
            reservation_service.create_reservation(
                equipment.id,
                member_user.id,
                datetime(2026, 6, 15, 13, 0, tzinfo=UTC),
                duration,
                None,
                'slack',
            )

    @pytest.mark.parametrize(
        ('field_name', 'value', 'message'),
        [
            ('min_advance_notice_minutes', -1, 'Minimum advance notice'),
            ('max_advance_notice_minutes', 0, 'Maximum advance notice'),
            ('max_advance_notice_minutes', -1, 'Maximum advance notice'),
            ('min_duration_minutes', 0, 'Minimum reservation duration'),
            ('max_duration_minutes', 15, 'Maximum reservation duration'),
            ('slot_granularity_minutes', 0, 'Slot granularity'),
            ('min_duration_minutes', 45, 'Minimum reservation duration'),
            ('max_duration_minutes', 100, 'Maximum reservation duration'),
        ],
    )
    def test_rejects_invalid_reservation_settings_policy(
        self, app, make_equipment, staff_user, monkeypatch, field_name, value, message,
    ):
        _freeze_now(monkeypatch)
        equipment = make_equipment(name=f'Invalid Policy Tool {field_name} {value}')
        settings = _settings(equipment)
        setattr(settings, field_name, value)
        _db.session.commit()

        with pytest.raises(ValidationError, match=message):
            reservation_service.create_reservation(
                equipment.id,
                staff_user.id,
                datetime(2026, 6, 15, 13, 0, tzinfo=UTC),
                60,
                None,
                'slack',
            )

    def test_enforces_advance_notice_and_slot_granularity(
        self, app, make_equipment, monkeypatch,
    ):
        _freeze_now(monkeypatch)
        member_user = _create_user('member', username='member_advance_policy')
        equipment = make_equipment(name='Window Tool')
        _settings(equipment, min_advance=120, max_advance=180, granularity=30)

        with pytest.raises(ValidationError, match='past'):
            reservation_service.create_reservation(
                equipment.id,
                member_user.id,
                datetime(2026, 6, 15, 11, 30, tzinfo=UTC),
                60,
                None,
                'slack',
            )
        with pytest.raises(ValidationError, match='minimum advance notice'):
            reservation_service.create_reservation(
                equipment.id,
                member_user.id,
                datetime(2026, 6, 15, 13, 30, tzinfo=UTC),
                60,
                None,
                'slack',
            )
        with pytest.raises(ValidationError, match='maximum advance notice'):
            reservation_service.create_reservation(
                equipment.id,
                member_user.id,
                datetime(2026, 6, 15, 16, 0, tzinfo=UTC),
                60,
                None,
                'slack',
            )
        with pytest.raises(ValidationError, match='Start time'):
            reservation_service.create_reservation(
                equipment.id,
                member_user.id,
                datetime(2026, 6, 15, 14, 15, tzinfo=UTC),
                60,
                None,
                'slack',
            )
        with pytest.raises(ValidationError, match='Start time'):
            reservation_service.create_reservation(
                equipment.id,
                member_user.id,
                datetime(2026, 6, 15, 14, 0, 30, tzinfo=UTC),
                60,
                None,
                'slack',
            )

    @pytest.mark.parametrize('role', ['staff', 'technician'])
    def test_staff_and_technicians_bypass_duration_and_advance_notice_bounds(
        self, app, make_equipment, monkeypatch, role,
    ):
        _freeze_now(monkeypatch)
        user = _create_user(role, username=f'{role}_reservation_override')
        equipment = make_equipment(name=f'{role.title()} Override Tool')
        _settings(
            equipment,
            min_advance=120,
            max_advance=180,
            min_duration=60,
            max_duration=120,
            granularity=15,
        )

        short_notice = reservation_service.create_reservation(
            equipment.id,
            user.id,
            datetime(2026, 6, 15, 12, 15, tzinfo=UTC),
            15,
            None,
            'slack',
        )
        far_future = reservation_service.create_reservation(
            equipment.id,
            user.id,
            datetime(2026, 6, 20, 12, 0, tzinfo=UTC),
            180,
            None,
            'slack',
        )

        assert short_notice.starts_at == datetime(2026, 6, 15, 12, 15)
        assert short_notice.ends_at == datetime(2026, 6, 15, 12, 30)
        assert far_future.ends_at == datetime(2026, 6, 20, 15, 0)

    def test_policy_override_still_requires_future_aligned_non_overlapping_time(
        self, app, make_equipment, staff_user, tech_user, monkeypatch,
    ):
        _freeze_now(monkeypatch)
        equipment = make_equipment(name='Override Guardrail Tool')
        _settings(equipment, min_duration=60, max_duration=120, granularity=30)
        _reservation(
            equipment,
            tech_user,
            starts_at=datetime(2026, 6, 15, 14, 0),
            ends_at=datetime(2026, 6, 15, 15, 0),
        )

        with pytest.raises(ValidationError, match='past'):
            reservation_service.create_reservation(
                equipment.id,
                staff_user.id,
                datetime(2026, 6, 15, 11, 30, tzinfo=UTC),
                30,
                None,
                'slack',
            )
        with pytest.raises(ValidationError, match='increments'):
            reservation_service.create_reservation(
                equipment.id,
                staff_user.id,
                datetime(2026, 6, 15, 13, 0, tzinfo=UTC),
                45,
                None,
                'slack',
            )
        with pytest.raises(ValidationError, match='Start time'):
            reservation_service.create_reservation(
                equipment.id,
                staff_user.id,
                datetime(2026, 6, 15, 13, 15, tzinfo=UTC),
                30,
                None,
                'slack',
            )
        with pytest.raises(ValidationError, match='overlaps'):
            reservation_service.create_reservation(
                equipment.id,
                staff_user.id,
                datetime(2026, 6, 15, 14, 30, tzinfo=UTC),
                30,
                None,
                'slack',
            )

    def test_prevents_overlapping_active_reservations(
        self, app, make_equipment, staff_user, tech_user, monkeypatch,
    ):
        _freeze_now(monkeypatch)
        equipment = make_equipment(name='Conflict Tool')
        _settings(equipment)
        _reservation(
            equipment,
            staff_user,
            starts_at=datetime(2026, 6, 15, 13, 0),
            ends_at=datetime(2026, 6, 15, 14, 0),
        )

        with pytest.raises(ValidationError, match='overlaps'):
            reservation_service.create_reservation(
                equipment.id,
                tech_user.id,
                datetime(2026, 6, 15, 13, 30, tzinfo=UTC),
                60,
                None,
                'slack',
            )

    def test_canceled_reservations_do_not_block_time(
        self, app, make_equipment, staff_user, tech_user, monkeypatch,
    ):
        _freeze_now(monkeypatch)
        equipment = make_equipment(name='Canceled Conflict Tool')
        _settings(equipment)
        _reservation(
            equipment,
            staff_user,
            starts_at=datetime(2026, 6, 15, 13, 0),
            ends_at=datetime(2026, 6, 15, 14, 0),
            status='canceled',
        )

        reservation = reservation_service.create_reservation(
            equipment.id,
            tech_user.id,
            datetime(2026, 6, 15, 13, 0, tzinfo=UTC),
            60,
            None,
            'slack',
        )

        assert reservation.id is not None


class TestCancelReservation:
    def test_cancel_reservation_preserves_history(
        self, app, make_equipment, staff_user, tech_user, monkeypatch,
    ):
        _freeze_now(monkeypatch)
        equipment = make_equipment(name='Cancel Tool')
        reservation = _reservation(
            equipment,
            tech_user,
            starts_at=datetime(2026, 6, 15, 13, 0),
        )

        canceled = reservation_service.cancel_reservation(reservation.id, staff_user.id)

        assert canceled.status == 'canceled'
        assert canceled.canceled_by_user_id == staff_user.id
        assert canceled.canceled_at == FROZEN_NOW
        assert _db.session.get(Reservation, reservation.id) is not None


class TestListUserUpcomingReservations:
    def test_returns_only_active_future_reservations(
        self, app, make_equipment, staff_user, monkeypatch,
    ):
        _freeze_now(monkeypatch)
        equipment = make_equipment(name='Upcoming Tool')
        future = _reservation(
            equipment,
            staff_user,
            starts_at=datetime(2026, 6, 15, 13, 0),
        )
        _reservation(
            equipment,
            staff_user,
            starts_at=datetime(2026, 6, 15, 9, 0),
            ends_at=datetime(2026, 6, 15, 10, 0),
        )
        _reservation(
            equipment,
            staff_user,
            starts_at=datetime(2026, 6, 15, 15, 0),
            status='canceled',
        )

        reservations = reservation_service.list_user_upcoming_reservations(staff_user.id)

        assert reservations == [future]


class TestPublicAvailability:
    def test_public_availability_is_utc_and_privacy_safe(
        self, app, make_area, make_equipment, staff_user,
    ):
        area = make_area(name='Public Area')
        enabled = make_equipment(name='Enabled Public Tool', area=area)
        disabled = make_equipment(name='Disabled Public Tool', area=area)
        archived = make_equipment(name='Archived Public Tool', area=area, is_archived=True)
        _settings(enabled, slug='enabled-public-tool')
        _settings(disabled, slug='disabled-public-tool', enabled=False)
        _settings(archived, slug='archived-public-tool')
        _reservation(
            enabled,
            staff_user,
            starts_at=datetime(2026, 6, 15, 14, 0),
            ends_at=datetime(2026, 6, 15, 15, 0),
            notes='secret member note',
        )

        availability = reservation_service.get_public_availability(
            now=datetime(2026, 6, 15, 12, 0, tzinfo=UTC),
        )

        names = [item['name'] for item in availability['equipment']]
        assert names == ['Enabled Public Tool']
        enabled_item = availability['equipment'][0]
        assert enabled_item['reservations'] == [{
            'label': 'Reserved',
            'starts_at': '2026-06-15T14:00:00+00:00',
            'ends_at': '2026-06-15T15:00:00+00:00',
        }]
        assert enabled_item['min_advance_notice_minutes'] == 0
        assert enabled_item['max_advance_notice_minutes'] == 14 * 24 * 60
        assert 'timezone' not in availability
        assert 'generated_at' not in availability
        assert 'secret member note' not in str(availability)
        assert staff_user.username not in str(availability)
