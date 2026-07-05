"""Tests for resolve-clears-machine queueing in repair_service (F2)."""

import pytest

from esb.extensions import db
from esb.models.pending_notification import PendingNotification
from esb.services import repair_service


@pytest.fixture
def mac_url(app):
    app.config['MAC_URL'] = 'http://mac.test'
    return app.config['MAC_URL']


def _mac_clears():
    return db.session.execute(
        db.select(PendingNotification).filter_by(notification_type='mac_clear')
    ).scalars().all()


class TestResolveClearsMachine:
    def test_resolve_queues_mac_clear(self, mac_url, make_equipment, staff_user):
        eq = make_equipment(mac_machine_name='planer')
        rec = repair_service.create_repair_record(
            equipment_id=eq.id, description='broken', created_by='t', severity='Down',
        )
        repair_service.update_repair_record(
            rec.id, updated_by='t', status='Resolved', note='fixed',
        )
        clears = _mac_clears()
        assert len(clears) == 1
        assert clears[0].target == 'planer'
        assert clears[0].payload['repair_record_id'] == rec.id

    def test_closed_no_issue_queues(self, mac_url, make_equipment):
        eq = make_equipment(mac_machine_name='planer')
        rec = repair_service.create_repair_record(
            equipment_id=eq.id, description='x', created_by='t',
        )
        repair_service.update_repair_record(
            rec.id, updated_by='t', status='Closed - No Issue Found', note='n',
        )
        assert len(_mac_clears()) == 1

    def test_closed_duplicate_does_not_queue(self, mac_url, make_equipment):
        eq = make_equipment(mac_machine_name='planer')
        authoritative = repair_service.create_repair_record(
            equipment_id=eq.id, description='real', created_by='t',
        )
        dup = repair_service.create_repair_record(
            equipment_id=eq.id, description='dup', created_by='t',
        )
        repair_service.update_repair_record(
            dup.id, updated_by='t', status='Closed - Duplicate',
            duplicated_repair_id=authoritative.id,
        )
        assert _mac_clears() == []

    def test_other_open_repair_blocks_queue(self, mac_url, make_equipment):
        eq = make_equipment(mac_machine_name='planer')
        repair_service.create_repair_record(
            equipment_id=eq.id, description='still open', created_by='t',
        )
        rec2 = repair_service.create_repair_record(
            equipment_id=eq.id, description='resolving', created_by='t',
        )
        repair_service.update_repair_record(
            rec2.id, updated_by='t', status='Resolved', note='done',
        )
        # Another open repair remains -> machine must stay locked.
        assert _mac_clears() == []

    def test_unlinked_equipment_no_queue(self, mac_url, make_equipment):
        eq = make_equipment()  # no mac_machine_name
        rec = repair_service.create_repair_record(
            equipment_id=eq.id, description='x', created_by='t',
        )
        repair_service.update_repair_record(
            rec.id, updated_by='t', status='Resolved', note='n',
        )
        assert _mac_clears() == []

    def test_mac_disabled_no_queue(self, app, make_equipment):
        app.config['MAC_URL'] = ''
        eq = make_equipment(mac_machine_name='planer')
        rec = repair_service.create_repair_record(
            equipment_id=eq.id, description='x', created_by='t',
        )
        repair_service.update_repair_record(
            rec.id, updated_by='t', status='Resolved', note='n',
        )
        assert _mac_clears() == []

    def test_resolved_still_queues_when_notify_resolved_off(self, mac_url, make_equipment):
        # mac_clear is a SIBLING of the Slack notify_resolved check, not nested.
        from esb.services import config_service
        config_service.set_config('notify_resolved', 'false', changed_by='t')
        eq = make_equipment(mac_machine_name='planer')
        rec = repair_service.create_repair_record(
            equipment_id=eq.id, description='x', created_by='t',
        )
        repair_service.update_repair_record(
            rec.id, updated_by='t', status='Resolved', note='n',
        )
        assert len(_mac_clears()) == 1
