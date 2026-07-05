"""Tests for esb.services.mac_service."""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest
from requests import RequestException

from esb.extensions import db
from esb.models.machine_activity_event import MachineActivityEvent
from esb.models.machine_status import MachineStatus
from esb.services import mac_service


@pytest.fixture
def mac_url(app):
    """Enable the MAC integration for a test."""
    app.config['MAC_URL'] = 'http://mac.test'
    return app.config['MAC_URL']


def _status_dict(name='planer', **over):
    d = {
        'name': name,
        'display_name': name.title(),
        'status': 'idle',
        'relay': False,
        'oops': False,
        'locked_out': False,
        'current_user': None,
        'last_checkin': None,
        'last_update': None,
    }
    d.update(over)
    return d


class TestGating:
    def test_mac_enabled_true(self, mac_url):
        assert mac_service.mac_enabled() is True

    def test_mac_enabled_false(self, app):
        app.config['MAC_URL'] = ''
        assert mac_service.mac_enabled() is False

    def test_base_url_trimmed(self, app):
        app.config['MAC_URL'] = 'http://mac.test/  '
        assert mac_service._base_url() == 'http://mac.test'


class TestFetchAllStatus:
    def test_parses_machines_key(self, mac_url):
        with patch('esb.services.mac_service.requests') as mock_req:
            resp = MagicMock()
            resp.json.return_value = {'machines': [_status_dict(), _status_dict('lathe')]}
            mock_req.get.return_value = resp
            result = mac_service.fetch_all_status()
        assert [m['name'] for m in result] == ['planer', 'lathe']
        resp.raise_for_status.assert_called_once()

    def test_disabled_returns_empty(self, app):
        app.config['MAC_URL'] = ''
        with patch('esb.services.mac_service.requests') as mock_req:
            assert mac_service.fetch_all_status() == []
            mock_req.get.assert_not_called()


class TestControls:
    def _resp(self, status_code=200, body=None):
        resp = MagicMock()
        resp.status_code = status_code
        resp.json.return_value = body or {'success': True}
        return resp

    def test_control_disabled_raises_without_calling_requests(self, app):
        app.config['MAC_URL'] = ''
        with patch('esb.services.mac_service.requests') as mock_req:
            with pytest.raises(RuntimeError):
                mac_service.set_oops('planer')
            mock_req.request.assert_not_called()

    def test_set_oops_success(self, mac_url):
        with patch('esb.services.mac_service.requests') as mock_req:
            mock_req.request.return_value = self._resp(200)
            warned = mac_service.set_oops('planer')
        assert warned is False
        args = mock_req.request.call_args
        assert args[0][0] == 'post'
        assert args[0][1].endswith('/api/machine/oops/planer')

    def test_503_action_applied_is_success_with_warning(self, mac_url):
        with patch('esb.services.mac_service.requests') as mock_req:
            mock_req.request.return_value = self._resp(503, {'action_applied': True})
            warned = mac_service.set_lockout('planer')
        assert warned is True

    def test_503_without_action_applied_raises(self, mac_url):
        with patch('esb.services.mac_service.requests') as mock_req:
            mock_req.request.return_value = self._resp(503, {'error': 'x'})
            with pytest.raises(RuntimeError):
                mac_service.set_oops('planer')

    def test_non_2xx_raises(self, mac_url):
        with patch('esb.services.mac_service.requests') as mock_req:
            mock_req.request.return_value = self._resp(500)
            with pytest.raises(RuntimeError):
                mac_service.clear_oops('planer')

    def test_transport_error_raises(self, mac_url):
        with patch('esb.services.mac_service.requests') as mock_req:
            mock_req.request.side_effect = RequestException('boom')
            with pytest.raises(RuntimeError):
                mac_service.set_oops('planer')

    def test_name_is_url_encoded(self, mac_url):
        # A machine name with a space / reserved chars must be percent-encoded.
        with patch('esb.services.mac_service.requests') as mock_req:
            mock_req.request.return_value = self._resp(200)
            mac_service.set_oops('cnc router#2')
        url = mock_req.request.call_args[0][1]
        assert url == 'http://mac.test/api/machine/oops/cnc%20router%232'

    def test_clear_issues_both_deletes(self, mac_url):
        with patch('esb.services.mac_service.requests') as mock_req:
            mock_req.request.return_value = self._resp(200)
            mac_service.clear('planer')
        methods_paths = [(c[0][0], c[0][1]) for c in mock_req.request.call_args_list]
        assert ('delete', 'http://mac.test/api/machine/oops/planer') in methods_paths
        assert ('delete', 'http://mac.test/api/machine/locked_out/planer') in methods_paths


class TestUpsert:
    def test_create_and_epoch_conversion(self, mac_url):
        epoch = 1_750_000_000.0
        row = mac_service.upsert_machine_status(_status_dict(
            status='in_use', oops=False,
            current_user={'account_id': 'a1', 'full_name': 'Alice'},
            last_checkin=epoch, last_update=epoch,
        ))
        db.session.refresh(row)
        assert row.status == 'in_use'
        assert row.current_user_full_name == 'Alice'
        # Stored naive-UTC; compare naive-to-naive (F7).
        expected = datetime.fromtimestamp(epoch, tz=UTC).replace(tzinfo=None)
        assert row.last_checkin == expected

    def test_null_epoch_stored_none(self, mac_url):
        row = mac_service.upsert_machine_status(_status_dict(last_checkin=None))
        assert row.last_checkin is None

    def test_bad_epoch_values_coerce_to_none(self, mac_url):
        # Non-numeric / NaN / Infinity epochs must not raise (they'd 500 the
        # webhook / abort the poll) -- they store None.
        for bad in ('not-a-number', float('nan'), float('inf'), True):
            row = mac_service.upsert_machine_status(_status_dict('planer', last_checkin=bad))
            assert row.last_checkin is None

    def test_null_status_coerced_to_unknown(self, mac_url):
        # Explicit null status must not violate the NOT NULL column.
        row = mac_service.upsert_machine_status(_status_dict('planer', status=None))
        assert row.status == 'unknown'

    def test_update_existing(self, mac_url):
        mac_service.upsert_machine_status(_status_dict(status='idle'))
        mac_service.upsert_machine_status(_status_dict(status='oops', oops=True))
        rows = db.session.execute(db.select(MachineStatus)).scalars().all()
        assert len(rows) == 1
        assert rows[0].status == 'oops'
        assert rows[0].oops is True

    def test_f1_concurrency_retry(self, mac_url, monkeypatch):
        # Pre-create the row (the "racing" process's insert).
        mac_service.upsert_machine_status(_status_dict(status='idle'))

        # Force the initial SELECT to miss so the code takes the INSERT path;
        # the INSERT then hits the real UNIQUE constraint -> IntegrityError ->
        # retry path re-selects and UPDATEs.
        real_execute = db.session.execute
        state = {'first': True}

        def fake_execute(*a, **k):
            result = real_execute(*a, **k)
            if state['first']:
                state['first'] = False
                miss = MagicMock()
                miss.scalar_one_or_none.return_value = None
                return miss
            return result

        monkeypatch.setattr(db.session, 'execute', fake_execute)
        row = mac_service.upsert_machine_status(_status_dict(status='oops', oops=True))
        monkeypatch.undo()

        rows = db.session.execute(db.select(MachineStatus)).scalars().all()
        assert len(rows) == 1
        assert row.status == 'oops'


class TestActivityLog:
    def _payload(self, name='planer', event='oops', ts=1_750_000_000.0):
        p = _status_dict(name)
        p['event'] = event
        p['timestamp'] = ts
        p['user'] = {'account_id': 'a1', 'full_name': 'Alice'}
        return p

    def test_record_inserts(self, mac_url):
        event = mac_service.record_activity_event(self._payload())
        assert event is not None
        assert event.event_type == 'oops'
        assert event.user_full_name == 'Alice'

    def test_dedup_returns_none(self, mac_url):
        first = mac_service.record_activity_event(self._payload())
        assert first is not None
        dup = mac_service.record_activity_event(self._payload())
        assert dup is None
        count = db.session.execute(
            db.select(db.func.count()).select_from(MachineActivityEvent)
        ).scalar_one()
        assert count == 1

    def test_prune_keeps_newest_n(self, mac_url):
        base = datetime(2026, 7, 1, 12, 0, 0)
        for i in range(5):
            db.session.add(MachineActivityEvent(
                machine_name='planer', event_type='login',
                event_timestamp=base.replace(minute=i),
            ))
        db.session.commit()
        deleted = mac_service.prune_activity_events('planer', keep=3)
        assert deleted == 2
        remaining = db.session.execute(
            db.select(MachineActivityEvent).filter_by(machine_name='planer')
        ).scalars().all()
        assert len(remaining) == 3
        # Newest three retained (minutes 2,3,4).
        assert {r.event_timestamp.minute for r in remaining} == {2, 3, 4}


class TestReconcileOrphans:
    def test_deletes_unseen(self, mac_url):
        for name in ('planer', 'lathe', 'saw'):
            mac_service.upsert_machine_status(_status_dict(name))
        deleted = mac_service.reconcile_orphans({'planer'})
        assert deleted == 2
        remaining = db.session.execute(db.select(MachineStatus)).scalars().all()
        assert [r.machine_name for r in remaining] == ['planer']

    def test_empty_seen_set_deletes_nothing(self, mac_url):
        # Defensive: an empty set must NOT wipe the whole cache.
        mac_service.upsert_machine_status(_status_dict('planer'))
        deleted = mac_service.reconcile_orphans(set())
        assert deleted == 0
        remaining = db.session.execute(db.select(MachineStatus)).scalars().all()
        assert len(remaining) == 1


class TestVisibleStatuses:
    def test_defaults_public(self, mac_url):
        assert mac_service.visible_statuses('public') == {'oops', 'locked_out'}

    def test_kiosk_default_all(self, mac_url):
        assert mac_service.visible_statuses('kiosk') == {
            'in_use', 'idle', 'oops', 'locked_out', 'unknown',
        }

    def test_config_override(self, mac_url):
        from esb.services import config_service
        config_service.set_config('mac_show_public_in_use', 'true', changed_by='t')
        assert 'in_use' in mac_service.visible_statuses('public')

    def test_disabled_empty(self, app):
        app.config['MAC_URL'] = ''
        assert mac_service.visible_statuses('public') == set()


class TestLookups:
    def test_get_status_for_equipment(self, mac_url, make_equipment):
        mac_service.upsert_machine_status(_status_dict('planer', status='oops'))
        eq = make_equipment(mac_machine_name='planer')
        status = mac_service.get_status_for_equipment(eq)
        assert status is not None and status.status == 'oops'

    def test_get_status_for_unlinked(self, mac_url, make_equipment):
        eq = make_equipment()
        assert mac_service.get_status_for_equipment(eq) is None

    def test_get_status_for_equipment_case_insensitive(self, mac_url, make_equipment):
        # MAC reports 'planer'; admin typed 'Planer'. Must still resolve.
        mac_service.upsert_machine_status(_status_dict('planer', status='oops'))
        eq = make_equipment(mac_machine_name='Planer')
        status = mac_service.get_status_for_equipment(eq)
        assert status is not None and status.status == 'oops'

    def test_get_equipment_by_machine_name_case_insensitive(self, mac_url, make_equipment):
        eq = make_equipment(mac_machine_name='Planer')
        found = mac_service.get_equipment_by_machine_name('planer')
        assert found is not None and found.id == eq.id

    def test_get_recent_activity_case_insensitive(self, mac_url):
        from datetime import datetime
        from esb.models.machine_activity_event import MachineActivityEvent
        # Events stored under MAC's casing ('planer'); caller passes 'Planer'.
        db.session.add(MachineActivityEvent(
            machine_name='planer', event_type='login',
            event_timestamp=datetime(2026, 7, 1, 12, 0, 0),
        ))
        db.session.commit()
        events = mac_service.get_recent_activity('Planer')
        assert len(events) == 1

    def test_get_recent_activity_gated_when_disabled(self, app):
        from datetime import datetime
        from esb.models.machine_activity_event import MachineActivityEvent
        db.session.add(MachineActivityEvent(
            machine_name='planer', event_type='login',
            event_timestamp=datetime(2026, 7, 1, 12, 0, 0),
        ))
        db.session.commit()
        app.config['MAC_URL'] = ''
        assert mac_service.get_recent_activity('planer') == []

    def test_get_equipment_by_machine_name(self, mac_url, make_equipment):
        eq = make_equipment(mac_machine_name='planer')
        found = mac_service.get_equipment_by_machine_name('planer')
        assert found.id == eq.id

    def test_multi_match_returns_first(self, mac_url, make_area, make_equipment):
        area = make_area()
        e1 = make_equipment(name='A', area=area, mac_machine_name='dup')
        make_equipment(name='B', area=area, mac_machine_name='dup')
        found = mac_service.get_equipment_by_machine_name('dup')
        assert found.id == e1.id  # lowest id wins

    def test_ignores_archived(self, mac_url, make_area, make_equipment):
        # F2: an archived equipment with a lower id sharing the name must NOT be
        # returned -- only the active one resolves.
        area = make_area()
        archived = make_equipment(name='Old', area=area, mac_machine_name='planer',
                                  is_archived=True)
        active = make_equipment(name='New', area=area, mac_machine_name='planer')
        found = mac_service.get_equipment_by_machine_name('planer')
        assert found.id == active.id
        assert found.id != archived.id


class TestMaybeCreateOopsRepair:
    def _payload(self, name='planer', full_name='Alice'):
        p = _status_dict(name)
        p['event'] = 'oops'
        p['timestamp'] = 1_750_000_000.0
        p['user'] = {'account_id': 'a1', 'full_name': full_name} if full_name is not None else None
        return p

    def test_creates_down_repair(self, mac_url, make_equipment):
        eq = make_equipment(mac_machine_name='planer')
        repair = mac_service.maybe_create_oops_repair(self._payload())
        assert repair is not None
        assert repair.equipment_id == eq.id
        assert repair.severity == 'Down'
        assert repair.reporter_name == 'Alice'
        assert repair.reporter_email is None

    def test_no_duplicate_when_open_repair(self, mac_url, make_equipment, make_repair_record):
        eq = make_equipment(mac_machine_name='planer')
        make_repair_record(equipment=eq, status='New')
        result = mac_service.maybe_create_oops_repair(self._payload())
        assert result is None

    def test_no_equipment_match(self, mac_url):
        assert mac_service.maybe_create_oops_repair(self._payload('ghost')) is None

    def test_missing_full_name(self, mac_url, make_equipment):
        make_equipment(mac_machine_name='planer')
        repair = mac_service.maybe_create_oops_repair(self._payload(full_name=None))
        assert repair is not None
        assert repair.reporter_name is None
