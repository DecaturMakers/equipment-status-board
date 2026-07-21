"""Tests for public and administrative reservation read models."""

from datetime import UTC, datetime

from sqlalchemy import event

from esb.extensions import db as _db
from esb.services import reservation_read_service
from esb.utils.timezones import MAKERSPACE_TIMEZONE
from tests.reservation_helpers import (
    create_reservation_row as _reservation,
    create_reservation_settings as _settings,
)


class TestListReservableEquipment:
    def test_lists_non_archived_equipment_with_enabled_settings(self, app, make_area, make_equipment):
        area = make_area(name="Scheduling Area")
        enabled = make_equipment(name="Enabled Tool", area=area)
        disabled = make_equipment(name="Disabled Tool", area=area)
        ordinary = make_equipment(name="Ordinary Tool", area=area)
        archived = make_equipment(name="Archived Tool", area=area, is_archived=True)
        _settings(enabled, slug="enabled-tool")
        _settings(disabled, slug="disabled-tool", enabled=False)
        _settings(archived, slug="archived-tool")

        equipment = reservation_read_service.list_reservable_equipment()

        assert [item.name for item in equipment] == ["Enabled Tool"]
        assert disabled not in equipment
        assert ordinary not in equipment
        assert archived not in equipment


class TestPublicCalendarData:
    def test_returns_columns_and_anonymized_reservation_details(
        self,
        app,
        make_area,
        make_equipment,
        staff_user,
    ):
        area = make_area(name="Calendar Area")
        reservable = make_equipment(name="Laser Cutter", area=area)
        ordinary = make_equipment(name="Ordinary Tool", area=area)
        disabled = make_equipment(name="Disabled Tool", area=area)
        _settings(reservable, slug="laser-calendar")
        _settings(disabled, slug="disabled-calendar", enabled=False)
        _reservation(
            reservable,
            staff_user,
            starts_at=datetime(2026, 6, 15, 14, 0),
            ends_at=datetime(2026, 6, 15, 15, 30),
            notes="private member details",
        )

        data = reservation_read_service.get_public_calendar_data(
            now=datetime(2026, 6, 15, 12, 0, tzinfo=UTC),
        )

        assert (
            data["startDate"]
            == datetime(2026, 6, 15, 12, 0, tzinfo=UTC).astimezone(MAKERSPACE_TIMEZONE).date().isoformat()
        )
        assert data["columns"] == [{"id": str(reservable.id), "name": "Laser Cutter"}]
        assert len(data["events"]) == 1
        assert data["events"][0]["resource"] == str(reservable.id)
        assert data["events"][0]["text"] == "Reserved"
        assert "reservedBy" not in data["events"][0]
        assert "note" not in data["events"][0]
        assert "2026-06-15T" in data["events"][0]["start"]
        assert "2026-06-15T" in data["events"][0]["end"]
        serialized = str(data)
        assert staff_user.display_name not in serialized
        assert "private member details" not in serialized
        assert ordinary.name not in serialized
        assert disabled.name not in serialized

    def test_uses_makerspace_timezone_for_calendar_date(self, app):
        data = reservation_read_service.get_public_calendar_data(
            now=datetime(2026, 6, 15, 3, 0, tzinfo=UTC),
        )

        assert data["startDate"] == "2026-06-14"


class TestAdminReservationReadModelQueries:
    def test_calendar_and_history_use_a_bounded_query_count(
        self,
        app,
        make_equipment,
        staff_user,
    ):
        equipment = make_equipment(name="Bounded Query Tool")
        _settings(equipment)
        _reservation(
            equipment,
            staff_user,
            starts_at=datetime(2026, 6, 15, 13, 0),
            ends_at=datetime(2026, 6, 15, 14, 0),
        )
        filters = reservation_read_service.AdminReservationFilters(
            starts_on=datetime(2026, 6, 15).date(),
            ends_on=datetime(2026, 6, 15).date(),
            calendar_date=datetime(2026, 6, 15).date(),
        )
        statements = []

        def record_statement(*args):
            statements.append(args[2])

        event.listen(_db.engine, "before_cursor_execute", record_statement)
        try:
            data = reservation_read_service.get_admin_calendar_data(filters=filters)
        finally:
            event.remove(_db.engine, "before_cursor_execute", record_statement)

        assert data["pagination"]["total"] == 1
        assert len(statements) <= 5


class TestPublicAvailability:
    def test_public_availability_is_utc_and_privacy_safe(
        self,
        app,
        make_area,
        make_equipment,
        staff_user,
    ):
        area = make_area(name="Public Area")
        enabled = make_equipment(name="Enabled Public Tool", area=area)
        disabled = make_equipment(name="Disabled Public Tool", area=area)
        archived = make_equipment(name="Archived Public Tool", area=area, is_archived=True)
        _settings(enabled, slug="enabled-public-tool")
        _settings(disabled, slug="disabled-public-tool", enabled=False)
        _settings(archived, slug="archived-public-tool")
        _reservation(
            enabled,
            staff_user,
            starts_at=datetime(2026, 6, 15, 14, 0),
            ends_at=datetime(2026, 6, 15, 15, 0),
            notes="secret member note",
        )

        availability = reservation_read_service.get_public_availability(
            now=datetime(2026, 6, 15, 12, 0, tzinfo=UTC),
        )

        names = [item["name"] for item in availability["equipment"]]
        assert names == ["Enabled Public Tool"]
        enabled_item = availability["equipment"][0]
        assert enabled_item["reservations"] == [
            {
                "label": "Reserved",
                "starts_at": "2026-06-15T14:00:00+00:00",
                "ends_at": "2026-06-15T15:00:00+00:00",
            }
        ]
        assert enabled_item["min_advance_notice_minutes"] == 0
        assert enabled_item["max_advance_notice_minutes"] == 14 * 24 * 60
        assert "timezone" not in availability
        assert "generated_at" not in availability
        assert "secret member note" not in str(availability)
        assert staff_user.username not in str(availability)
