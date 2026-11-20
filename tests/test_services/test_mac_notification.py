"""Tests for MAC pieces of notification_service: mac_clear + periodic refresh."""

from unittest.mock import MagicMock, patch

import pytest

from esb.extensions import db
from esb.models.machine_status import MachineStatus
from esb.services import notification_service


@pytest.fixture
def mac_url(app):
    app.config['MAC_URL'] = 'http://mac.test'
    return app.config['MAC_URL']


def _status_dict(name):
    return {
        'name': name, 'display_name': name, 'status': 'idle', 'relay': False,
        'oops': False, 'locked_out': False, 'current_user': None,
        'last_checkin': None, 'last_update': None,
    }


class TestMacClearNotification:
    def test_type_accepted(self, mac_url):
        notif = notification_service.queue_notification('mac_clear', 'planer', {'repair_record_id': 1})
        assert notif.notification_type == 'mac_clear'

    def test_dispatch_calls_clear(self, mac_url):
        notif = notification_service.queue_notification('mac_clear', 'planer')
        with patch('esb.services.mac_service.clear') as mock_clear:
            notification_service.process_notification(notif)
        mock_clear.assert_called_once_with('planer')

    def test_delivery_issues_both_deletes(self, mac_url):
        notif = notification_service.queue_notification('mac_clear', 'planer')
        with patch('esb.services.mac_service.requests') as mock_req:
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {'success': True}
            mock_req.request.return_value = resp
            notification_service.process_notification(notif)
        paths = [(c[0][0], c[0][1]) for c in mock_req.request.call_args_list]
        assert ('delete', 'http://mac.test/api/machine/oops/planer') in paths
        assert ('delete', 'http://mac.test/api/machine/locked_out/planer') in paths

    def test_failure_marks_failed_with_backoff(self, mac_url):
        notif = notification_service.queue_notification('mac_clear', 'planer')
        with patch('esb.services.mac_service.clear', side_effect=RuntimeError('down')):
            with pytest.raises(RuntimeError):
                notification_service.process_notification(notif)
        # Worker would call mark_failed on the raised exception.
        updated = notification_service.mark_failed(notif.id, 'down')
        assert updated.retry_count == 1
        assert updated.next_retry_at is not None


class TestMacRefresh:
    def test_do_refresh_upserts_and_reconciles(self, mac_url):
        # Pre-existing orphan not returned by MAC -> should be reconciled away.
        db.session.add(MachineStatus(machine_name='ghost', status='idle'))
        db.session.commit()
        with patch('esb.services.mac_service.fetch_all_status',
                   return_value=[_status_dict('planer'), _status_dict('lathe')]):
            notification_service._do_mac_refresh()
        names = {r.machine_name for r in db.session.execute(db.select(MachineStatus)).scalars().all()}
        assert names == {'planer', 'lathe'}

    def test_do_refresh_disabled_noop(self, app):
        app.config['MAC_URL'] = ''
        with patch('esb.services.mac_service.fetch_all_status') as mock_fetch:
            notification_service._do_mac_refresh()
        mock_fetch.assert_not_called()

    def test_refresh_swallows_errors(self, mac_url, monkeypatch):
        monkeypatch.setattr(notification_service, '_last_mac_refresh', None)
        with patch.object(notification_service, '_do_mac_refresh', side_effect=RuntimeError('boom')):
            # Must not raise (F3): a MAC outage can't crash the worker cycle.
            notification_service._refresh_mac_status()

    def test_throttle_gates_repeat_calls(self, mac_url, monkeypatch):
        monkeypatch.setattr(notification_service, '_last_mac_refresh', None)
        calls = {'n': 0}

        def _count():
            calls['n'] += 1

        with patch.object(notification_service, '_do_mac_refresh', side_effect=_count):
            notification_service._refresh_mac_status()  # first call runs
            notification_service._refresh_mac_status()  # within 60s -> skipped
        assert calls['n'] == 1


class TestMacClear404:
    """Issue #90: MAC 404 (no such machine) fails the mac_clear at once."""

    def test_404_raises_not_found(self, mac_url):
        from esb.services import mac_service

        with patch('esb.services.mac_service.requests') as mock_req:
            resp = MagicMock()
            resp.status_code = 404
            mock_req.request.return_value = resp
            with pytest.raises(mac_service.MacMachineNotFoundError, match="'Resaw'"):
                mac_service.clear('Resaw')

    def test_worker_fails_404_permanently_without_retry(self, mac_url):
        from esb.models.pending_notification import PendingNotification
        from esb.services import mac_service

        notif = notification_service.queue_notification('mac_clear', 'Resaw')
        err = mac_service.MacMachineNotFoundError('HTTP 404 for Resaw')
        with patch.object(notification_service, 'process_notification', side_effect=err), \
             patch('esb.services.notification_service.time') as mock_time, \
             patch('esb.services.notification_service.signal'), \
             patch.object(notification_service, '_refresh_mac_status'), \
             patch.object(notification_service, '_refresh_static_reservations'):
            mock_time.sleep.side_effect = KeyboardInterrupt
            try:
                notification_service.run_worker_loop(poll_interval=1)
            except KeyboardInterrupt:
                pass
        db.session.expire_all()
        saved = db.session.get(PendingNotification, notif.id)
        assert saved.status == 'failed'
        assert saved.retry_count == 1
        assert saved.next_retry_at is None
        assert 'Resaw' in saved.error_message

    def test_mark_failed_permanent(self, mac_url):
        notif = notification_service.queue_notification('mac_clear', 'Resaw')
        updated = notification_service.mark_failed(notif.id, 'gone', permanent=True)
        assert updated.status == 'failed'
        assert updated.next_retry_at is None
