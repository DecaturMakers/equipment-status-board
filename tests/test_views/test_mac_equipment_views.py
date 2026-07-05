"""View tests for MAC controls, activity JSON, form uniqueness, badges, toggles."""

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from esb.extensions import db
from esb.models.machine_activity_event import MachineActivityEvent
from esb.services import config_service, equipment_service, mac_service
from esb.utils.exceptions import ValidationError


@pytest.fixture
def mac_url(app):
    app.config['MAC_URL'] = 'http://mac.test'
    return app.config['MAC_URL']


def _status_dict(name, status='oops'):
    return {
        'name': name, 'display_name': name, 'status': status, 'relay': False,
        'oops': status == 'oops', 'locked_out': status == 'locked_out',
        'current_user': None, 'last_checkin': None, 'last_update': None,
    }


def _mock_resp(status_code=200, body=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = body or {'success': True}
    return resp


class TestMacControls:
    def test_oops_button_calls_mac_and_flashes(self, staff_client, mac_url, make_equipment):
        eq = make_equipment(mac_machine_name='planer')
        with patch('esb.services.mac_service.requests') as mock_req:
            mock_req.request.return_value = _mock_resp(200)
            resp = staff_client.post(f'/equipment/{eq.id}/mac/oops', follow_redirects=True)
        assert resp.status_code == 200
        called = [(c[0][0], c[0][1]) for c in mock_req.request.call_args_list]
        assert ('post', 'http://mac.test/api/machine/oops/planer') in called
        assert b'Oops applied' in resp.data

    def test_503_flashes_warning(self, staff_client, mac_url, make_equipment):
        eq = make_equipment(mac_machine_name='planer')
        with patch('esb.services.mac_service.requests') as mock_req:
            mock_req.request.return_value = _mock_resp(503, {'action_applied': True})
            resp = staff_client.post(f'/equipment/{eq.id}/mac/oops', follow_redirects=True)
        assert b'save timeout' in resp.data

    def test_failure_flashes_danger(self, staff_client, mac_url, make_equipment):
        eq = make_equipment(mac_machine_name='planer')
        with patch('esb.services.mac_service.requests') as mock_req:
            mock_req.request.return_value = _mock_resp(500)
            resp = staff_client.post(f'/equipment/{eq.id}/mac/clear', follow_redirects=True)
        assert b'failed' in resp.data

    def test_non_staff_denied(self, tech_client, mac_url, make_equipment):
        eq = make_equipment(mac_machine_name='planer')
        resp = tech_client.post(f'/equipment/{eq.id}/mac/oops')
        assert resp.status_code == 403

    def test_unlinked_equipment_flashes(self, staff_client, mac_url, make_equipment):
        eq = make_equipment()
        resp = staff_client.post(f'/equipment/{eq.id}/mac/oops', follow_redirects=True)
        assert b'not linked to a MAC machine' in resp.data

    def test_card_and_controls_shown_without_cached_status(self, staff_client, mac_url, make_equipment):
        # Linked but no MachineStatus cached yet (before first webhook/poll, or a
        # typo'd name): the card, controls, and activity button must still render
        # with a placeholder rather than vanishing silently.
        eq = make_equipment(mac_machine_name='planer')
        resp = staff_client.get(f'/equipment/{eq.id}')
        assert resp.status_code == 200
        assert b'MAC Machine Status' in resp.data
        assert b'No status received from MAC yet' in resp.data
        assert f'/equipment/{eq.id}/mac/oops'.encode() in resp.data
        assert b'mac-activity-btn' in resp.data

    def test_card_hidden_when_unlinked(self, staff_client, mac_url, make_equipment):
        eq = make_equipment()  # MAC enabled but no machine name linked
        resp = staff_client.get(f'/equipment/{eq.id}')
        assert b'MAC Machine Status' not in resp.data


class TestActivityJson:
    def test_returns_events_newest_first(self, tech_client, mac_url, make_equipment):
        eq = make_equipment(mac_machine_name='planer')
        for i in range(3):
            db.session.add(MachineActivityEvent(
                machine_name='planer', event_type='login',
                event_timestamp=datetime(2026, 7, 1, 12, i, 0),
            ))
        db.session.commit()
        resp = tech_client.get(f'/equipment/{eq.id}/mac-activity.json')
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data) == 3
        # Newest first.
        assert data[0]['event_timestamp'] > data[1]['event_timestamp']

    def test_requires_login(self, client, mac_url, make_equipment):
        eq = make_equipment(mac_machine_name='planer')
        resp = client.get(f'/equipment/{eq.id}/mac-activity.json')
        assert resp.status_code == 302  # redirect to login


class TestFormUniqueness:
    def test_duplicate_rejected_on_create(self, mac_url, make_area, make_equipment):
        area = make_area()
        make_equipment(area=area, mac_machine_name='planer')
        with pytest.raises(ValidationError):
            equipment_service.create_equipment(
                name='B', manufacturer='m', model='x',
                area_id=area.id, created_by='t',
                mac_machine_name='planer',
            )

    def test_duplicate_rejected_case_insensitive(self, mac_url, make_area, make_equipment):
        area = make_area()
        make_equipment(area=area, mac_machine_name='Planer')
        with pytest.raises(ValidationError):
            equipment_service.create_equipment(
                name='B', manufacturer='m', model='x', area_id=area.id,
                created_by='t', mac_machine_name='planer',
            )

    def test_duplicate_rejected_on_edit(self, mac_url, make_area, make_equipment):
        area = make_area()
        make_equipment(name='A', area=area, mac_machine_name='planer')
        c = make_equipment(name='C', area=area)
        with pytest.raises(ValidationError):
            equipment_service.update_equipment(
                c.id, updated_by='t', mac_machine_name='planer',
            )

    def test_self_edit_accepted(self, mac_url, make_equipment):
        eq = make_equipment(mac_machine_name='planer')
        # Re-saving the same value on the same record is fine (self excluded).
        equipment_service.update_equipment(eq.id, updated_by='t', mac_machine_name='planer')
        db.session.refresh(eq)
        assert eq.mac_machine_name == 'planer'

    def test_blank_coerced_to_none(self, mac_url, make_equipment):
        eq = make_equipment(mac_machine_name='planer')
        equipment_service.update_equipment(eq.id, updated_by='t', mac_machine_name='   ')
        db.session.refresh(eq)
        assert eq.mac_machine_name is None


class TestBadgeRendering:
    def test_public_shows_oops_badge(self, client, mac_url, make_area, make_equipment):
        area = make_area()
        make_equipment(name='Planer', area=area, mac_machine_name='planer')
        mac_service.upsert_machine_status(_status_dict('planer', status='oops'))
        resp = client.get('/public/')
        assert b'Oops' in resp.data

    def test_public_hides_in_use_but_kiosk_shows(self, client, mac_url, make_area, make_equipment):
        area = make_area()
        make_equipment(name='Planer', area=area, mac_machine_name='planer')
        mac_service.upsert_machine_status(_status_dict('planer', status='in_use'))
        # Default: public in_use off, kiosk in_use on.
        public = client.get('/public/')
        assert b'In Use' not in public.data
        kiosk = client.get('/public/kiosk')
        assert b'In Use' in kiosk.data

    def test_nothing_renders_when_disabled(self, client, app, make_area, make_equipment):
        app.config['MAC_URL'] = ''
        area = make_area()
        make_equipment(name='Planer', area=area, mac_machine_name='planer')
        resp = client.get('/public/')
        assert b'mac-status-badge' not in resp.data


class TestAdminToggles:
    def test_toggles_rendered(self, staff_client):
        resp = staff_client.get('/admin/config')
        assert b'MAC Machine Status Display' in resp.data
        assert b'mac_show_public_oops' in resp.data
        assert b'mac_show_kiosk_in_use' in resp.data

    def test_toggle_roundtrip(self, staff_client):
        # Turn public in_use ON (default off) and persist.
        staff_client.post('/admin/config', data={
            'wifi_info_default': 'none',
            'mac_show_public_in_use': 'y',
            'mac_show_public_oops': 'y',
            'mac_show_public_locked_out': 'y',
        })
        assert config_service.get_config('mac_show_public_in_use', 'false') == 'true'
