"""Tests for reservation service scheduling rules."""

import json
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.dialects import mysql

from esb.extensions import db as _db
from esb.models.reservation import Reservation
from esb.services import reservation_policy, reservation_read_service, reservation_service
from esb.utils.exceptions import ValidationError
from tests.conftest import _create_user
from tests.reservation_helpers import (
    FROZEN_NOW,
    create_reservation_row as _reservation,
    create_reservation_settings as _settings,
    freeze_reservation_now as _freeze_now,
)


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

    def test_actor_role_controls_policy_override_not_reservation_owner(
        self,
        app,
        make_equipment,
        staff_user,
        monkeypatch,
    ):
        _freeze_now(monkeypatch)
        member = _create_user("member", username="reservation_owner_member")
        equipment = make_equipment(name="Actor Policy Tool")
        _settings(
            equipment,
            min_advance=120,
            min_duration=60,
            max_duration=120,
            granularity=15,
        )

        reservation = reservation_service.create_reservation(
            equipment_id=equipment.id,
            owner_user_id=member.id,
            starts_at_utc=datetime(2026, 6, 15, 12, 15, tzinfo=UTC),
            duration_minutes=15,
            notes=None,
            created_via="admin",
            actor_user_id=staff_user.id,
        )

        assert reservation.user_id == member.id
        assert reservation.starts_at == datetime(2026, 6, 15, 12, 15)
        assert reservation.created_by_user_id == staff_user.id

    def test_validation_does_not_persist_a_reservation(
        self,
        app,
        make_equipment,
        staff_user,
        monkeypatch,
    ):
        _freeze_now(monkeypatch)
        equipment = make_equipment(name="Validate Only Tool")
        _settings(equipment)

        validated = reservation_service.validate_reservation_request(
            equipment_id=equipment.id,
            starts_at_utc=datetime(2026, 6, 15, 13, 0, tzinfo=UTC),
            duration_minutes=60,
            actor_user_id=staff_user.id,
        )

        assert validated.equipment_id == equipment.id
        assert validated.starts_at == datetime(2026, 6, 15, 13, 0)
        assert validated.ends_at == datetime(2026, 6, 15, 14, 0)
        assert _db.session.query(Reservation).count() == 0

    def test_evaluation_returns_all_structured_policy_violations(
        self,
        app,
        make_equipment,
        monkeypatch,
    ):
        _freeze_now(monkeypatch)
        member = _create_user("member", username="structured_validation_member")
        equipment = make_equipment(name="Structured Validation Tool")
        _settings(
            equipment,
            min_advance=120,
            max_advance=180,
            min_duration=60,
            max_duration=120,
            granularity=30,
        )

        result = reservation_service.evaluate_reservation_request(
            equipment_id=equipment.id,
            starts_at_utc=datetime(2026, 6, 15, 12, 15, tzinfo=UTC),
            duration_minutes=45,
            actor_user_id=member.id,
        )

        assert [violation.code for violation in result.violations] == [
            reservation_policy.VIOLATION_DURATION_BELOW_MINIMUM,
            reservation_policy.VIOLATION_DURATION_GRANULARITY,
            reservation_policy.VIOLATION_MIN_ADVANCE_NOTICE,
            reservation_policy.VIOLATION_START_GRANULARITY,
        ]
        assert result.actor_can_override_policy is False
        assert result.hard_violations == ()
        assert [violation.code for violation in result.overridable_violations] == [
            reservation_policy.VIOLATION_DURATION_BELOW_MINIMUM,
            reservation_policy.VIOLATION_DURATION_GRANULARITY,
            reservation_policy.VIOLATION_MIN_ADVANCE_NOTICE,
            reservation_policy.VIOLATION_START_GRANULARITY,
        ]

    def test_evaluation_marks_equipment_failures_as_hard_violations(
        self,
        app,
        make_equipment,
        staff_user,
        monkeypatch,
    ):
        _freeze_now(monkeypatch)
        equipment = make_equipment(name="Archived Structured Tool", is_archived=True)
        _settings(equipment)

        result = reservation_service.evaluate_reservation_request(
            equipment_id=equipment.id,
            starts_at_utc=datetime(2026, 6, 15, 13, 0, tzinfo=UTC),
            duration_minutes=60,
            actor_user_id=staff_user.id,
        )

        assert [violation.code for violation in result.hard_violations] == [
            reservation_policy.VIOLATION_EQUIPMENT_ARCHIVED,
        ]
        assert result.overridable_violations == ()

    def test_locked_evaluation_uses_a_current_read_for_conflicts(
        self,
        app,
        make_equipment,
        staff_user,
        monkeypatch,
    ):
        _freeze_now(monkeypatch)
        equipment = make_equipment(name="Current Read Tool")
        _settings(equipment)
        original_execute = _db.session.execute
        statements = []

        def tracked_execute(statement, *args, **kwargs):
            statements.append(statement)
            return original_execute(statement, *args, **kwargs)

        monkeypatch.setattr(_db.session, "execute", tracked_execute)

        reservation_service.evaluate_reservation_request(
            equipment_id=equipment.id,
            starts_at_utc=datetime(2026, 6, 15, 13, 0, tzinfo=UTC),
            duration_minutes=60,
            actor_user_id=staff_user.id,
        )
        reservation_service.evaluate_reservation_request(
            equipment_id=equipment.id,
            starts_at_utc=datetime(2026, 6, 15, 13, 0, tzinfo=UTC),
            duration_minutes=60,
            actor_user_id=staff_user.id,
            lock_equipment=True,
        )

        conflict_sql = [
            str(statement.compile(dialect=mysql.dialect()))
            for statement in statements
            if "FROM reservations" in str(statement.compile(dialect=mysql.dialect()))
        ]
        assert len(conflict_sql) == 2
        assert "FOR UPDATE" not in conflict_sql[0]
        assert "FOR UPDATE" in conflict_sql[1]

    def test_create_can_leave_transaction_to_caller(
        self,
        app,
        make_equipment,
        staff_user,
        monkeypatch,
    ):
        _freeze_now(monkeypatch)
        equipment = make_equipment(name="Caller Transaction Tool")
        _settings(equipment)

        reservation = reservation_service.create_reservation(
            equipment_id=equipment.id,
            owner_user_id=staff_user.id,
            starts_at_utc=datetime(2026, 6, 15, 13, 0, tzinfo=UTC),
            duration_minutes=60,
            notes=None,
            created_via="admin",
            actor_user_id=staff_user.id,
            commit=False,
        )

        reservation_id = reservation.id
        assert reservation_id is not None
        _db.session.rollback()
        assert _db.session.get(Reservation, reservation_id) is None

    def test_slot_granularity_uses_makerspace_wall_time(
        self,
        app,
        make_equipment,
        staff_user,
        monkeypatch,
    ):
        _freeze_now(monkeypatch)
        equipment = make_equipment(name="Local Slot Tool")
        _settings(
            equipment,
            min_duration=45,
            max_duration=90,
            granularity=45,
        )

        reservation = reservation_service.create_reservation(
            equipment_id=equipment.id,
            owner_user_id=staff_user.id,
            starts_at_utc=datetime(2026, 6, 15, 13, 0, tzinfo=UTC),
            duration_minutes=45,
            notes=None,
            created_via="slack",
        )

        assert reservation.starts_at == datetime(2026, 6, 15, 13, 0)

    def test_creates_admin_hold_with_actor_and_override_audit_data(
        self,
        app,
        make_equipment,
        staff_user,
        monkeypatch,
    ):
        _freeze_now(monkeypatch)
        equipment = make_equipment(name="Admin Hold Tool")
        _settings(equipment)

        reservation = reservation_service.create_reservation(
            equipment_id=equipment.id,
            owner_user_id=None,
            starts_at_utc=datetime(2026, 6, 15, 13, 0, tzinfo=UTC),
            duration_minutes=60,
            notes="Maintenance window",
            created_via="admin",
            actor_user_id=staff_user.id,
            reservation_type="admin_hold",
            overridden_policy_codes=["conflict"],
        )

        assert reservation.user_id is None
        assert reservation.reservation_type == "admin_hold"
        assert reservation.created_by_user_id == staff_user.id
        assert reservation.overridden_policy_codes == ["conflict"]

    @pytest.mark.parametrize(
        ("reservation_type", "owner_user_id", "message"),
        [
            ("member", None, "require an owner"),
            ("admin_hold", "owner", "cannot have an owner"),
            ("unknown", "owner", "Invalid reservation type"),
        ],
    )
    def test_rejects_invalid_reservation_shapes(
        self,
        app,
        make_equipment,
        staff_user,
        monkeypatch,
        reservation_type,
        owner_user_id,
        message,
    ):
        _freeze_now(monkeypatch)
        equipment = make_equipment(name=f"Invalid Shape {reservation_type}")
        _settings(equipment)
        owner_id = staff_user.id if owner_user_id == "owner" else owner_user_id

        with pytest.raises(ValidationError, match=message):
            reservation_service.create_reservation(
                equipment_id=equipment.id,
                owner_user_id=owner_id,
                starts_at_utc=datetime(2026, 6, 15, 13, 0, tzinfo=UTC),
                duration_minutes=60,
                notes=None,
                created_via="admin",
                actor_user_id=staff_user.id,
                reservation_type=reservation_type,
            )

    def test_rejects_invalid_override_audit_codes(
        self,
        app,
        make_equipment,
        staff_user,
        monkeypatch,
    ):
        _freeze_now(monkeypatch)
        equipment = make_equipment(name="Invalid Override Audit Tool")
        _settings(equipment)

        with pytest.raises(ValidationError, match="Invalid overridden policy code"):
            reservation_service.create_reservation(
                equipment_id=equipment.id,
                owner_user_id=staff_user.id,
                starts_at_utc=datetime(2026, 6, 15, 13, 0, tzinfo=UTC),
                duration_minutes=60,
                notes=None,
                created_via="admin",
                actor_user_id=staff_user.id,
                overridden_policy_codes=["not_a_real_policy"],
            )


class TestAdminReservationCreation:
    """Explicit confirmation behavior for admin-created reservations and holds."""

    def test_requires_active_member_and_a_note(
        self,
        app,
        make_equipment,
        staff_user,
        monkeypatch,
    ):
        _freeze_now(monkeypatch)
        equipment = make_equipment(name="Admin Eligibility Tool")
        _settings(equipment)
        inactive = _create_user("member", username="inactive_reservation_member")
        inactive.is_active = False
        _db.session.commit()
        values = {
            "equipment_id": equipment.id,
            "owner_user_id": inactive.id,
            "starts_at_utc": datetime(2026, 6, 15, 13, 0, tzinfo=UTC),
            "duration_minutes": 60,
            "notes": "Admin scheduling note",
            "actor_user_id": staff_user.id,
            "reservation_type": "member",
        }

        with pytest.raises(ValidationError, match="active owner"):
            reservation_service.preview_admin_reservation(**values)

        values["owner_user_id"] = staff_user.id
        values["notes"] = "   "
        with pytest.raises(ValidationError, match="note is required"):
            reservation_service.preview_admin_reservation(**values)

    def test_requires_privileged_actor_at_the_service_boundary(
        self,
        app,
        make_equipment,
        monkeypatch,
    ):
        _freeze_now(monkeypatch)
        member = _create_user("member", username="unprivileged_admin_actor")
        equipment = make_equipment(name="Privileged Admin Tool")
        _settings(equipment)
        values = {
            "equipment_id": equipment.id,
            "owner_user_id": member.id,
            "starts_at_utc": datetime(2026, 6, 15, 13, 0, tzinfo=UTC),
            "duration_minutes": 60,
            "notes": "Attempted admin scheduling note",
            "actor_user_id": member.id,
            "reservation_type": "member",
        }

        with pytest.raises(ValidationError, match="staff or technician actor"):
            reservation_service.preview_admin_reservation(**values)
        with pytest.raises(ValidationError, match="staff or technician actor"):
            reservation_service.create_admin_reservation(**values)

        assert _db.session.query(Reservation).count() == 0

    def test_creates_hold_only_after_confirming_current_warning_codes(
        self,
        app,
        make_equipment,
        staff_user,
        monkeypatch,
    ):
        _freeze_now(monkeypatch)
        equipment = make_equipment(name="Confirmed Hold Tool")
        _settings(equipment, min_duration=60)
        values = {
            "equipment_id": equipment.id,
            "owner_user_id": None,
            "starts_at_utc": datetime(2026, 6, 15, 13, 0, tzinfo=UTC),
            "duration_minutes": 30,
            "notes": "Short maintenance window",
            "actor_user_id": staff_user.id,
            "reservation_type": "admin_hold",
        }

        preview = reservation_service.preview_admin_reservation(**values)
        assert [item.code for item in preview.overridable_violations] == [
            reservation_policy.VIOLATION_DURATION_BELOW_MINIMUM,
        ]
        with pytest.raises(ValidationError, match="warnings changed"):
            reservation_service.create_admin_reservation(**values)

        reservation = reservation_service.create_admin_reservation(
            **values,
            overridden_policy_codes=[reservation_policy.VIOLATION_DURATION_BELOW_MINIMUM],
        )

        assert reservation.reservation_type == "admin_hold"
        assert reservation.user_id is None
        assert reservation.overridden_policy_codes == [
            reservation_policy.VIOLATION_DURATION_BELOW_MINIMUM,
        ]
        availability = reservation_read_service.get_public_availability(
            now=datetime(2026, 6, 15, 12, 0, tzinfo=UTC),
        )
        assert availability["equipment"][0]["reservations"][0]["label"] == "Reserved"

    def test_persist_rejects_invalid_interval(
        self,
        app,
        make_equipment,
        staff_user,
    ):
        equipment = make_equipment(name="Persist Invalid Interval Tool")
        invalid_interval = reservation_policy.ValidatedReservation(
            equipment_id=equipment.id,
            starts_at=datetime(2026, 6, 15, 14, 0),
            ends_at=datetime(2026, 6, 15, 14, 0),
        )

        with pytest.raises(ValidationError, match="end must be after start"):
            reservation_service.persist_reservation(
                validated=invalid_interval,
                owner_user_id=staff_user.id,
                notes=None,
                created_via="admin",
                created_by_user_id=staff_user.id,
            )

    def test_rejects_non_utc_reservation_start(
        self,
        app,
        make_equipment,
        staff_user,
        monkeypatch,
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
        self,
        app,
        make_area,
        make_equipment,
        staff_user,
        monkeypatch,
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
            reservation_service.create_reservation(archived.id, staff_user.id, starts_at, 60, None, "slack")
        with pytest.raises(ValidationError, match='not reservable'):
            reservation_service.create_reservation(ordinary.id, staff_user.id, starts_at, 60, None, "slack")
        with pytest.raises(ValidationError, match='disabled'):
            reservation_service.create_reservation(disabled.id, staff_user.id, starts_at, 60, None, "slack")

    @pytest.mark.parametrize(
        ('duration', 'message'),
        [
            (15, 'at least'),
            (150, 'cannot exceed'),
            (45, 'increments'),
        ],
    )
    def test_enforces_duration_rules(
        self,
        app,
        make_equipment,
        monkeypatch,
        duration,
        message,
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
        self,
        app,
        make_equipment,
        staff_user,
        monkeypatch,
        field_name,
        value,
        message,
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
        self,
        app,
        make_equipment,
        monkeypatch,
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
        self,
        app,
        make_equipment,
        monkeypatch,
        role,
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
        self,
        app,
        make_equipment,
        staff_user,
        tech_user,
        monkeypatch,
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
        self,
        app,
        make_equipment,
        staff_user,
        tech_user,
        monkeypatch,
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
        self,
        app,
        make_equipment,
        staff_user,
        tech_user,
        monkeypatch,
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
    def test_cancel_locks_reservation_before_changing_status(
        self,
        app,
        make_equipment,
        staff_user,
        tech_user,
        monkeypatch,
    ):
        equipment = make_equipment(name="Locked Cancel Tool")
        reservation = _reservation(
            equipment,
            tech_user,
            starts_at=datetime(2026, 6, 15, 13, 0),
        )
        original_get = reservation_service._get_reservation
        calls = []

        def tracked_get(reservation_id, *, for_update):
            calls.append((reservation_id, for_update))
            return original_get(reservation_id, for_update=for_update)

        monkeypatch.setattr(reservation_service, "_get_reservation", tracked_get)

        reservation_service.cancel_reservation(reservation.id, staff_user.id)

        assert calls == [(reservation.id, True)]

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

    def test_cancel_can_leave_transaction_to_caller(
        self,
        app,
        make_equipment,
        staff_user,
        tech_user,
        monkeypatch,
    ):
        _freeze_now(monkeypatch)
        equipment = make_equipment(name="Caller Transaction Cancel Tool")
        reservation = _reservation(
            equipment,
            tech_user,
            starts_at=datetime(2026, 6, 15, 13, 0),
        )

        canceled = reservation_service.cancel_reservation(
            reservation.id,
            staff_user.id,
            commit=False,
        )

        assert canceled.status == "canceled"
        _db.session.rollback()
        restored = _db.session.get(Reservation, reservation.id)
        assert restored.status == "active"


class TestReplaceAdminReservation:
    def test_replaces_active_reservation_without_self_conflict(
        self,
        app,
        make_equipment,
        staff_user,
        monkeypatch,
    ):
        _freeze_now(monkeypatch)
        equipment = make_equipment(name="Replacement Tool")
        _settings(equipment)
        original = _reservation(
            equipment,
            staff_user,
            starts_at=datetime(2026, 6, 15, 13, 0),
            ends_at=datetime(2026, 6, 15, 14, 0),
        )

        replacement = reservation_service.replace_admin_reservation(
            reservation_id=original.id,
            equipment_id=equipment.id,
            owner_user_id=staff_user.id,
            starts_at_utc=datetime(2026, 6, 15, 13, 0, tzinfo=UTC),
            duration_minutes=60,
            notes="Updated reservation note",
            actor_user_id=staff_user.id,
            reservation_type="member",
        )

        updated_original = _db.session.get(Reservation, original.id)
        assert replacement.status == "active"
        assert replacement.replaces_reservation_id == original.id
        assert updated_original.status == "canceled"
        assert updated_original.canceled_by_user_id == staff_user.id

    def test_failed_replacement_leaves_original_active(
        self,
        app,
        make_equipment,
        staff_user,
        monkeypatch,
    ):
        _freeze_now(monkeypatch)
        equipment = make_equipment(name="Failed Replacement Tool")
        _settings(equipment)
        original = _reservation(
            equipment,
            staff_user,
            starts_at=datetime(2026, 6, 15, 13, 0),
        )

        with pytest.raises(ValidationError, match="duration must be greater"):
            reservation_service.replace_admin_reservation(
                reservation_id=original.id,
                equipment_id=equipment.id,
                owner_user_id=staff_user.id,
                starts_at_utc=datetime(2026, 6, 15, 13, 0, tzinfo=UTC),
                duration_minutes=0,
                notes="Invalid replacement",
                actor_user_id=staff_user.id,
                reservation_type="member",
            )

        assert _db.session.get(Reservation, original.id).status == "active"


class TestReservationMutationLogging:
    def test_logs_admin_create_replace_and_cancel_without_notes(
        self,
        app,
        make_equipment,
        staff_user,
        monkeypatch,
        capture,
    ):
        _freeze_now(monkeypatch)
        equipment = make_equipment(name="Logged Reservation Tool")
        _settings(equipment)
        values = {
            "equipment_id": equipment.id,
            "owner_user_id": staff_user.id,
            "starts_at_utc": datetime(2026, 6, 15, 13, 0, tzinfo=UTC),
            "duration_minutes": 60,
            "notes": "Private reservation details",
            "actor_user_id": staff_user.id,
            "reservation_type": "member",
        }

        original = reservation_service.create_admin_reservation(**values)
        replacement = reservation_service.replace_admin_reservation(
            reservation_id=original.id,
            **values,
        )
        reservation_service.cancel_reservation(replacement.id, staff_user.id)

        entries = [
            json.loads(record.message) for record in capture.records if '"event": "reservation.' in record.message
        ]
        assert [entry["event"] for entry in entries] == [
            "reservation.created",
            "reservation.updated",
            "reservation.status_changed",
        ]
        assert entries[0]["data"]["reservation_id"] == original.id
        assert entries[1]["data"]["replacement_reservation_id"] == replacement.id
        assert entries[2]["data"]["new_status"] == "canceled"
        assert "Private reservation details" not in json.dumps(entries)


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

        reservations = reservation_read_service.list_user_upcoming_reservations(staff_user.id)

        assert reservations == [future]


class TestGetUserReservation:
    def test_returns_reservation_owned_by_user(self, app, make_equipment, staff_user):
        equipment = make_equipment(name='Owned Reservation Tool')
        reservation = _reservation(
            equipment,
            staff_user,
            starts_at=datetime(2026, 6, 15, 13, 0),
        )

        result = reservation_read_service.get_user_reservation(reservation.id, staff_user.id)

        assert result == reservation

    def test_returns_none_for_other_user_reservation(
        self, app, make_equipment, staff_user,
    ):
        other_user = _create_user('member', username='other_reservation_owner')
        equipment = make_equipment(name='Other User Reservation Tool')
        reservation = _reservation(
            equipment,
            other_user,
            starts_at=datetime(2026, 6, 15, 13, 0),
        )

        result = reservation_read_service.get_user_reservation(reservation.id, staff_user.id)

        assert result is None
