"""Tests for public views (status dashboard, kiosk, QR equipment pages, problem reports)."""

import re
from datetime import date
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from esb.models.repair_record import RepairRecord


def _main_element_classes(html: str) -> list[str]:
    """Return the class list on the rendered ``<main>`` element."""
    match = re.search(r'''<main\b[^>]*\bclass=["']([^"']*)["']''', html)
    assert match, 'no <main> element with class attribute found'
    return match.group(1).split()


class TestStatusDashboardView:
    """Tests for the status dashboard route."""

    def test_dashboard_renders_for_staff(self, staff_client, make_area, make_equipment):
        """Staff user can access the status dashboard."""
        area = make_area(name='Workshop')
        make_equipment(name='Table Saw', area=area)

        response = staff_client.get('/public/')
        assert response.status_code == 200
        assert b'Equipment Status' in response.data

    def test_dashboard_renders_for_technician(self, tech_client, make_area, make_equipment):
        """Technician user can access the status dashboard."""
        area = make_area(name='Lab')
        make_equipment(name='Oscilloscope', area=area)

        response = tech_client.get('/public/')
        assert response.status_code == 200
        assert b'Equipment Status' in response.data

    def test_dashboard_accessible_unauthenticated(self, client, make_area, make_equipment):
        """Unauthenticated user can access the status dashboard."""
        area = make_area(name='Workshop')
        make_equipment(name='Drill Press', area=area)

        response = client.get('/public/')
        assert response.status_code == 200
        assert b'Equipment Status' in response.data

    def test_dashboard_shows_login_link_when_unauthenticated(self, client):
        """Unauthenticated user sees Staff Login link."""
        response = client.get('/public/')
        assert response.status_code == 200
        assert b'Staff Login' in response.data
        assert b'/auth/login' in response.data

    def test_dashboard_hides_login_link_when_authenticated(self, staff_client):
        """Authenticated user does not see Staff Login link."""
        response = staff_client.get('/public/')
        assert response.status_code == 200
        assert b'Staff Login' not in response.data

    def test_dashboard_shows_kiosk_link(self, client):
        """Dashboard shows Kiosk View dropdown with the All Equipment link."""
        response = client.get('/public/')
        assert response.status_code == 200
        html = response.data.decode()
        # Must contain the All Equipment dropdown item linking to /public/kiosk
        # (not just any kiosk URL -- the per-area links would also satisfy a
        # naive substring check).
        assert 'href="/public/kiosk"' in html
        assert 'All Equipment' in html

    def test_dashboard_kiosk_dropdown_contains_all_equipment_link(self, client):
        """Dashboard renders Kiosk View as a Bootstrap dropdown with All Equipment item."""
        response = client.get('/public/')
        assert response.status_code == 200
        html = response.data.decode()
        assert 'data-bs-toggle="dropdown"' in html
        assert 'href="/public/kiosk"' in html
        assert 'All Equipment' in html

    def test_dashboard_kiosk_dropdown_contains_per_area_links_for_populated_areas(
        self, client, make_area, make_equipment,
    ):
        """Dropdown includes per-area kiosk URLs for areas with equipment."""
        area1 = make_area(name='Wood Shop')
        area2 = make_area(name='Metal Shop')
        make_equipment(name='Lathe', area=area1)
        make_equipment(name='Welder', area=area2)

        response = client.get('/public/')
        assert response.status_code == 200
        html = response.data.decode()
        assert f'href="/public/kiosk/{area1.id}"' in html
        assert f'href="/public/kiosk/{area2.id}"' in html
        assert 'Wood Shop' in html
        assert 'Metal Shop' in html

    def test_dashboard_kiosk_dropdown_excludes_empty_areas(
        self, client, make_area, make_equipment,
    ):
        """Dropdown excludes per-area links for areas with zero equipment."""
        populated = make_area(name='Busy Shop')
        empty = make_area(name='Empty Room')
        make_equipment(name='Drill', area=populated)

        response = client.get('/public/')
        assert response.status_code == 200
        html = response.data.decode()
        assert f'href="/public/kiosk/{populated.id}"' in html
        assert f'href="/public/kiosk/{empty.id}"' not in html

    def test_dashboard_kiosk_dropdown_excludes_archived_areas(
        self, client, make_area, make_equipment,
    ):
        """Dropdown excludes per-area links for archived areas (even with equipment)."""
        from esb.extensions import db

        active = make_area(name='Active Shop')
        archived = make_area(name='Closed Wing')
        make_equipment(name='Active Tool', area=active)
        make_equipment(name='Old Tool', area=archived)
        archived.is_archived = True
        db.session.commit()

        response = client.get('/public/')
        assert response.status_code == 200
        html = response.data.decode()
        assert f'href="/public/kiosk/{active.id}"' in html
        assert f'href="/public/kiosk/{archived.id}"' not in html
        assert 'Closed Wing' not in html

    def test_dashboard_kiosk_dropdown_only_all_equipment_when_no_areas(self, app, client):
        """Empty database: dropdown has All Equipment, no divider, no per-area URLs."""
        from esb.services import status_service
        # Precondition: empty DB (guard against future fixtures seeding default areas).
        assert status_service.get_area_status_dashboard() == []

        response = client.get('/public/')
        assert response.status_code == 200
        html = response.data.decode()
        assert 'href="/public/kiosk"' in html
        assert 'All Equipment' in html
        assert '<hr class="dropdown-divider">' not in html
        assert not re.search(r'href="/public/kiosk/\d+"', html)

    def test_dashboard_loads_bootstrap_bundle_js(self, client):
        """Dashboard loads bootstrap.bundle.min.js (the dropdown's JS dependency)."""
        response = client.get('/public/')
        assert response.status_code == 200
        html = response.data.decode()
        assert 'bootstrap.bundle.min.js' in html

    def test_equipment_page_links_to_dashboard(self, client, make_area, make_equipment):
        """Equipment page has a Back to Status Dashboard link."""
        area = make_area(name='Shop')
        equip = make_equipment(name='Lathe', area=area)

        response = client.get(f'/public/equipment/{equip.id}')
        assert response.status_code == 200
        assert b'Back to Status Dashboard' in response.data
        assert b'/public/' in response.data

    def test_dashboard_authenticated_has_navbar(self, staff_client, make_area, make_equipment):
        """Authenticated user gets full navbar and footer from base.html."""
        area = make_area(name='Workshop')
        make_equipment(name='Saw', area=area)

        response = staff_client.get('/public/')
        assert response.status_code == 200
        assert b'navbar' in response.data
        self._assert_copyright_footer(response.data)

    def test_dashboard_unauthenticated_has_footer(self, client, make_area, make_equipment):
        """Unauthenticated dashboard (extends base_public.html) also shows the copyright footer."""
        area = make_area(name='Workshop')
        make_equipment(name='Saw', area=area)

        response = client.get('/public/')
        assert response.status_code == 200
        self._assert_copyright_footer(response.data)

    @staticmethod
    def _assert_copyright_footer(body):
        """Verify the new copyright footer text, both links, and absence of the old text."""
        assert b'Jason Antman' in body
        assert b'href="https://github.com/jantman/equipment-status-board"' in body
        assert b'href="https://opensource.org/license/mit"' in body
        assert b'MIT licensed' in body
        assert b'Decatur Makers' not in body

    def test_area_headings_displayed(self, staff_client, make_area, make_equipment):
        """Area names are displayed as section headings."""
        area1 = make_area(name='Metal Shop')
        area2 = make_area(name='Wood Shop')
        make_equipment(name='Welder', area=area1)
        make_equipment(name='Bandsaw', area=area2)

        response = staff_client.get('/public/')
        assert b'Metal Shop' in response.data
        assert b'Wood Shop' in response.data

    def test_equipment_names_displayed(self, staff_client, make_area, make_equipment):
        """Equipment names are displayed on the dashboard."""
        area = make_area(name='Shop')
        make_equipment(name='CNC Router', area=area)
        make_equipment(name='Drill Press', area=area)

        response = staff_client.get('/public/')
        assert b'CNC Router' in response.data
        assert b'Drill Press' in response.data

    def test_status_indicator_css_classes(
        self, staff_client, make_area, make_equipment, make_repair_record,
    ):
        """Status indicator CSS classes present for green, yellow, red."""
        area = make_area(name='Shop')
        make_equipment(name='Good Tool', area=area)
        yellow_equip = make_equipment(name='Iffy Tool', area=area)
        red_equip = make_equipment(name='Broken Tool', area=area)

        make_repair_record(equipment=yellow_equip, status='New', severity='Degraded')
        make_repair_record(equipment=red_equip, status='New', severity='Down')

        # green_equip has no records, so green
        response = staff_client.get('/public/')
        html = response.data.decode()

        assert 'bg-success' in html  # green
        assert 'bg-warning' in html  # yellow
        assert 'bg-danger' in html   # red

    def test_issue_description_for_degraded_equipment(
        self, staff_client, make_area, make_equipment, make_repair_record,
    ):
        """Yellow/red equipment shows issue description."""
        area = make_area(name='Shop')
        equip = make_equipment(name='Lathe', area=area)
        make_repair_record(
            equipment=equip, status='New', severity='Degraded',
            description='Belt needs replacement',
        )

        response = staff_client.get('/public/')
        assert b'Belt needs replacement' in response.data

    def test_empty_state_no_areas(self, staff_client):
        """Empty state message when no areas/equipment exist."""
        response = staff_client.get('/public/')
        assert b'No equipment registered yet.' in response.data

    def test_archived_equipment_not_shown(
        self, staff_client, make_area, make_equipment,
    ):
        """Archived equipment is excluded from the dashboard."""
        area = make_area(name='Shop')
        make_equipment(name='Active Tool', area=area)
        make_equipment(name='Retired Tool', area=area, is_archived=True)

        response = staff_client.get('/public/')
        assert b'Active Tool' in response.data
        assert b'Retired Tool' not in response.data

    def test_status_indicator_aria_labels(
        self, staff_client, make_area, make_equipment, make_repair_record,
    ):
        """Status indicators include ARIA labels for accessibility."""
        area = make_area(name='Shop')
        equip = make_equipment(name='Printer', area=area)
        make_repair_record(equipment=equip, status='New', severity='Down')

        response = staff_client.get('/public/')
        html = response.data.decode()
        assert 'aria-label="Equipment status: Down"' in html

    def test_operational_equipment_aria_label(
        self, staff_client, make_area, make_equipment,
    ):
        """Operational equipment has correct ARIA label."""
        area = make_area(name='Shop')
        make_equipment(name='Good Tool', area=area)

        response = staff_client.get('/public/')
        html = response.data.decode()
        assert 'aria-label="Equipment status: Operational"' in html

    def test_responsive_layout_classes(self, staff_client, make_area, make_equipment):
        """Dashboard grid has responsive column classes."""
        area = make_area(name='Shop')
        make_equipment(name='Tool', area=area)

        response = staff_client.get('/public/')
        html = response.data.decode()
        assert 'col-12' in html
        assert 'col-sm-6' in html
        assert 'col-lg-4' in html
        assert 'col-xl-3' in html

    def test_issue_description_for_down_equipment(
        self, staff_client, make_area, make_equipment, make_repair_record,
    ):
        """Down (red) equipment shows issue description."""
        area = make_area(name='Shop')
        equip = make_equipment(name='CNC Mill', area=area)
        make_repair_record(
            equipment=equip, status='New', severity='Down',
            description='Spindle motor failed',
        )

        response = staff_client.get('/public/')
        assert b'Spindle motor failed' in response.data

    def test_status_dashboard_displays_eta_when_set(
        self, client, make_area, make_equipment, make_repair_record,
    ):
        area = make_area(name='Shop')
        equip = make_equipment(name='Lathe', area=area)
        make_repair_record(
            equipment=equip, status='New', severity='Down',
            description='broken', eta=date(2026, 7, 4),
        )
        response = client.get('/public/')
        expected = ('ETA: ' + date(2026, 7, 4).strftime('%b %d, %Y')).encode()
        assert expected in response.data

    def test_status_dashboard_omits_eta_when_unset(
        self, client, make_area, make_equipment, make_repair_record,
    ):
        area = make_area(name='Shop')
        equip = make_equipment(name='Lathe', area=area)
        make_repair_record(
            equipment=equip, status='New', severity='Down', description='broken',
        )
        response = client.get('/public/')
        assert b'ETA:' not in response.data

    def test_status_dashboard_displays_past_eta(
        self, client, make_area, make_equipment, make_repair_record,
    ):
        area = make_area(name='Shop')
        equip = make_equipment(name='Lathe', area=area)
        make_repair_record(
            equipment=equip, status='New', severity='Down',
            description='broken', eta=date(2025, 1, 1),
        )
        response = client.get('/public/')
        expected = date(2025, 1, 1).strftime('%b %d, %Y').encode()
        assert expected in response.data

    def test_status_dashboard_displays_eta_today(
        self, client, make_area, make_equipment, make_repair_record,
    ):
        # Capture once so the test stays deterministic across midnight UTC.
        today = date.today()
        area = make_area(name='Shop')
        equip = make_equipment(name='Lathe', area=area)
        make_repair_record(
            equipment=equip, status='New', severity='Down',
            description='broken', eta=today,
        )
        response = client.get('/public/')
        expected = today.strftime('%b %d, %Y').encode()
        assert expected in response.data

    def test_status_dashboard_displays_far_future_eta(
        self, client, make_area, make_equipment, make_repair_record,
    ):
        area = make_area(name='Shop')
        equip = make_equipment(name='Lathe', area=area)
        make_repair_record(
            equipment=equip, status='New', severity='Down',
            description='broken', eta=date(2030, 12, 31),
        )
        response = client.get('/public/')
        expected = date(2030, 12, 31).strftime('%b %d, %Y').encode()
        assert expected in response.data

    def test_equipment_tiles_link_to_equipment_page(self, client, make_area, make_equipment):
        """Equipment tiles on the status dashboard link to the QR code equipment page (issue #13)."""
        area = make_area(name='Shop')
        equip = make_equipment(name='Table Saw', area=area)

        response = client.get('/public/')
        html = response.data.decode()
        assert f'/public/equipment/{equip.id}' in html

    def test_not_sure_severity_displays_as_yellow(
        self, staff_client, make_area, make_equipment, make_repair_record,
    ):
        """'Not Sure' severity renders as yellow/bg-warning on dashboard (AC #3)."""
        area = make_area(name='Shop')
        equip = make_equipment(name='Mystery Tool', area=area)
        make_repair_record(
            equipment=equip, status='New', severity='Not Sure',
            description='Making odd sounds',
        )

        response = staff_client.get('/public/')
        html = response.data.decode()
        assert 'bg-warning' in html
        assert 'Making odd sounds' in html


class TestKioskView:
    """Tests for the kiosk display route."""

    def test_kiosk_renders_without_authentication(self, client, make_area, make_equipment):
        """Kiosk page is accessible without login (AC #1)."""
        area = make_area(name='Workshop')
        make_equipment(name='Table Saw', area=area)

        response = client.get('/public/kiosk')
        assert response.status_code == 200
        assert b'Table Saw' in response.data

    def test_kiosk_area_headings_displayed(self, client, make_area, make_equipment):
        """Kiosk displays area headings (AC #2)."""
        area1 = make_area(name='Metal Shop')
        area2 = make_area(name='Wood Shop')
        make_equipment(name='Welder', area=area1)
        make_equipment(name='Bandsaw', area=area2)

        response = client.get('/public/kiosk')
        assert b'Metal Shop' in response.data
        assert b'Wood Shop' in response.data

    def test_kiosk_equipment_names_displayed(self, client, make_area, make_equipment):
        """Kiosk displays equipment names (AC #2)."""
        area = make_area(name='Shop')
        make_equipment(name='CNC Router', area=area)
        make_equipment(name='Drill Press', area=area)

        response = client.get('/public/kiosk')
        assert b'CNC Router' in response.data
        assert b'Drill Press' in response.data

    def test_kiosk_status_indicators(
        self, client, make_area, make_equipment, make_repair_record,
    ):
        """Kiosk displays compact status indicators with color classes (AC #7)."""
        area = make_area(name='Shop')
        make_equipment(name='Good Tool', area=area)
        yellow_equip = make_equipment(name='Iffy Tool', area=area)
        red_equip = make_equipment(name='Broken Tool', area=area)

        make_repair_record(equipment=yellow_equip, status='New', severity='Degraded')
        make_repair_record(equipment=red_equip, status='New', severity='Down')

        response = client.get('/public/kiosk')
        html = response.data.decode()
        assert 'bg-success' in html
        assert 'bg-warning' in html
        assert 'bg-danger' in html

    def test_kiosk_issue_description_degraded(
        self, client, make_area, make_equipment, make_repair_record,
    ):
        """Degraded equipment shows issue description on kiosk (AC #3)."""
        area = make_area(name='Shop')
        equip = make_equipment(name='Lathe', area=area)
        make_repair_record(
            equipment=equip, status='New', severity='Degraded',
            description='Belt needs replacement',
        )

        response = client.get('/public/kiosk')
        assert b'Belt needs replacement' in response.data

    def test_kiosk_issue_description_down(
        self, client, make_area, make_equipment, make_repair_record,
    ):
        """Down equipment shows issue description on kiosk (AC #3)."""
        area = make_area(name='Shop')
        equip = make_equipment(name='CNC Mill', area=area)
        make_repair_record(
            equipment=equip, status='New', severity='Down',
            description='Spindle motor failed',
        )

        response = client.get('/public/kiosk')
        assert b'Spindle motor failed' in response.data

    def test_kiosk_displays_eta_when_set(
        self, client, make_area, make_equipment, make_repair_record,
    ):
        area = make_area(name='Shop')
        equip = make_equipment(name='Lathe', area=area)
        make_repair_record(
            equipment=equip, status='New', severity='Down',
            description='broken', eta=date(2026, 6, 15),
        )
        response = client.get('/public/kiosk')
        expected = ('ETA: ' + date(2026, 6, 15).strftime('%b %d, %Y')).encode()
        assert expected in response.data

    def test_kiosk_omits_eta_when_unset(
        self, client, make_area, make_equipment, make_repair_record,
    ):
        area = make_area(name='Shop')
        equip = make_equipment(name='Lathe', area=area)
        make_repair_record(
            equipment=equip, status='New', severity='Down', description='broken',
        )
        response = client.get('/public/kiosk')
        assert b'ETA:' not in response.data

    def test_kiosk_empty_state(self, client):
        """Kiosk shows empty state when no areas/equipment (AC #1)."""
        response = client.get('/public/kiosk')
        assert response.status_code == 200
        assert b'No equipment registered yet.' in response.data

    def test_kiosk_empty_state_when_all_areas_have_no_equipment(self, client, make_area):
        """All-areas kiosk shows empty-state copy when areas exist but none have equipment (F4)."""
        make_area(name='Empty One')
        make_area(name='Empty Two')

        response = client.get('/public/kiosk')
        assert response.status_code == 200
        html = response.data.decode()
        assert 'No equipment registered yet.' in html
        # Sanity: the per-area empty copy must NOT appear on the all-areas view.
        assert 'No equipment in this area yet.' not in html

    def test_kiosk_excludes_archived_equipment(self, client, make_area, make_equipment):
        """Archived equipment is excluded from kiosk display."""
        area = make_area(name='Shop')
        make_equipment(name='Active Tool', area=area)
        make_equipment(name='Retired Tool', area=area, is_archived=True)

        response = client.get('/public/kiosk')
        assert b'Active Tool' in response.data
        assert b'Retired Tool' not in response.data

    def test_kiosk_meta_refresh_tag(self, client):
        """Kiosk includes meta refresh tag for auto-refresh (AC #4)."""
        response = client.get('/public/kiosk')
        html = response.data.decode()
        assert 'meta http-equiv="refresh" content="60"' in html

    def test_kiosk_no_navbar(self, client, make_area, make_equipment):
        """Kiosk has no navbar elements (AC #1)."""
        area = make_area(name='Shop')
        make_equipment(name='Tool', area=area)

        response = client.get('/public/kiosk')
        html = response.data.decode()
        assert '<nav' not in html
        assert 'navbar' not in html

    def test_kiosk_status_aria_labels(
        self, client, make_area, make_equipment, make_repair_record,
    ):
        """Kiosk status indicators include ARIA labels (AC #7)."""
        area = make_area(name='Shop')
        equip = make_equipment(name='Printer', area=area)
        make_repair_record(equipment=equip, status='New', severity='Down')

        response = client.get('/public/kiosk')
        html = response.data.decode()
        assert 'aria-label="Equipment status: Down"' in html

    def test_kiosk_css_classes_large_fonts(self, client, make_area, make_equipment):
        """Kiosk uses CSS classes for large fonts (AC #2)."""
        area = make_area(name='Shop')
        make_equipment(name='Tool', area=area)

        response = client.get('/public/kiosk')
        html = response.data.decode()
        assert 'kiosk-area-heading' in html
        assert 'kiosk-equipment-name' in html

    def test_kiosk_grid_auto_fill_class(self, client, make_area, make_equipment):
        """Kiosk uses CSS Grid auto-fill for responsive layout (AC #6)."""
        area = make_area(name='Shop')
        make_equipment(name='Tool', area=area)

        response = client.get('/public/kiosk')
        html = response.data.decode()
        assert 'kiosk-equipment-grid' in html

    def test_kiosk_param_redirects_to_kiosk(self, staff_client):
        """?kiosk=true on dashboard redirects to /public/kiosk (AC #1)."""
        response = staff_client.get('/public/?kiosk=true')
        assert response.status_code == 302
        assert '/public/kiosk' in response.headers['Location']

    def test_kiosk_accessible_by_authenticated_user(
        self, staff_client, make_area, make_equipment,
    ):
        """Authenticated users can also access the kiosk route."""
        area = make_area(name='Shop')
        make_equipment(name='Tool', area=area)

        response = staff_client.get('/public/kiosk')
        assert response.status_code == 200
        assert b'Tool' in response.data

    def test_kiosk_param_unauthenticated_redirects_to_kiosk(self, client):
        """Unauthenticated user hitting ?kiosk=true is redirected to kiosk view."""
        response = client.get('/public/?kiosk=true')
        assert response.status_code == 302
        assert '/public/kiosk' in response.headers['Location']

    def test_kiosk_skips_empty_areas(self, client, make_area, make_equipment):
        """Areas with no equipment are not rendered on kiosk display."""
        populated_area = make_area(name='Busy Shop')
        make_area(name='Empty Room')
        make_equipment(name='Lathe', area=populated_area)

        response = client.get('/public/kiosk')
        html = response.data.decode()
        assert 'Busy Shop' in html
        assert 'Empty Room' not in html

    def test_kiosk_excludes_archived_areas(self, client, make_area, make_equipment):
        """Archived areas are excluded from kiosk display."""
        from esb.extensions import db

        active_area = make_area(name='Active Shop')
        archived_area = make_area(name='Closed Wing')
        archived_area.is_archived = True
        make_equipment(name='Drill', area=active_area)
        make_equipment(name='Old Saw', area=archived_area)
        db.session.commit()

        response = client.get('/public/kiosk')
        html = response.data.decode()
        assert 'Active Shop' in html
        assert 'Closed Wing' not in html

    def test_kiosk_has_visually_hidden_h1(self, client, make_area, make_equipment):
        """Kiosk page has a visually-hidden h1 for accessibility (no area-name suffix on all-areas view)."""
        area = make_area(name='Shop')
        make_equipment(name='Tool', area=area)

        response = client.get('/public/kiosk')
        html = response.data.decode()
        # Bind H1 element, visually-hidden class, AND text in a single match
        # so a regression that drops any of the three is caught.
        match = re.search(
            r'<h1[^>]*class="[^"]*\bvisually-hidden\b[^"]*"[^>]*>([^<]*)</h1>',
            html,
        )
        assert match, 'expected <h1 class="visually-hidden">...</h1>'
        # All-areas kiosk: no area name suffix.
        assert match.group(1).strip() == 'Equipment Status'

    def test_kiosk_equipment_name_is_heading(self, client, make_area, make_equipment):
        """Equipment names use h3 elements for proper heading hierarchy."""
        area = make_area(name='Shop')
        make_equipment(name='CNC Router', area=area)

        response = client.get('/public/kiosk')
        html = response.data.decode()
        assert '<h3 class="kiosk-equipment-name' in html

    def test_kiosk_has_scale_wrapper_div(self, client, make_area, make_equipment):
        """Kiosk page wraps content in #kiosk-scale-content for the JS scaler to target."""
        area = make_area(name='Shop')
        make_equipment(name='Tool', area=area)

        response = client.get('/public/kiosk')
        assert response.status_code == 200
        html = response.data.decode()
        assert 'id="kiosk-scale-content"' in html
        assert 'kiosk-scale-wrapper' in html

    def test_kiosk_main_has_no_padding(self, client, make_area, make_equipment):
        """Kiosk <main> uses p-0 (no padding) so the scaling wrapper measures full viewport."""
        area = make_area(name='Shop')
        make_equipment(name='Tool', area=area)

        response = client.get('/public/kiosk')
        assert response.status_code == 200
        classes = _main_element_classes(response.data.decode())
        assert 'p-0' in classes
        assert 'p-3' not in classes

    def test_app_css_kiosk_body_has_overflow_hidden(self):
        """app.css .kiosk-body rule sets overflow: hidden (no-JS-fallback / pre-JS scrollbar guard)."""
        css_path = Path(__file__).resolve().parents[2] / 'esb' / 'static' / 'css' / 'app.css'
        css = css_path.read_text()
        assert '.kiosk-body' in css
        idx = css.index('.kiosk-body')
        block_end = css.index('}', idx)
        block = css[idx:block_end]
        assert 'overflow: hidden' in block

    def test_kiosk_loads_app_js(self, client, make_area, make_equipment):
        """Kiosk pages must load app.js -- it carries the scaling implementation."""
        area = make_area(name='Shop')
        make_equipment(name='Tool', area=area)

        response = client.get('/public/kiosk')
        assert response.status_code == 200
        html = response.data.decode()
        assert 'js/app.js' in html


class TestPerAreaKioskView:
    """Tests for the per-area kiosk display route /public/kiosk/<int:area_id>."""

    def test_per_area_kiosk_renders_unauthenticated(self, client, make_area, make_equipment):
        """Per-area kiosk is accessible without login."""
        area = make_area(name='Wood Shop')
        make_equipment(name='Lathe', area=area)

        response = client.get(f'/public/kiosk/{area.id}')
        assert response.status_code == 200
        assert b'Lathe' in response.data

    def test_per_area_kiosk_shows_only_that_areas_equipment(
        self, client, make_area, make_equipment,
    ):
        """Per-area kiosk excludes equipment from other areas."""
        area_a = make_area(name='Wood Shop')
        area_b = make_area(name='Metal Shop')
        make_equipment(name='Lathe', area=area_a)
        make_equipment(name='Welder', area=area_b)

        response = client.get(f'/public/kiosk/{area_a.id}')
        assert response.status_code == 200
        html = response.data.decode()
        assert 'Lathe' in html
        assert 'Welder' not in html
        assert 'Metal Shop' not in html

    def test_per_area_kiosk_shows_area_name_in_h1(self, client, make_area, make_equipment):
        """The visually-hidden h1 includes the area name."""
        area = make_area(name='Wood Shop')
        make_equipment(name='Lathe', area=area)

        response = client.get(f'/public/kiosk/{area.id}')
        assert response.status_code == 200
        html = response.data.decode()
        match = re.search(
            r'<h1[^>]*class="[^"]*\bvisually-hidden\b[^"]*"[^>]*>([^<]*)</h1>',
            html,
        )
        assert match, 'expected visually-hidden <h1>'
        assert match.group(1).strip() == 'Equipment Status - Wood Shop'

    def test_per_area_kiosk_shows_area_name_in_h2_heading(
        self, client, make_area, make_equipment,
    ):
        """Per-area kiosk shows the area name as the kiosk-area-heading h2."""
        area = make_area(name='Wood Shop')
        make_equipment(name='Lathe', area=area)

        response = client.get(f'/public/kiosk/{area.id}')
        assert response.status_code == 200
        html = response.data.decode()
        match = re.search(
            r'<h2[^>]*class="[^"]*\bkiosk-area-heading\b[^"]*"[^>]*>([^<]*)</h2>',
            html,
        )
        assert match, 'expected <h2 class="kiosk-area-heading">'
        assert match.group(1).strip() == 'Wood Shop'

    def test_per_area_kiosk_shows_area_name_in_title(self, client, make_area, make_equipment):
        """Per-area kiosk <title> includes the area name."""
        area = make_area(name='Wood Shop')
        make_equipment(name='Lathe', area=area)

        response = client.get(f'/public/kiosk/{area.id}')
        assert response.status_code == 200
        html = response.data.decode()
        title_match = re.search(r'<title>([^<]*)</title>', html)
        assert title_match
        assert 'Wood Shop' in title_match.group(1)

    def test_per_area_kiosk_404_for_missing_area(self, client):
        """Returns 404 when no area exists with the given id."""
        response = client.get('/public/kiosk/999999')
        assert response.status_code == 404

    def test_per_area_kiosk_404_for_archived_area(self, client, make_area, make_equipment):
        """Returns 404 for archived area (no leakage of 'exists but archived')."""
        from esb.extensions import db

        area = make_area(name='Closed Wing')
        make_equipment(name='Old Tool', area=area)
        area.is_archived = True
        db.session.commit()

        response = client.get(f'/public/kiosk/{area.id}')
        assert response.status_code == 404

    def test_per_area_kiosk_404_for_non_integer(self, client):
        """Returns 404 when area_id is not an integer (Flask int converter)."""
        response = client.get('/public/kiosk/abc')
        assert response.status_code == 404

    def test_per_area_kiosk_excludes_archived_equipment(
        self, client, make_area, make_equipment,
    ):
        """Archived equipment in the area is excluded from the per-area kiosk."""
        area = make_area(name='Shop')
        make_equipment(name='Active Tool', area=area)
        make_equipment(name='Retired Tool', area=area, is_archived=True)

        response = client.get(f'/public/kiosk/{area.id}')
        assert response.status_code == 200
        html = response.data.decode()
        assert 'Active Tool' in html
        assert 'Retired Tool' not in html

    def test_per_area_kiosk_shows_status_indicators(
        self, client, make_area, make_equipment, make_repair_record,
    ):
        """Per-area kiosk renders compact status-indicator color classes."""
        area = make_area(name='Shop')
        # Side-effect-only Equipment to exercise the green path:
        make_equipment(name='Good Tool', area=area)
        yellow = make_equipment(name='Iffy Tool', area=area)
        red = make_equipment(name='Broken Tool', area=area)
        make_repair_record(equipment=yellow, status='New', severity='Degraded')
        make_repair_record(equipment=red, status='New', severity='Down')

        response = client.get(f'/public/kiosk/{area.id}')
        assert response.status_code == 200
        html = response.data.decode()
        assert 'bg-success' in html
        assert 'bg-warning' in html
        assert 'bg-danger' in html

    def test_per_area_kiosk_shows_issue_descriptions(
        self, client, make_area, make_equipment, make_repair_record,
    ):
        """Per-area kiosk shows issue descriptions for non-green equipment."""
        area = make_area(name='Shop')
        equip = make_equipment(name='Lathe', area=area)
        make_repair_record(
            equipment=equip, status='New', severity='Down',
            description='Spindle motor failed',
        )

        response = client.get(f'/public/kiosk/{area.id}')
        assert response.status_code == 200
        assert b'Spindle motor failed' in response.data

    def test_per_area_kiosk_displays_eta_when_set(
        self, client, make_area, make_equipment, make_repair_record,
    ):
        area = make_area(name='Shop')
        equip = make_equipment(name='Lathe', area=area)
        make_repair_record(
            equipment=equip, status='New', severity='Down',
            description='broken', eta=date(2026, 6, 15),
        )
        response = client.get(f'/public/kiosk/{area.id}')
        expected = ('ETA: ' + date(2026, 6, 15).strftime('%b %d, %Y')).encode()
        assert expected in response.data

    def test_per_area_kiosk_meta_refresh_present(self, client, make_area, make_equipment):
        """Per-area kiosk inherits the 60s meta refresh from base_kiosk.html (exactly one tag)."""
        area = make_area(name='Shop')
        make_equipment(name='Tool', area=area)

        response = client.get(f'/public/kiosk/{area.id}')
        assert response.status_code == 200
        html = response.data.decode()
        meta_tags = re.findall(r'<meta\s+http-equiv="refresh"[^>]*>', html)
        assert len(meta_tags) == 1
        assert 'content="60"' in meta_tags[0]

    def test_per_area_kiosk_no_navbar(self, client, make_area, make_equipment):
        """Per-area kiosk has no navbar elements (element-bound, not substring-match)."""
        area = make_area(name='Shop')
        make_equipment(name='Tool', area=area)

        response = client.get(f'/public/kiosk/{area.id}')
        assert response.status_code == 200
        html = response.data.decode()
        # Element-bound: a `<nav` tag opening, not just any "<nav" substring
        # in user content (e.g., an area named "navbar maintenance").
        assert not re.search(r'<nav[\s>]', html)
        assert not re.search(r'\bclass="[^"]*\bnavbar\b', html)

    def test_per_area_kiosk_empty_area_shows_per_area_empty_copy(self, client, make_area):
        """Area with no equipment renders the per-area-specific empty-state copy AND area name."""
        area = make_area(name='Empty Room')
        response = client.get(f'/public/kiosk/{area.id}')
        assert response.status_code == 200
        html = response.data.decode()
        assert 'No equipment in this area yet.' in html
        assert 'No equipment registered yet.' not in html
        # Visible heading must show which area we're looking at (F1).
        match = re.search(
            r'<h2[^>]*class="[^"]*\bkiosk-area-heading\b[^"]*"[^>]*>([^<]*)</h2>',
            html,
        )
        assert match, 'empty per-area kiosk should still display the area name as a visible h2'
        assert match.group(1).strip() == 'Empty Room'

    def test_per_area_kiosk_has_scale_wrapper_div(self, client, make_area, make_equipment):
        """Per-area kiosk wraps content in #kiosk-scale-content for the JS scaler."""
        area = make_area(name='Shop')
        make_equipment(name='Tool', area=area)

        response = client.get(f'/public/kiosk/{area.id}')
        assert response.status_code == 200
        html = response.data.decode()
        assert 'id="kiosk-scale-content"' in html
        assert 'kiosk-scale-wrapper' in html

    def test_per_area_kiosk_main_has_no_padding(self, client, make_area, make_equipment):
        """Per-area kiosk <main> uses p-0 (no padding)."""
        area = make_area(name='Shop')
        make_equipment(name='Tool', area=area)

        response = client.get(f'/public/kiosk/{area.id}')
        assert response.status_code == 200
        classes = _main_element_classes(response.data.decode())
        assert 'p-0' in classes
        assert 'p-3' not in classes


class TestEquipmentPageView:
    """Tests for the QR code equipment page route (AC: #2, #3, #4, #7)."""

    def test_renders_without_authentication(self, client, make_area, make_equipment):
        """Equipment page is accessible without login (AC #2)."""
        area = make_area(name='Workshop')
        equip = make_equipment(name='Table Saw', area=area)

        response = client.get(f'/public/equipment/{equip.id}')
        assert response.status_code == 200

    def test_shows_equipment_name_and_area(self, client, make_area, make_equipment):
        """Equipment page shows name and area (AC #3)."""
        area = make_area(name='Wood Shop')
        equip = make_equipment(name='Band Saw', area=area)

        response = client.get(f'/public/equipment/{equip.id}')
        html = response.data.decode()
        assert 'Band Saw' in html
        assert 'Wood Shop' in html

    def test_shows_large_status_indicator(self, client, make_area, make_equipment):
        """Equipment page shows large status indicator (AC #3)."""
        area = make_area(name='Shop')
        equip = make_equipment(name='Lathe', area=area)

        response = client.get(f'/public/equipment/{equip.id}')
        html = response.data.decode()
        assert 'status-indicator-large' in html

    def test_shows_issue_description_for_degraded(
        self, client, make_area, make_equipment, make_repair_record,
    ):
        """Degraded equipment shows issue description (AC #4)."""
        area = make_area(name='Shop')
        equip = make_equipment(name='Lathe', area=area)
        make_repair_record(
            equipment=equip, status='New', severity='Degraded',
            description='Belt needs replacement',
        )

        response = client.get(f'/public/equipment/{equip.id}')
        assert b'Belt needs replacement' in response.data

    def test_shows_issue_description_for_down(
        self, client, make_area, make_equipment, make_repair_record,
    ):
        """Down equipment shows issue description (AC #4)."""
        area = make_area(name='Shop')
        equip = make_equipment(name='Mill', area=area)
        make_repair_record(
            equipment=equip, status='New', severity='Down',
            description='Motor burned out',
        )

        response = client.get(f'/public/equipment/{equip.id}')
        assert b'Motor burned out' in response.data

    def test_shows_eta_when_available(
        self, client, make_area, make_equipment, make_repair_record,
    ):
        """ETA is displayed when available on an open repair (AC #4)."""
        area = make_area(name='Shop')
        equip = make_equipment(name='Drill Press', area=area)
        make_repair_record(
            equipment=equip, status='New', severity='Down',
            description='Broken chuck', eta=date(2026, 3, 15),
        )

        response = client.get(f'/public/equipment/{equip.id}')
        assert b'Mar 15, 2026' in response.data

    def test_eta_displayed_independent_of_issue_description(
        self, client, make_area, make_equipment, make_repair_record,
    ):
        """ETA renders even when issue_description is empty (decoupled, F4 / AC 31)."""
        area = make_area(name='Shop')
        equip = make_equipment(name='Drill', area=area)
        # Use a non-empty description to satisfy NOT NULL but it would not be
        # rendered for a green status anyway. The decoupling matters even when
        # status is non-green: simulate by setting an empty issue description.
        make_repair_record(
            equipment=equip, status='New', severity='Down',
            description='', eta=date(2026, 6, 15),
        )
        response = client.get(f'/public/equipment/{equip.id}')
        assert b'ETA: ' + date(2026, 6, 15).strftime('%b %d, %Y').encode() in response.data

    def test_qr_page_eta_uses_highest_severity_record_only(
        self, client, make_area, make_equipment, make_repair_record,
    ):
        """QR page ETA matches dashboard semantics: highest-severity record only.

        This test exercises ``_build_equipment_page_context``, which is also
        called from ``report_problem()`` on form-validation failure; both
        paths share the migrated ETA computation. Down (highest severity)
        has eta=None; Degraded (lower) has an ETA -- post-migration the QR
        page must NOT display the Degraded record's ETA (AC 32, F19/F24).
        """
        area = make_area(name='Shop')
        equip = make_equipment(name='Drill', area=area)
        make_repair_record(
            equipment=equip, status='New', severity='Down',
            description='broken', eta=None,
        )
        make_repair_record(
            equipment=equip, status='New', severity='Degraded',
            description='wobbly', eta=date(2026, 6, 15),
        )
        response = client.get(f'/public/equipment/{equip.id}')
        assert b'Jun 15, 2026' not in response.data

    def test_qr_page_eta_displayed_when_highest_severity_has_eta(
        self, client, make_area, make_equipment, make_repair_record,
    ):
        """QR page shows the Down record's ETA, not the Degraded one (AC 33)."""
        area = make_area(name='Shop')
        equip = make_equipment(name='Drill', area=area)
        make_repair_record(
            equipment=equip, status='New', severity='Down',
            description='broken', eta=date(2026, 5, 1),
        )
        make_repair_record(
            equipment=equip, status='New', severity='Degraded',
            description='wobbly', eta=date(2026, 7, 1),
        )
        response = client.get(f'/public/equipment/{equip.id}')
        assert b'May 01, 2026' in response.data
        assert b'Jul 01, 2026' not in response.data

    def test_shows_known_issues_when_open_repairs(
        self, client, make_area, make_equipment, make_repair_record,
    ):
        """Known Issues section is shown when open repairs exist (AC #4)."""
        area = make_area(name='Shop')
        equip = make_equipment(name='Lathe', area=area)
        make_repair_record(
            equipment=equip, status='New', severity='Degraded',
            description='Vibration issue',
        )

        response = client.get(f'/public/equipment/{equip.id}')
        html = response.data.decode()
        assert 'Known Issues' in html
        assert 'Vibration issue' in html

    def test_hides_known_issues_when_no_open_repairs(
        self, client, make_area, make_equipment,
    ):
        """Known Issues section hidden when no open repairs."""
        area = make_area(name='Shop')
        equip = make_equipment(name='Good Tool', area=area)

        response = client.get(f'/public/equipment/{equip.id}')
        html = response.data.decode()
        assert 'Known Issues' not in html

    def test_returns_404_for_nonexistent(self, client):
        """Returns 404 for non-existent equipment (AC #2)."""
        response = client.get('/public/equipment/99999')
        assert response.status_code == 404

    def test_returns_404_for_archived(self, client, make_area, make_equipment):
        """Returns 404 for archived equipment (AC #2)."""
        area = make_area(name='Shop')
        equip = make_equipment(name='Old Tool', area=area, is_archived=True)

        response = client.get(f'/public/equipment/{equip.id}')
        assert response.status_code == 404

    def test_has_equipment_info_link(self, client, make_area, make_equipment):
        """Equipment page has link to info/documentation page (AC #5)."""
        area = make_area(name='Shop')
        equip = make_equipment(name='Lathe', area=area)

        response = client.get(f'/public/equipment/{equip.id}')
        html = response.data.decode()
        assert f'/public/equipment/{equip.id}/info' in html
        assert 'Equipment Info' in html

    def test_aria_labels_present(
        self, client, make_area, make_equipment, make_repair_record,
    ):
        """ARIA labels present on status indicator and interactive elements (AC #7)."""
        area = make_area(name='Shop')
        equip = make_equipment(name='Printer', area=area)
        make_repair_record(equipment=equip, status='New', severity='Down')

        response = client.get(f'/public/equipment/{equip.id}')
        html = response.data.decode()
        assert 'aria-label="Equipment status: Down"' in html
        assert 'aria-label="View equipment info and documentation"' in html

    def test_closed_repairs_not_shown_as_known_issues(
        self, client, make_area, make_equipment, make_repair_record,
    ):
        """Closed repair records are not shown in Known Issues."""
        area = make_area(name='Shop')
        equip = make_equipment(name='Lathe', area=area)
        make_repair_record(
            equipment=equip, status='Resolved', severity='Down',
            description='Fixed motor',
        )

        response = client.get(f'/public/equipment/{equip.id}')
        html = response.data.decode()
        assert 'Known Issues' not in html

    def test_qr_page_hero_class(self, client, make_area, make_equipment):
        """Equipment page has qr-page-hero CSS class for mobile layout."""
        area = make_area(name='Shop')
        equip = make_equipment(name='Tool', area=area)

        response = client.get(f'/public/equipment/{equip.id}')
        html = response.data.decode()
        assert 'qr-page-hero' in html


class TestEquipmentInfoView:
    """Tests for the equipment info/documentation page route (AC: #5, #6)."""

    def test_renders_without_authentication(self, client, make_area, make_equipment):
        """Info page is accessible without login (AC #5)."""
        area = make_area(name='Workshop')
        equip = make_equipment(name='Table Saw', area=area)

        response = client.get(f'/public/equipment/{equip.id}/info')
        assert response.status_code == 200

    def test_shows_equipment_name(self, client, make_area, make_equipment):
        """Info page shows equipment name."""
        area = make_area(name='Shop')
        equip = make_equipment(name='CNC Router', area=area)

        response = client.get(f'/public/equipment/{equip.id}/info')
        assert b'CNC Router' in response.data

    def test_shows_documents_grouped_by_category(self, client, db, make_area, make_equipment):
        """Info page shows documents organized by category (AC #6)."""
        from esb.models.document import Document

        area = make_area(name='Shop')
        equip = make_equipment(name='Lathe', area=area)

        doc = Document(
            original_filename='manual.pdf',
            stored_filename='abc123.pdf',
            content_type='application/pdf',
            size_bytes=1024,
            category='owners_manual',
            parent_type='equipment_doc',
            parent_id=equip.id,
            uploaded_by='testuser',
        )
        db.session.add(doc)
        db.session.commit()

        response = client.get(f'/public/equipment/{equip.id}/info')
        html = response.data.decode()
        assert "Owner&#39;s Manual" in html or "Owner's Manual" in html
        assert 'manual.pdf' in html

    def test_shows_download_links(self, client, db, make_area, make_equipment):
        """Info page has download links for documents (AC #6)."""
        from esb.models.document import Document

        area = make_area(name='Shop')
        equip = make_equipment(name='Mill', area=area)

        doc = Document(
            original_filename='guide.pdf',
            stored_filename='def456.pdf',
            content_type='application/pdf',
            size_bytes=2048,
            category='quick_start',
            parent_type='equipment_doc',
            parent_id=equip.id,
            uploaded_by='testuser',
        )
        db.session.add(doc)
        db.session.commit()

        response = client.get(f'/public/equipment/{equip.id}/info')
        html = response.data.decode()
        assert 'download="guide.pdf"' in html

    def test_shows_photos(self, client, db, make_area, make_equipment):
        """Info page shows photos (AC #6)."""
        from esb.models.document import Document

        area = make_area(name='Shop')
        equip = make_equipment(name='Drill', area=area)

        photo = Document(
            original_filename='front.jpg',
            stored_filename='photo123.jpg',
            content_type='image/jpeg',
            size_bytes=5000,
            parent_type='equipment_photo',
            parent_id=equip.id,
            uploaded_by='testuser',
        )
        db.session.add(photo)
        db.session.commit()

        response = client.get(f'/public/equipment/{equip.id}/info')
        html = response.data.decode()
        assert 'front.jpg' in html

    def test_shows_external_links_with_target_blank(
        self, client, db, make_area, make_equipment,
    ):
        """Info page shows external links with target=_blank (AC #6)."""
        from esb.models.external_link import ExternalLink

        area = make_area(name='Shop')
        equip = make_equipment(name='Lathe', area=area)

        link = ExternalLink(
            equipment_id=equip.id,
            title='Manufacturer Site',
            url='https://example.com/lathe',
            created_by='testuser',
        )
        db.session.add(link)
        db.session.commit()

        response = client.get(f'/public/equipment/{equip.id}/info')
        html = response.data.decode()
        assert 'Manufacturer Site' in html
        assert 'target="_blank"' in html
        assert 'rel="noopener noreferrer"' in html

    def test_returns_404_for_nonexistent(self, client):
        """Returns 404 for non-existent equipment."""
        response = client.get('/public/equipment/99999/info')
        assert response.status_code == 404

    def test_returns_404_for_archived(self, client, make_area, make_equipment):
        """Returns 404 for archived equipment."""
        area = make_area(name='Shop')
        equip = make_equipment(name='Old Tool', area=area, is_archived=True)

        response = client.get(f'/public/equipment/{equip.id}/info')
        assert response.status_code == 404

    def test_hides_empty_sections(self, client, make_area, make_equipment):
        """Info page hides empty sections (AC #6)."""
        area = make_area(name='Shop')
        equip = make_equipment(name='New Tool', area=area)

        response = client.get(f'/public/equipment/{equip.id}/info')
        html = response.data.decode()
        assert 'No documentation available' in html

    def test_back_to_status_link(self, client, make_area, make_equipment):
        """Info page has back link to equipment status page (AC #5)."""
        area = make_area(name='Shop')
        equip = make_equipment(name='Lathe', area=area)

        response = client.get(f'/public/equipment/{equip.id}/info')
        html = response.data.decode()
        assert f'/public/equipment/{equip.id}' in html
        assert 'Back to Status' in html


class TestServeUploadView:
    """Tests for the public file serving route."""

    def test_serves_equipment_file(self, client, app, make_area, make_equipment, tmp_path):
        """Serves a file from the equipment uploads directory."""
        area = make_area(name='Shop')
        equip = make_equipment(name='Lathe', area=area)

        # Create a file in the expected upload path
        equip_dir = tmp_path / 'equipment' / str(equip.id) / 'docs'
        equip_dir.mkdir(parents=True)
        test_file = equip_dir / 'manual.pdf'
        test_file.write_bytes(b'%PDF-fake-content')

        app.config['UPLOAD_PATH'] = str(tmp_path)
        response = client.get(f'/public/uploads/equipment/{equip.id}/docs/manual.pdf')
        assert response.status_code == 200
        assert response.data == b'%PDF-fake-content'

    def test_rejects_directory_traversal(self, client, app, tmp_path):
        """Rejects paths containing '..' for directory traversal prevention."""
        app.config['UPLOAD_PATH'] = str(tmp_path)
        response = client.get('/public/uploads/equipment/../../../etc/passwd')
        assert response.status_code == 404

    def test_rejects_non_equipment_paths(self, client, app, tmp_path):
        """Rejects paths that don't start with 'equipment/' to prevent access to other uploads."""
        # Create a repair photo that should NOT be publicly accessible
        repair_dir = tmp_path / 'repair' / '1' / 'photos'
        repair_dir.mkdir(parents=True)
        (repair_dir / 'secret.jpg').write_bytes(b'secret-photo')

        app.config['UPLOAD_PATH'] = str(tmp_path)
        response = client.get('/public/uploads/repair/1/photos/secret.jpg')
        assert response.status_code == 404

    def test_serves_equipment_photo(self, client, app, make_area, make_equipment, tmp_path):
        """Serves a photo file from the equipment uploads directory."""
        area = make_area(name='Shop')
        equip = make_equipment(name='Drill', area=area)

        photo_dir = tmp_path / 'equipment' / str(equip.id) / 'photos'
        photo_dir.mkdir(parents=True)
        (photo_dir / 'front.jpg').write_bytes(b'JPEG')

        app.config['UPLOAD_PATH'] = str(tmp_path)
        response = client.get(f'/public/uploads/equipment/{equip.id}/photos/front.jpg')
        assert response.status_code == 200
        assert response.data == b'JPEG'

    def test_returns_404_for_missing_file(self, client, app, tmp_path):
        """Returns 404 when requested file does not exist."""
        app.config['UPLOAD_PATH'] = str(tmp_path)
        response = client.get('/public/uploads/equipment/1/docs/nonexistent.pdf')
        assert response.status_code == 404


class TestProblemReportFormDisplay:
    """Tests for problem report form display on equipment page (AC: #3, #4)."""

    def test_equipment_page_shows_report_form(self, client, make_area, make_equipment):
        """Equipment page shows problem report form without authentication (AC #3)."""
        area = make_area(name='Shop')
        equip = make_equipment(name='Lathe', area=area)

        response = client.get(f'/public/equipment/{equip.id}')
        html = response.data.decode()
        assert 'Report a Problem' in html

    def test_form_has_required_fields(self, client, make_area, make_equipment):
        """Form has required fields: name and description (AC #4)."""
        area = make_area(name='Shop')
        equip = make_equipment(name='Lathe', area=area)

        response = client.get(f'/public/equipment/{equip.id}')
        html = response.data.decode()
        assert 'Your Name' in html
        assert 'Description' in html

    def test_form_has_optional_fields(self, client, make_area, make_equipment):
        """Form has optional fields: severity, safety risk, consumable, email, photo (AC #4)."""
        area = make_area(name='Shop')
        equip = make_equipment(name='Lathe', area=area)

        response = client.get(f'/public/equipment/{equip.id}')
        html = response.data.decode()
        assert 'Severity' in html
        assert 'safety risk' in html.lower()
        assert 'consumable' in html.lower()
        assert 'Email' in html
        assert 'Photo' in html

    def test_form_has_submit_button(self, client, make_area, make_equipment):
        """Form has a submit button (AC #4)."""
        area = make_area(name='Shop')
        equip = make_equipment(name='Lathe', area=area)

        response = client.get(f'/public/equipment/{equip.id}')
        html = response.data.decode()
        assert 'Submit Report' in html
        assert 'report-submit-btn' in html

    def test_form_posts_to_report_route(self, client, make_area, make_equipment):
        """Form action posts to the report route (CSRF rendered but disabled in test config)."""
        area = make_area(name='Shop')
        equip = make_equipment(name='Lathe', area=area)

        response = client.get(f'/public/equipment/{equip.id}')
        html = response.data.decode()
        assert f'/public/equipment/{equip.id}/report' in html
        assert 'method="POST"' in html

    def test_form_has_multipart_enctype(self, client, make_area, make_equipment):
        """Form has enctype multipart/form-data for photo upload (AC #4)."""
        area = make_area(name='Shop')
        equip = make_equipment(name='Lathe', area=area)

        response = client.get(f'/public/equipment/{equip.id}')
        html = response.data.decode()
        assert 'enctype="multipart/form-data"' in html

    def test_form_fields_have_associated_labels(self, client, make_area, make_equipment):
        """Form fields have associated <label for=''> elements for accessibility."""
        area = make_area(name='Shop')
        equip = make_equipment(name='Lathe', area=area)

        response = client.get(f'/public/equipment/{equip.id}')
        html = response.data.decode()
        assert 'for="reporter_name"' in html
        assert 'for="description"' in html
        assert 'for="severity"' in html


class TestProblemReportSubmission:
    """Tests for problem report form submission (AC: #5, #6, #7, #9)."""

    def _valid_data(self):
        """Return valid form data for problem report."""
        return {
            'reporter_name': 'Sarah Member',
            'description': 'Motor making grinding noise',
            'severity': 'Down',
        }

    def test_valid_submission_creates_repair_record(
        self, client, db, make_area, make_equipment,
    ):
        """Valid submission creates a repair record with status New (AC #5)."""
        area = make_area(name='Shop')
        equip = make_equipment(name='Lathe', area=area)

        response = client.post(
            f'/public/equipment/{equip.id}/report',
            data=self._valid_data(),
        )
        assert response.status_code == 302

        record = db.session.query(RepairRecord).filter_by(equipment_id=equip.id).first()
        assert record is not None
        assert record.status == 'New'
        assert record.description == 'Motor making grinding noise'

    def test_submission_sets_reporter_name_and_email(
        self, client, db, make_area, make_equipment,
    ):
        """Submission sets reporter_name and reporter_email on record (AC #5)."""
        area = make_area(name='Shop')
        equip = make_equipment(name='Lathe', area=area)

        data = self._valid_data()
        data['reporter_email'] = 'sarah@example.com'
        client.post(f'/public/equipment/{equip.id}/report', data=data)

        record = db.session.query(RepairRecord).filter_by(equipment_id=equip.id).first()
        assert record.reporter_name == 'Sarah Member'
        assert record.reporter_email == 'sarah@example.com'

    def test_submission_with_severity(self, client, db, make_area, make_equipment):
        """Submission with severity sets severity on record (AC #5)."""
        area = make_area(name='Shop')
        equip = make_equipment(name='Lathe', area=area)

        data = self._valid_data()
        data['severity'] = 'Degraded'
        client.post(f'/public/equipment/{equip.id}/report', data=data)

        record = db.session.query(RepairRecord).filter_by(equipment_id=equip.id).first()
        assert record.severity == 'Degraded'

    def test_submission_without_severity_defaults_to_not_sure(
        self, client, db, make_area, make_equipment,
    ):
        """Submission without severity defaults to Not Sure (AC #5)."""
        area = make_area(name='Shop')
        equip = make_equipment(name='Lathe', area=area)

        data = {
            'reporter_name': 'Sarah Member',
            'description': 'Something seems off',
        }
        client.post(f'/public/equipment/{equip.id}/report', data=data)

        record = db.session.query(RepairRecord).filter_by(equipment_id=equip.id).first()
        assert record.severity == 'Not Sure'

    def test_submission_with_safety_risk(self, client, db, make_area, make_equipment):
        """Submission with safety risk flag sets has_safety_risk=True (AC #7)."""
        area = make_area(name='Shop')
        equip = make_equipment(name='Lathe', area=area)

        data = self._valid_data()
        data['has_safety_risk'] = 'y'
        client.post(f'/public/equipment/{equip.id}/report', data=data)

        record = db.session.query(RepairRecord).filter_by(equipment_id=equip.id).first()
        assert record.has_safety_risk is True

    def test_submission_with_consumable_flag(self, client, db, make_area, make_equipment):
        """Submission with consumable flag sets is_consumable=True (AC #5)."""
        area = make_area(name='Shop')
        equip = make_equipment(name='Lathe', area=area)

        data = self._valid_data()
        data['is_consumable'] = 'y'
        client.post(f'/public/equipment/{equip.id}/report', data=data)

        record = db.session.query(RepairRecord).filter_by(equipment_id=equip.id).first()
        assert record.is_consumable is True

    def test_missing_name_shows_validation_error(
        self, client, db, make_area, make_equipment,
    ):
        """Missing name shows validation error, no record created (AC #6)."""
        area = make_area(name='Shop')
        equip = make_equipment(name='Lathe', area=area)

        data = {'description': 'Something broke'}
        response = client.post(f'/public/equipment/{equip.id}/report', data=data)
        assert response.status_code == 200
        html = response.data.decode()
        assert 'Name is required' in html

        count = db.session.query(RepairRecord).filter_by(equipment_id=equip.id).count()
        assert count == 0

    def test_missing_description_shows_validation_error(
        self, client, db, make_area, make_equipment,
    ):
        """Missing description shows validation error, no record created (AC #6)."""
        area = make_area(name='Shop')
        equip = make_equipment(name='Lathe', area=area)

        data = {'reporter_name': 'Sarah Member'}
        response = client.post(f'/public/equipment/{equip.id}/report', data=data)
        assert response.status_code == 200
        html = response.data.decode()
        assert 'Description is required' in html

        count = db.session.query(RepairRecord).filter_by(equipment_id=equip.id).count()
        assert count == 0

    def test_submission_with_photo(
        self, client, db, make_area, make_equipment, tmp_path,
    ):
        """Submission with photo saves photo to uploads (AC #9)."""
        area = make_area(name='Shop')
        equip = make_equipment(name='Lathe', area=area)

        data = self._valid_data()
        data['photo'] = (BytesIO(b'fake image content'), 'problem.jpg')

        with patch('esb.services.upload_service.save_upload') as mock_save:
            mock_save.return_value = None
            response = client.post(
                f'/public/equipment/{equip.id}/report',
                data=data,
                content_type='multipart/form-data',
            )

        assert response.status_code == 302
        mock_save.assert_called_once()
        call_kwargs = mock_save.call_args
        assert call_kwargs[1]['parent_type'] == 'repair_photo'
        assert call_kwargs[1]['uploaded_by'] == 'Sarah Member'

    def test_submission_redirects_to_confirmation(
        self, client, make_area, make_equipment,
    ):
        """Valid submission redirects to confirmation page (AC #5)."""
        area = make_area(name='Shop')
        equip = make_equipment(name='Lathe', area=area)

        response = client.post(
            f'/public/equipment/{equip.id}/report',
            data=self._valid_data(),
        )
        assert response.status_code == 302
        assert '/report-confirmation' in response.headers['Location']

    def test_submission_for_archived_equipment_returns_404(
        self, client, make_area, make_equipment,
    ):
        """Submission for archived equipment returns 404."""
        area = make_area(name='Shop')
        equip = make_equipment(name='Old Tool', area=area, is_archived=True)

        response = client.post(
            f'/public/equipment/{equip.id}/report',
            data=self._valid_data(),
        )
        assert response.status_code == 404

    def test_submission_for_nonexistent_equipment_returns_404(self, client):
        """Submission for non-existent equipment returns 404."""
        response = client.post(
            '/public/equipment/99999/report',
            data={'reporter_name': 'Test', 'description': 'Test'},
        )
        assert response.status_code == 404

    def test_valid_submission_creates_timeline_entry(
        self, client, db, make_area, make_equipment,
    ):
        """Valid submission creates a timeline entry."""
        from esb.models.repair_timeline_entry import RepairTimelineEntry as RepairTimeline

        area = make_area(name='Shop')
        equip = make_equipment(name='Lathe', area=area)

        client.post(f'/public/equipment/{equip.id}/report', data=self._valid_data())

        record = db.session.query(RepairRecord).filter_by(equipment_id=equip.id).first()
        timeline = db.session.query(RepairTimeline).filter_by(repair_record_id=record.id).first()
        assert timeline is not None


class TestReportConfirmationView:
    """Tests for the problem report confirmation page (AC: #8)."""

    def test_renders_without_authentication(self, client, make_area, make_equipment):
        """Confirmation page is accessible without login (AC #8)."""
        area = make_area(name='Shop')
        equip = make_equipment(name='Lathe', area=area)

        response = client.get(f'/public/equipment/{equip.id}/report-confirmation?record_id=1')
        assert response.status_code == 200

    def test_shows_success_message(self, client, make_area, make_equipment):
        """Confirmation page shows success message (AC #8)."""
        area = make_area(name='Shop')
        equip = make_equipment(name='Lathe', area=area)

        response = client.get(f'/public/equipment/{equip.id}/report-confirmation?record_id=1')
        html = response.data.decode()
        assert 'Report Submitted' in html
        assert 'Thank you' in html

    def test_shows_slack_channel_links(self, client, make_area, make_equipment):
        """Confirmation page shows Slack channel links (AC #8)."""
        area = make_area(name='Shop', slack_channel='#shop-area')
        equip = make_equipment(name='Lathe', area=area)

        response = client.get(f'/public/equipment/{equip.id}/report-confirmation?record_id=1')
        html = response.data.decode()
        assert '#shop-area' in html
        assert '#oops' in html

    def test_has_report_another_link(self, client, make_area, make_equipment):
        """Confirmation page has Report Another Issue link (AC #8)."""
        area = make_area(name='Shop')
        equip = make_equipment(name='Lathe', area=area)

        response = client.get(f'/public/equipment/{equip.id}/report-confirmation?record_id=1')
        html = response.data.decode()
        assert 'Report Another Issue' in html
        assert '#report-form' in html

    def test_has_back_to_status_link(self, client, make_area, make_equipment):
        """Confirmation page has Back to equipment link (AC #8)."""
        area = make_area(name='Shop')
        equip = make_equipment(name='Lathe', area=area)

        response = client.get(f'/public/equipment/{equip.id}/report-confirmation?record_id=1')
        html = response.data.decode()
        assert f'/public/equipment/{equip.id}' in html
        assert 'Back to' in html

    def test_returns_404_for_nonexistent_equipment(self, client):
        """Confirmation page returns 404 for non-existent equipment (AC #8)."""
        response = client.get('/public/equipment/99999/report-confirmation?record_id=1')
        assert response.status_code == 404

    def test_returns_404_for_archived_equipment(self, client, make_area, make_equipment):
        """Confirmation page returns 404 for archived equipment."""
        area = make_area(name='Shop')
        equip = make_equipment(name='Old Tool', area=area, is_archived=True)

        response = client.get(f'/public/equipment/{equip.id}/report-confirmation?record_id=1')
        assert response.status_code == 404

    def test_hides_slack_channels_when_no_slack_channel(self, client, make_area, make_equipment):
        """Confirmation page hides Slack section when area has no slack_channel."""
        area = make_area(name='Shop', slack_channel=None)
        equip = make_equipment(name='Lathe', area=area)

        response = client.get(f'/public/equipment/{equip.id}/report-confirmation?record_id=1')
        html = response.data.decode()
        assert '#oops' not in html
        assert 'Stay Updated' not in html

    def test_shows_issue_summary(self, client, db, make_area, make_equipment):
        """Confirmation page shows submitted issue description and severity."""
        area = make_area(name='Shop')
        equip = make_equipment(name='Lathe', area=area)

        # Create a repair record via the form submission
        data = {
            'reporter_name': 'Sarah Member',
            'description': 'Motor making grinding noise',
            'severity': 'Down',
        }
        post_resp = client.post(f'/public/equipment/{equip.id}/report', data=data)
        assert post_resp.status_code == 302
        # Follow the redirect to confirmation
        response = client.get(post_resp.headers['Location'])
        html = response.data.decode()
        assert 'Issue Summary' in html
        assert 'Motor making grinding noise' in html
        assert 'Down' in html
