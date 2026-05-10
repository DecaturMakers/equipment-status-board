"""Tests for repair service layer."""

import json
from datetime import UTC, date, datetime, timedelta

import pytest

from esb.extensions import db as _db
from esb.models.audit_log import AuditLog
from esb.models.repair_record import RepairRecord
from esb.models.repair_timeline_entry import RepairTimelineEntry
from esb.services import repair_service
from esb.utils.exceptions import ValidationError


class TestCreateRepairRecord:
    """Tests for create_repair_record()."""

    def test_create_with_minimal_fields(self, app, make_equipment, staff_user, capture):
        """Creates record with minimal required fields."""
        eq = make_equipment()
        record = repair_service.create_repair_record(
            equipment_id=eq.id,
            description='Motor grinding noise',
            created_by='staffuser',
            author_id=staff_user.id,
        )
        assert record.id is not None
        assert record.equipment_id == eq.id
        assert record.description == 'Motor grinding noise'
        assert record.status == 'New'
        assert record.severity is None
        assert record.assignee_id is None

    def test_create_with_all_optional_fields(self, app, make_equipment, staff_user, tech_user, capture):
        """Creates record with all optional fields populated."""
        eq = make_equipment()
        record = repair_service.create_repair_record(
            equipment_id=eq.id,
            description='Laser tube needs replacement',
            created_by='staffuser',
            severity='Down',
            reporter_name='John Doe',
            reporter_email='john@example.com',
            assignee_id=tech_user.id,
            has_safety_risk=True,
            is_consumable=True,
            author_id=staff_user.id,
        )
        assert record.severity == 'Down'
        assert record.reporter_name == 'John Doe'
        assert record.reporter_email == 'john@example.com'
        assert record.assignee_id == tech_user.id
        assert record.has_safety_risk is True
        assert record.is_consumable is True

    def test_creates_timeline_creation_entry(self, app, make_equipment, staff_user, capture):
        """Creates a timeline entry with type 'creation'."""
        eq = make_equipment()
        record = repair_service.create_repair_record(
            equipment_id=eq.id,
            description='Broken belt',
            created_by='staffuser',
            author_id=staff_user.id,
        )
        entries = record.timeline_entries.all()
        assert len(entries) == 1
        assert entries[0].entry_type == 'creation'
        assert entries[0].content == 'Broken belt'
        assert entries[0].author_id == staff_user.id

    def test_creates_audit_log_entry(self, app, make_equipment, staff_user, capture):
        """Creates an audit log entry on creation."""
        eq = make_equipment()
        record = repair_service.create_repair_record(
            equipment_id=eq.id,
            description='Broken belt',
            created_by='staffuser',
            author_id=staff_user.id,
        )
        audit = _db.session.execute(
            _db.select(AuditLog).filter_by(
                entity_type='repair_record', entity_id=record.id,
            )
        ).scalar_one()
        assert audit.action == 'created'
        assert audit.user_id == staff_user.id
        assert audit.changes['status'] == 'New'

    def test_mutation_log_emitted(self, app, make_equipment, staff_user, capture):
        """Mutation log is emitted on creation."""
        eq = make_equipment()
        record = repair_service.create_repair_record(
            equipment_id=eq.id,
            description='Motor issue',
            created_by='staffuser',
            author_id=staff_user.id,
        )
        created_logs = [
            r for r in capture.records
            if 'repair_record.created' in r.message
        ]
        assert len(created_logs) == 1
        log_data = json.loads(created_logs[0].message)
        assert log_data['event'] == 'repair_record.created'
        assert log_data['user'] == 'staffuser'
        assert log_data['data']['id'] == record.id

    def test_raises_for_missing_description(self, app, make_equipment):
        """Raises ValidationError when description is empty."""
        eq = make_equipment()
        with pytest.raises(ValidationError, match='Description is required'):
            repair_service.create_repair_record(
                equipment_id=eq.id,
                description='   ',
                created_by='staffuser',
            )

    def test_raises_for_nonexistent_equipment(self, app):
        """Raises ValidationError when equipment doesn't exist."""
        with pytest.raises(ValidationError, match='Equipment with id 9999 not found'):
            repair_service.create_repair_record(
                equipment_id=9999,
                description='Broken',
                created_by='staffuser',
            )

    def test_raises_for_archived_equipment(self, app, make_equipment):
        """Raises ValidationError when equipment is archived."""
        eq = make_equipment(is_archived=True)
        with pytest.raises(ValidationError, match='archived'):
            repair_service.create_repair_record(
                equipment_id=eq.id,
                description='Broken',
                created_by='staffuser',
            )

    def test_raises_for_invalid_severity(self, app, make_equipment):
        """Raises ValidationError for invalid severity value."""
        eq = make_equipment()
        with pytest.raises(ValidationError, match='Invalid severity'):
            repair_service.create_repair_record(
                equipment_id=eq.id,
                description='Broken',
                created_by='staffuser',
                severity='Critical',
            )

    def test_raises_for_nonexistent_assignee(self, app, make_equipment):
        """Raises ValidationError when assignee user doesn't exist."""
        eq = make_equipment()
        with pytest.raises(ValidationError, match='User with id 9999 not found'):
            repair_service.create_repair_record(
                equipment_id=eq.id,
                description='Broken',
                created_by='staffuser',
                assignee_id=9999,
            )


class TestCreateRepairRecordStaticPageHook:
    """Tests for static_page_push notification hook in create_repair_record()."""

    def test_queues_static_page_push_notification(self, app, make_equipment, staff_user, capture):
        """create_repair_record() queues a static_page_push notification."""
        from esb.models.pending_notification import PendingNotification

        eq = make_equipment()
        repair_service.create_repair_record(
            equipment_id=eq.id,
            description='Motor grinding noise',
            created_by='staffuser',
            author_id=staff_user.id,
        )

        notifications = _db.session.execute(
            _db.select(PendingNotification).filter_by(notification_type='static_page_push')
        ).scalars().all()
        assert len(notifications) == 1
        assert notifications[0].target == 'status_change'
        assert notifications[0].payload['trigger'] == 'repair_record_created'


class TestUpdateRepairRecordStaticPageHook:
    """Tests for static_page_push notification hook in update_repair_record()."""

    def test_status_change_queues_notification(self, app, make_repair_record, staff_user, capture):
        """update_repair_record() with status change queues a static_page_push notification."""
        from esb.models.pending_notification import PendingNotification

        record = make_repair_record(status='New')
        repair_service.update_repair_record(
            record.id, 'staffuser', author_id=staff_user.id, status='In Progress',
        )

        notifications = _db.session.execute(
            _db.select(PendingNotification).filter_by(notification_type='static_page_push')
        ).scalars().all()
        assert len(notifications) == 1
        assert notifications[0].payload['trigger'] == 'repair_record_updated'

    def test_severity_change_queues_notification(self, app, make_repair_record, staff_user, capture):
        """update_repair_record() with severity change queues a static_page_push notification."""
        from esb.models.pending_notification import PendingNotification

        record = make_repair_record()
        repair_service.update_repair_record(
            record.id, 'staffuser', author_id=staff_user.id, severity='Down',
        )

        notifications = _db.session.execute(
            _db.select(PendingNotification).filter_by(notification_type='static_page_push')
        ).scalars().all()
        assert len(notifications) == 1

    def test_assignee_only_does_not_queue_notification(self, app, make_repair_record, staff_user, tech_user, capture):
        """update_repair_record() with only assignee change does NOT queue a static_page_push."""
        from esb.models.pending_notification import PendingNotification

        record = make_repair_record()
        repair_service.update_repair_record(
            record.id, 'staffuser', author_id=staff_user.id, assignee_id=tech_user.id,
        )

        notifications = _db.session.execute(
            _db.select(PendingNotification).filter_by(notification_type='static_page_push')
        ).scalars().all()
        assert len(notifications) == 0

    def test_note_only_does_not_queue_notification(self, app, make_repair_record, staff_user, capture):
        """update_repair_record() with only note does NOT queue a static_page_push."""
        from esb.models.pending_notification import PendingNotification

        record = make_repair_record()
        repair_service.update_repair_record(
            record.id, 'staffuser', author_id=staff_user.id, note='Just a note',
        )

        notifications = _db.session.execute(
            _db.select(PendingNotification).filter_by(notification_type='static_page_push')
        ).scalars().all()
        assert len(notifications) == 0


class TestCreateRepairRecordSlackNotification:
    """Test slack_message notification queuing on repair record creation."""

    def test_slack_notification_queued_when_trigger_enabled(self, app, make_area, make_equipment, staff_user, capture):
        """create_repair_record() queues slack_message when notify_new_report is enabled (default)."""
        from esb.models.pending_notification import PendingNotification

        area = make_area(name='Woodshop', slack_channel='#woodshop')
        equip = make_equipment(name='SawStop', area=area)

        repair_service.create_repair_record(
            equipment_id=equip.id, description='Motor broken',
            created_by='staffuser', reporter_name='Test User', severity='Down',
            author_id=staff_user.id,
        )

        notifications = _db.session.execute(
            _db.select(PendingNotification).filter_by(notification_type='slack_message')
        ).scalars().all()
        assert len(notifications) == 1
        assert notifications[0].target == '#woodshop'
        assert notifications[0].payload['event_type'] == 'new_report'
        assert notifications[0].payload['equipment_name'] == 'SawStop'
        assert notifications[0].payload['area_name'] == 'Woodshop'

    def test_no_slack_notification_when_trigger_disabled(self, app, make_area, make_equipment, staff_user, capture):
        """create_repair_record() does NOT queue slack_message when notify_new_report is disabled."""
        from esb.models.pending_notification import PendingNotification
        from esb.services import config_service

        config_service.set_config('notify_new_report', 'false', changed_by='test')

        area = make_area(name='Woodshop', slack_channel='#woodshop')
        equip = make_equipment(name='SawStop', area=area)

        repair_service.create_repair_record(
            equipment_id=equip.id, description='Motor broken',
            created_by='staffuser', reporter_name='Test User', severity='Down',
            author_id=staff_user.id,
        )

        notifications = _db.session.execute(
            _db.select(PendingNotification).filter_by(notification_type='slack_message')
        ).scalars().all()
        assert len(notifications) == 0

    def test_slack_payload_contains_correct_fields(self, app, make_area, make_equipment, staff_user, capture):
        """slack_message payload contains all expected fields."""
        from esb.models.pending_notification import PendingNotification

        area = make_area(name='Woodshop', slack_channel='#woodshop')
        equip = make_equipment(name='SawStop', area=area)

        repair_service.create_repair_record(
            equipment_id=equip.id, description='Motor broken',
            created_by='staffuser', reporter_name='Test User', severity='Down',
            has_safety_risk=True, author_id=staff_user.id,
        )

        notification = _db.session.execute(
            _db.select(PendingNotification).filter_by(notification_type='slack_message')
        ).scalar_one()
        payload = notification.payload
        assert payload['event_type'] == 'new_report'
        assert payload['equipment_id'] == equip.id
        assert payload['equipment_name'] == 'SawStop'
        assert payload['area_name'] == 'Woodshop'
        assert payload['severity'] == 'Down'
        assert payload['description'] == 'Motor broken'
        assert payload['reporter_name'] == 'Test User'
        assert payload['has_safety_risk'] is True


class TestUpdateRepairRecordSlackNotification:
    """Test slack_message notification queuing on repair record updates."""

    def test_resolved_status_queues_notification(self, app, make_area, make_equipment, staff_user, capture):
        """update_repair_record() with status->Resolved queues slack_message when notify_resolved is enabled."""
        from esb.models.pending_notification import PendingNotification

        area = make_area(name='Woodshop', slack_channel='#woodshop')
        equip = make_equipment(name='SawStop', area=area)
        record = RepairRecord(equipment_id=equip.id, description='Test', status='In Progress')
        _db.session.add(record)
        _db.session.commit()

        repair_service.update_repair_record(
            record.id, 'staffuser', author_id=staff_user.id, status='Resolved',
        )

        notifications = _db.session.execute(
            _db.select(PendingNotification).filter_by(notification_type='slack_message')
        ).scalars().all()
        assert len(notifications) == 1
        assert notifications[0].payload['event_type'] == 'resolved'
        assert notifications[0].payload['old_status'] == 'In Progress'
        assert notifications[0].payload['new_status'] == 'Resolved'

    def test_resolved_status_no_notification_when_disabled(self, app, make_area, make_equipment, staff_user, capture):
        """update_repair_record() with status->Resolved does NOT queue slack_message when disabled."""
        from esb.models.pending_notification import PendingNotification
        from esb.services import config_service

        config_service.set_config('notify_resolved', 'false', changed_by='test')

        area = make_area(name='Woodshop', slack_channel='#woodshop')
        equip = make_equipment(name='SawStop', area=area)
        record = RepairRecord(equipment_id=equip.id, description='Test', status='In Progress')
        _db.session.add(record)
        _db.session.commit()

        repair_service.update_repair_record(
            record.id, 'staffuser', author_id=staff_user.id, status='Resolved',
        )

        notifications = _db.session.execute(
            _db.select(PendingNotification).filter_by(notification_type='slack_message')
        ).scalars().all()
        assert len(notifications) == 0

    def test_severity_change_queues_notification(self, app, make_area, make_equipment, staff_user, capture):
        """update_repair_record() with severity change queues slack_message when enabled."""
        from esb.models.pending_notification import PendingNotification

        area = make_area(name='Woodshop', slack_channel='#woodshop')
        equip = make_equipment(name='SawStop', area=area)
        record = RepairRecord(equipment_id=equip.id, description='Test', severity='Degraded')
        _db.session.add(record)
        _db.session.commit()

        repair_service.update_repair_record(
            record.id, 'staffuser', author_id=staff_user.id, severity='Down',
        )

        notifications = _db.session.execute(
            _db.select(PendingNotification).filter_by(notification_type='slack_message')
        ).scalars().all()
        assert len(notifications) == 1
        assert notifications[0].payload['event_type'] == 'severity_changed'
        assert notifications[0].payload['old_severity'] == 'Degraded'
        assert notifications[0].payload['new_severity'] == 'Down'

    def test_severity_change_no_notification_when_disabled(self, app, make_area, make_equipment, staff_user, capture):
        """update_repair_record() with severity change does NOT queue when disabled."""
        from esb.models.pending_notification import PendingNotification
        from esb.services import config_service

        config_service.set_config('notify_severity_changed', 'false', changed_by='test')

        area = make_area(name='Woodshop', slack_channel='#woodshop')
        equip = make_equipment(name='SawStop', area=area)
        record = RepairRecord(equipment_id=equip.id, description='Test', severity='Degraded')
        _db.session.add(record)
        _db.session.commit()

        repair_service.update_repair_record(
            record.id, 'staffuser', author_id=staff_user.id, severity='Down',
        )

        notifications = _db.session.execute(
            _db.select(PendingNotification).filter_by(notification_type='slack_message')
        ).scalars().all()
        assert len(notifications) == 0

    def test_eta_change_queues_notification(self, app, make_area, make_equipment, staff_user, capture):
        """update_repair_record() with ETA change queues slack_message when enabled."""
        from datetime import date

        from esb.models.pending_notification import PendingNotification

        area = make_area(name='Woodshop', slack_channel='#woodshop')
        equip = make_equipment(name='SawStop', area=area)
        record = RepairRecord(equipment_id=equip.id, description='Test')
        _db.session.add(record)
        _db.session.commit()

        repair_service.update_repair_record(
            record.id, 'staffuser', author_id=staff_user.id, eta=date(2026, 3, 15),
        )

        notifications = _db.session.execute(
            _db.select(PendingNotification).filter_by(notification_type='slack_message')
        ).scalars().all()
        assert len(notifications) == 1
        assert notifications[0].payload['event_type'] == 'eta_updated'
        assert notifications[0].payload['eta'] == '2026-03-15'

    def test_eta_change_no_notification_when_disabled(self, app, make_area, make_equipment, staff_user, capture):
        """update_repair_record() with ETA change does NOT queue when disabled."""
        from datetime import date

        from esb.models.pending_notification import PendingNotification
        from esb.services import config_service

        config_service.set_config('notify_eta_updated', 'false', changed_by='test')

        area = make_area(name='Woodshop', slack_channel='#woodshop')
        equip = make_equipment(name='SawStop', area=area)
        record = RepairRecord(equipment_id=equip.id, description='Test')
        _db.session.add(record)
        _db.session.commit()

        repair_service.update_repair_record(
            record.id, 'staffuser', author_id=staff_user.id, eta=date(2026, 3, 15),
        )

        notifications = _db.session.execute(
            _db.select(PendingNotification).filter_by(notification_type='slack_message')
        ).scalars().all()
        assert len(notifications) == 0

    def test_eta_change_queues_static_page_push(self, app, make_area, make_equipment, staff_user):
        """update_repair_record() with ETA-only change queues static_page_push."""
        from datetime import date

        from esb.models.pending_notification import PendingNotification

        area = make_area(name='Woodshop')
        equip = make_equipment(name='SawStop', area=area)
        record = RepairRecord(equipment_id=equip.id, description='Test')
        _db.session.add(record)
        _db.session.commit()

        repair_service.update_repair_record(
            record.id, 'staffuser', author_id=staff_user.id, eta=date(2026, 3, 15),
        )

        notifications = _db.session.execute(
            _db.select(PendingNotification).filter_by(notification_type='static_page_push')
        ).scalars().all()
        assert len(notifications) == 1
        assert 'eta' in notifications[0].payload['changes']

    def test_multiple_triggers_in_one_update(self, app, make_area, make_equipment, staff_user, capture):
        """Multiple triggers in one update (severity change + status->Resolved) queue multiple notifications."""
        from esb.models.pending_notification import PendingNotification

        area = make_area(name='Woodshop', slack_channel='#woodshop')
        equip = make_equipment(name='SawStop', area=area)
        record = RepairRecord(equipment_id=equip.id, description='Test', status='In Progress', severity='Degraded')
        _db.session.add(record)
        _db.session.commit()

        repair_service.update_repair_record(
            record.id, 'staffuser', author_id=staff_user.id,
            status='Resolved', severity='Down',
        )

        notifications = _db.session.execute(
            _db.select(PendingNotification).filter_by(notification_type='slack_message')
        ).scalars().all()
        event_types = {n.payload['event_type'] for n in notifications}
        assert 'resolved' in event_types
        assert 'severity_changed' in event_types
        assert len(notifications) == 2

    def test_non_resolved_status_does_not_queue_resolved(self, app, make_area, make_equipment, staff_user, capture):
        """Status change to non-resolved status does NOT queue resolved notification."""
        from esb.models.pending_notification import PendingNotification

        area = make_area(name='Woodshop', slack_channel='#woodshop')
        equip = make_equipment(name='SawStop', area=area)
        record = RepairRecord(equipment_id=equip.id, description='Test', status='New')
        _db.session.add(record)
        _db.session.commit()

        repair_service.update_repair_record(
            record.id, 'staffuser', author_id=staff_user.id, status='In Progress',
        )

        notifications = _db.session.execute(
            _db.select(PendingNotification).filter_by(notification_type='slack_message')
        ).scalars().all()
        assert len(notifications) == 0

    def test_closed_no_issue_queues_resolved(self, app, make_area, make_equipment, staff_user, capture):
        """Status change to 'Closed - No Issue Found' queues resolved notification."""
        from esb.models.pending_notification import PendingNotification

        area = make_area(name='Woodshop', slack_channel='#woodshop')
        equip = make_equipment(name='SawStop', area=area)
        record = RepairRecord(equipment_id=equip.id, description='Test', status='In Progress')
        _db.session.add(record)
        _db.session.commit()

        repair_service.update_repair_record(
            record.id, 'staffuser', author_id=staff_user.id, status='Closed - No Issue Found',
        )

        notifications = _db.session.execute(
            _db.select(PendingNotification).filter_by(notification_type='slack_message')
        ).scalars().all()
        assert len(notifications) == 1
        assert notifications[0].payload['event_type'] == 'resolved'
        assert notifications[0].payload['new_status'] == 'Closed - No Issue Found'

    def test_closed_duplicate_queues_resolved(self, app, make_area, make_equipment, staff_user, capture):
        """Status change to 'Closed - Duplicate' queues resolved notification."""
        from esb.models.pending_notification import PendingNotification

        area = make_area(name='Woodshop', slack_channel='#woodshop')
        equip = make_equipment(name='SawStop', area=area)
        record = RepairRecord(equipment_id=equip.id, description='Test', status='In Progress')
        _db.session.add(record)
        _db.session.commit()

        repair_service.update_repair_record(
            record.id, 'staffuser', author_id=staff_user.id, status='Closed - Duplicate',
        )

        notifications = _db.session.execute(
            _db.select(PendingNotification).filter_by(notification_type='slack_message')
        ).scalars().all()
        assert len(notifications) == 1
        assert notifications[0].payload['event_type'] == 'resolved'
        assert notifications[0].payload['new_status'] == 'Closed - Duplicate'

    def test_slack_notification_fallback_target_when_no_slack_channel(self, app, make_area, make_equipment, staff_user, capture):
        """Notification target falls back to '#general' when area has no slack_channel."""
        from esb.models.pending_notification import PendingNotification

        area = make_area(name='No Slack Area', slack_channel=None)
        equip = make_equipment(name='SawStop', area=area)

        repair_service.create_repair_record(
            equipment_id=equip.id, description='Motor broken',
            created_by='staffuser', severity='Down', author_id=staff_user.id,
        )

        notification = _db.session.execute(
            _db.select(PendingNotification).filter_by(notification_type='slack_message')
        ).scalar_one()
        assert notification.target == '#general'
        assert notification.payload['area_name'] == 'No Slack Area'


class TestGetRepairRecord:
    """Tests for get_repair_record()."""

    def test_returns_record_by_id(self, app, make_equipment):
        """Returns the repair record for a valid ID."""
        eq = make_equipment()
        record = RepairRecord(equipment_id=eq.id, description='Test')
        _db.session.add(record)
        _db.session.commit()

        fetched = repair_service.get_repair_record(record.id)
        assert fetched.id == record.id

    def test_raises_when_not_found(self, app):
        """Raises ValidationError when record doesn't exist."""
        with pytest.raises(ValidationError, match='Repair record with id 9999 not found'):
            repair_service.get_repair_record(9999)


class TestListRepairRecords:
    """Tests for list_repair_records()."""

    def test_returns_all_ordered_by_created_at_desc(self, app, make_equipment):
        """Returns all records ordered by created_at desc."""
        eq = make_equipment()
        r1 = RepairRecord(equipment_id=eq.id, description='First')
        r2 = RepairRecord(equipment_id=eq.id, description='Second')
        _db.session.add_all([r1, r2])
        _db.session.commit()

        records = repair_service.list_repair_records()
        assert len(records) == 2
        # Most recent first
        assert records[0].created_at >= records[1].created_at

    def test_filters_by_equipment_id(self, app, make_area, make_equipment):
        """Filters records by equipment_id."""
        area = make_area()
        eq1 = make_equipment('Printer', area=area)
        eq2 = make_equipment('Laser', area=area)
        _db.session.add_all([
            RepairRecord(equipment_id=eq1.id, description='Printer issue'),
            RepairRecord(equipment_id=eq2.id, description='Laser issue'),
        ])
        _db.session.commit()

        records = repair_service.list_repair_records(equipment_id=eq1.id)
        assert len(records) == 1
        assert records[0].equipment_id == eq1.id

    def test_filters_by_status(self, app, make_equipment):
        """Filters records by status."""
        eq = make_equipment()
        r1 = RepairRecord(equipment_id=eq.id, description='First', status='New')
        r2 = RepairRecord(equipment_id=eq.id, description='Second', status='Assigned')
        _db.session.add_all([r1, r2])
        _db.session.commit()

        records = repair_service.list_repair_records(status='New')
        assert len(records) == 1
        assert records[0].status == 'New'

    def test_returns_empty_list_when_none_exist(self, app):
        """Returns empty list when no records exist."""
        records = repair_service.list_repair_records()
        assert records == []

    def test_eager_load_assignee_flag_avoids_n_plus_one(
        self, app, make_equipment, tech_user,
    ):
        """With eager_load_assignee=True, accessing record.assignee triggers no extra queries."""
        eq = make_equipment()
        for i in range(5):
            _db.session.add(RepairRecord(
                equipment_id=eq.id, description=f'Issue {i}',
                assignee_id=tech_user.id,
            ))
        _db.session.commit()
        _db.session.expire_all()

        records = repair_service.list_repair_records(
            equipment_id=eq.id, eager_load_assignee=True,
        )

        from sqlalchemy import event
        query_count = [0]

        def _count(conn, cursor, statement, params, context, executemany):
            query_count[0] += 1

        event.listen(_db.engine, 'before_cursor_execute', _count)
        try:
            usernames = [r.assignee.username for r in records]
        finally:
            event.remove(_db.engine, 'before_cursor_execute', _count)

        assert all(u == tech_user.username for u in usernames)
        assert query_count[0] == 0, \
            f'Expected no lazy queries after joinedload, got {query_count[0]}'

    def test_default_does_not_eager_load_assignee(
        self, app, make_equipment, tech_user,
    ):
        """Default behavior leaves assignee lazy so callers that don't need it
        don't pay for an unnecessary JOIN on users."""
        eq = make_equipment()
        _db.session.add(RepairRecord(
            equipment_id=eq.id, description='Issue',
            assignee_id=tech_user.id,
        ))
        _db.session.commit()
        _db.session.expire_all()

        records = repair_service.list_repair_records(equipment_id=eq.id)

        from sqlalchemy import event
        query_count = [0]

        def _count(conn, cursor, statement, params, context, executemany):
            query_count[0] += 1

        event.listen(_db.engine, 'before_cursor_execute', _count)
        try:
            _ = records[0].assignee.username
        finally:
            event.remove(_db.engine, 'before_cursor_execute', _count)

        assert query_count[0] >= 1, \
            'Default list_repair_records should not eager-load assignee'


class TestUpdateRepairRecord:
    """Tests for update_repair_record()."""

    def test_status_change_creates_timeline_entry(self, app, make_repair_record, staff_user, capture):
        """Status change creates a status_change timeline entry with old/new values."""
        record = make_repair_record(status='New')
        updated = repair_service.update_repair_record(
            record.id, 'staffuser', author_id=staff_user.id, status='In Progress',
        )
        assert updated.status == 'In Progress'
        timeline = _db.session.execute(
            _db.select(RepairTimelineEntry).filter_by(
                repair_record_id=record.id, entry_type='status_change',
            )
        ).scalar_one()
        assert timeline.old_value == 'New'
        assert timeline.new_value == 'In Progress'

    def test_assignee_change_creates_timeline_entry(self, app, make_repair_record, staff_user, tech_user, capture):
        """Assignee change creates an assignee_change timeline entry with usernames."""
        record = make_repair_record()
        updated = repair_service.update_repair_record(
            record.id, 'staffuser', author_id=staff_user.id, assignee_id=tech_user.id,
        )
        assert updated.assignee_id == tech_user.id
        timeline = _db.session.execute(
            _db.select(RepairTimelineEntry).filter_by(
                repair_record_id=record.id, entry_type='assignee_change',
            )
        ).scalar_one()
        assert timeline.old_value is None
        assert timeline.new_value == 'techuser'

    def test_assignee_clear_creates_timeline_entry(self, app, make_repair_record, staff_user, tech_user, capture):
        """Clearing assignee (set to None) creates a timeline entry."""
        record = make_repair_record(assignee_id=tech_user.id)
        updated = repair_service.update_repair_record(
            record.id, 'staffuser', author_id=staff_user.id, assignee_id=None,
        )
        assert updated.assignee_id is None
        timeline = _db.session.execute(
            _db.select(RepairTimelineEntry).filter_by(
                repair_record_id=record.id, entry_type='assignee_change',
            )
        ).scalar_one()
        assert timeline.old_value == 'techuser'
        assert timeline.new_value is None

    def test_eta_change_creates_timeline_entry(self, app, make_repair_record, staff_user, capture):
        """ETA change creates an eta_update timeline entry with date strings."""
        record = make_repair_record()
        eta_date = date(2026, 3, 15)
        updated = repair_service.update_repair_record(
            record.id, 'staffuser', author_id=staff_user.id, eta=eta_date,
        )
        assert updated.eta == eta_date
        timeline = _db.session.execute(
            _db.select(RepairTimelineEntry).filter_by(
                repair_record_id=record.id, entry_type='eta_update',
            )
        ).scalar_one()
        assert timeline.old_value is None
        assert timeline.new_value == '2026-03-15'

    def test_eta_clear_creates_timeline_entry(self, app, make_repair_record, staff_user, capture):
        """Clearing ETA creates a timeline entry."""
        record = make_repair_record(eta=date(2026, 3, 15))
        updated = repair_service.update_repair_record(
            record.id, 'staffuser', author_id=staff_user.id, eta=None,
        )
        assert updated.eta is None
        timeline = _db.session.execute(
            _db.select(RepairTimelineEntry).filter_by(
                repair_record_id=record.id, entry_type='eta_update',
            )
        ).scalar_one()
        assert timeline.old_value == '2026-03-15'
        assert timeline.new_value is None

    def test_note_creates_timeline_entry(self, app, make_repair_record, staff_user, capture):
        """Note creates a note timeline entry with content."""
        record = make_repair_record()
        repair_service.update_repair_record(
            record.id, 'staffuser', author_id=staff_user.id, note='Checked wiring',
        )
        timeline = _db.session.execute(
            _db.select(RepairTimelineEntry).filter_by(
                repair_record_id=record.id, entry_type='note',
            )
        ).scalar_one()
        assert timeline.content == 'Checked wiring'

    def test_batch_changes_create_individual_entries(self, app, make_repair_record, staff_user, tech_user, capture):
        """Multiple changes create individual timeline entries for each change type."""
        record = make_repair_record(status='New')
        repair_service.update_repair_record(
            record.id, 'staffuser', author_id=staff_user.id,
            status='In Progress', assignee_id=tech_user.id, note='Starting work',
        )
        entries = _db.session.execute(
            _db.select(RepairTimelineEntry).filter_by(repair_record_id=record.id)
        ).scalars().all()
        entry_types = {e.entry_type for e in entries}
        assert 'status_change' in entry_types
        assert 'assignee_change' in entry_types
        assert 'note' in entry_types
        assert len(entries) == 3

    def test_severity_change_updates_record(self, app, make_repair_record, staff_user, capture):
        """Severity change updates record but does not create a specific timeline entry."""
        record = make_repair_record()
        updated = repair_service.update_repair_record(
            record.id, 'staffuser', author_id=staff_user.id, severity='Down',
        )
        assert updated.severity == 'Down'
        # No specific timeline entry type for severity
        entries = _db.session.execute(
            _db.select(RepairTimelineEntry).filter_by(repair_record_id=record.id)
        ).scalars().all()
        assert len(entries) == 0

    def test_specialist_description_saved(self, app, make_repair_record, staff_user, capture):
        """Specialist description is persisted with audit log and mutation log."""
        record = make_repair_record()
        updated = repair_service.update_repair_record(
            record.id, 'staffuser', author_id=staff_user.id,
            specialist_description='Needs electrician for high-voltage panel',
        )
        assert updated.specialist_description == 'Needs electrician for high-voltage panel'
        audit = _db.session.execute(
            _db.select(AuditLog).filter_by(
                entity_type='repair_record', entity_id=record.id, action='updated',
            )
        ).scalar_one()
        assert 'specialist_description' in audit.changes
        updated_logs = [
            r for r in capture.records
            if 'repair_record.updated' in r.message
        ]
        assert len(updated_logs) == 1
        log_data = json.loads(updated_logs[0].message)
        assert 'specialist_description' in log_data['data']['changes']

    def test_audit_log_created_with_changes(self, app, make_repair_record, staff_user, capture):
        """Audit log entry created with all changes as JSON."""
        record = make_repair_record(status='New')
        repair_service.update_repair_record(
            record.id, 'staffuser', author_id=staff_user.id,
            status='Assigned', severity='Degraded',
        )
        audit = _db.session.execute(
            _db.select(AuditLog).filter_by(
                entity_type='repair_record', entity_id=record.id, action='updated',
            )
        ).scalar_one()
        assert audit.user_id == staff_user.id
        assert 'status' in audit.changes
        assert audit.changes['status'] == ['New', 'Assigned']
        assert 'severity' in audit.changes

    def test_mutation_log_emitted(self, app, make_repair_record, staff_user, capture):
        """Mutation log is emitted on update."""
        record = make_repair_record(status='New')
        repair_service.update_repair_record(
            record.id, 'staffuser', author_id=staff_user.id, status='Assigned',
        )
        updated_logs = [
            r for r in capture.records
            if 'repair_record.updated' in r.message
        ]
        assert len(updated_logs) == 1
        log_data = json.loads(updated_logs[0].message)
        assert log_data['event'] == 'repair_record.updated'
        assert log_data['user'] == 'staffuser'
        assert log_data['data']['id'] == record.id
        assert 'status' in log_data['data']['changes']

    def test_invalid_status_raises(self, app, make_repair_record, staff_user):
        """Raises ValidationError for invalid status value."""
        record = make_repair_record()
        with pytest.raises(ValidationError, match='Invalid status'):
            repair_service.update_repair_record(
                record.id, 'staffuser', author_id=staff_user.id, status='Bogus',
            )

    def test_invalid_severity_raises(self, app, make_repair_record, staff_user):
        """Raises ValidationError for invalid severity value."""
        record = make_repair_record()
        with pytest.raises(ValidationError, match='Invalid severity'):
            repair_service.update_repair_record(
                record.id, 'staffuser', author_id=staff_user.id, severity='Critical',
            )

    def test_invalid_assignee_raises(self, app, make_repair_record, staff_user):
        """Raises ValidationError for non-existent assignee user."""
        record = make_repair_record()
        with pytest.raises(ValidationError, match='User with id 9999 not found'):
            repair_service.update_repair_record(
                record.id, 'staffuser', author_id=staff_user.id, assignee_id=9999,
            )

    def test_not_found_raises(self, app, staff_user):
        """Raises ValidationError for non-existent repair record."""
        with pytest.raises(ValidationError, match='Repair record with id 9999 not found'):
            repair_service.update_repair_record(
                9999, 'staffuser', author_id=staff_user.id, status='New',
            )

    def test_no_changes_no_entries(self, app, make_repair_record, staff_user, capture):
        """No actual changes results in no timeline entries and no audit log."""
        record = make_repair_record(status='New')
        repair_service.update_repair_record(
            record.id, 'staffuser', author_id=staff_user.id, status='New',
        )
        entries = _db.session.execute(
            _db.select(RepairTimelineEntry).filter_by(repair_record_id=record.id)
        ).scalars().all()
        assert len(entries) == 0
        audits = _db.session.execute(
            _db.select(AuditLog).filter_by(
                entity_type='repair_record', entity_id=record.id, action='updated',
            )
        ).scalars().all()
        assert len(audits) == 0
        assert len(capture.records) == 0

    def test_unknown_field_raises(self, app, make_repair_record, staff_user):
        """Raises ValidationError for unknown field names."""
        record = make_repair_record()
        with pytest.raises(ValidationError, match='Unknown fields'):
            repair_service.update_repair_record(
                record.id, 'staffuser', author_id=staff_user.id, bogus_field='value',
            )

    def test_any_to_any_status_transition(self, app, make_repair_record, staff_user, capture):
        """Can transition from any status to any other status."""
        record = make_repair_record(status='Resolved')
        updated = repair_service.update_repair_record(
            record.id, 'staffuser', author_id=staff_user.id, status='New',
        )
        assert updated.status == 'New'


class TestAddRepairNote:
    """Tests for add_repair_note()."""

    def test_creates_note_timeline_entry(self, app, make_repair_record, staff_user, capture):
        """Creates a note timeline entry with content, author_name, author_id."""
        record = make_repair_record()
        entry = repair_service.add_repair_note(
            record.id, 'Motor bearings look worn', 'staffuser', author_id=staff_user.id,
        )
        assert entry.entry_type == 'note'
        assert entry.content == 'Motor bearings look worn'
        assert entry.author_name == 'staffuser'
        assert entry.author_id == staff_user.id
        assert entry.repair_record_id == record.id

    def test_creates_audit_log(self, app, make_repair_record, staff_user, capture):
        """Creates an audit log entry with action='note_added'."""
        record = make_repair_record()
        repair_service.add_repair_note(
            record.id, 'Check wiring', 'staffuser', author_id=staff_user.id,
        )
        audit = _db.session.execute(
            _db.select(AuditLog).filter_by(
                entity_type='repair_record', entity_id=record.id, action='note_added',
            )
        ).scalar_one()
        assert audit.user_id == staff_user.id
        assert audit.changes['note'] == 'Check wiring'

    def test_emits_mutation_log(self, app, make_repair_record, staff_user, capture):
        """Mutation log is emitted with event='repair_record.note_added'."""
        record = make_repair_record()
        repair_service.add_repair_note(
            record.id, 'Bearing noise', 'staffuser', author_id=staff_user.id,
        )
        assert len(capture.records) == 1
        log_data = json.loads(capture.records[0].message)
        assert log_data['event'] == 'repair_record.note_added'
        assert log_data['user'] == 'staffuser'
        assert log_data['data']['id'] == record.id
        assert log_data['data']['note'] == 'Bearing noise'

    def test_empty_note_raises(self, app, make_repair_record):
        """Raises ValidationError when note is empty string."""
        record = make_repair_record()
        with pytest.raises(ValidationError, match='Note text is required'):
            repair_service.add_repair_note(record.id, '', 'staffuser')

    def test_whitespace_note_raises(self, app, make_repair_record):
        """Raises ValidationError when note is whitespace only."""
        record = make_repair_record()
        with pytest.raises(ValidationError, match='Note text is required'):
            repair_service.add_repair_note(record.id, '   ', 'staffuser')

    def test_nonexistent_record_raises(self, app):
        """Raises ValidationError for non-existent repair record."""
        with pytest.raises(ValidationError, match='Repair record with id 9999 not found'):
            repair_service.add_repair_note(9999, 'test note', 'staffuser')

    def test_strips_whitespace(self, app, make_repair_record, staff_user, capture):
        """Leading and trailing whitespace is stripped from note content."""
        record = make_repair_record()
        entry = repair_service.add_repair_note(
            record.id, '  trimmed note  ', 'staffuser', author_id=staff_user.id,
        )
        assert entry.content == 'trimmed note'


class TestAddRepairPhoto:
    """Tests for add_repair_photo()."""

    def test_creates_document_and_timeline_entry(self, app, make_repair_record, staff_user, tmp_path, capture):
        """Creates Document via upload_service and photo timeline entry."""
        record = make_repair_record()
        app.config['UPLOAD_PATH'] = str(tmp_path)

        from io import BytesIO
        from werkzeug.datastructures import FileStorage
        fake_file = FileStorage(
            stream=BytesIO(b'fake image content'),
            filename='test.jpg',
            content_type='image/jpeg',
        )

        doc, entry = repair_service.add_repair_photo(
            record.id, fake_file, 'staffuser', author_id=staff_user.id,
        )
        assert doc.parent_type == 'repair_photo'
        assert doc.parent_id == record.id
        assert entry.entry_type == 'photo'
        assert entry.content == str(doc.id)
        assert entry.author_name == 'staffuser'
        assert entry.repair_record_id == record.id

    def test_creates_audit_log(self, app, make_repair_record, staff_user, tmp_path, capture):
        """Creates audit log entry with action='photo_added'."""
        record = make_repair_record()
        app.config['UPLOAD_PATH'] = str(tmp_path)

        from io import BytesIO
        from werkzeug.datastructures import FileStorage
        fake_file = FileStorage(
            stream=BytesIO(b'fake image data'),
            filename='photo.png',
            content_type='image/png',
        )

        doc, _entry = repair_service.add_repair_photo(
            record.id, fake_file, 'staffuser', author_id=staff_user.id,
        )
        audit = _db.session.execute(
            _db.select(AuditLog).filter_by(
                entity_type='repair_record', entity_id=record.id, action='photo_added',
            )
        ).scalar_one()
        assert audit.user_id == staff_user.id
        assert audit.changes['document_id'] == doc.id

    def test_emits_mutation_log(self, app, make_repair_record, staff_user, tmp_path, capture):
        """Mutation log is emitted with event='repair_record.photo_added'."""
        record = make_repair_record()
        app.config['UPLOAD_PATH'] = str(tmp_path)

        from io import BytesIO
        from werkzeug.datastructures import FileStorage
        fake_file = FileStorage(
            stream=BytesIO(b'fake image data'),
            filename='photo.jpg',
            content_type='image/jpeg',
        )

        doc, _entry = repair_service.add_repair_photo(
            record.id, fake_file, 'staffuser', author_id=staff_user.id,
        )
        # upload_service emits its own mutation log + our photo_added log
        photo_logs = [
            r for r in capture.records
            if 'photo_added' in r.message
        ]
        assert len(photo_logs) == 1
        log_data = json.loads(photo_logs[0].message)
        assert log_data['event'] == 'repair_record.photo_added'
        assert log_data['data']['document_id'] == doc.id

    def test_nonexistent_record_raises(self, app):
        """Raises ValidationError for non-existent repair record."""
        from io import BytesIO
        from werkzeug.datastructures import FileStorage
        fake_file = FileStorage(
            stream=BytesIO(b'data'),
            filename='test.jpg',
            content_type='image/jpeg',
        )
        with pytest.raises(ValidationError, match='Repair record with id 9999 not found'):
            repair_service.add_repair_photo(9999, fake_file, 'staffuser')


class TestGetKanbanData:
    """Tests for get_kanban_data()."""

    def test_returns_only_open_records(self, app, make_area, make_equipment):
        """Excludes Resolved, Closed - No Issue Found, Closed - Duplicate."""
        area = make_area()
        eq = make_equipment('Printer', area=area)
        open_statuses = ['New', 'Assigned', 'In Progress', 'Parts Needed',
                         'Parts Ordered', 'Parts Received', 'Needs Specialist']
        closed_statuses = ['Resolved', 'Closed - No Issue Found', 'Closed - Duplicate']
        for s in open_statuses + closed_statuses:
            _db.session.add(RepairRecord(
                equipment_id=eq.id, description=f'{s} record', status=s,
            ))
        _db.session.commit()

        result = repair_service.get_kanban_data()
        all_records = [r for records in result.values() for r in records]
        result_statuses = {r.status for r in all_records}
        for s in closed_statuses:
            assert s not in result_statuses
        assert len(all_records) == len(open_statuses)

    def test_records_grouped_by_status(self, app, make_area, make_equipment):
        """Records are grouped into correct status columns."""
        area = make_area()
        eq = make_equipment('Router', area=area)
        _db.session.add_all([
            RepairRecord(equipment_id=eq.id, description='new', status='New'),
            RepairRecord(equipment_id=eq.id, description='assigned', status='Assigned'),
            RepairRecord(equipment_id=eq.id, description='in progress', status='In Progress'),
        ])
        _db.session.commit()

        result = repair_service.get_kanban_data()
        assert len(result['New']) == 1
        assert len(result['Assigned']) == 1
        assert len(result['In Progress']) == 1
        assert result['New'][0].status == 'New'
        assert result['Assigned'][0].status == 'Assigned'
        assert result['In Progress'][0].status == 'In Progress'

    def test_ordering_oldest_time_in_column_first(self, app, make_area, make_equipment):
        """Within a column, records are ordered by time-in-column (oldest first)."""
        area = make_area()
        eq = make_equipment('Laser', area=area)
        now = datetime.now(UTC)

        # Both records are "New" but with different created_at (no status changes)
        r_old = RepairRecord(
            equipment_id=eq.id, description='old new',
            status='New', created_at=now - timedelta(days=5),
        )
        r_new = RepairRecord(
            equipment_id=eq.id, description='recent new',
            status='New', created_at=now - timedelta(days=1),
        )
        _db.session.add_all([r_new, r_old])
        _db.session.commit()

        result = repair_service.get_kanban_data()
        descriptions = [r.description for r in result['New']]
        assert descriptions == ['old new', 'recent new']

    def test_time_in_column_uses_last_status_change(self, app, make_area, make_equipment):
        """Time-in-column uses the most recent status_change entry timestamp."""
        area = make_area()
        eq = make_equipment('CNC', area=area)
        now = datetime.now(UTC)

        # Record was created 10 days ago but moved to Assigned 2 days ago
        record = RepairRecord(
            equipment_id=eq.id, description='recently moved',
            status='Assigned', created_at=now - timedelta(days=10),
        )
        _db.session.add(record)
        _db.session.flush()
        _db.session.add(RepairTimelineEntry(
            repair_record_id=record.id,
            entry_type='status_change',
            old_value='New',
            new_value='Assigned',
            author_name='staffuser',
            created_at=now - timedelta(days=2),
        ))
        _db.session.commit()

        result = repair_service.get_kanban_data()
        rec = result['Assigned'][0]
        # time_in_column should be ~2 days, not 10
        assert rec.time_in_column < timedelta(days=3).total_seconds()

    def test_time_in_column_falls_back_to_created_at(self, app, make_area, make_equipment):
        """When no status_change exists, time-in-column uses created_at."""
        area = make_area()
        eq = make_equipment('Drill', area=area)
        now = datetime.now(UTC)
        record = RepairRecord(
            equipment_id=eq.id, description='still new',
            status='New', created_at=now - timedelta(days=7),
        )
        _db.session.add(record)
        _db.session.commit()

        result = repair_service.get_kanban_data()
        rec = result['New'][0]
        assert rec.time_in_column >= timedelta(days=6).total_seconds()

    def test_empty_columns_included(self, app):
        """All Kanban columns are present in result even when empty."""
        result = repair_service.get_kanban_data()
        expected = ['New', 'Assigned', 'In Progress', 'Parts Needed',
                    'Parts Ordered', 'Parts Received', 'Needs Specialist']
        for col in expected:
            assert col in result
            assert result[col] == []

    def test_eager_loads_equipment_area_assignee(self, app, make_area, make_equipment, tech_user):
        """Returned records have accessible equipment name, area name, and assignee."""
        area = make_area('Woodshop')
        eq = make_equipment('Table Saw', area=area)
        _db.session.add(RepairRecord(
            equipment_id=eq.id, description='issue',
            assignee_id=tech_user.id,
        ))
        _db.session.commit()

        result = repair_service.get_kanban_data()
        rec = result['New'][0]
        assert rec.equipment.name == 'Table Saw'
        assert rec.equipment.area.name == 'Woodshop'
        assert rec.assignee.username == 'techuser'


class TestGetRepairQueue:
    """Tests for get_repair_queue()."""

    def test_returns_only_open_records(self, app, make_area, make_equipment):
        """Excludes Resolved, Closed - No Issue Found, Closed - Duplicate."""
        area = make_area()
        eq = make_equipment('Printer', area=area)
        open_statuses = ['New', 'Assigned', 'In Progress', 'Parts Needed']
        closed_statuses = ['Resolved', 'Closed - No Issue Found', 'Closed - Duplicate']
        for s in open_statuses + closed_statuses:
            _db.session.add(RepairRecord(
                equipment_id=eq.id, description=f'{s} record', status=s,
            ))
        _db.session.commit()

        results = repair_service.get_repair_queue()
        result_statuses = {r.status for r in results}
        assert len(results) == len(open_statuses)
        for s in closed_statuses:
            assert s not in result_statuses

    def test_default_sort_severity_then_age(self, app, make_area, make_equipment):
        """Default order: severity priority (Down=0, Degraded=1, Not Sure=2, NULL=3) then oldest first."""
        area = make_area()
        eq = make_equipment('Router', area=area)
        now = datetime.now(UTC)
        # Create records with different severities and ages
        r_null_old = RepairRecord(
            equipment_id=eq.id, description='null old', severity=None,
            created_at=now - timedelta(days=5),
        )
        r_down_new = RepairRecord(
            equipment_id=eq.id, description='down new', severity='Down',
            created_at=now - timedelta(days=1),
        )
        r_down_old = RepairRecord(
            equipment_id=eq.id, description='down old', severity='Down',
            created_at=now - timedelta(days=3),
        )
        r_degraded = RepairRecord(
            equipment_id=eq.id, description='degraded', severity='Degraded',
            created_at=now - timedelta(days=2),
        )
        r_not_sure = RepairRecord(
            equipment_id=eq.id, description='not sure', severity='Not Sure',
            created_at=now - timedelta(days=4),
        )
        _db.session.add_all([r_null_old, r_down_new, r_down_old, r_degraded, r_not_sure])
        _db.session.commit()

        results = repair_service.get_repair_queue()
        descriptions = [r.description for r in results]
        # Down (oldest first): down_old, down_new; Degraded; Not Sure; NULL
        assert descriptions == ['down old', 'down new', 'degraded', 'not sure', 'null old']

    def test_area_id_filter(self, app, make_area, make_equipment):
        """Filters by equipment's area_id."""
        area1 = make_area('Woodshop')
        area2 = make_area('Metalshop', slack_channel='#metalshop')
        eq1 = make_equipment('Table Saw', area=area1)
        eq2 = make_equipment('Welder', area=area2)
        _db.session.add_all([
            RepairRecord(equipment_id=eq1.id, description='saw issue'),
            RepairRecord(equipment_id=eq2.id, description='welder issue'),
        ])
        _db.session.commit()

        results = repair_service.get_repair_queue(area_id=area1.id)
        assert len(results) == 1
        assert results[0].description == 'saw issue'

    def test_status_filter(self, app, make_area, make_equipment):
        """Filters by status."""
        area = make_area()
        eq = make_equipment('Laser', area=area)
        _db.session.add_all([
            RepairRecord(equipment_id=eq.id, description='new', status='New'),
            RepairRecord(equipment_id=eq.id, description='assigned', status='Assigned'),
        ])
        _db.session.commit()

        results = repair_service.get_repair_queue(status='Assigned')
        assert len(results) == 1
        assert results[0].status == 'Assigned'

    def test_combined_area_and_status_filter(self, app, make_area, make_equipment):
        """Area + status filters work together (AND logic)."""
        area1 = make_area('Woodshop')
        area2 = make_area('Metalshop', slack_channel='#metalshop')
        eq1 = make_equipment('Table Saw', area=area1)
        eq2 = make_equipment('Welder', area=area2)
        _db.session.add_all([
            RepairRecord(equipment_id=eq1.id, description='saw new', status='New'),
            RepairRecord(equipment_id=eq1.id, description='saw assigned', status='Assigned'),
            RepairRecord(equipment_id=eq2.id, description='welder new', status='New'),
        ])
        _db.session.commit()

        results = repair_service.get_repair_queue(area_id=area1.id, status='New')
        assert len(results) == 1
        assert results[0].description == 'saw new'

    def test_empty_result_set(self, app):
        """Returns empty list when no open records exist."""
        results = repair_service.get_repair_queue()
        assert results == []

    def test_includes_equipment_and_area_relationships(self, app, make_area, make_equipment, tech_user):
        """Returned records have accessible equipment name, area name, and assignee username."""
        area = make_area('Woodshop')
        eq = make_equipment('Table Saw', area=area)
        _db.session.add(RepairRecord(
            equipment_id=eq.id, description='issue',
            assignee_id=tech_user.id,
        ))
        _db.session.commit()

        results = repair_service.get_repair_queue()
        assert len(results) == 1
        assert results[0].equipment.name == 'Table Saw'
        assert results[0].equipment.area.name == 'Woodshop'
        assert results[0].assignee.username == 'techuser'
