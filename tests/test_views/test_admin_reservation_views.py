"""Tests for administrative reservation views."""

import re
from datetime import UTC, date, datetime, time, timedelta

import pytest

from esb.extensions import db as _db
from esb.models.equipment_reservation_settings import EquipmentReservationSettings
from esb.models.pending_notification import PendingNotification
from esb.models.reservation import Reservation
from esb.models.user import User
from esb.utils.timezones import MAKERSPACE_TIMEZONE, local_datetime_to_utc


class TestAdminReservations:
    """Tests for GET /admin/reservations."""

    def _settings(self, equipment, *, enabled=True):
        settings = EquipmentReservationSettings(
            equipment_id=equipment.id,
            reservation_slug=f"{equipment.id}-admin-reservation-view",
            reservations_enabled=enabled,
            min_advance_notice_minutes=120,
            max_advance_notice_minutes=14 * 24 * 60,
            min_duration_minutes=30,
            max_duration_minutes=120,
            slot_granularity_minutes=30,
        )
        _db.session.add(settings)
        _db.session.commit()
        return settings

    def _reservation(
        self,
        equipment,
        user,
        *,
        starts_at=None,
        status="active",
        notes="private admin note",
    ):
        starts_at = starts_at or datetime.now(UTC).replace(
            second=0,
            microsecond=0,
        ) + timedelta(hours=3)
        reservation = Reservation(
            equipment_id=equipment.id,
            user_id=user.id,
            starts_at=starts_at.replace(tzinfo=None),
            ends_at=(starts_at + timedelta(hours=1)).replace(tzinfo=None),
            status=status,
            notes=notes,
            created_via="admin",
        )
        _db.session.add(reservation)
        _db.session.commit()
        return reservation

    def test_staff_sees_reservation_management(
        self,
        staff_client,
        staff_user,
        tech_user,
        make_area,
        make_equipment,
    ):
        area = make_area(name="Reservation Shop")
        equipment = make_equipment(name="Laser Cutter", area=area)
        self._settings(equipment)
        self._reservation(equipment, tech_user)

        resp = staff_client.get("/admin/reservations")

        assert resp.status_code == 200
        html = resp.data.decode()
        assert "Reservation Management" in html
        assert "Laser Cutter" in html
        assert "Techuser" in html
        assert "private admin note" in html
        assert "daypilot-javascript.min.js" in html
        assert "cdn.jsdelivr.net" not in html

    def test_technician_can_view_reservation_management(
        self,
        tech_client,
        tech_user,
        make_area,
        make_equipment,
    ):
        area = make_area(name="Reservation Shop")
        equipment = make_equipment(name="Drill Press", area=area)
        self._settings(equipment)
        self._reservation(equipment, tech_user)

        resp = tech_client.get("/admin/reservations")

        assert resp.status_code == 200
        assert b"Reservation Management" in resp.data
        assert b"Drill Press" in resp.data

    def test_unauthenticated_redirects_to_login(self, client):
        resp = client.get("/admin/reservations")

        assert resp.status_code == 302
        assert "/auth/login" in resp.headers["Location"]

    def test_ordinary_user_is_denied(self, client, app):
        member = User(username="memberuser", email="member@example.com", role="member")
        member.set_password("testpass")
        _db.session.add(member)
        _db.session.commit()
        client.post("/auth/login", data={"username": "memberuser", "password": "testpass"})

        resp = client.get("/admin/reservations")

        assert resp.status_code == 403

    def test_filters_by_equipment(
        self,
        staff_client,
        tech_user,
        make_area,
        make_equipment,
    ):
        area = make_area(name="Reservation Shop")
        laser = make_equipment(name="Laser Cutter", area=area)
        drill = make_equipment(name="Drill Press", area=area)
        self._settings(laser)
        self._settings(drill)
        self._reservation(laser, tech_user, notes="laser reservation note")
        self._reservation(drill, tech_user, notes="drill reservation note")

        resp = staff_client.get(f"/admin/reservations?equipment_id={laser.id}")

        assert resp.status_code == 200
        assert b"Laser Cutter" in resp.data
        assert b"laser reservation note" in resp.data
        assert b"drill reservation note" not in resp.data

    def test_invalid_filters_are_ignored_with_warning(self, staff_client, staff_user):
        resp = staff_client.get(
            "/admin/reservations?starts_on=invalid&ends_on=2020-01-01"
            "&status=unknown&created_via=api&area_id=-1&page=-2",
        )

        assert resp.status_code == 200
        assert b"Ignoring invalid reservation start date filter" in resp.data
        assert b"Ignoring invalid reservation status filter" in resp.data
        assert b"Ignoring invalid reservation source filter" in resp.data
        assert b"Ignoring invalid reservation area filter" in resp.data
        assert b"Ignoring invalid reservation page" in resp.data

    def test_archived_and_disabled_equipment_history_remains_visible(
        self,
        staff_client,
        tech_user,
        make_area,
        make_equipment,
    ):
        area = make_area(name="History Shop")
        archived = make_equipment(name="Archived Laser", area=area, is_archived=True)
        disabled = make_equipment(name="Disabled Drill", area=area)
        self._settings(archived, enabled=False)
        self._settings(disabled, enabled=False)
        self._reservation(archived, tech_user, notes="archived history")
        self._reservation(disabled, tech_user, notes="disabled history")

        resp = staff_client.get("/admin/reservations")

        assert resp.status_code == 200
        assert b"Archived Laser" in resp.data
        assert b"Disabled Drill" in resp.data
        assert b"archived history" in resp.data
        assert b"disabled history" in resp.data
        assert b"Archived" in resp.data
        assert b"Disabled" in resp.data

    def test_history_is_paginated_and_calendar_navigation_preserves_filters(
        self,
        staff_client,
        tech_user,
        make_area,
        make_equipment,
    ):
        area = make_area(name="Pagination Shop")
        equipment = make_equipment(name="Paged Tool", area=area)
        self._settings(equipment)
        for number in range(26):
            self._reservation(
                equipment,
                tech_user,
                starts_at=datetime.now(UTC).replace(second=0, microsecond=0) + timedelta(hours=number + 3),
                notes=f"page note {number}",
            )

        resp = staff_client.get(f"/admin/reservations?equipment_id={equipment.id}")

        assert resp.status_code == 200
        html = resp.data.decode()
        assert "Page 1 of 2" in html
        assert "calendar_date=" in html
        assert f"equipment_id={equipment.id}" in html
        assert 'data-admin-reservation-tab="calendar"' in html
        assert 'data-admin-reservation-tab="list"' in html
        assert "reservationDetailModal" in html
        assert "data-reservation-edit" in html
        assert "data-reservation-cancel" in html

    def test_admin_details_do_not_leak_to_public_calendar(
        self,
        staff_client,
        tech_user,
        make_area,
        make_equipment,
    ):
        area = make_area(name="Reservation Shop")
        equipment = make_equipment(name="Laser Cutter", area=area)
        self._settings(equipment)
        self._reservation(equipment, tech_user)

        admin_resp = staff_client.get("/admin/reservations")
        public_resp = staff_client.get("/reservations/")

        assert admin_resp.status_code == 200
        assert public_resp.status_code == 200
        assert b"Techuser" in admin_resp.data
        assert b"private admin note" in admin_resp.data
        assert b"Reserved" in public_resp.data
        assert b"Techuser" not in public_resp.data
        assert b"private admin note" not in public_resp.data


class TestAdminReservationCreation:
    """Tests for the admin reservation and administrative-hold workflow."""

    def _settings(self, equipment, *, min_duration=30):
        settings = EquipmentReservationSettings(
            equipment_id=equipment.id,
            reservation_slug=f"{equipment.name.lower().replace(' ', '-')}-{equipment.id}",
            reservations_enabled=True,
            min_advance_notice_minutes=120,
            max_advance_notice_minutes=14 * 24 * 60,
            min_duration_minutes=min_duration,
            max_duration_minutes=120,
            slot_granularity_minutes=30,
        )
        _db.session.add(settings)
        _db.session.commit()

    def _data(self, equipment, owner_user_id, **overrides):
        start = datetime.now(UTC).astimezone(MAKERSPACE_TIMEZONE).replace(
            minute=0,
            second=0,
            microsecond=0,
        ) + timedelta(hours=3)
        values = {
            "reservation_type": "member",
            "equipment_id": str(equipment.id),
            "owner_user_id": str(owner_user_id),
            "start_date": start.strftime("%Y-%m-%d"),
            "start_time": start.strftime("%H:%M"),
            "duration_minutes": "60",
            "notes": "Admin scheduling note",
        }
        values.update(overrides)
        return values

    def _confirmation_token(self, response):
        match = re.search(
            rb'name="confirmation_token"[^>]*value="([^"]+)"',
            response.data,
        )
        assert match, response.data.decode()
        return match.group(1).decode()

    def test_get_shows_only_eligible_equipment_and_active_members(
        self,
        staff_client,
        staff_user,
        make_area,
        make_equipment,
    ):
        area = make_area("Admin Creation Area")
        enabled = make_equipment(name="Eligible Reservation Tool", area=area)
        disabled = make_equipment(name="Disabled Reservation Tool", area=area)
        self._settings(enabled)
        self._settings(disabled)
        disabled.reservation_settings.reservations_enabled = False
        inactive = User(username="inactiveowner", email="inactive@example.com", role="technician")
        inactive.set_password("testpass")
        inactive.is_active = False
        _db.session.add(inactive)
        _db.session.commit()

        response = staff_client.get("/admin/reservations/new")

        assert response.status_code == 200
        assert b"Eligible Reservation Tool" in response.data
        assert b"Disabled Reservation Tool" not in response.data
        assert b"Inactiveowner" not in response.data
        assert b"Staffuser" in response.data

    def test_creates_member_reservation(self, staff_client, staff_user, make_equipment):
        equipment = make_equipment(name="Admin Member Tool")
        self._settings(equipment)

        response = staff_client.post(
            "/admin/reservations/new",
            data=self._data(equipment, staff_user.id),
        )

        assert response.status_code == 302
        reservation = _db.session.execute(_db.select(Reservation).filter_by(equipment_id=equipment.id)).scalar_one()
        assert reservation.user_id == staff_user.id
        assert reservation.reservation_type == "member"
        assert reservation.created_via == "admin"
        assert reservation.notes == "Admin scheduling note"

    def test_creates_admin_hold_without_owner(self, tech_client, tech_user, make_equipment):
        equipment = make_equipment(name="Admin Hold Form Tool")
        self._settings(equipment)

        response = tech_client.post(
            "/admin/reservations/new",
            data=self._data(
                equipment,
                0,
                reservation_type="admin_hold",
                notes="Maintenance hold",
            ),
        )

        assert response.status_code == 302
        reservation = _db.session.execute(_db.select(Reservation).filter_by(equipment_id=equipment.id)).scalar_one()
        assert reservation.user_id is None
        assert reservation.reservation_type == "admin_hold"
        assert reservation.created_by_user_id == tech_user.id

    def test_notes_are_required(self, staff_client, staff_user, make_equipment):
        equipment = make_equipment(name="Admin Note Tool")
        self._settings(equipment)

        response = staff_client.post(
            "/admin/reservations/new",
            data=self._data(equipment, staff_user.id, notes=""),
        )

        assert response.status_code == 200
        assert b"This field is required." in response.data
        assert _db.session.query(Reservation).count() == 0

    def test_conflict_requires_signed_confirmation(
        self,
        staff_client,
        staff_user,
        make_equipment,
    ):
        equipment = make_equipment(name="Confirmed Conflict Tool")
        self._settings(equipment)
        data = self._data(equipment, staff_user.id)
        local_start = datetime.strptime(
            f"{data['start_date']} {data['start_time']}",
            "%Y-%m-%d %H:%M",
        ).replace(tzinfo=MAKERSPACE_TIMEZONE)
        existing = Reservation(
            equipment_id=equipment.id,
            user_id=staff_user.id,
            starts_at=local_start.astimezone(UTC).replace(tzinfo=None),
            ends_at=(local_start + timedelta(minutes=60)).astimezone(UTC).replace(tzinfo=None),
            created_via="admin",
        )
        _db.session.add(existing)
        _db.session.commit()

        review = staff_client.post("/admin/reservations/new", data=data)
        token = self._confirmation_token(review)
        confirmed = staff_client.post(
            "/admin/reservations/new",
            data={"confirmation_token": token},
        )

        assert review.status_code == 200
        assert b"Reservation overlaps an existing reservation" in review.data
        assert b"Confirmed Conflict Tool" in review.data
        assert staff_user.display_name.encode() in review.data
        assert b"data-submit-once" in review.data
        assert review.data.count(b'name="confirmation_token"') == 1
        assert confirmed.status_code == 302
        reservations = _db.session.execute(_db.select(Reservation).filter_by(equipment_id=equipment.id)).scalars().all()
        assert len(reservations) == 2
        assert reservations[-1].overridden_policy_codes == ["conflict"]

    def test_confirmation_rechecks_new_conflicts(
        self,
        staff_client,
        staff_user,
        make_equipment,
    ):
        equipment = make_equipment(name="Changed Warning Tool")
        self._settings(equipment, min_duration=90)
        data = self._data(equipment, staff_user.id, duration_minutes="60")

        review = staff_client.post("/admin/reservations/new", data=data)
        token = self._confirmation_token(review)
        local_start = datetime.strptime(
            f"{data['start_date']} {data['start_time']}",
            "%Y-%m-%d %H:%M",
        ).replace(tzinfo=MAKERSPACE_TIMEZONE)
        _db.session.add(
            Reservation(
                equipment_id=equipment.id,
                user_id=staff_user.id,
                starts_at=local_start.astimezone(UTC).replace(tzinfo=None),
                ends_at=(local_start + timedelta(minutes=60)).astimezone(UTC).replace(tzinfo=None),
                created_via="admin",
            )
        )
        _db.session.commit()

        response = staff_client.post(
            "/admin/reservations/new",
            data={"confirmation_token": token},
        )

        assert response.status_code == 200
        assert b"Reservation warnings changed" in response.data
        assert _db.session.query(Reservation).count() == 1

    def test_edit_replaces_original_and_preserves_lineage(
        self,
        staff_client,
        staff_user,
        make_equipment,
    ):
        equipment = make_equipment(name="Edit Replacement Tool")
        self._settings(equipment)
        data = self._data(equipment, staff_user.id)
        local_start = datetime.strptime(
            f"{data['start_date']} {data['start_time']}",
            "%Y-%m-%d %H:%M",
        ).replace(tzinfo=MAKERSPACE_TIMEZONE)
        original = Reservation(
            equipment_id=equipment.id,
            user_id=staff_user.id,
            starts_at=local_start.astimezone(UTC).replace(tzinfo=None),
            ends_at=(local_start + timedelta(minutes=60)).astimezone(UTC).replace(tzinfo=None),
            created_via="slack",
        )
        _db.session.add(original)
        _db.session.commit()

        edit_data = self._data(
            equipment,
            staff_user.id,
            notes="Replacement admin note",
        )
        get_response = staff_client.get(f"/admin/reservations/{original.id}/edit")
        response = staff_client.post(
            f"/admin/reservations/{original.id}/edit",
            data=edit_data,
        )

        assert get_response.status_code == 200
        assert b"Edit Reservation" in get_response.data
        assert response.status_code == 302
        updated_original = _db.session.get(Reservation, original.id)
        replacement = _db.session.execute(
            _db.select(Reservation).filter_by(replaces_reservation_id=original.id)
        ).scalar_one()
        assert updated_original.status == "canceled"
        assert replacement.status == "active"
        assert replacement.notes == "Replacement admin note"
        assert replacement.created_by_user_id == staff_user.id

    def test_cancel_requires_confirmation_and_is_idempotent(
        self,
        tech_client,
        tech_user,
        make_equipment,
    ):
        equipment = make_equipment(name="Cancellation Tool")
        self._settings(equipment)
        start = datetime.now(UTC).replace(second=0, microsecond=0) + timedelta(hours=3)
        reservation = Reservation(
            equipment_id=equipment.id,
            user_id=tech_user.id,
            starts_at=start.replace(tzinfo=None),
            ends_at=(start + timedelta(minutes=60)).replace(tzinfo=None),
            created_via="slack",
        )
        _db.session.add(reservation)
        _db.session.commit()

        review = tech_client.post(f"/admin/reservations/{reservation.id}/cancel")
        token = self._confirmation_token(review)
        canceled = tech_client.post(
            f"/admin/reservations/{reservation.id}/cancel",
            data={"confirmation_token": token},
        )
        repeated = tech_client.post(f"/admin/reservations/{reservation.id}/cancel")

        assert review.status_code == 200
        assert b"Cancel Reservation" in review.data
        assert b"data-submit-once" in review.data
        assert review.data.count(b'name="confirmation_token"') == 1
        assert canceled.status_code == 302
        assert _db.session.get(Reservation, reservation.id).status == "canceled"
        assert _db.session.get(Reservation, reservation.id).canceled_by_user_id == tech_user.id
        assert repeated.status_code == 302
        repeated_page = tech_client.get("/admin/reservations")
        assert b"Reservation is already canceled." in repeated_page.data

    def test_failed_edit_validation_keeps_original_active(
        self,
        staff_client,
        staff_user,
        make_equipment,
    ):
        equipment = make_equipment(name="Failed Edit Tool")
        self._settings(equipment)
        data = self._data(equipment, staff_user.id)
        local_start = datetime.strptime(
            f"{data['start_date']} {data['start_time']}",
            "%Y-%m-%d %H:%M",
        ).replace(tzinfo=MAKERSPACE_TIMEZONE)
        original = Reservation(
            equipment_id=equipment.id,
            user_id=staff_user.id,
            starts_at=local_start.astimezone(UTC).replace(tzinfo=None),
            ends_at=(local_start + timedelta(minutes=60)).astimezone(UTC).replace(tzinfo=None),
            created_via="admin",
        )
        _db.session.add(original)
        _db.session.commit()

        response = staff_client.post(
            f"/admin/reservations/{original.id}/edit",
            data=self._data(equipment, staff_user.id, duration_minutes="0"),
        )

        assert response.status_code == 200
        assert b"Number must be at least 1." in response.data
        assert _db.session.get(Reservation, original.id).status == "active"

    def test_member_mutations_queue_create_update_and_cancel_notifications(
        self,
        app,
        staff_client,
        staff_user,
        make_equipment,
    ):
        app.config["SLACK_BOT_TOKEN"] = "xoxb-test"
        equipment = make_equipment(name="Notification Mutation Tool")
        self._settings(equipment)
        data = self._data(equipment, staff_user.id)

        created = staff_client.post("/admin/reservations/new", data=data)
        original = _db.session.execute(_db.select(Reservation).filter_by(equipment_id=equipment.id)).scalar_one()
        updated = staff_client.post(
            f"/admin/reservations/{original.id}/edit",
            data=self._data(equipment, staff_user.id, notes="Updated for notification"),
        )
        replacement = _db.session.execute(
            _db.select(Reservation).filter_by(replaces_reservation_id=original.id)
        ).scalar_one()
        cancel_review = staff_client.post(f"/admin/reservations/{replacement.id}/cancel")
        canceled = staff_client.post(
            f"/admin/reservations/{replacement.id}/cancel",
            data={"confirmation_token": self._confirmation_token(cancel_review)},
        )

        notifications = (
            _db.session.execute(
                _db.select(PendingNotification).filter_by(notification_type="slack_dm").order_by(PendingNotification.id)
            )
            .scalars()
            .all()
        )
        assert created.status_code == 302
        assert updated.status_code == 302
        assert canceled.status_code == 302
        assert [item.payload["event_type"] for item in notifications] == [
            "reservation_created",
            "reservation_updated",
            "reservation_canceled",
        ]

    def test_reassignment_notifies_the_previous_owner_of_cancellation(
        self,
        app,
        staff_client,
        staff_user,
        make_equipment,
    ):
        app.config["SLACK_BOT_TOKEN"] = "xoxb-test"
        equipment = make_equipment(name="Reassignment Notification Tool")
        self._settings(equipment)
        new_owner = User(username="newowner", email="newowner@example.com", role="technician")
        new_owner.set_password("testpass")
        _db.session.add(new_owner)
        _db.session.commit()

        data = self._data(equipment, staff_user.id)
        local_start = datetime.strptime(
            f"{data['start_date']} {data['start_time']}",
            "%Y-%m-%d %H:%M",
        ).replace(tzinfo=MAKERSPACE_TIMEZONE)
        original = Reservation(
            equipment_id=equipment.id,
            user_id=staff_user.id,
            starts_at=local_start.astimezone(UTC).replace(tzinfo=None),
            ends_at=(local_start + timedelta(minutes=60)).astimezone(UTC).replace(tzinfo=None),
            created_via="admin",
        )
        _db.session.add(original)
        _db.session.commit()

        response = staff_client.post(
            f"/admin/reservations/{original.id}/edit",
            data=self._data(equipment, new_owner.id, notes="Reassigned reservation"),
        )

        notifications = (
            _db.session.execute(
                _db.select(PendingNotification).filter_by(notification_type="slack_dm").order_by(PendingNotification.id)
            )
            .scalars()
            .all()
        )
        assert response.status_code == 302
        assert [(item.target, item.payload["event_type"]) for item in notifications] == [
            (staff_user.email, "reservation_canceled"),
            (new_owner.email, "reservation_updated"),
        ]


class TestAdminReservationMutationCsrf:
    def test_create_edit_and_cancel_reject_missing_csrf_tokens(
        self,
        app,
        staff_client,
        staff_user,
        make_equipment,
    ):
        equipment = make_equipment(name="Reservation CSRF Tool")
        settings = EquipmentReservationSettings(
            equipment_id=equipment.id,
            reservation_slug="reservation-csrf-tool",
            reservations_enabled=True,
            min_advance_notice_minutes=0,
            max_advance_notice_minutes=14 * 24 * 60,
            min_duration_minutes=30,
            max_duration_minutes=120,
            slot_granularity_minutes=30,
        )
        start = datetime.now(UTC).replace(second=0, microsecond=0) + timedelta(hours=3)
        reservation = Reservation(
            equipment_id=equipment.id,
            user_id=staff_user.id,
            starts_at=start.replace(tzinfo=None),
            ends_at=(start + timedelta(hours=1)).replace(tzinfo=None),
            created_via="admin",
        )
        _db.session.add_all([settings, reservation])
        _db.session.commit()
        app.config["WTF_CSRF_ENABLED"] = True

        create = staff_client.post("/admin/reservations/new", data={})
        edit = staff_client.post(f"/admin/reservations/{reservation.id}/edit", data={})
        cancel = staff_client.post(f"/admin/reservations/{reservation.id}/cancel", data={})

        assert create.status_code == 400
        assert edit.status_code == 400
        assert cancel.status_code == 400
        assert _db.session.get(Reservation, reservation.id).status == "active"


class TestAdminReservationTimezoneValidation:
    def test_rejects_dst_gap_and_ambiguous_local_time(self, app):
        from esb.utils.exceptions import ValidationError

        with pytest.raises(ValidationError, match="does not exist"):
            local_datetime_to_utc(date(2026, 3, 8), time(2, 30))
        with pytest.raises(ValidationError, match="ambiguous"):
            local_datetime_to_utc(date(2026, 11, 1), time(1, 30))


# --- Area Management View Tests ---
