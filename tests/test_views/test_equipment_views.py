"""Tests for equipment views."""

import io
import json
import re
from datetime import date, datetime

from esb.extensions import db as _db
from esb.models.document import Document
from esb.models.equipment import Equipment
from esb.models.external_link import ExternalLink


class TestListEquipment:
    """Tests for GET /equipment/."""

    def test_staff_sees_equipment_list(self, staff_client, make_equipment):
        """Staff can access the equipment list page."""
        make_equipment('Table Saw', 'SawStop', 'PCS')
        resp = staff_client.get('/equipment/')
        assert resp.status_code == 200
        assert b'Table Saw' in resp.data
        assert b'Equipment Registry' in resp.data

    def test_technician_sees_equipment_list(self, tech_client, make_equipment):
        """Technicians can access the equipment list page."""
        make_equipment('Drill Press', 'JET', 'JDP-17')
        resp = tech_client.get('/equipment/')
        assert resp.status_code == 200
        assert b'Drill Press' in resp.data

    def test_unauthenticated_redirects_to_login(self, client):
        """Unauthenticated users are redirected to login."""
        resp = client.get('/equipment/')
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']

    def test_area_filter(self, staff_client, make_area, make_equipment):
        """Equipment list can be filtered by area."""
        area1 = make_area('Woodshop', '#wood')
        area2 = make_area('Metal Shop', '#metal')
        make_equipment('Table Saw', 'SawStop', 'PCS', area=area1)
        make_equipment('Welder', 'Lincoln', '210MP', area=area2)

        resp = staff_client.get(f'/equipment/?area_id={area1.id}')
        assert resp.status_code == 200
        assert b'Table Saw' in resp.data
        assert b'Welder' not in resp.data

    def test_empty_state(self, staff_client):
        """Empty state is shown when no equipment exists."""
        resp = staff_client.get('/equipment/')
        assert resp.status_code == 200
        assert b'No equipment' in resp.data

    def test_archived_equipment_excluded(self, staff_client, make_equipment):
        """Archived equipment is not shown in listings."""
        eq = make_equipment('Old Laser', 'Epilog', 'Zing')
        eq.is_archived = True
        _db.session.commit()

        resp = staff_client.get('/equipment/')
        assert b'Old Laser' not in resp.data

    def test_add_equipment_button_staff_only(self, tech_client, make_equipment):
        """Technicians do not see the Add Equipment button."""
        make_equipment('Item', 'Co', 'M')
        resp = tech_client.get('/equipment/')
        assert b'Add Equipment' not in resp.data

    def test_area_filter_dropdown_in_sort_order_then_name(
        self, staff_client, make_area,
    ):
        """The /equipment area filter dropdown options follow (sort_order, name)."""
        make_area(name='Area A', slack_channel='#a', sort_order=10)
        make_area(name='Area B', slack_channel='#b', sort_order=5)
        make_area(name='Area C', slack_channel='#c', sort_order=5)

        resp = staff_client.get('/equipment/')
        options = re.findall(r'<option[^>]*>([^<]+)</option>', resp.data.decode())
        area_options = [o for o in options if o in ('Area A', 'Area B', 'Area C')]
        assert area_options == ['Area B', 'Area C', 'Area A']


class TestCreateEquipment:
    """Tests for GET/POST /equipment/new."""

    def test_staff_sees_create_form(self, staff_client, make_area):
        """Staff can access the create equipment form."""
        make_area('Woodshop', '#wood')
        resp = staff_client.get('/equipment/new')
        assert resp.status_code == 200
        assert b'Add Equipment' in resp.data

    def test_technician_gets_403(self, tech_client):
        """Technicians cannot access the create form."""
        resp = tech_client.get('/equipment/new')
        assert resp.status_code == 403

    def test_creates_equipment_with_valid_data(self, staff_client, make_area):
        """Staff can create equipment with valid data."""
        area = make_area('Woodshop', '#wood')
        resp = staff_client.post('/equipment/new', data={
            'name': 'Table Saw',
            'manufacturer': 'SawStop',
            'model': 'PCS',
            'area_id': area.id,
        }, follow_redirects=False)
        assert resp.status_code == 302

        eq = _db.session.execute(
            _db.select(Equipment).filter_by(name='Table Saw')
        ).scalar_one_or_none()
        assert eq is not None
        assert eq.manufacturer == 'SawStop'

    def test_redirects_to_detail_after_create(self, staff_client, make_area):
        """After creating equipment, redirects to detail page."""
        area = make_area('Woodshop', '#wood')
        resp = staff_client.post('/equipment/new', data={
            'name': 'Drill Press',
            'manufacturer': 'JET',
            'model': 'JDP-17',
            'area_id': area.id,
        }, follow_redirects=False)
        assert resp.status_code == 302
        assert '/equipment/' in resp.headers['Location']

    def test_validation_error_missing_name(self, staff_client, make_area):
        """Missing name shows validation error."""
        area = make_area('Woodshop', '#wood')
        resp = staff_client.post('/equipment/new', data={
            'name': '',
            'manufacturer': 'SawStop',
            'model': 'PCS',
            'area_id': area.id,
        })
        assert resp.status_code == 200
        assert b'This field is required' in resp.data

    def test_validation_error_missing_area(self, staff_client, make_area):
        """Missing area shows validation error."""
        make_area('Woodshop', '#wood')
        resp = staff_client.post('/equipment/new', data={
            'name': 'Drill Press',
            'manufacturer': 'JET',
            'model': 'JDP-17',
            'area_id': 0,
        })
        assert resp.status_code == 200

    def test_creates_equipment_with_optional_fields(self, staff_client, make_area):
        """Staff can create equipment with optional fields populated."""
        area = make_area('Woodshop', '#wood')
        resp = staff_client.post('/equipment/new', data={
            'name': 'CNC Router',
            'manufacturer': 'ShopBot',
            'model': 'Desktop',
            'area_id': area.id,
            'serial_number': 'SN-99887',
            'acquisition_date': '2024-06-15',
            'acquisition_source': 'Direct purchase',
            'acquisition_cost': '4999.99',
            'warranty_expiration': '2026-06-15',
            'description': 'Desktop CNC for woodworking',
        }, follow_redirects=False)
        assert resp.status_code == 302

        eq = _db.session.execute(
            _db.select(Equipment).filter_by(name='CNC Router')
        ).scalar_one_or_none()
        assert eq is not None
        assert eq.serial_number == 'SN-99887'
        assert str(eq.acquisition_date) == '2024-06-15'
        assert eq.acquisition_source == 'Direct purchase'
        assert str(eq.acquisition_cost) == '4999.99'
        assert str(eq.warranty_expiration) == '2026-06-15'
        assert eq.description == 'Desktop CNC for woodworking'

    def test_unauthenticated_redirects(self, client):
        """Unauthenticated users are redirected to login."""
        resp = client.get('/equipment/new')
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']

    def test_area_dropdown_in_sort_order_then_name(self, staff_client, make_area):
        """The /equipment/new area dropdown options follow (sort_order, name)."""
        make_area(name='Area A', slack_channel='#a', sort_order=10)
        make_area(name='Area B', slack_channel='#b', sort_order=5)
        make_area(name='Area C', slack_channel='#c', sort_order=5)

        resp = staff_client.get('/equipment/new')
        options = re.findall(r'<option[^>]*>([^<]+)</option>', resp.data.decode())
        area_options = [
            o for o in options if o not in ('-- Select Area --',)
            and o.startswith('Area ')
        ]
        assert area_options == ['Area B', 'Area C', 'Area A']


class TestEquipmentDetail:
    """Tests for GET /equipment/<id>."""

    def test_staff_sees_detail(self, staff_client, make_equipment):
        """Staff can access equipment detail page."""
        eq = make_equipment('Table Saw', 'SawStop', 'PCS')
        resp = staff_client.get(f'/equipment/{eq.id}')
        assert resp.status_code == 200
        assert b'Table Saw' in resp.data
        assert b'SawStop' in resp.data
        assert b'PCS' in resp.data

    def test_technician_sees_detail(self, tech_client, make_equipment):
        """Technicians can access equipment detail page."""
        eq = make_equipment('Drill Press', 'JET', 'JDP-17')
        resp = tech_client.get(f'/equipment/{eq.id}')
        assert resp.status_code == 200
        assert b'Drill Press' in resp.data

    def test_not_found_returns_404(self, staff_client):
        """Non-existent equipment returns 404."""
        resp = staff_client.get('/equipment/99999')
        assert resp.status_code == 404

    def test_unauthenticated_redirects(self, client):
        """Unauthenticated users are redirected to login."""
        resp = client.get('/equipment/1')
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']

    def test_edit_button_staff_only(self, tech_client, make_equipment):
        """Technicians do not see the Edit button."""
        eq = make_equipment('Item', 'Co', 'M')
        resp = tech_client.get(f'/equipment/{eq.id}')
        assert b'Edit' not in resp.data


class TestEquipmentDetailRepairHistory:
    """Tests for the Repair History section on GET /equipment/<id>."""

    def test_repair_history_section_rendered(self, staff_client, make_equipment):
        """The Repair History card is always rendered on the detail page."""
        eq = make_equipment('Table Saw', 'SawStop', 'PCS')
        resp = staff_client.get(f'/equipment/{eq.id}')
        assert resp.status_code == 200
        assert b'Repair History' in resp.data

    def test_empty_state_when_no_records(self, staff_client, make_equipment):
        """Empty state message is shown when the equipment has no repair records."""
        eq = make_equipment('Table Saw', 'SawStop', 'PCS')
        resp = staff_client.get(f'/equipment/{eq.id}')
        assert resp.status_code == 200
        assert b'No repair records yet.' in resp.data

    def test_open_record_appears_in_history(
        self, staff_client, make_equipment, make_repair_record,
    ):
        """Open repair records are listed in the history table."""
        eq = make_equipment('Table Saw', 'SawStop', 'PCS')
        rec = make_repair_record(
            equipment=eq, status='New', severity='Down',
            description='Motor making grinding noise',
        )
        resp = staff_client.get(f'/equipment/{eq.id}')
        assert resp.status_code == 200
        assert b'Motor making grinding noise' in resp.data
        assert b'repair-history-table' in resp.data
        # Row is clickable and data-href points at the repair detail page
        body = resp.data.decode()
        match = re.search(
            r'<tr[^>]*class="repair-history-row[^"]*"[^>]*data-href="([^"]+)"',
            body,
        )
        assert match is not None
        assert match.group(1) == f'/repairs/{rec.id}'

    def test_resolved_record_still_visible_in_history(
        self, staff_client, make_equipment, make_repair_record,
    ):
        """Resolved repair records remain visible (this is the Issue #23 fix)."""
        eq = make_equipment('Drill Press', 'JET', 'JDP-17')
        rec = make_repair_record(
            equipment=eq, status='Resolved', severity='Degraded',
            description='Belt replaced; tested OK.',
        )
        resp = staff_client.get(f'/equipment/{eq.id}')
        assert resp.status_code == 200
        assert b'Belt replaced; tested OK.' in resp.data
        assert f'/repairs/{rec.id}'.encode() in resp.data
        assert b'Resolved' in resp.data

    def test_closed_no_issue_and_duplicate_visible(
        self, staff_client, make_equipment, make_repair_record,
    ):
        """Other closed statuses (No Issue Found, Duplicate) are also shown."""
        eq = make_equipment('Laser', 'Epilog', 'Helix')
        make_repair_record(
            equipment=eq, status='Closed - No Issue Found',
            description='Could not reproduce',
        )
        make_repair_record(
            equipment=eq, status='Closed - Duplicate',
            description='Same as #42',
        )
        resp = staff_client.get(f'/equipment/{eq.id}')
        assert resp.status_code == 200
        assert b'Could not reproduce' in resp.data
        assert b'Same as #42' in resp.data
        assert b'Closed - No Issue Found' in resp.data
        assert b'Closed - Duplicate' in resp.data

    def test_history_ordered_newest_first(
        self, staff_client, make_equipment, make_repair_record,
    ):
        """Repair history is ordered most recent first."""
        eq = make_equipment('CNC', 'ShopBot', 'Desktop')
        older = make_repair_record(
            equipment=eq, status='Resolved', description='First issue',
        )
        older.created_at = datetime(2024, 1, 1, 12, 0, 0)
        newer = make_repair_record(
            equipment=eq, status='New', description='Second issue',
        )
        newer.created_at = datetime(2024, 6, 1, 12, 0, 0)
        _db.session.commit()

        resp = staff_client.get(f'/equipment/{eq.id}')
        body = resp.data.decode()
        assert body.index('Second issue') < body.index('First issue')

    def test_history_filters_to_this_equipment(
        self, staff_client, make_area, make_equipment, make_repair_record,
    ):
        """Repair records for other equipment do not appear in this page's history."""
        area1 = make_area('Woodshop', '#wood')
        area2 = make_area('Metal Shop', '#metal')
        eq1 = make_equipment('Table Saw', 'SawStop', 'PCS', area=area1)
        eq2 = make_equipment('Drill Press', 'JET', 'JDP-17', area=area2)
        make_repair_record(equipment=eq1, status='New', description='Saw blade issue')
        make_repair_record(equipment=eq2, status='New', description='Drill chuck issue')

        resp = staff_client.get(f'/equipment/{eq1.id}')
        assert b'Saw blade issue' in resp.data
        assert b'Drill chuck issue' not in resp.data

    def test_technician_sees_repair_history(
        self, tech_client, make_equipment, make_repair_record,
    ):
        """Technicians can see repair history on the equipment page."""
        eq = make_equipment('Table Saw', 'SawStop', 'PCS')
        make_repair_record(
            equipment=eq, status='Resolved', description='Historical repair',
        )
        resp = tech_client.get(f'/equipment/{eq.id}')
        assert resp.status_code == 200
        assert b'Historical repair' in resp.data

    def test_archived_equipment_still_shows_history(
        self, staff_client, make_equipment, make_repair_record,
    ):
        """Archiving equipment does not hide its repair history."""
        eq = make_equipment('Retired Mill', 'Old Co', 'V1')
        make_repair_record(
            equipment=eq, status='Resolved',
            description='Spindle replaced before archive',
        )
        eq.is_archived = True
        _db.session.commit()

        resp = staff_client.get(f'/equipment/{eq.id}')
        assert resp.status_code == 200
        assert b'Spindle replaced before archive' in resp.data
        assert b'Repair History' in resp.data

    def test_unauthenticated_cannot_see_history(
        self, client, make_equipment, make_repair_record,
    ):
        """Unauthenticated users are redirected to login (history not exposed)."""
        eq = make_equipment('Table Saw', 'SawStop', 'PCS')
        make_repair_record(
            equipment=eq, status='New', description='Confidential repair note',
        )
        resp = client.get(f'/equipment/{eq.id}')
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']

    def test_repair_history_shows_eta_in_table(
        self, staff_client, make_equipment, make_repair_record,
    ):
        # Region-scoped: equipment.acquisition_date and warranty_expiration on
        # the same page also use format_date, so we anchor to the table id.
        eq = make_equipment(
            'Table Saw', 'SawStop', 'PCS',
            acquisition_date=None, warranty_expiration=None,
        )
        make_repair_record(
            equipment=eq, status='New', severity='Down',
            description='broken', eta=date(2026, 6, 15),
        )
        resp = staff_client.get(f'/equipment/{eq.id}')
        assert re.search(
            rb'<table[^>]*id="repair-history-table"[\s\S]*?Jun 15, 2026[\s\S]*?</table>',
            resp.data,
        )

    def test_repair_history_eta_blank_when_unset(
        self, staff_client, make_equipment, make_repair_record, tech_user,
    ):
        eq = make_equipment(
            'Table Saw', 'SawStop', 'PCS',
            acquisition_date=None, warranty_expiration=None,
        )
        # Assign so the only blank <td> in the row is the ETA cell -- otherwise
        # an empty Assignee cell would also satisfy a naive `<td></td>` check.
        make_repair_record(
            equipment=eq, status='New', severity='Down', description='broken',
            assignee_id=tech_user.id,
        )
        resp = staff_client.get(f'/equipment/{eq.id}')
        table_match = re.search(
            rb'<table[^>]*id="repair-history-table">([\s\S]*?)</table>',
            resp.data,
        )
        assert table_match
        # ETA cell renders empty (format_date(None) == '') and is the only
        # blank <td> in this row.
        assert table_match.group(1).count(b'<td></td>') == 1


class TestEditEquipment:
    """Tests for GET/POST /equipment/<id>/edit."""

    def test_staff_sees_edit_form(self, staff_client, make_area, make_equipment):
        """Staff can access the edit form."""
        area = make_area('Woodshop', '#wood')
        eq = make_equipment('Table Saw', 'SawStop', 'PCS', area=area)
        resp = staff_client.get(f'/equipment/{eq.id}/edit')
        assert resp.status_code == 200
        assert b'Edit Equipment' in resp.data

    def test_area_dropdown_in_sort_order_then_name(
        self, staff_client, make_area, make_equipment,
    ):
        """The /equipment/<id>/edit area dropdown follows (sort_order, name)."""
        area_a = make_area(name='Area A', slack_channel='#a', sort_order=10)
        make_area(name='Area B', slack_channel='#b', sort_order=5)
        make_area(name='Area C', slack_channel='#c', sort_order=5)
        eq = make_equipment('Table Saw', 'SawStop', 'PCS', area=area_a)

        resp = staff_client.get(f'/equipment/{eq.id}/edit')
        options = re.findall(r'<option[^>]*>([^<]+)</option>', resp.data.decode())
        area_options = [
            o for o in options if o not in ('-- Select Area --',)
            and o.startswith('Area ')
        ]
        assert area_options == ['Area B', 'Area C', 'Area A']

    def test_technician_gets_403(self, tech_client, make_equipment):
        """Technicians cannot access the edit form."""
        eq = make_equipment('Table Saw', 'SawStop', 'PCS')
        resp = tech_client.get(f'/equipment/{eq.id}/edit')
        assert resp.status_code == 403

    def test_updates_equipment(self, staff_client, make_area, make_equipment):
        """Staff can update equipment."""
        area = make_area('Woodshop', '#wood')
        eq = make_equipment('Old Name', 'OldCo', 'OldModel', area=area)
        resp = staff_client.post(f'/equipment/{eq.id}/edit', data={
            'name': 'New Name',
            'manufacturer': 'NewCo',
            'model': 'NewModel',
            'area_id': area.id,
        }, follow_redirects=False)
        assert resp.status_code == 302

        updated = _db.session.get(Equipment, eq.id)
        assert updated.name == 'New Name'
        assert updated.manufacturer == 'NewCo'

    def test_redirects_to_detail_after_edit(self, staff_client, make_area, make_equipment):
        """After editing equipment, redirects to detail page."""
        area = make_area('Woodshop', '#wood')
        eq = make_equipment('Item', 'Co', 'M', area=area)
        resp = staff_client.post(f'/equipment/{eq.id}/edit', data={
            'name': 'Updated',
            'manufacturer': 'Co',
            'model': 'M',
            'area_id': area.id,
        }, follow_redirects=False)
        assert resp.status_code == 302
        assert f'/equipment/{eq.id}' in resp.headers['Location']

    def test_validation_error_on_edit(self, staff_client, make_area, make_equipment):
        """Validation errors shown on edit form."""
        area = make_area('Woodshop', '#wood')
        eq = make_equipment('Item', 'Co', 'M', area=area)
        resp = staff_client.post(f'/equipment/{eq.id}/edit', data={
            'name': '',
            'manufacturer': 'Co',
            'model': 'M',
            'area_id': area.id,
        })
        assert resp.status_code == 200
        assert b'This field is required' in resp.data

    def test_not_found_returns_404(self, staff_client):
        """Non-existent equipment returns 404."""
        resp = staff_client.get('/equipment/99999/edit')
        assert resp.status_code == 404

    def test_unauthenticated_redirects(self, client):
        """Unauthenticated users are redirected to login."""
        resp = client.get('/equipment/1/edit')
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']


class TestArchiveEquipment:
    """Tests for POST /equipment/<id>/archive."""

    def test_staff_can_archive(self, staff_client, make_equipment):
        """Staff can archive equipment."""
        eq = make_equipment('Laser', 'Epilog', 'Zing')
        resp = staff_client.post(f'/equipment/{eq.id}/archive')
        assert resp.status_code == 302

        updated = _db.session.get(Equipment, eq.id)
        assert updated.is_archived is True

    def test_technician_gets_403(self, tech_client, make_equipment):
        """Technicians cannot archive equipment."""
        eq = make_equipment('Laser', 'Epilog', 'Zing')
        resp = tech_client.post(f'/equipment/{eq.id}/archive')
        assert resp.status_code == 403

    def test_unauthenticated_redirects_to_login(self, client, make_equipment, app):
        """Unauthenticated users are redirected to login."""
        with app.app_context():
            eq = make_equipment('Laser', 'Epilog', 'Zing')
            resp = client.post(f'/equipment/{eq.id}/archive')
            assert resp.status_code == 302
            assert '/auth/login' in resp.headers['Location']

    def test_archived_detail_shows_warning_banner(self, staff_client, make_equipment):
        """Archived equipment detail page shows warning banner."""
        eq = make_equipment('Laser', 'Epilog', 'Zing')
        eq.is_archived = True
        _db.session.commit()

        resp = staff_client.get(f'/equipment/{eq.id}')
        assert resp.status_code == 200
        assert b'archived' in resp.data
        assert b'alert-warning' in resp.data

    def test_archived_hides_edit_archive_buttons(self, staff_client, make_equipment):
        """Archived equipment hides Edit and Archive buttons."""
        eq = make_equipment('Laser', 'Epilog', 'Zing')
        eq.is_archived = True
        _db.session.commit()

        resp = staff_client.get(f'/equipment/{eq.id}')
        assert b'btn btn-outline-secondary' not in resp.data  # Edit button
        assert b'btn btn-danger' not in resp.data  # Archive button

    def test_archived_hides_upload_add_controls(self, staff_client, make_equipment):
        """Archived equipment hides upload/add/delete controls."""
        eq = make_equipment('Laser', 'Epilog', 'Zing')
        eq.is_archived = True
        _db.session.commit()

        resp = staff_client.get(f'/equipment/{eq.id}')
        assert b'Upload Document' not in resp.data
        assert b'Upload Photo' not in resp.data
        assert b'Add Link' not in resp.data

    def test_edit_route_blocked_for_archived(self, staff_client, make_equipment):
        """Edit route redirects with warning for archived equipment."""
        eq = make_equipment('Laser', 'Epilog', 'Zing')
        eq.is_archived = True
        _db.session.commit()

        resp = staff_client.get(f'/equipment/{eq.id}/edit', follow_redirects=True)
        assert resp.status_code == 200
        assert b'Cannot edit archived equipment' in resp.data

    def test_upload_blocked_for_archived(self, staff_client, make_equipment):
        """Upload routes blocked for archived equipment."""
        eq = make_equipment('Laser', 'Epilog', 'Zing')
        eq.is_archived = True
        _db.session.commit()

        resp = staff_client.post(
            f'/equipment/{eq.id}/documents',
            data={'file': (io.BytesIO(b'content'), 'test.pdf'), 'category': 'other'},
            content_type='multipart/form-data',
            follow_redirects=True,
        )
        assert b'Cannot modify archived equipment' in resp.data

    def test_add_link_blocked_for_archived(self, staff_client, make_equipment):
        """Add link route blocked for archived equipment."""
        eq = make_equipment('Laser', 'Epilog', 'Zing')
        eq.is_archived = True
        _db.session.commit()

        resp = staff_client.post(
            f'/equipment/{eq.id}/links',
            data={'title': 'Test', 'url': 'https://example.com'},
            follow_redirects=True,
        )
        assert b'Cannot modify archived equipment' in resp.data

    def test_archived_excluded_from_list(self, staff_client, make_equipment, make_area):
        """Archived equipment is excluded from list view."""
        area = make_area('Shop', '#shop')
        eq = make_equipment('Old Laser', 'Epilog', 'Zing', area=area)
        eq.is_archived = True
        _db.session.commit()
        make_equipment('Active CNC', 'ShopBot', 'Desktop', area=area)

        resp = staff_client.get('/equipment/')
        assert b'Old Laser' not in resp.data
        assert b'Active CNC' in resp.data

    def test_archive_success_flash(self, staff_client, make_equipment):
        """Successful archive shows success flash."""
        eq = make_equipment('Laser', 'Epilog', 'Zing')
        resp = staff_client.post(f'/equipment/{eq.id}/archive', follow_redirects=True)
        assert b'Equipment archived successfully' in resp.data

    def test_photo_upload_blocked_for_archived(self, staff_client, make_equipment):
        """Photo upload route blocked for archived equipment."""
        eq = make_equipment('Laser', 'Epilog', 'Zing')
        eq.is_archived = True
        _db.session.commit()

        resp = staff_client.post(
            f'/equipment/{eq.id}/photos',
            data={'file': (io.BytesIO(b'content'), 'photo.jpg')},
            content_type='multipart/form-data',
            follow_redirects=True,
        )
        assert b'Cannot modify archived equipment' in resp.data

    def test_delete_document_blocked_for_archived(self, staff_client, make_equipment, db):
        """Document delete blocked for archived equipment."""
        eq = make_equipment('Laser', 'Epilog', 'Zing')
        doc = Document(
            original_filename='test.pdf', stored_filename='x.pdf',
            content_type='application/pdf', size_bytes=7,
            parent_type='equipment_doc', parent_id=eq.id, uploaded_by='staffuser',
        )
        db.session.add(doc)
        db.session.commit()
        eq.is_archived = True
        db.session.commit()

        resp = staff_client.post(
            f'/equipment/{eq.id}/documents/{doc.id}/delete',
            follow_redirects=True,
        )
        assert b'Cannot modify archived equipment' in resp.data

    def test_delete_photo_blocked_for_archived(self, staff_client, make_equipment, db):
        """Photo delete blocked for archived equipment."""
        eq = make_equipment('Laser', 'Epilog', 'Zing')
        doc = Document(
            original_filename='photo.jpg', stored_filename='x.jpg',
            content_type='image/jpeg', size_bytes=5,
            parent_type='equipment_photo', parent_id=eq.id, uploaded_by='staffuser',
        )
        db.session.add(doc)
        db.session.commit()
        eq.is_archived = True
        db.session.commit()

        resp = staff_client.post(
            f'/equipment/{eq.id}/photos/{doc.id}/delete',
            follow_redirects=True,
        )
        assert b'Cannot modify archived equipment' in resp.data

    def test_delete_link_blocked_for_archived(self, staff_client, make_equipment, db):
        """Link delete blocked for archived equipment."""
        eq = make_equipment('Laser', 'Epilog', 'Zing')
        link = ExternalLink(
            equipment_id=eq.id, title='Test',
            url='https://example.com', created_by='staffuser',
        )
        db.session.add(link)
        db.session.commit()
        eq.is_archived = True
        db.session.commit()

        resp = staff_client.post(
            f'/equipment/{eq.id}/links/{link.id}/delete',
            follow_redirects=True,
        )
        assert b'Cannot modify archived equipment' in resp.data

    def test_archive_mutation_logging(self, staff_client, make_equipment, capture):
        """Archive logs equipment.archived mutation."""
        eq = make_equipment('Laser', 'Epilog', 'Zing')
        capture.records.clear()
        staff_client.post(f'/equipment/{eq.id}/archive')
        entries = [
            json.loads(r.message) for r in capture.records
            if 'equipment.archived' in r.message
        ]
        assert len(entries) == 1
        assert entries[0]['data']['name'] == 'Laser'


class TestTechnicianPermissions:
    """Tests for technician doc edit permissions."""

    def test_tech_can_upload_doc_when_enabled(self, tech_client, make_equipment, app, tmp_path):
        """Technician can upload document when permission enabled."""
        from esb.services import config_service
        config_service.set_config('tech_doc_edit_enabled', 'true', 'test')

        app.config['UPLOAD_PATH'] = str(tmp_path)
        eq = make_equipment()
        resp = tech_client.post(
            f'/equipment/{eq.id}/documents',
            data={
                'file': (io.BytesIO(b'fake pdf'), 'manual.pdf'),
                'category': 'other',
            },
            content_type='multipart/form-data',
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert b'Document uploaded successfully' in resp.data

    def test_tech_can_upload_photo_when_enabled(self, tech_client, make_equipment, app, tmp_path):
        """Technician can upload photo when permission enabled."""
        from esb.services import config_service
        config_service.set_config('tech_doc_edit_enabled', 'true', 'test')

        app.config['UPLOAD_PATH'] = str(tmp_path)
        eq = make_equipment()
        resp = tech_client.post(
            f'/equipment/{eq.id}/photos',
            data={'file': (io.BytesIO(b'fake image'), 'photo.jpg')},
            content_type='multipart/form-data',
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert b'Photo uploaded successfully' in resp.data

    def test_tech_can_add_link_when_enabled(self, tech_client, make_equipment):
        """Technician can add link when permission enabled."""
        from esb.services import config_service
        config_service.set_config('tech_doc_edit_enabled', 'true', 'test')

        eq = make_equipment()
        resp = tech_client.post(
            f'/equipment/{eq.id}/links',
            data={'title': 'Manual', 'url': 'https://example.com'},
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert b'Link added successfully' in resp.data

    def test_tech_gets_403_upload_when_disabled(self, tech_client, make_equipment):
        """Technician gets 403 on upload when permission disabled (default)."""
        eq = make_equipment()
        resp = tech_client.post(
            f'/equipment/{eq.id}/documents',
            data={
                'file': (io.BytesIO(b'content'), 'test.pdf'),
                'category': 'other',
            },
            content_type='multipart/form-data',
        )
        assert resp.status_code == 403

    def test_tech_can_delete_doc_when_enabled(self, tech_client, make_equipment, db, tmp_path, app):
        """Technician can delete document when permission enabled."""
        from esb.services import config_service
        config_service.set_config('tech_doc_edit_enabled', 'true', 'test')

        app.config['UPLOAD_PATH'] = str(tmp_path)
        eq = make_equipment()
        doc_dir = tmp_path / 'equipment' / str(eq.id) / 'docs'
        doc_dir.mkdir(parents=True)
        (doc_dir / 'stored.pdf').write_bytes(b'content')
        doc = Document(
            original_filename='test.pdf', stored_filename='stored.pdf',
            content_type='application/pdf', size_bytes=7,
            parent_type='equipment_doc', parent_id=eq.id, uploaded_by='techuser',
        )
        db.session.add(doc)
        db.session.commit()

        resp = tech_client.post(
            f'/equipment/{eq.id}/documents/{doc.id}/delete',
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert b'Document deleted' in resp.data

    def test_tech_gets_403_delete_when_disabled(self, tech_client, make_equipment, db):
        """Technician gets 403 on delete when permission disabled."""
        eq = make_equipment()
        doc = Document(
            original_filename='test.pdf', stored_filename='x.pdf',
            content_type='application/pdf', size_bytes=7,
            parent_type='equipment_doc', parent_id=eq.id, uploaded_by='staffuser',
        )
        db.session.add(doc)
        db.session.commit()

        resp = tech_client.post(f'/equipment/{eq.id}/documents/{doc.id}/delete')
        assert resp.status_code == 403

    def test_tech_sees_edit_controls_when_enabled(self, tech_client, make_equipment):
        """Technician sees upload/add buttons on detail when permission enabled."""
        from esb.services import config_service
        config_service.set_config('tech_doc_edit_enabled', 'true', 'test')

        eq = make_equipment()
        resp = tech_client.get(f'/equipment/{eq.id}')
        assert resp.status_code == 200
        assert b'Upload Document' in resp.data
        assert b'Upload Photo' in resp.data
        assert b'Add Link' in resp.data

    def test_tech_no_edit_controls_when_disabled(self, tech_client, make_equipment):
        """Technician sees no upload/add buttons on detail when permission disabled."""
        eq = make_equipment()
        resp = tech_client.get(f'/equipment/{eq.id}')
        assert resp.status_code == 200
        assert b'Upload Document' not in resp.data
        assert b'Upload Photo' not in resp.data
        assert b'Add Link' not in resp.data

    def test_tech_no_edit_controls_on_archived_when_enabled(self, tech_client, make_equipment):
        """Tech with edit perms sees no edit controls on archived equipment."""
        from esb.services import config_service
        config_service.set_config('tech_doc_edit_enabled', 'true', 'test')

        eq = make_equipment()
        eq.is_archived = True
        _db.session.commit()

        resp = tech_client.get(f'/equipment/{eq.id}')
        assert resp.status_code == 200
        assert b'Upload Document' not in resp.data
        assert b'Upload Photo' not in resp.data
        assert b'Add Link' not in resp.data


class TestRBACAndEdgeCases:
    """Tests for RBAC and edge cases (Task 6)."""

    def test_staff_required_on_create(self, tech_client):
        """@role_required('staff') on create route returns 403 for technicians."""
        resp = tech_client.post('/equipment/new', data={
            'name': 'X', 'manufacturer': 'Y', 'model': 'Z', 'area_id': 1,
        })
        assert resp.status_code == 403

    def test_staff_required_on_edit(self, tech_client, make_equipment):
        """@role_required('staff') on edit route returns 403 for technicians."""
        eq = make_equipment('Item', 'Co', 'M')
        resp = tech_client.post(f'/equipment/{eq.id}/edit', data={
            'name': 'X', 'manufacturer': 'Y', 'model': 'Z', 'area_id': 1,
        })
        assert resp.status_code == 403

    def test_login_required_on_list(self, client):
        """@login_required on list redirects unauthenticated."""
        resp = client.get('/equipment/')
        assert resp.status_code == 302

    def test_login_required_on_detail(self, client):
        """@login_required on detail redirects unauthenticated."""
        resp = client.get('/equipment/1')
        assert resp.status_code == 302

    def test_area_dropdown_excludes_archived(self, staff_client, make_area):
        """Area dropdown on create form excludes archived areas."""
        make_area('Active Shop', '#active')
        archived = make_area('Old Shop', '#old')
        archived.is_archived = True
        _db.session.commit()

        resp = staff_client.get('/equipment/new')
        assert b'Active Shop' in resp.data
        assert b'Old Shop' not in resp.data

    def test_archived_equipment_excluded_from_list(self, staff_client, make_equipment):
        """Archived equipment is excluded from the list view."""
        eq = make_equipment('Retired Laser', 'Epilog', 'Zing')
        eq.is_archived = True
        _db.session.commit()
        make_equipment('Active CNC', 'ShopBot', 'Desktop', area=eq.area)

        resp = staff_client.get('/equipment/')
        assert b'Retired Laser' not in resp.data
        assert b'Active CNC' in resp.data


class TestEquipmentMutationLogging:
    """Tests for mutation logging on equipment views."""

    def test_equipment_created_event_logged(self, staff_client, capture, make_area):
        """Equipment creation logs equipment.created mutation."""
        area = make_area('Woodshop', '#wood')
        staff_client.post('/equipment/new', data={
            'name': 'Laser Cutter',
            'manufacturer': 'Epilog',
            'model': 'Zing',
            'area_id': area.id,
        })
        created_entries = [
            json.loads(r.message) for r in capture.records
            if 'equipment.created' in r.message
        ]
        assert len(created_entries) == 1
        assert created_entries[0]['data']['name'] == 'Laser Cutter'

    def test_equipment_updated_event_logged(self, staff_client, capture, make_area, make_equipment):
        """Equipment edit logs equipment.updated mutation."""
        area = make_area('Woodshop', '#wood')
        eq = make_equipment('Old Name', 'Co', 'M', area=area)
        capture.records.clear()
        staff_client.post(f'/equipment/{eq.id}/edit', data={
            'name': 'New Name',
            'manufacturer': 'Co',
            'model': 'M',
            'area_id': area.id,
        })
        updated_entries = [
            json.loads(r.message) for r in capture.records
            if 'equipment.updated' in r.message
        ]
        assert len(updated_entries) == 1
        assert updated_entries[0]['data']['changes']['name'] == ['Old Name', 'New Name']


# --- Document Upload/Delete View Tests ---


class TestUploadDocument:
    """Tests for POST /equipment/<id>/documents."""

    def test_staff_uploads_document(self, staff_client, make_equipment, db, capture, tmp_path, app):
        """Staff can upload a document to an equipment item."""
        app.config['UPLOAD_PATH'] = str(tmp_path)
        eq = make_equipment()
        data = {
            'file': (io.BytesIO(b'fake pdf content'), 'manual.pdf'),
            'category': 'owners_manual',
        }
        resp = staff_client.post(
            f'/equipment/{eq.id}/documents',
            data=data,
            content_type='multipart/form-data',
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert b'Document uploaded successfully' in resp.data
        doc = db.session.execute(
            db.select(Document).filter_by(parent_type='equipment_doc', parent_id=eq.id)
        ).scalar_one_or_none()
        assert doc is not None
        assert doc.original_filename == 'manual.pdf'

    def test_technician_gets_403(self, tech_client, make_equipment):
        """Technicians cannot upload documents."""
        eq = make_equipment()
        data = {
            'file': (io.BytesIO(b'content'), 'test.pdf'),
            'category': 'other',
        }
        resp = tech_client.post(
            f'/equipment/{eq.id}/documents',
            data=data,
            content_type='multipart/form-data',
        )
        assert resp.status_code == 403

    def test_404_for_nonexistent_equipment(self, staff_client):
        """Upload to non-existent equipment returns 404."""
        data = {
            'file': (io.BytesIO(b'content'), 'test.pdf'),
            'category': 'other',
        }
        resp = staff_client.post(
            '/equipment/99999/documents',
            data=data,
            content_type='multipart/form-data',
        )
        assert resp.status_code == 404

    def test_validation_error_no_file(self, staff_client, make_equipment):
        """No file selected shows validation error."""
        eq = make_equipment()
        resp = staff_client.post(
            f'/equipment/{eq.id}/documents',
            data={'category': 'other'},
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert b'Please select a file' in resp.data


class TestUploadPhoto:
    """Tests for POST /equipment/<id>/photos."""

    def test_staff_uploads_photo(self, staff_client, make_equipment, db, tmp_path, app):
        """Staff can upload a photo."""
        app.config['UPLOAD_PATH'] = str(tmp_path)
        eq = make_equipment()
        data = {
            'file': (io.BytesIO(b'fake image'), 'photo.jpg'),
        }
        resp = staff_client.post(
            f'/equipment/{eq.id}/photos',
            data=data,
            content_type='multipart/form-data',
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert b'Photo uploaded successfully' in resp.data

    def test_technician_gets_403(self, tech_client, make_equipment):
        """Technicians cannot upload photos."""
        eq = make_equipment()
        data = {
            'file': (io.BytesIO(b'content'), 'photo.jpg'),
        }
        resp = tech_client.post(
            f'/equipment/{eq.id}/photos',
            data=data,
            content_type='multipart/form-data',
        )
        assert resp.status_code == 403


class TestDeleteDocument:
    """Tests for POST /equipment/<id>/documents/<doc_id>/delete."""

    def test_staff_deletes_document(self, staff_client, make_equipment, db, capture, tmp_path, app):
        """Staff can delete a document."""
        app.config['UPLOAD_PATH'] = str(tmp_path)
        eq = make_equipment()
        doc_dir = tmp_path / 'equipment' / str(eq.id) / 'docs'
        doc_dir.mkdir(parents=True)
        (doc_dir / 'stored.pdf').write_bytes(b'content')
        doc = Document(
            original_filename='manual.pdf', stored_filename='stored.pdf',
            content_type='application/pdf', size_bytes=7,
            parent_type='equipment_doc', parent_id=eq.id, uploaded_by='staffuser',
        )
        db.session.add(doc)
        db.session.commit()

        resp = staff_client.post(
            f'/equipment/{eq.id}/documents/{doc.id}/delete',
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert b'Document deleted' in resp.data
        assert db.session.get(Document, doc.id) is None

    def test_technician_gets_403(self, tech_client, make_equipment, db):
        """Technicians cannot delete documents."""
        eq = make_equipment()
        doc = Document(
            original_filename='test.pdf', stored_filename='x.pdf',
            content_type='application/pdf', size_bytes=7,
            parent_type='equipment_doc', parent_id=eq.id, uploaded_by='staffuser',
        )
        db.session.add(doc)
        db.session.commit()
        resp = tech_client.post(f'/equipment/{eq.id}/documents/{doc.id}/delete')
        assert resp.status_code == 403

    def test_cross_equipment_delete_rejected(self, staff_client, make_equipment, make_area, db):
        """Cannot delete a document belonging to another equipment."""
        area = make_area('Shop', '#shop')
        eq1 = make_equipment('Eq1', 'Co', 'M', area=area)
        eq2 = make_equipment('Eq2', 'Co', 'M', area=area)
        doc = Document(
            original_filename='test.pdf', stored_filename='x.pdf',
            content_type='application/pdf', size_bytes=7,
            parent_type='equipment_doc', parent_id=eq1.id, uploaded_by='staffuser',
        )
        db.session.add(doc)
        db.session.commit()
        resp = staff_client.post(
            f'/equipment/{eq2.id}/documents/{doc.id}/delete',
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert db.session.get(Document, doc.id) is not None


class TestDeletePhoto:
    """Tests for POST /equipment/<id>/photos/<photo_id>/delete."""

    def test_staff_deletes_photo(self, staff_client, make_equipment, db, tmp_path, app):
        """Staff can delete a photo."""
        app.config['UPLOAD_PATH'] = str(tmp_path)
        eq = make_equipment()
        doc_dir = tmp_path / 'equipment' / str(eq.id) / 'photos'
        doc_dir.mkdir(parents=True)
        (doc_dir / 'stored.jpg').write_bytes(b'image')
        doc = Document(
            original_filename='photo.jpg', stored_filename='stored.jpg',
            content_type='image/jpeg', size_bytes=5,
            parent_type='equipment_photo', parent_id=eq.id, uploaded_by='staffuser',
        )
        db.session.add(doc)
        db.session.commit()

        resp = staff_client.post(
            f'/equipment/{eq.id}/photos/{doc.id}/delete',
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert b'Photo deleted' in resp.data

    def test_technician_gets_403(self, tech_client, make_equipment, db):
        """Technicians cannot delete photos."""
        eq = make_equipment()
        doc = Document(
            original_filename='photo.jpg', stored_filename='x.jpg',
            content_type='image/jpeg', size_bytes=5,
            parent_type='equipment_photo', parent_id=eq.id, uploaded_by='staffuser',
        )
        db.session.add(doc)
        db.session.commit()
        resp = tech_client.post(f'/equipment/{eq.id}/photos/{doc.id}/delete')
        assert resp.status_code == 403

    def test_cross_equipment_delete_rejected(self, staff_client, make_equipment, make_area, db):
        """Cannot delete a photo belonging to another equipment."""
        area = make_area('Shop', '#shop')
        eq1 = make_equipment('Eq1', 'Co', 'M', area=area)
        eq2 = make_equipment('Eq2', 'Co', 'M', area=area)
        doc = Document(
            original_filename='photo.jpg', stored_filename='x.jpg',
            content_type='image/jpeg', size_bytes=5,
            parent_type='equipment_photo', parent_id=eq1.id, uploaded_by='staffuser',
        )
        db.session.add(doc)
        db.session.commit()
        resp = staff_client.post(
            f'/equipment/{eq2.id}/photos/{doc.id}/delete',
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert db.session.get(Document, doc.id) is not None


# --- External Link View Tests ---


class TestAddLink:
    """Tests for POST /equipment/<id>/links."""

    def test_staff_adds_link(self, staff_client, make_equipment, db):
        """Staff can add an external link."""
        eq = make_equipment()
        resp = staff_client.post(
            f'/equipment/{eq.id}/links',
            data={'title': 'Manual', 'url': 'https://example.com/manual'},
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert b'Link added successfully' in resp.data
        link = db.session.execute(
            db.select(ExternalLink).filter_by(equipment_id=eq.id)
        ).scalar_one_or_none()
        assert link is not None
        assert link.title == 'Manual'

    def test_technician_gets_403(self, tech_client, make_equipment):
        """Technicians cannot add links."""
        eq = make_equipment()
        resp = tech_client.post(
            f'/equipment/{eq.id}/links',
            data={'title': 'Test', 'url': 'https://example.com'},
        )
        assert resp.status_code == 403

    def test_404_for_nonexistent_equipment(self, staff_client):
        """Add link to non-existent equipment returns 404."""
        resp = staff_client.post(
            '/equipment/99999/links',
            data={'title': 'Test', 'url': 'https://example.com'},
        )
        assert resp.status_code == 404

    def test_validation_error_missing_title(self, staff_client, make_equipment):
        """Missing title shows validation error."""
        eq = make_equipment()
        resp = staff_client.post(
            f'/equipment/{eq.id}/links',
            data={'title': '', 'url': 'https://example.com'},
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert b'This field is required' in resp.data


class TestDeleteLink:
    """Tests for POST /equipment/<id>/links/<link_id>/delete."""

    def test_staff_deletes_link(self, staff_client, make_equipment, db, capture):
        """Staff can delete an external link."""
        eq = make_equipment()
        link = ExternalLink(
            equipment_id=eq.id, title='Old Link',
            url='https://example.com', created_by='staffuser',
        )
        db.session.add(link)
        db.session.commit()

        resp = staff_client.post(
            f'/equipment/{eq.id}/links/{link.id}/delete',
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert b'Link deleted' in resp.data
        assert db.session.get(ExternalLink, link.id) is None

    def test_technician_gets_403(self, tech_client, make_equipment, db):
        """Technicians cannot delete links."""
        eq = make_equipment()
        link = ExternalLink(
            equipment_id=eq.id, title='Test',
            url='https://example.com', created_by='staffuser',
        )
        db.session.add(link)
        db.session.commit()
        resp = tech_client.post(f'/equipment/{eq.id}/links/{link.id}/delete')
        assert resp.status_code == 403

    def test_cross_equipment_delete_rejected(self, staff_client, make_equipment, make_area, db):
        """Cannot delete a link belonging to another equipment."""
        area = make_area('Shop', '#shop')
        eq1 = make_equipment('Eq1', 'Co', 'M', area=area)
        eq2 = make_equipment('Eq2', 'Co', 'M', area=area)
        link = ExternalLink(
            equipment_id=eq1.id, title='Test',
            url='https://example.com', created_by='staffuser',
        )
        db.session.add(link)
        db.session.commit()
        resp = staff_client.post(
            f'/equipment/{eq2.id}/links/{link.id}/delete',
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert db.session.get(ExternalLink, link.id) is not None


# --- File Serving View Tests ---


class TestFileServing:
    """Tests for file serving routes."""

    def test_serve_document_requires_login(self, client):
        """Unauthenticated users are redirected on file serve."""
        resp = client.get('/equipment/1/files/docs/test.pdf')
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']

    def test_serve_photo_requires_login(self, client):
        """Unauthenticated users are redirected on photo serve."""
        resp = client.get('/equipment/1/files/photos/photo.jpg')
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']

    def test_serve_document_authenticated(self, staff_client, make_equipment, tmp_path, app):
        """Authenticated user can download a document file."""
        app.config['UPLOAD_PATH'] = str(tmp_path)
        eq = make_equipment()
        doc_dir = tmp_path / 'equipment' / str(eq.id) / 'docs'
        doc_dir.mkdir(parents=True)
        (doc_dir / 'test.pdf').write_bytes(b'PDF content')

        resp = staff_client.get(f'/equipment/{eq.id}/files/docs/test.pdf')
        assert resp.status_code == 200
        assert resp.data == b'PDF content'

    def test_serve_photo_authenticated(self, staff_client, make_equipment, tmp_path, app):
        """Authenticated user can download a photo file."""
        app.config['UPLOAD_PATH'] = str(tmp_path)
        eq = make_equipment()
        photo_dir = tmp_path / 'equipment' / str(eq.id) / 'photos'
        photo_dir.mkdir(parents=True)
        (photo_dir / 'photo.jpg').write_bytes(b'JPEG content')

        resp = staff_client.get(f'/equipment/{eq.id}/files/photos/photo.jpg')
        assert resp.status_code == 200
        assert resp.data == b'JPEG content'


# --- 413 Error Handler Test ---


class TestRequestTooLarge:
    """Tests for 413 Request Entity Too Large handler."""

    def test_413_shows_flash_message(self, staff_client, make_equipment, app):
        """413 error shows flash message about file size limit."""
        app.config['MAX_CONTENT_LENGTH'] = 10  # 10 bytes
        app.config['UPLOAD_MAX_SIZE_MB'] = 1
        eq = make_equipment()
        big_data = b'x' * 100
        data = {
            'file': (io.BytesIO(big_data), 'big.pdf'),
            'category': 'other',
        }
        resp = staff_client.post(
            f'/equipment/{eq.id}/documents',
            data=data,
            content_type='multipart/form-data',
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert b'too large' in resp.data


# --- Document/Photo/Link Mutation Logging View Tests ---


class TestDocumentMutationLogging:
    """Tests for mutation logging on document/link operations."""

    def test_document_upload_logs_mutation(self, staff_client, make_equipment, capture, tmp_path, app):
        """Document upload logs document.created mutation."""
        app.config['UPLOAD_PATH'] = str(tmp_path)
        eq = make_equipment()
        capture.records.clear()
        data = {
            'file': (io.BytesIO(b'content'), 'test.pdf'),
            'category': 'other',
        }
        staff_client.post(
            f'/equipment/{eq.id}/documents',
            data=data,
            content_type='multipart/form-data',
        )
        entries = [
            json.loads(r.message) for r in capture.records
            if 'document.created' in r.message
        ]
        assert len(entries) == 1
        assert entries[0]['event'] == 'document.created'
        assert entries[0]['user'] == 'staffuser'

    def test_document_delete_logs_mutation(self, staff_client, make_equipment, db, capture, tmp_path, app):
        """Document delete logs document.deleted mutation."""
        app.config['UPLOAD_PATH'] = str(tmp_path)
        eq = make_equipment()
        doc = Document(
            original_filename='test.pdf', stored_filename='x.pdf',
            content_type='application/pdf', size_bytes=7,
            parent_type='equipment_doc', parent_id=eq.id, uploaded_by='staffuser',
        )
        db.session.add(doc)
        db.session.commit()
        capture.records.clear()

        staff_client.post(f'/equipment/{eq.id}/documents/{doc.id}/delete')
        entries = [
            json.loads(r.message) for r in capture.records
            if 'document.deleted' in r.message
        ]
        assert len(entries) == 1

    def test_link_add_logs_mutation(self, staff_client, make_equipment, capture):
        """Link add logs equipment_link.created mutation."""
        eq = make_equipment()
        capture.records.clear()
        staff_client.post(
            f'/equipment/{eq.id}/links',
            data={'title': 'Support', 'url': 'https://support.example.com'},
        )
        entries = [
            json.loads(r.message) for r in capture.records
            if 'equipment_link.created' in r.message
        ]
        assert len(entries) == 1

    def test_link_delete_logs_mutation(self, staff_client, make_equipment, db, capture):
        """Link delete logs equipment_link.deleted mutation."""
        eq = make_equipment()
        link = ExternalLink(
            equipment_id=eq.id, title='Test',
            url='https://example.com', created_by='staffuser',
        )
        db.session.add(link)
        db.session.commit()
        capture.records.clear()

        staff_client.post(f'/equipment/{eq.id}/links/{link.id}/delete')
        entries = [
            json.loads(r.message) for r in capture.records
            if 'equipment_link.deleted' in r.message
        ]
        assert len(entries) == 1


class TestExportCsv:
    """Tests for GET /equipment/export.csv."""

    def test_unauthenticated_redirects_to_login(self, client):
        """Unauthenticated users are redirected to login."""
        resp = client.get('/equipment/export.csv')
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']

    def test_staff_can_download(self, staff_client, make_equipment):
        """Staff can download the CSV export."""
        make_equipment('Table Saw', 'SawStop', 'PCS')
        resp = staff_client.get('/equipment/export.csv')
        assert resp.status_code == 200
        assert resp.mimetype == 'text/csv'
        assert 'attachment' in resp.headers.get('Content-Disposition', '')
        assert 'equipment_inventory.csv' in resp.headers.get('Content-Disposition', '')

    def test_tech_can_download(self, tech_client, make_equipment):
        """Technicians can download the CSV export."""
        make_equipment('Drill Press', 'JET', 'JDP-17')
        resp = tech_client.get('/equipment/export.csv')
        assert resp.status_code == 200

    def test_csv_content_includes_equipment(self, staff_client, make_equipment):
        """CSV body contains the equipment name and identifying fields."""
        make_equipment('Table Saw', 'SawStop', 'PCS')
        resp = staff_client.get('/equipment/export.csv')
        body = resp.data.decode('utf-8')
        assert 'Table Saw' in body
        assert 'SawStop' in body
        assert 'PCS' in body

    def test_csv_has_header_row(self, staff_client):
        """First CSV line is the header row."""
        resp = staff_client.get('/equipment/export.csv')
        body = resp.data.decode('utf-8')
        first_line = body.splitlines()[0]
        assert 'name' in first_line
        assert 'manufacturer' in first_line
        assert 'model' in first_line
        assert 'serial_number' in first_line
        assert 'area' in first_line

    def test_area_filter_applies(self, staff_client, make_area, make_equipment):
        """Passing area_id restricts export to that area."""
        wood = make_area('Woodshop', '#wood')
        metal = make_area('Metal Shop', '#metal')
        make_equipment('Table Saw', 'SawStop', 'PCS', area=wood)
        make_equipment('Welder', 'Lincoln', '210MP', area=metal)

        resp = staff_client.get(f'/equipment/export.csv?area_id={wood.id}')
        body = resp.data.decode('utf-8')
        assert 'Table Saw' in body
        assert 'Welder' not in body

    def test_archived_excluded_by_default(self, staff_client, make_equipment, db):
        """Archived equipment is not in the default export."""
        eq = make_equipment('Old Saw', 'OldCo', 'Old')
        eq.is_archived = True
        db.session.commit()

        resp = staff_client.get('/equipment/export.csv')
        body = resp.data.decode('utf-8')
        assert 'Old Saw' not in body

    def test_include_archived_parameter(self, staff_client, make_equipment, db):
        """include_archived=1 brings archived rows into the export."""
        eq = make_equipment('Old Saw', 'OldCo', 'Old')
        eq.is_archived = True
        db.session.commit()

        resp = staff_client.get('/equipment/export.csv?include_archived=1')
        body = resp.data.decode('utf-8')
        assert 'Old Saw' in body

    def test_include_archived_parsing_is_case_insensitive(
        self, staff_client, make_equipment, db,
    ):
        """include_archived accepts truthy values regardless of case."""
        eq = make_equipment('Old Saw', 'OldCo', 'Old')
        eq.is_archived = True
        db.session.commit()

        for value in ('TRUE', 'True', 'true', 'TrUe'):
            resp = staff_client.get(f'/equipment/export.csv?include_archived={value}')
            body = resp.data.decode('utf-8')
            assert 'Old Saw' in body, f'value={value!r} did not enable archived rows'

    def test_include_archived_false_excludes_archived(
        self, staff_client, make_equipment, db,
    ):
        """include_archived with a non-truthy value does not bring archived rows."""
        eq = make_equipment('Old Saw', 'OldCo', 'Old')
        eq.is_archived = True
        db.session.commit()

        resp = staff_client.get('/equipment/export.csv?include_archived=no')
        body = resp.data.decode('utf-8')
        assert 'Old Saw' not in body

    def test_list_page_has_export_button(self, staff_client):
        """Equipment list page exposes the Export CSV link."""
        resp = staff_client.get('/equipment/')
        assert b'Export CSV' in resp.data
        assert b'/equipment/export.csv' in resp.data

    def test_response_is_utf8_with_bom(self, staff_client, make_equipment):
        """Response body starts with a UTF-8 BOM and declares charset=utf-8 exactly once."""
        make_equipment('Équipe Saw', 'SawStop', 'PCS')
        resp = staff_client.get('/equipment/export.csv')
        content_type = resp.headers.get('Content-Type', '').lower()
        assert 'charset=utf-8' in content_type
        # Guard against a duplicated "charset=utf-8; charset=utf-8" header.
        assert content_type.count('charset=') == 1
        assert resp.data.startswith(b'\xef\xbb\xbf')
        body = resp.data.decode('utf-8-sig')
        assert 'Équipe Saw' in body

    def test_export_is_audit_logged(self, staff_client, make_equipment, capture):
        """Downloading the CSV emits an equipment.exported_csv mutation log."""
        make_equipment('Table Saw', 'SawStop', 'PCS')
        capture.records.clear()
        resp = staff_client.get('/equipment/export.csv?include_archived=1')
        assert resp.status_code == 200
        entries = [
            json.loads(r.message) for r in capture.records
            if 'equipment.exported_csv' in r.message
        ]
        assert len(entries) == 1
        entry = entries[0]
        assert entry['user'] == 'staffuser'
        assert entry['data']['include_archived'] is True


class TestEquipmentQR:
    """Tests for /equipment/<id>/qr and /equipment/<id>/qr/preview."""

    def test_get_qr_form_staff(self, staff_client, make_equipment, configured_base_url):
        eq = make_equipment('Table Saw', 'SawStop', 'PCS')
        resp = staff_client.get(f'/equipment/{eq.id}/qr')
        assert resp.status_code == 200
        assert b'name="size"' in resp.data
        assert b'name="include_name"' in resp.data
        assert b'name="include_url"' in resp.data
        assert b'id="qr-preview"' in resp.data

    def test_get_qr_form_tech(self, tech_client, make_equipment, configured_base_url):
        eq = make_equipment('Drill', 'JET', 'JDP')
        resp = tech_client.get(f'/equipment/{eq.id}/qr')
        assert resp.status_code == 200

    def test_get_qr_form_unauthenticated(self, client, make_equipment, configured_base_url):
        eq = make_equipment('X', 'Y', 'Z')
        resp = client.get(f'/equipment/{eq.id}/qr')
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']

    def test_get_qr_form_not_found(self, staff_client, configured_base_url):
        resp = staff_client.get('/equipment/99999/qr')
        assert resp.status_code == 404

    def test_get_qr_form_archived_returns_404(self, staff_client, make_equipment, configured_base_url):
        eq = make_equipment('Old', 'Co', 'M')
        eq.is_archived = True
        _db.session.commit()
        resp = staff_client.get(f'/equipment/{eq.id}/qr')
        assert resp.status_code == 404

    def test_get_qr_form_empty_base_url_redirects(self, staff_client, make_equipment, app):
        app.config['ESB_BASE_URL'] = ''
        eq = make_equipment('X', 'Y', 'Z')
        resp = staff_client.get(f'/equipment/{eq.id}/qr')
        assert resp.status_code == 302
        assert f'/equipment/{eq.id}' in resp.headers['Location']
        # Follow to see the flash.
        resp2 = staff_client.get(f'/equipment/{eq.id}')
        assert b'ESB_BASE_URL is not configured' in resp2.data

    def test_get_qr_form_invalid_scheme_redirects(self, staff_client, make_equipment, app):
        app.config['ESB_BASE_URL'] = 'javascript:alert(1)'
        eq = make_equipment('X', 'Y', 'Z')
        resp = staff_client.get(f'/equipment/{eq.id}/qr')
        assert resp.status_code == 302
        resp2 = staff_client.get(f'/equipment/{eq.id}')
        assert b'http(s) URL' in resp2.data

    def test_post_qr_download_returns_png_attachment(
        self, staff_client, make_equipment, configured_base_url,
    ):
        eq = make_equipment('Table Saw #1!', 'SawStop', 'PCS')
        resp = staff_client.post(
            f'/equipment/{eq.id}/qr',
            data={'size': 'sticker_2', 'wifi_info': 'none', 'submit': 'Download QR Code'},
        )
        assert resp.status_code == 200
        assert resp.content_type.startswith('image/png')
        cd = resp.headers.get('Content-Disposition', '')
        assert 'attachment' in cd
        # No device posted → defaults to laser_300, which is encoded in the filename.
        assert f'filename="qr-{eq.id}-Table-Saw-1-laser_300.png"' in cd or \
            f"filename=qr-{eq.id}-Table-Saw-1-laser_300.png" in cd

    def test_post_qr_download_unknown_size_rejected(
        self, staff_client, make_equipment, configured_base_url,
    ):
        eq = make_equipment('X', 'Y', 'Z')
        resp = staff_client.post(
            f'/equipment/{eq.id}/qr',
            data={'size': 'not_a_size', 'submit': 'Download QR Code'},
        )
        assert resp.status_code == 200
        # Form is re-rendered (WTForms SelectField validates against choices).
        assert b'name="size"' in resp.data

    def test_post_qr_download_url_too_long_flashes_and_rerenders(
        self, staff_client, make_equipment, configured_base_url, monkeypatch,
    ):
        eq = make_equipment('X', 'Y', 'Z')
        from esb.services import qr_service

        def raiser(*a, **kw):
            raise ValueError(
                'URL is too long for preset "1"×1" sticker" — '
                'choose a larger preset or shorten ESB_BASE_URL.'
            )

        monkeypatch.setattr(qr_service, 'render_qr_png', raiser)
        resp = staff_client.post(
            f'/equipment/{eq.id}/qr',
            data={'size': 'sticker_2', 'wifi_info': 'none', 'submit': 'Download QR Code'},
        )
        assert resp.status_code == 200
        assert b'choose a larger preset' in resp.data
        # Form re-rendered, not binary PNG.
        assert b'name="size"' in resp.data

    def test_get_qr_preview_url_too_long_400(
        self, staff_client, make_equipment, configured_base_url, monkeypatch,
    ):
        eq = make_equipment('X', 'Y', 'Z')
        from esb.services import qr_service

        def raiser(*a, **kw):
            raise ValueError('URL too long')

        monkeypatch.setattr(qr_service, 'render_qr_png', raiser)
        resp = staff_client.get(f'/equipment/{eq.id}/qr/preview?size=sticker_1')
        assert resp.status_code == 400

    def test_get_qr_preview_png_inline(self, staff_client, make_equipment, configured_base_url):
        eq = make_equipment('X', 'Y', 'Z')
        resp = staff_client.get(f'/equipment/{eq.id}/qr/preview?size=sticker_2')
        assert resp.status_code == 200
        assert resp.content_type.startswith('image/png')
        assert 'attachment' not in resp.headers.get('Content-Disposition', '')
        cache = resp.headers.get('Cache-Control', '')
        assert 'private' in cache
        assert 'max-age=300' in cache

    def test_get_qr_preview_invalid_size_400(
        self, staff_client, make_equipment, configured_base_url,
    ):
        eq = make_equipment('X', 'Y', 'Z')
        resp = staff_client.get(f'/equipment/{eq.id}/qr/preview?size=bogus')
        assert resp.status_code == 400

    def test_get_qr_preview_empty_base_url_404(self, staff_client, make_equipment, app):
        app.config['ESB_BASE_URL'] = ''
        eq = make_equipment('X', 'Y', 'Z')
        resp = staff_client.get(f'/equipment/{eq.id}/qr/preview?size=sticker_2')
        assert resp.status_code == 404

    def test_get_qr_preview_archived_404(self, staff_client, make_equipment, configured_base_url):
        eq = make_equipment('X', 'Y', 'Z')
        eq.is_archived = True
        _db.session.commit()
        resp = staff_client.get(f'/equipment/{eq.id}/qr/preview?size=sticker_2')
        assert resp.status_code == 404

    def test_detail_page_shows_generate_qr_button_when_configured(
        self, staff_client, make_equipment, configured_base_url,
    ):
        eq = make_equipment('X', 'Y', 'Z')
        resp = staff_client.get(f'/equipment/{eq.id}')
        assert resp.status_code == 200
        assert f'href="/equipment/{eq.id}/qr"'.encode() in resp.data
        assert b'Generate QR Code' in resp.data

    def test_detail_page_shows_disabled_generate_qr_button_when_unconfigured(
        self, staff_client, make_equipment, app,
    ):
        app.config['ESB_BASE_URL'] = ''
        eq = make_equipment('X', 'Y', 'Z')
        resp = staff_client.get(f'/equipment/{eq.id}')
        assert resp.status_code == 200
        assert b'disabled' in resp.data
        assert b'ESB_BASE_URL not configured' in resp.data

    def test_detail_page_hides_qr_button_when_archived(
        self, staff_client, make_equipment, configured_base_url,
    ):
        eq = make_equipment('X', 'Y', 'Z')
        eq.is_archived = True
        _db.session.commit()
        resp = staff_client.get(f'/equipment/{eq.id}')
        assert resp.status_code == 200
        assert f'href="/equipment/{eq.id}/qr"'.encode() not in resp.data
        # The disabled-button variant also should not render (button is inside not-archived block).
        assert b'ESB_BASE_URL not configured' not in resp.data

    # --- JS-preview contract (Task 16a) ---

    def test_qr_form_template_has_preview_data_binding(
        self, staff_client, make_equipment, configured_base_url,
    ):
        eq = make_equipment('X', 'Y', 'Z')
        resp = staff_client.get(f'/equipment/{eq.id}/qr')
        assert resp.status_code == 200
        assert b'id="qr-form"' in resp.data
        expected_base = f'data-preview-base="/equipment/{eq.id}/qr/preview"'.encode()
        assert expected_base in resp.data
        # qr-preview img points at the preview URL.
        assert b'id="qr-preview"' in resp.data
        assert f'/equipment/{eq.id}/qr/preview'.encode() in resp.data

    # --- Device / DPI dropdown tests ---

    def test_qr_form_shows_device_dropdown(self, staff_client, make_equipment, configured_base_url):
        eq = make_equipment('X', 'Y', 'Z')
        resp = staff_client.get(f'/equipment/{eq.id}/qr')
        assert resp.status_code == 200
        assert b'name="device"' in resp.data
        html = resp.data.decode()
        for label in (
            'Laser/Inkjet (300 dpi)', 'Laser/Inkjet (600 dpi)', 'Laser/Inkjet (1200 dpi)',
            'Thermal Label (203 dpi)', 'Brother P-Touch (180 dpi)',
        ):
            assert label in html

    def test_post_qr_download_honors_device_dpi(
        self, staff_client, make_equipment, configured_base_url,
    ):
        from PIL import Image
        eq = make_equipment('X', 'Y', 'Z')
        resp = staff_client.post(
            f'/equipment/{eq.id}/qr',
            data={'size': 'sticker_4', 'device': 'thermal_203', 'wifi_info': 'none',
                  'submit': 'Download QR Code'},
        )
        assert resp.status_code == 200
        assert resp.content_type.startswith('image/png')
        img = Image.open(io.BytesIO(resp.data))
        assert img.size == (812, 812)  # int(4*203+0.5)
        assert tuple(round(v) for v in img.info['dpi']) == (203, 203)
        # Device key is encoded in the filename so per-device labels don't collide.
        assert 'thermal_203.png' in resp.headers.get('Content-Disposition', '')

    def test_post_qr_download_unknown_device_rejected(
        self, staff_client, make_equipment, configured_base_url,
    ):
        eq = make_equipment('X', 'Y', 'Z')
        # Complete payload, only `device` invalid → re-render attributable to device validation.
        resp = staff_client.post(
            f'/equipment/{eq.id}/qr',
            data={'size': 'sticker_2', 'device': 'bogus', 'wifi_info': 'none',
                  'submit': 'Download QR Code'},
        )
        assert resp.status_code == 200
        assert b'name="device"' in resp.data
        assert not resp.content_type.startswith('image/png')
        # The clamp branch reset the bogus device to the default so the re-rendered
        # preview src points at a valid device (not the broken `device=bogus`).
        assert b'device=laser_300' in resp.data
        assert b'device=bogus' not in resp.data

    def test_qr_preview_includes_device_param(
        self, staff_client, make_equipment, configured_base_url,
    ):
        eq = make_equipment('X', 'Y', 'Z')
        resp = staff_client.get(f'/equipment/{eq.id}/qr')
        assert resp.status_code == 200
        assert b'device=' in resp.data

    def test_get_qr_preview_invalid_device_400(
        self, staff_client, make_equipment, configured_base_url,
    ):
        eq = make_equipment('X', 'Y', 'Z')
        resp = staff_client.get(f'/equipment/{eq.id}/qr/preview?size=sticker_2&device=bogus')
        assert resp.status_code == 400

    def test_get_qr_preview_default_device_when_missing(
        self, staff_client, make_equipment, configured_base_url,
    ):
        from PIL import Image
        eq = make_equipment('X', 'Y', 'Z')
        resp = staff_client.get(f'/equipment/{eq.id}/qr/preview?size=sticker_4')
        assert resp.status_code == 200
        img = Image.open(io.BytesIO(resp.data))
        assert img.size == (1200, 1200)  # defaults to 300 dpi
        assert tuple(round(v) for v in img.info['dpi']) == (300, 300)

    def test_post_qr_download_oversized_flashes_danger(
        self, staff_client, make_equipment, configured_base_url,
    ):
        eq = make_equipment('X', 'Y', 'Z')
        # Real render exercising the guard end-to-end (no monkeypatch). Letter @ 1200 dpi.
        resp = staff_client.post(
            f'/equipment/{eq.id}/qr',
            data={'size': 'letter', 'device': 'laser_1200', 'wifi_info': 'none',
                  'submit': 'Download QR Code'},
        )
        assert resp.status_code == 200
        assert not resp.content_type.startswith('image/png')
        assert b'too large to render' in resp.data

    def test_get_qr_preview_oversized_400(
        self, staff_client, make_equipment, configured_base_url,
    ):
        eq = make_equipment('X', 'Y', 'Z')
        resp = staff_client.get(
            f'/equipment/{eq.id}/qr/preview?size=letter&device=laser_1200'
        )
        assert resp.status_code == 400

    # --- WiFi dropdown tests ---

    def test_qr_form_shows_wifi_dropdown(self, staff_client, make_equipment, configured_base_url):
        eq = make_equipment('X', 'Y', 'Z')
        resp = staff_client.get(f'/equipment/{eq.id}/qr')
        assert resp.status_code == 200
        assert b'name="wifi_info"' in resp.data

    def test_qr_form_wifi_choices_no_config(self, staff_client, make_equipment, configured_base_url):
        eq = make_equipment('X', 'Y', 'Z')
        resp = staff_client.get(f'/equipment/{eq.id}/qr')
        html = resp.data.decode()
        assert 'value="none"' in html
        assert 'value="header"' in html
        assert 'value="ssid"' not in html
        assert 'value="password"' not in html

    def test_qr_form_wifi_choices_ssid_only(self, staff_client, make_equipment, configured_base_url):
        from esb.services import config_service
        config_service.set_config('wifi_ssid', 'MyNet', 'test')
        eq = make_equipment('X', 'Y', 'Z')
        resp = staff_client.get(f'/equipment/{eq.id}/qr')
        html = resp.data.decode()
        assert 'value="ssid"' in html
        assert 'value="password"' not in html

    def test_qr_form_wifi_choices_ssid_and_password(
        self, staff_client, make_equipment, configured_base_url,
    ):
        from esb.services import config_service
        config_service.set_config('wifi_ssid', 'MyNet', 'test')
        config_service.set_config('wifi_password', 'secret', 'test')
        eq = make_equipment('X', 'Y', 'Z')
        resp = staff_client.get(f'/equipment/{eq.id}/qr')
        html = resp.data.decode()
        assert 'value="none"' in html
        assert 'value="header"' in html
        assert 'value="ssid"' in html
        assert 'value="password"' in html

    def test_qr_form_wifi_default_from_config(self, staff_client, make_equipment, configured_base_url):
        from esb.services import config_service
        config_service.set_config('wifi_info_default', 'header', 'test')
        eq = make_equipment('X', 'Y', 'Z')
        resp = staff_client.get(f'/equipment/{eq.id}/qr')
        html = resp.data.decode()
        assert 'selected' in html
        idx_header = html.find('value="header"')
        assert idx_header != -1
        tag_start = html.rfind('<option', max(0, idx_header - 100), idx_header)
        tag_end = html.find('>', idx_header)
        option_tag = html[tag_start:tag_end + 1]
        assert 'selected' in option_tag

    def test_qr_form_wifi_default_fallback_no_password(
        self, staff_client, make_equipment, configured_base_url,
    ):
        from esb.services import config_service
        config_service.set_config('wifi_info_default', 'password', 'test')
        config_service.set_config('wifi_ssid', 'MyNet', 'test')
        eq = make_equipment('X', 'Y', 'Z')
        resp = staff_client.get(f'/equipment/{eq.id}/qr')
        html = resp.data.decode()
        idx_none = html.find('value="none"')
        assert idx_none != -1
        tag_start = html.rfind('<option', max(0, idx_none - 100), idx_none)
        tag_end = html.find('>', idx_none)
        option_tag = html[tag_start:tag_end + 1]
        assert 'selected' in option_tag

    def test_qr_form_wifi_default_fallback_no_ssid(
        self, staff_client, make_equipment, configured_base_url,
    ):
        from esb.services import config_service
        config_service.set_config('wifi_info_default', 'ssid', 'test')
        eq = make_equipment('X', 'Y', 'Z')
        resp = staff_client.get(f'/equipment/{eq.id}/qr')
        html = resp.data.decode()
        idx_none = html.find('value="none"')
        assert idx_none != -1
        tag_start = html.rfind('<option', max(0, idx_none - 100), idx_none)
        tag_end = html.find('>', idx_none)
        option_tag = html[tag_start:tag_end + 1]
        assert 'selected' in option_tag

    def test_qr_preview_includes_wifi_param(self, staff_client, make_equipment, configured_base_url):
        eq = make_equipment('X', 'Y', 'Z')
        resp = staff_client.get(f'/equipment/{eq.id}/qr/preview?size=sticker_2&wifi_info=header')
        assert resp.status_code == 200
        assert resp.content_type.startswith('image/png')

    def test_qr_download_with_wifi_header(self, staff_client, make_equipment, configured_base_url):
        eq = make_equipment('X', 'Y', 'Z')
        resp = staff_client.post(
            f'/equipment/{eq.id}/qr',
            data={'size': 'sticker_2', 'wifi_info': 'header', 'submit': 'Download QR Code'},
        )
        assert resp.status_code == 200
        assert resp.content_type.startswith('image/png')
        assert 'attachment' in resp.headers.get('Content-Disposition', '')

    def test_qr_download_clamps_stale_wifi_info(self, staff_client, make_equipment, configured_base_url):
        from esb.services import config_service
        config_service.set_config('wifi_ssid', 'MyNet', 'test')
        config_service.set_config('wifi_password', 'secret', 'test')
        eq = make_equipment('X', 'Y', 'Z')
        config_service.set_config('wifi_password', '', 'test')
        resp = staff_client.post(
            f'/equipment/{eq.id}/qr',
            data={'size': 'sticker_2', 'wifi_info': 'password', 'submit': 'Download QR Code'},
            follow_redirects=False,
        )
        assert resp.status_code == 200
        assert resp.content_type.startswith('image/png')

    def test_qr_download_without_wifi_info_param(self, staff_client, make_equipment, configured_base_url):
        """POST without wifi_info field (e.g., scripted client) should succeed, treated as 'none'."""
        eq = make_equipment('X', 'Y', 'Z')
        resp = staff_client.post(
            f'/equipment/{eq.id}/qr',
            data={'size': 'sticker_2', 'submit': 'Download QR Code'},
        )
        assert resp.status_code == 200
        assert resp.content_type.startswith('image/png')

    def test_qr_preview_rejects_invalid_wifi_info(self, staff_client, make_equipment, configured_base_url):
        eq = make_equipment('X', 'Y', 'Z')
        resp_bogus = staff_client.get(f'/equipment/{eq.id}/qr/preview?size=sticker_2&wifi_info=bogus')
        resp_none = staff_client.get(f'/equipment/{eq.id}/qr/preview?size=sticker_2&wifi_info=none')
        assert resp_bogus.status_code == 200
        assert resp_none.status_code == 200
        assert resp_bogus.data == resp_none.data, 'bogus wifi_info should render identically to none'
