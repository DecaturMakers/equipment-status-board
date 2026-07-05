"""Tests for the inbound MAC webhook receiver."""

import pytest

from esb.extensions import db
from esb.models.machine_activity_event import MachineActivityEvent
from esb.models.machine_status import MachineStatus
from esb.models.repair_record import RepairRecord


@pytest.fixture
def mac_url(app):
    app.config['MAC_URL'] = 'http://mac.test'
    return app.config['MAC_URL']


def _payload(name='planer', event='login', ts=1_750_000_000.0, **over):
    p = {
        'name': name,
        'display_name': name.title(),
        'status': over.get('status', 'idle'),
        'relay': False,
        'oops': over.get('oops', False),
        'locked_out': False,
        'current_user': {'account_id': 'a1', 'full_name': 'Alice'},
        'last_checkin': ts,
        'last_update': ts,
        'event': event,
        'timestamp': ts,
        'user': {'account_id': 'a1', 'full_name': 'Alice'},
    }
    p.update({k: v for k, v in over.items() if k in p})
    return p


class TestWebhookGating:
    def test_disabled_returns_204_writes_nothing(self, client, app):
        app.config['MAC_URL'] = ''
        resp = client.post('/webhooks/mac', json=_payload())
        assert resp.status_code == 204
        assert db.session.execute(db.select(MachineStatus)).scalars().first() is None

    def test_csrf_exempt_post_succeeds(self, client, mac_url):
        # No CSRF token supplied; still succeeds (route is csrf-exempt).
        resp = client.post('/webhooks/mac', json=_payload())
        assert resp.status_code == 204


class TestWebhookProcessing:
    def test_valid_payload_writes_status_and_activity(self, client, mac_url):
        resp = client.post('/webhooks/mac', json=_payload(status='oops', oops=True, event='oops'))
        assert resp.status_code == 204
        status = db.session.execute(db.select(MachineStatus)).scalars().one()
        assert status.machine_name == 'planer'
        assert status.status == 'oops'
        assert status.oops is True
        assert status.current_user_full_name == 'Alice'
        event = db.session.execute(db.select(MachineActivityEvent)).scalars().one()
        assert event.event_type == 'oops'

    def test_malformed_body_returns_400(self, client, mac_url):
        resp = client.post('/webhooks/mac', data='not json',
                           content_type='application/json')
        assert resp.status_code == 400
        assert db.session.execute(db.select(MachineStatus)).scalars().first() is None

    def test_missing_name_returns_400(self, client, mac_url):
        resp = client.post('/webhooks/mac', json={'event': 'login', 'timestamp': 1.0})
        assert resp.status_code == 400

    def test_missing_event_or_timestamp_returns_400_no_write(self, client, mac_url):
        # F5: required fields validated before any DB write.
        resp = client.post('/webhooks/mac', json={'name': 'planer', 'timestamp': 1.0})
        assert resp.status_code == 400
        resp = client.post('/webhooks/mac', json={'name': 'planer', 'event': 'oops'})
        assert resp.status_code == 400
        assert db.session.execute(db.select(MachineStatus)).scalars().first() is None

    def test_non_numeric_timestamp_returns_400_not_500(self, client, mac_url):
        # A string/bool timestamp must be rejected as 400 (unprocessable), not
        # crash into a 500 that MAC would retry forever.
        for bad in ('not-a-number', True, None):
            resp = client.post('/webhooks/mac', json=_payload(name='planer', event='oops', ts=bad))
            assert resp.status_code == 400, bad
        assert db.session.execute(db.select(MachineStatus)).scalars().first() is None

    def test_non_string_name_or_event_returns_400(self, client, mac_url):
        assert client.post('/webhooks/mac', json={'name': 123, 'event': 'oops', 'timestamp': 1.0}).status_code == 400
        assert client.post('/webhooks/mac', json={'name': 'planer', 'event': {'x': 1}, 'timestamp': 1.0}).status_code == 400

    def test_non_finite_timestamp_returns_400_not_500(self, client, mac_url):
        # NaN/Infinity pass isinstance(float) but crash datetime.fromtimestamp();
        # Python's JSON parser accepts them, so they must be rejected as 400.
        for bad in (float('nan'), float('inf'), float('-inf')):
            resp = client.post('/webhooks/mac', json=_payload(name='planer', event='oops', ts=bad))
            assert resp.status_code == 400, bad
        assert db.session.execute(db.select(MachineStatus)).scalars().first() is None

    def test_internal_error_returns_500(self, client, mac_url):
        # F4: a server-side failure returns 5xx so MAC retries (not 400).
        from unittest.mock import patch
        with patch('esb.services.mac_service.upsert_machine_status', side_effect=RuntimeError('db down')):
            resp = client.post('/webhooks/mac', json=_payload())
        assert resp.status_code == 500

    def test_oops_repair_recreated_after_resolution_on_redelivery(self, client, mac_url, make_equipment):
        # F1: auto-repair is driven by the open-repair guard, not the activity
        # dedup. An identical oops re-delivered after the first repair is closed
        # creates a fresh repair (no open one exists), rather than being lost.
        make_equipment(mac_machine_name='planer')
        p = _payload(event='oops', status='oops', oops=True)
        assert client.post('/webhooks/mac', json=p).status_code == 204
        first = db.session.execute(db.select(RepairRecord)).scalars().one()
        # Close the repair, then re-deliver the identical (deduped) webhook.
        first.status = 'Resolved'
        db.session.commit()
        assert client.post('/webhooks/mac', json=p).status_code == 204
        repairs = db.session.execute(db.select(RepairRecord)).scalars().all()
        assert len(repairs) == 2  # a new open repair was created

    def test_bad_last_checkin_does_not_500(self, client, mac_url):
        # A bad last_checkin (not the event timestamp) must not crash the upsert;
        # it stores None and the webhook still succeeds (204).
        resp = client.post('/webhooks/mac', json=_payload(name='planer', event='oops', last_checkin='bad'))
        assert resp.status_code == 204
        status = db.session.execute(db.select(MachineStatus)).scalars().one()
        assert status.last_checkin is None

    def test_null_status_does_not_500(self, client, mac_url):
        resp = client.post('/webhooks/mac', json=_payload(name='planer', event='oops', status=None))
        assert resp.status_code == 204
        status = db.session.execute(db.select(MachineStatus)).scalars().one()
        assert status.status == 'unknown'

    def test_oops_creates_repair(self, client, mac_url, make_equipment):
        eq = make_equipment(mac_machine_name='planer')
        resp = client.post('/webhooks/mac', json=_payload(event='oops', status='oops', oops=True))
        assert resp.status_code == 204
        repair = db.session.execute(db.select(RepairRecord)).scalars().one()
        assert repair.equipment_id == eq.id
        assert repair.severity == 'Down'

    def test_duplicate_delivery_idempotent(self, client, mac_url, make_equipment):
        make_equipment(mac_machine_name='planer')
        p = _payload(event='oops', status='oops', oops=True)
        assert client.post('/webhooks/mac', json=p).status_code == 204
        # Identical re-delivery: no second activity row, no second repair.
        assert client.post('/webhooks/mac', json=p).status_code == 204
        events = db.session.execute(db.select(MachineActivityEvent)).scalars().all()
        assert len(events) == 1
        repairs = db.session.execute(db.select(RepairRecord)).scalars().all()
        assert len(repairs) == 1


class TestWebhookToken:
    def test_wrong_token_403(self, client, app):
        app.config['MAC_URL'] = 'http://mac.test'
        app.config['MAC_WEBHOOK_TOKEN'] = 'secret'
        assert client.post('/webhooks/mac', json=_payload()).status_code == 403
        assert client.post('/webhooks/mac/wrong', json=_payload()).status_code == 403

    def test_correct_token_204(self, client, app):
        app.config['MAC_URL'] = 'http://mac.test'
        app.config['MAC_WEBHOOK_TOKEN'] = 'secret'
        assert client.post('/webhooks/mac/secret', json=_payload()).status_code == 204

    def test_empty_token_accepts_any(self, client, app):
        app.config['MAC_URL'] = 'http://mac.test'
        app.config['MAC_WEBHOOK_TOKEN'] = ''
        assert client.post('/webhooks/mac', json=_payload()).status_code == 204
        assert client.post('/webhooks/mac/anything', json=_payload()).status_code == 204

    def test_disabled_with_token_set_returns_204_not_403(self, client, app):
        # Disabled integration is a documented 204 no-op regardless of a leftover
        # token -- the enabled check runs before the token guard.
        app.config['MAC_URL'] = ''
        app.config['MAC_WEBHOOK_TOKEN'] = 'secret'
        assert client.post('/webhooks/mac', json=_payload()).status_code == 204
        assert client.post('/webhooks/mac/wrong', json=_payload()).status_code == 204

    def test_whitespace_only_token_treated_as_unset(self, client, app):
        app.config['MAC_URL'] = 'http://mac.test'
        app.config['MAC_WEBHOOK_TOKEN'] = '   '
        assert client.post('/webhooks/mac', json=_payload()).status_code == 204
