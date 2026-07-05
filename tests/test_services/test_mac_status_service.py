"""Tests for machine_status injection into the status_service dashboards."""

import pytest

from esb.services import mac_service, status_service


@pytest.fixture
def mac_url(app):
    app.config['MAC_URL'] = 'http://mac.test'
    return app.config['MAC_URL']


def _status_dict(name, status='oops'):
    return {
        'name': name, 'display_name': name, 'status': status, 'relay': False,
        'oops': status == 'oops', 'locked_out': False, 'current_user': None,
        'last_checkin': None, 'last_update': None,
    }


class TestDashboardInjection:
    def test_area_dashboard_includes_machine_status(self, mac_url, make_area, make_equipment):
        area = make_area()
        make_equipment(name='Planer', area=area, mac_machine_name='planer')
        mac_service.upsert_machine_status(_status_dict('planer'))
        dashboard = status_service.get_area_status_dashboard()
        item = dashboard[0]['equipment'][0]
        assert 'machine_status' in item
        assert item['machine_status'].status == 'oops'

    def test_single_area_dashboard_includes_machine_status(self, mac_url, make_area, make_equipment):
        area = make_area()
        make_equipment(name='Planer', area=area, mac_machine_name='planer')
        mac_service.upsert_machine_status(_status_dict('planer'))
        data = status_service.get_single_area_status_dashboard(area.id)
        assert data['equipment'][0]['machine_status'].status == 'oops'

    def test_none_when_disabled(self, app, make_area, make_equipment):
        app.config['MAC_URL'] = ''
        area = make_area()
        make_equipment(name='Planer', area=area, mac_machine_name='planer')
        dashboard = status_service.get_area_status_dashboard()
        assert dashboard[0]['equipment'][0]['machine_status'] is None

    def test_batched_single_query(self, mac_url, make_area, make_equipment):
        # Two linked machines: the dashboard should batch-load statuses, not N+1.
        area = make_area()
        make_equipment(name='A', area=area, mac_machine_name='a')
        make_equipment(name='B', area=area, mac_machine_name='b')
        mac_service.upsert_machine_status(_status_dict('a'))
        mac_service.upsert_machine_status(_status_dict('b', status='idle'))
        with pytest.MonkeyPatch().context() as mp:
            calls = {'n': 0}
            orig = mac_service.get_statuses_for_names

            def counting(names):
                calls['n'] += 1
                return orig(names)

            mp.setattr(mac_service, 'get_statuses_for_names', counting)
            status_service.get_area_status_dashboard()
            assert calls['n'] == 1  # one batched call for the whole build
