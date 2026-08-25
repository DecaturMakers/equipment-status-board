"""Focused tests for the published static reservation calendar."""

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from esb.extensions import db
from esb.models.pending_notification import PendingNotification
from esb.services import (
    equipment_service,
    notification_service,
    reservation_service,
    static_page_service,
)
from tests.reservation_helpers import create_reservation_row, create_reservation_settings


def _reservation_fixture(make_area, make_equipment, staff_user):
    equipment = make_equipment(name="Laser Cutter", area=make_area(name="Fab Lab"))
    create_reservation_settings(equipment, slug="laser-cutter")
    reservation = create_reservation_row(
        equipment,
        staff_user,
        starts_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=1),
        notes="member secret",
    )
    return equipment, reservation


class TestReservationArtifacts:
    def test_generation_is_standalone_and_anonymous(
        self, app, make_area, make_equipment, staff_user
    ):
        _reservation_fixture(make_area, make_equipment, staff_user)

        html, raw_json = static_page_service.generate_reservations()
        data = json.loads(raw_json)

        assert "daypilot-javascript.min.js" not in html
        assert "DayPilot" in html
        assert "Create or change a reservation through Slack or from inside the makerspace" in html
        assert "reservations.json" in html
        assert data["timeZone"] == "America/New_York"
        assert data["columns"] == [{"id": "laser-cutter", "name": "Laser Cutter"}]
        assert data["events"][0]["resource"] == "laser-cutter"
        assert data["events"][0]["text"] == "Reserved"
        assert "id" not in data["events"][0]
        assert isinstance(data["columns"][0]["id"], str)
        assert staff_user.username not in raw_json
        assert "member secret" not in raw_json

    def test_local_publish_writes_both_sibling_files(self, app, tmp_path):
        app.config.update(STATIC_PAGE_PUSH_METHOD="local", STATIC_PAGE_PUSH_TARGET=str(tmp_path))
        with patch.object(static_page_service, "generate_reservations", return_value=("<html>x</html>", "{}")):
            static_page_service.generate_and_push_reservations()

        assert (tmp_path / "reservations.json").read_text() == "{}"
        assert (tmp_path / "reservations.html").read_text() == "<html>x</html>"

    def test_s3_publish_uses_sibling_keys_and_one_invalidation(self, app):
        app.config.update(
            STATIC_PAGE_PUSH_METHOD="s3",
            STATIC_PAGE_PUSH_TARGET="bucket/public/index.html",
            CLOUDFRONT_DISTRIBUTION_ID="DIST",
        )
        s3 = MagicMock()
        cloudfront = MagicMock()
        cloudfront.create_invalidation.return_value = {"Invalidation": {"Id": "INV"}}

        def client(service):
            return s3 if service == "s3" else cloudfront

        with (
            patch.object(static_page_service, "generate_reservations", return_value=("<html>x</html>", "{}")),
            patch("boto3.client", side_effect=client),
        ):
            static_page_service.generate_and_push_reservations()

        assert [call.kwargs["Key"] for call in s3.put_object.call_args_list] == [
            "public/reservations.json",
            "public/reservations.html",
        ]
        assert s3.put_object.call_args_list[0].kwargs["ContentType"] == static_page_service.JSON_CONTENT_TYPE
        paths = cloudfront.create_invalidation.call_args.kwargs["InvalidationBatch"]["Paths"]
        assert paths == {
            "Quantity": 2,
            "Items": ["/public/reservations.json", "/public/reservations.html"],
        }

    def test_gcs_publish_uses_sibling_objects(self, app):
        app.config.update(
            STATIC_PAGE_PUSH_METHOD="gcs",
            STATIC_PAGE_PUSH_TARGET="bucket/public/index.html",
        )
        from google.cloud import storage

        client = MagicMock()
        bucket = client.bucket.return_value
        json_blob = MagicMock()
        html_blob = MagicMock()
        bucket.blob.side_effect = [json_blob, html_blob]
        with (
            patch.object(static_page_service, "generate_reservations", return_value=("<html>x</html>", "{}")),
            patch.object(storage, "Client", return_value=client),
        ):
            static_page_service.generate_and_push_reservations()

        assert [call.args[0] for call in bucket.blob.call_args_list] == [
            "public/reservations.json",
            "public/reservations.html",
        ]
        json_blob.upload_from_string.assert_called_once_with(
            "{}", content_type=static_page_service.JSON_CONTENT_TYPE
        )


class TestReservationRefreshQueue:
    @pytest.fixture(autouse=True)
    def _configure_static_page_push(self, app, tmp_path):
        app.config["STATIC_PAGE_PUSH_TARGET"] = str(tmp_path)

    def test_delivery_routes_reservation_target(self, app):
        notification = PendingNotification(
            notification_type="static_page_push",
            target="reservations",
            status="pending",
        )
        db.session.add(notification)
        db.session.commit()
        with (
            patch.object(static_page_service, "generate_and_push_reservations") as reservations,
            patch.object(static_page_service, "generate_and_push") as status,
        ):
            notification_service._deliver_static_page_push(notification)
        reservations.assert_called_once_with()
        status.assert_not_called()

    def test_periodic_refresh_starts_immediately_and_is_hourly(self, app):
        notification_service._last_reservation_refresh = None
        with patch.object(notification_service.time, "monotonic", side_effect=[100, 200, 3800, 7500]):
            notification_service._refresh_static_reservations()
            notification_service._refresh_static_reservations()
            notification_service._refresh_static_reservations()
            first = db.session.execute(
                db.select(PendingNotification).filter_by(target="reservations")
            ).scalar_one()
            first.status = "delivered"
            db.session.commit()
            notification_service._refresh_static_reservations()

        rows = db.session.execute(
            db.select(PendingNotification).filter_by(target="reservations")
        ).scalars().all()
        assert len(rows) == 2

    def test_post_commit_queue_failure_is_nonfatal(self, app):
        with patch.object(notification_service, "queue_notification", side_effect=RuntimeError("db down")):
            assert notification_service.queue_static_reservation_refresh("test") is None

    def test_mutation_refresh_is_skipped_without_push_target(self, app):
        app.config["STATIC_PAGE_PUSH_TARGET"] = ""

        assert notification_service.queue_static_reservation_refresh("test") is None
        assert db.session.execute(db.select(PendingNotification)).scalar_one_or_none() is None

    def test_periodic_refresh_is_skipped_without_push_target(self, app):
        app.config["STATIC_PAGE_PUSH_TARGET"] = ""
        notification_service._last_reservation_refresh = None

        notification_service._refresh_static_reservations()

        assert db.session.execute(db.select(PendingNotification)).scalar_one_or_none() is None

    def test_reservation_create_and_cancel_queue_refreshes(
        self, app, make_equipment, staff_user
    ):
        equipment = make_equipment(name="Queue Tool")
        create_reservation_settings(equipment, slug="queue-tool")
        starts_at = datetime.now(UTC).replace(minute=0, second=0, microsecond=0) + timedelta(hours=3)
        reservation = reservation_service.create_reservation(
            equipment_id=equipment.id,
            owner_user_id=staff_user.id,
            starts_at_utc=starts_at,
            duration_minutes=30,
            notes=None,
            created_via="slack",
        )
        reservation_service.cancel_reservation(reservation.id, staff_user.id)

        triggers = [
            row.payload["trigger"]
            for row in db.session.execute(
                db.select(PendingNotification)
                .filter_by(target="reservations")
                .order_by(PendingNotification.id)
            ).scalars()
        ]
        assert triggers == ["reservation_created", "reservation_canceled"]

    def test_settings_and_reservable_rename_queue_refreshes(
        self, app, make_equipment
    ):
        equipment = make_equipment(name="Original Name")
        equipment_service.update_equipment_reservation_settings(
            equipment_id=equipment.id,
            updated_by="staff",
            reservations_enabled=True,
            reservation_slug="original-name",
            min_advance_notice_minutes=0,
            max_advance_notice_minutes=1440,
            min_duration_minutes=30,
            max_duration_minutes=120,
            slot_granularity_minutes=30,
        )
        equipment_service.update_equipment(equipment.id, "staff", name="New Name")

        triggers = [
            row.payload["trigger"]
            for row in db.session.execute(
                db.select(PendingNotification)
                .filter_by(target="reservations")
                .order_by(PendingNotification.id)
            ).scalars()
        ]
        assert triggers == ["reservation_settings_changed", "reservable_equipment_renamed"]

    def test_reservable_archive_queues_refresh(self, app, make_equipment):
        equipment = make_equipment(name="Archive Tool")
        create_reservation_settings(equipment, slug="archive-tool")

        equipment_service.archive_equipment(equipment.id, "staff")

        row = db.session.execute(
            db.select(PendingNotification).filter_by(target="reservations")
        ).scalar_one()
        assert row.payload["trigger"] == "reservable_equipment_archived"

    def test_admin_create_and_replace_each_queue_one_refresh(
        self, app, make_equipment, staff_user
    ):
        equipment = make_equipment(name="Admin Queue Tool")
        create_reservation_settings(equipment, slug="admin-queue-tool")
        starts_at = datetime.now(UTC).replace(minute=0, second=0, microsecond=0) + timedelta(hours=3)
        original = reservation_service.create_admin_reservation(
            equipment_id=equipment.id,
            owner_user_id=staff_user.id,
            starts_at_utc=starts_at,
            duration_minutes=30,
            notes="Admin reservation",
            actor_user_id=staff_user.id,
            reservation_type="member",
            overridden_policy_codes=[],
        )
        reservation_service.replace_admin_reservation(
            reservation_id=original.id,
            equipment_id=equipment.id,
            owner_user_id=staff_user.id,
            starts_at_utc=starts_at + timedelta(hours=1),
            duration_minutes=30,
            notes="Updated reservation",
            actor_user_id=staff_user.id,
            reservation_type="member",
            overridden_policy_codes=[],
        )

        triggers = [
            row.payload["trigger"]
            for row in db.session.execute(
                db.select(PendingNotification)
                .filter_by(target="reservations")
                .order_by(PendingNotification.id)
            ).scalars()
        ]
        assert triggers == ["reservation_created", "reservation_replaced"]
