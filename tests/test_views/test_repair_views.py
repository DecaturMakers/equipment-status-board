"""Tests for repair record views."""

import re
from datetime import UTC, date, datetime, timedelta
from io import BytesIO
from unittest.mock import patch

from esb.extensions import db as _db
from esb.models.document import Document
from esb.models.repair_record import RepairRecord
from esb.models.repair_timeline_entry import RepairTimelineEntry
from esb.utils.exceptions import ValidationError


def _main_element_classes(html: str) -> list[str]:
    """Return the class list on the rendered ``<main>`` element."""
    match = re.search(r'<main\b[^>]*\bclass="([^"]*)"', html)
    assert match, 'no <main> element with class attribute found'
    return match.group(1).split()


class TestCreateRepairRecord:
    """Tests for GET/POST /repairs/new."""

    def test_staff_sees_form(self, staff_client, make_equipment):
        """Staff can access the create repair record form."""
        make_equipment('Laser Cutter')
        resp = staff_client.get('/repairs/new')
        assert resp.status_code == 200
        assert b'Create Repair Record' in resp.data

    def test_technician_sees_form(self, tech_client, make_equipment):
        """Technicians can access the create repair record form."""
        make_equipment('Laser Cutter')
        resp = tech_client.get('/repairs/new')
        assert resp.status_code == 200
        assert b'Create Repair Record' in resp.data

    def test_unauthenticated_redirects_to_login(self, client):
        """Unauthenticated users are redirected to login."""
        resp = client.get('/repairs/new')
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']

    def test_staff_creates_record_successfully(self, staff_client, make_equipment):
        """Staff can create a repair record successfully."""
        eq = make_equipment('3D Printer')
        resp = staff_client.post('/repairs/new', data={
            'equipment_id': eq.id,
            'description': 'Nozzle clogged',
            'severity': 'Degraded',
            'assignee_id': 0,
            'has_safety_risk': False,
            'is_consumable': False,
        }, follow_redirects=False)
        assert resp.status_code == 302
        assert '/repairs/' in resp.headers['Location']

        record = _db.session.execute(
            _db.select(RepairRecord)
        ).scalar_one()
        assert record.description == 'Nozzle clogged'
        assert record.status == 'New'

    def test_technician_creates_record_successfully(self, tech_client, make_equipment):
        """Technicians can create a repair record successfully."""
        eq = make_equipment('CNC Router')
        resp = tech_client.post('/repairs/new', data={
            'equipment_id': eq.id,
            'description': 'Bit broke',
            'severity': '',
            'assignee_id': 0,
        }, follow_redirects=False)
        assert resp.status_code == 302

    def test_missing_required_field_shows_error(self, staff_client, make_equipment):
        """Missing description shows validation error."""
        eq = make_equipment('Laser')
        resp = staff_client.post('/repairs/new', data={
            'equipment_id': eq.id,
            'description': '',
            'severity': '',
            'assignee_id': 0,
        })
        assert resp.status_code == 200
        assert b'This field is required' in resp.data

    def test_invalid_equipment_shows_flash(self, staff_client, make_equipment):
        """Selecting no equipment shows flash error."""
        make_equipment()
        resp = staff_client.post('/repairs/new', data={
            'equipment_id': 0,
            'description': 'Broken',
            'severity': '',
            'assignee_id': 0,
        })
        assert resp.status_code == 200
        assert b'Please select an equipment item' in resp.data

    def test_preselected_equipment_via_query_param(self, staff_client, make_equipment):
        """Equipment is pre-selected when equipment_id query param is provided."""
        eq = make_equipment('Table Saw')
        resp = staff_client.get(f'/repairs/new?equipment_id={eq.id}')
        assert resp.status_code == 200
        # WTForms renders: <option selected value="X">
        assert f'selected value="{eq.id}"'.encode() in resp.data


class TestRepairRecordDetail:
    """Tests for GET /repairs/<id>."""

    def test_staff_sees_detail(self, staff_client, make_repair_record):
        """Staff can view repair record detail page."""
        record = make_repair_record(description='Motor grinding')
        resp = staff_client.get(f'/repairs/{record.id}')
        assert resp.status_code == 200
        assert b'Motor grinding' in resp.data

    def test_technician_sees_detail(self, tech_client, make_repair_record):
        """Technicians can view repair record detail page."""
        record = make_repair_record(description='Belt slipping')
        resp = tech_client.get(f'/repairs/{record.id}')
        assert resp.status_code == 200
        assert b'Belt slipping' in resp.data

    def test_unauthenticated_redirects_to_login(self, client, make_repair_record):
        """Unauthenticated users are redirected to login."""
        record = make_repair_record()
        resp = client.get(f'/repairs/{record.id}')
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']

    def test_nonexistent_record_returns_404(self, staff_client):
        """Non-existent repair record returns 404."""
        resp = staff_client.get('/repairs/9999')
        assert resp.status_code == 404

    def test_shows_timeline_entries(self, staff_client, make_repair_record):
        """Detail page shows timeline entries."""
        record = make_repair_record(description='Broken belt')
        entry = RepairTimelineEntry(
            repair_record_id=record.id,
            entry_type='creation',
            content='Broken belt',
            author_name='staffuser',
        )
        _db.session.add(entry)
        _db.session.commit()

        resp = staff_client.get(f'/repairs/{record.id}')
        assert resp.status_code == 200
        assert b'Repair record created' in resp.data
        assert b'Broken belt' in resp.data

    def test_shows_equipment_name_and_link(self, staff_client, make_equipment, make_repair_record):
        """Detail page shows equipment name with link."""
        eq = make_equipment('Laser Cutter')
        record = make_repair_record(equipment=eq, description='Tube issue')
        resp = staff_client.get(f'/repairs/{record.id}')
        assert resp.status_code == 200
        assert b'Laser Cutter' in resp.data
        assert f'/equipment/{eq.id}'.encode() in resp.data

    def test_detail_eta_uses_format_date(self, staff_client, make_repair_record):
        record = make_repair_record(eta=date(2026, 6, 15))
        resp = staff_client.get(f'/repairs/{record.id}')
        assert b'ETA</dt>' in resp.data
        assert b'Jun 15, 2026' in resp.data

    def test_timeline_eta_update_uses_format_date(self, staff_client, make_repair_record):
        record = make_repair_record()
        _db.session.add(RepairTimelineEntry(
            repair_record_id=record.id, entry_type='eta_update',
            new_value='2026-03-15', author_name='staffuser',
        ))
        _db.session.commit()
        resp = staff_client.get(f'/repairs/{record.id}')
        assert re.search(rb'set to\s+Mar 15, 2026\b', resp.data)
        assert b'set to 2026-03-15' not in resp.data


class TestEditRepairRecord:
    """Tests for GET/POST /repairs/<id>/edit."""

    def test_edit_page_staff_sees_form(self, staff_client, make_repair_record):
        """Staff can access the edit form pre-populated."""
        record = make_repair_record(status='New', description='Motor issue')
        resp = staff_client.get(f'/repairs/{record.id}/edit')
        assert resp.status_code == 200
        assert b'Edit Repair' in resp.data
        assert b'Save Changes' in resp.data

    def test_edit_page_technician_sees_form(self, tech_client, make_repair_record):
        """Technicians can access the edit form."""
        record = make_repair_record()
        resp = tech_client.get(f'/repairs/{record.id}/edit')
        assert resp.status_code == 200
        assert b'Edit Repair' in resp.data

    def test_edit_page_unauthenticated_redirects(self, client, make_repair_record):
        """Unauthenticated users are redirected to login."""
        record = make_repair_record()
        resp = client.get(f'/repairs/{record.id}/edit')
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']

    def test_edit_page_not_found(self, staff_client):
        """Non-existent record returns 404."""
        resp = staff_client.get('/repairs/9999/edit')
        assert resp.status_code == 404

    def test_edit_post_staff_updates_successfully(self, staff_client, make_repair_record):
        """Staff POST updates record and redirects to detail."""
        record = make_repair_record(status='New')
        resp = staff_client.post(f'/repairs/{record.id}/edit', data={
            'status': 'Assigned',
            'severity': '',
            'assignee_id': '0',
            'specialist_description': '',
            'note': '',
        }, follow_redirects=False)
        assert resp.status_code == 302
        assert f'/repairs/{record.id}' in resp.headers['Location']

    def test_edit_post_technician_updates_successfully(self, tech_client, make_repair_record):
        """Technician POST updates record and redirects."""
        record = make_repair_record(status='New')
        resp = tech_client.post(f'/repairs/{record.id}/edit', data={
            'status': 'In Progress',
            'severity': '',
            'assignee_id': '0',
            'specialist_description': '',
            'note': '',
        }, follow_redirects=False)
        assert resp.status_code == 302

    def test_edit_post_status_change_saved(self, staff_client, make_repair_record):
        """Status change is saved to the record after POST."""
        record = make_repair_record(status='New')
        staff_client.post(f'/repairs/{record.id}/edit', data={
            'status': 'In Progress',
            'severity': '',
            'assignee_id': '0',
            'specialist_description': '',
            'note': '',
        })
        updated = _db.session.get(RepairRecord, record.id)
        assert updated.status == 'In Progress'

    def test_edit_post_multiple_changes(self, staff_client, make_repair_record, tech_user):
        """POST with multiple changes (status + assignee + note) all saved."""
        record = make_repair_record(status='New')
        staff_client.post(f'/repairs/{record.id}/edit', data={
            'status': 'Assigned',
            'severity': 'Degraded',
            'assignee_id': str(tech_user.id),
            'specialist_description': '',
            'note': 'Assigning to tech',
        })
        updated = _db.session.get(RepairRecord, record.id)
        assert updated.status == 'Assigned'
        assert updated.assignee_id == tech_user.id
        entries = _db.session.execute(
            _db.select(RepairTimelineEntry).filter_by(repair_record_id=record.id)
        ).scalars().all()
        entry_types = {e.entry_type for e in entries}
        assert 'status_change' in entry_types
        assert 'assignee_change' in entry_types
        assert 'note' in entry_types

    def test_edit_post_specialist_description(self, staff_client, make_repair_record):
        """POST with Needs Specialist status saves specialist description."""
        record = make_repair_record(status='New')
        staff_client.post(f'/repairs/{record.id}/edit', data={
            'status': 'Needs Specialist',
            'severity': '',
            'assignee_id': '0',
            'specialist_description': 'Need licensed electrician',
            'note': '',
        })
        updated = _db.session.get(RepairRecord, record.id)
        assert updated.status == 'Needs Specialist'
        assert updated.specialist_description == 'Need licensed electrician'

    def test_edit_post_validation_error_shows_flash(self, staff_client, make_repair_record):
        """Service ValidationError is caught and displayed as flash message."""
        record = make_repair_record(status='New')
        with patch('esb.services.repair_service.update_repair_record') as mock_update:
            mock_update.side_effect = ValidationError('Test validation error')
            resp = staff_client.post(f'/repairs/{record.id}/edit', data={
                'status': 'New',
                'severity': '',
                'assignee_id': '0',
                'specialist_description': '',
                'note': '',
            })
        assert resp.status_code == 200
        assert b'Test validation error' in resp.data

    def test_edit_post_unauthenticated_redirects(self, client, make_repair_record):
        """Unauthenticated POST redirects to login."""
        record = make_repair_record()
        resp = client.post(f'/repairs/{record.id}/edit', data={
            'status': 'Assigned',
            'severity': '',
            'assignee_id': '0',
            'specialist_description': '',
            'note': '',
        })
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']


class TestAddNote:
    """Tests for POST /repairs/<id>/notes."""

    def test_detail_shows_note_form(self, staff_client, make_repair_record):
        """Detail page contains the note form."""
        record = make_repair_record()
        resp = staff_client.get(f'/repairs/{record.id}')
        assert resp.status_code == 200
        assert b'Add a Note' in resp.data
        assert b'Add Note' in resp.data

    def test_detail_shows_photo_upload_form(self, staff_client, make_repair_record):
        """Detail page contains the photo upload form."""
        record = make_repair_record()
        resp = staff_client.get(f'/repairs/{record.id}')
        assert resp.status_code == 200
        assert b'Upload Diagnostic Photo' in resp.data
        assert b'Upload Photo' in resp.data
        assert b'multipart/form-data' in resp.data

    def test_detail_shows_timeline_entries_all_types(self, staff_client, make_repair_record):
        """Detail page renders timeline with multiple entry types."""
        record = make_repair_record()
        _db.session.add_all([
            RepairTimelineEntry(
                repair_record_id=record.id, entry_type='creation',
                content='Created', author_name='staffuser',
            ),
            RepairTimelineEntry(
                repair_record_id=record.id, entry_type='note',
                content='Test note', author_name='staffuser',
            ),
            RepairTimelineEntry(
                repair_record_id=record.id, entry_type='status_change',
                old_value='New', new_value='In Progress', author_name='staffuser',
            ),
            RepairTimelineEntry(
                repair_record_id=record.id, entry_type='assignee_change',
                new_value='techuser', author_name='staffuser',
            ),
        ])
        _db.session.commit()

        resp = staff_client.get(f'/repairs/{record.id}')
        assert resp.status_code == 200
        assert b'Repair record created' in resp.data
        assert b'Note added' in resp.data
        assert b'Status changed from' in resp.data
        assert b'Assigned to techuser' in resp.data

    def test_staff_adds_note_successfully(self, staff_client, make_repair_record):
        """Staff POST note returns 302 redirect to detail."""
        record = make_repair_record()
        resp = staff_client.post(f'/repairs/{record.id}/notes', data={
            'note': 'Motor bearings worn',
        }, follow_redirects=False)
        assert resp.status_code == 302
        assert f'/repairs/{record.id}' in resp.headers['Location']

        entry = _db.session.execute(
            _db.select(RepairTimelineEntry).filter_by(
                repair_record_id=record.id, entry_type='note',
            )
        ).scalar_one()
        assert entry.content == 'Motor bearings worn'

    def test_tech_adds_note_successfully(self, tech_client, make_repair_record):
        """Technician POST note returns 302 redirect to detail."""
        record = make_repair_record()
        resp = tech_client.post(f'/repairs/{record.id}/notes', data={
            'note': 'Checked alignment',
        }, follow_redirects=False)
        assert resp.status_code == 302
        assert f'/repairs/{record.id}' in resp.headers['Location']

    def test_unauthenticated_redirects_to_login(self, client, make_repair_record):
        """Unauthenticated POST redirects to login."""
        record = make_repair_record()
        resp = client.post(f'/repairs/{record.id}/notes', data={
            'note': 'Should not work',
        })
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']

    def test_nonexistent_record_returns_404(self, staff_client):
        """POST to non-existent record returns 404."""
        resp = staff_client.post('/repairs/9999/notes', data={
            'note': 'No record',
        })
        assert resp.status_code == 404

    def test_empty_note_flashes_validation_error(self, staff_client, make_repair_record):
        """POST with empty note flashes form validation error."""
        record = make_repair_record()
        resp = staff_client.post(f'/repairs/{record.id}/notes', data={
            'note': '',
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert b'This field is required' in resp.data

    def test_detail_shows_photo_timeline_with_thumbnail(self, app, staff_client, make_repair_record, tmp_path):
        """Detail page renders photo timeline entry with thumbnail image."""
        app.config['UPLOAD_PATH'] = str(tmp_path)
        record = make_repair_record()

        doc = Document(
            parent_type='repair_photo',
            parent_id=record.id,
            original_filename='test_photo.jpg',
            stored_filename='abc123.jpg',
            content_type='image/jpeg',
            size_bytes=100,
            uploaded_by='staffuser',
        )
        _db.session.add(doc)
        _db.session.flush()

        entry = RepairTimelineEntry(
            repair_record_id=record.id,
            entry_type='photo',
            content=str(doc.id),
            author_name='staffuser',
        )
        _db.session.add(entry)
        _db.session.commit()

        file_dir = tmp_path / 'repairs' / str(record.id)
        file_dir.mkdir(parents=True)
        (file_dir / 'abc123.jpg').write_bytes(b'fake jpeg data')

        resp = staff_client.get(f'/repairs/{record.id}')
        assert resp.status_code == 200
        assert b'Photo uploaded' in resp.data
        assert b'img-thumbnail' in resp.data
        assert b'test_photo.jpg' in resp.data


class TestUploadPhoto:
    """Tests for POST /repairs/<id>/photos."""

    def test_staff_uploads_photo_successfully(self, app, staff_client, make_repair_record, tmp_path):
        """Staff POST with file returns 302 redirect to detail."""
        app.config['UPLOAD_PATH'] = str(tmp_path)
        record = make_repair_record()
        data = {'file': (BytesIO(b'fake image content'), 'test.jpg')}
        resp = staff_client.post(
            f'/repairs/{record.id}/photos',
            data=data,
            content_type='multipart/form-data',
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert f'/repairs/{record.id}' in resp.headers['Location']

    def test_tech_uploads_photo_successfully(self, app, tech_client, make_repair_record, tmp_path):
        """Technician POST with file returns 302 redirect to detail."""
        app.config['UPLOAD_PATH'] = str(tmp_path)
        record = make_repair_record()
        data = {'file': (BytesIO(b'fake image content'), 'photo.png')}
        resp = tech_client.post(
            f'/repairs/{record.id}/photos',
            data=data,
            content_type='multipart/form-data',
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert f'/repairs/{record.id}' in resp.headers['Location']

    def test_unauthenticated_redirects_to_login(self, client, make_repair_record):
        """Unauthenticated POST redirects to login."""
        record = make_repair_record()
        data = {'file': (BytesIO(b'fake'), 'test.jpg')}
        resp = client.post(
            f'/repairs/{record.id}/photos',
            data=data,
            content_type='multipart/form-data',
        )
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']

    def test_nonexistent_record_returns_404(self, staff_client):
        """POST to non-existent record returns 404."""
        data = {'file': (BytesIO(b'fake'), 'test.jpg')}
        resp = staff_client.post(
            '/repairs/9999/photos',
            data=data,
            content_type='multipart/form-data',
        )
        assert resp.status_code == 404

    def test_missing_file_flashes_validation_error(self, staff_client, make_repair_record):
        """POST without file flashes form validation error."""
        record = make_repair_record()
        resp = staff_client.post(
            f'/repairs/{record.id}/photos',
            data={},
            content_type='multipart/form-data',
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert b'Please select a file to upload' in resp.data


class TestServePhoto:
    """Tests for GET /repairs/<id>/files/<filename>."""

    def test_returns_uploaded_file(self, app, staff_client, make_repair_record, tmp_path):
        """File serving route returns the uploaded file."""
        app.config['UPLOAD_PATH'] = str(tmp_path)
        record = make_repair_record()

        # Create the file on disk
        file_dir = tmp_path / 'repairs' / str(record.id)
        file_dir.mkdir(parents=True)
        test_file = file_dir / 'test_photo.jpg'
        test_file.write_bytes(b'fake jpeg data')

        resp = staff_client.get(f'/repairs/{record.id}/files/test_photo.jpg')
        assert resp.status_code == 200
        assert resp.data == b'fake jpeg data'

    def test_nonexistent_file_returns_404(self, app, staff_client, make_repair_record, tmp_path):
        """Non-existent file returns 404."""
        app.config['UPLOAD_PATH'] = str(tmp_path)
        record = make_repair_record()
        resp = staff_client.get(f'/repairs/{record.id}/files/nonexistent.jpg')
        assert resp.status_code == 404

    def test_nonexistent_record_returns_404(self, staff_client):
        """Serving file for non-existent repair record returns 404."""
        resp = staff_client.get('/repairs/9999/files/test.jpg')
        assert resp.status_code == 404


class TestRepairQueue:
    """Tests for GET /repairs/queue and related redirect behavior."""

    def test_queue_loads_200_for_technician(self, tech_client):
        """Technician gets 200 on the queue page."""
        resp = tech_client.get('/repairs/queue')
        assert resp.status_code == 200
        assert b'Repair Queue' in resp.data

    def test_queue_loads_200_for_staff(self, staff_client):
        """Staff gets 200 on the queue page."""
        resp = staff_client.get('/repairs/queue')
        assert resp.status_code == 200
        assert b'Repair Queue' in resp.data

    def test_queue_redirects_unauthenticated(self, client):
        """Unauthenticated users are redirected to login."""
        resp = client.get('/repairs/queue')
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']

    def test_queue_displays_records_with_columns(self, tech_client, make_area, make_equipment, make_repair_record):
        """Queue shows equipment name, severity, area, status."""
        area = make_area('Woodshop')
        eq = make_equipment('Table Saw', area=area)
        make_repair_record(equipment=eq, description='Blade dull', severity='Degraded')
        resp = tech_client.get('/repairs/queue')
        assert resp.status_code == 200
        assert b'Table Saw' in resp.data
        assert b'Degraded' in resp.data
        assert b'Woodshop' in resp.data
        assert b'New' in resp.data

    def test_queue_severity_badge_down(self, tech_client, make_area, make_equipment, make_repair_record):
        """Down severity gets bg-danger badge."""
        area = make_area('Metalshop')
        eq = make_equipment('Welder', area=area)
        make_repair_record(equipment=eq, description='Broken', severity='Down')
        resp = tech_client.get('/repairs/queue')
        assert b'bg-danger' in resp.data

    def test_queue_severity_badge_degraded(self, tech_client, make_area, make_equipment, make_repair_record):
        """Degraded severity gets bg-warning badge."""
        area = make_area('Woodshop')
        eq = make_equipment('Table Saw', area=area)
        make_repair_record(equipment=eq, description='Dull', severity='Degraded')
        resp = tech_client.get('/repairs/queue')
        assert b'bg-warning' in resp.data

    def test_queue_empty_state(self, tech_client):
        """Shows empty state message when no open records."""
        resp = tech_client.get('/repairs/queue')
        assert b'No open repair records' in resp.data
        assert b'All equipment is operational' in resp.data

    def test_queue_area_filter(self, tech_client, make_area, make_equipment, make_repair_record):
        """Area filter param returns only matching records."""
        area1 = make_area('Woodshop')
        area2 = make_area('Metalshop', slack_channel='#metalshop')
        eq1 = make_equipment('Table Saw', area=area1)
        eq2 = make_equipment('Welder', area=area2)
        make_repair_record(equipment=eq1, description='Saw issue')
        make_repair_record(equipment=eq2, description='Welder issue')
        resp = tech_client.get(f'/repairs/queue?area={area1.id}')
        assert b'Table Saw' in resp.data
        assert b'Welder' not in resp.data

    def test_queue_status_filter(self, tech_client, make_area, make_equipment, make_repair_record):
        """Status filter param returns only matching records."""
        area = make_area('Shop')
        eq = make_equipment('Laser', area=area)
        make_repair_record(equipment=eq, description='new issue', status='New')
        make_repair_record(equipment=eq, description='assigned issue', status='Assigned')
        resp = tech_client.get('/repairs/queue?status=Assigned')
        assert b'assigned issue' not in resp.data  # description not shown in queue table
        # But the filtered table should contain only the Assigned record
        assert resp.data.count(b'data-status="Assigned"') == 2  # table row + mobile card
        assert resp.data.count(b'data-status="New"') == 0

    def test_index_redirects_to_queue(self, tech_client):
        """GET /repairs/ redirects to /repairs/queue."""
        resp = tech_client.get('/repairs/')
        assert resp.status_code == 302
        assert '/repairs/queue' in resp.headers['Location']

    def test_login_redirects_technician_to_queue(self, client, tech_user):
        """Technician login without next param redirects to /repairs/queue."""
        resp = client.post('/auth/login', data={
            'username': 'techuser',
            'password': 'testpass',
        }, follow_redirects=False)
        assert resp.status_code == 302
        assert '/repairs/queue' in resp.headers['Location']

    def test_navbar_contains_queue_link(self, tech_client):
        """Navbar Repairs link points to queue."""
        resp = tech_client.get('/repairs/queue')
        assert b'/repairs/queue' in resp.data

    def test_queue_combined_area_and_status_filter(self, tech_client, make_area, make_equipment, make_repair_record):
        """Combined area + status filter returns only matching records."""
        area1 = make_area('Woodshop')
        area2 = make_area('Metalshop', slack_channel='#metalshop')
        eq1 = make_equipment('Table Saw', area=area1)
        eq2 = make_equipment('Welder', area=area2)
        make_repair_record(equipment=eq1, description='saw new', status='New')
        make_repair_record(equipment=eq1, description='saw assigned', status='Assigned')
        make_repair_record(equipment=eq2, description='welder new', status='New')
        resp = tech_client.get(f'/repairs/queue?area={area1.id}&status=New')
        assert resp.data.count(b'data-status="New"') == 2  # table row + mobile card
        assert b'data-status="Assigned"' not in resp.data
        assert b'Welder' not in resp.data

    def test_queue_displays_assignee(self, tech_client, make_area, make_equipment, make_repair_record, tech_user):
        """Queue shows assignee username when assigned."""
        area = make_area('Woodshop')
        eq = make_equipment('Table Saw', area=area)
        make_repair_record(equipment=eq, description='Blade dull', assignee_id=tech_user.id)
        resp = tech_client.get('/repairs/queue')
        assert b'techuser' in resp.data

    def test_queue_mobile_cards_present(self, tech_client, make_area, make_equipment, make_repair_record):
        """Queue renders mobile card layout with expected structure."""
        area = make_area('Woodshop')
        eq = make_equipment('Table Saw', area=area)
        make_repair_record(equipment=eq, description='Blade dull', severity='Down')
        resp = tech_client.get('/repairs/queue')
        assert b'queue-card' in resp.data
        assert b'd-md-none' in resp.data
        assert b'queue-cards-wrapper' in resp.data

    def test_queue_displays_eta_column_header(self, tech_client, make_area, make_equipment, make_repair_record):
        area = make_area('Woodshop')
        eq = make_equipment('Table Saw', area=area)
        make_repair_record(equipment=eq, description='Blade dull', severity='Down')
        resp = tech_client.get('/repairs/queue')
        assert b'queue-eta-cell' in resp.data

    def test_queue_displays_eta_value(self, tech_client, make_area, make_equipment, make_repair_record):
        area = make_area('Woodshop')
        eq = make_equipment('Table Saw', area=area)
        make_repair_record(
            equipment=eq, description='Blade dull', severity='Down',
            eta=date(2026, 6, 15),
        )
        resp = tech_client.get('/repairs/queue')
        expected = (
            'queue-eta-cell" data-eta-iso="2026-06-15">'
            + date(2026, 6, 15).strftime('%b %d, %Y')
            + '<'
        ).encode()
        assert expected in resp.data

    def test_queue_eta_cell_blank_when_no_eta(self, tech_client, make_area, make_equipment, make_repair_record):
        area = make_area('Woodshop')
        eq = make_equipment('Table Saw', area=area)
        # Use Down severity so the row's severity badge is "Down", not literal "None".
        make_repair_record(
            equipment=eq, description='Blade dull', severity='Down', eta=None,
        )
        resp = tech_client.get('/repairs/queue')
        # Row-scoped: queue-eta-cell with empty data-eta-iso and empty content.
        assert re.search(
            rb'class="queue-eta-cell"[^>]*data-eta-iso=""[^>]*>\s*</td>',
            resp.data,
        )

    def test_queue_mobile_card_displays_eta(self, tech_client, make_area, make_equipment, make_repair_record):
        area = make_area('Woodshop')
        eq = make_equipment('Table Saw', area=area)
        make_repair_record(
            equipment=eq, description='Blade dull', severity='Down',
            eta=date(2026, 6, 15),
        )
        resp = tech_client.get('/repairs/queue')
        expected = ('ETA: ' + date(2026, 6, 15).strftime('%b %d, %Y')).encode()
        assert expected in resp.data

    def test_queue_existing_sortable_columns_unchanged(
        self, tech_client, make_area, make_equipment, make_repair_record,
    ):
        # AC 38: ETA column must NOT be sortable; existing 6 sortable columns remain.
        area = make_area('Woodshop')
        eq = make_equipment('Table Saw', area=area)
        make_repair_record(equipment=eq, description='Blade dull', severity='Down')
        resp = tech_client.get('/repairs/queue')
        sortable_ths = re.findall(rb'<th[^>]*\bdata-sort=', resp.data)
        assert len(sortable_ths) == 6


class TestKanbanBoard:
    """Tests for GET /repairs/kanban and Kanban-related behavior."""

    def test_kanban_loads_200_for_staff(self, staff_client):
        """Staff gets 200 on the kanban page."""
        resp = staff_client.get('/repairs/kanban')
        assert resp.status_code == 200
        assert b'Kanban Board' in resp.data

    def test_kanban_loads_200_for_technician(self, tech_client):
        """Technician gets 200 on the kanban page (accessible via role hierarchy)."""
        resp = tech_client.get('/repairs/kanban')
        assert resp.status_code == 200
        assert b'Kanban Board' in resp.data

    def test_kanban_redirects_unauthenticated(self, client):
        """Unauthenticated users are redirected to login."""
        resp = client.get('/repairs/kanban')
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']

    def test_kanban_displays_column_headers(self, staff_client):
        """Kanban shows all status column headers."""
        resp = staff_client.get('/repairs/kanban')
        assert resp.status_code == 200
        assert b'New' in resp.data
        assert b'Assigned' in resp.data
        assert b'In Progress' in resp.data
        assert b'Parts Needed' in resp.data
        assert b'Parts Ordered' in resp.data
        assert b'Parts Received' in resp.data
        assert b'Needs Specialist' in resp.data

    def test_kanban_shows_card_count(self, staff_client, make_area, make_equipment, make_repair_record):
        """Column headers show card count badges."""
        area = make_area('Woodshop')
        eq = make_equipment('Table Saw', area=area)
        make_repair_record(equipment=eq, description='issue1', status='New')
        make_repair_record(equipment=eq, description='issue2', status='New')
        resp = staff_client.get('/repairs/kanban')
        assert resp.status_code == 200
        # Count should show "2" for New column (badge text)
        assert b'>2<' in resp.data

    def test_kanban_cards_contain_equipment_and_area(self, staff_client, make_area, make_equipment, make_repair_record):
        """Kanban cards show equipment name and area badge."""
        area = make_area('Woodshop')
        eq = make_equipment('Table Saw', area=area)
        make_repair_record(equipment=eq, description='Blade dull')
        resp = staff_client.get('/repairs/kanban')
        assert resp.status_code == 200
        assert b'Table Saw' in resp.data
        assert b'Woodshop' in resp.data

    def test_kanban_cards_contain_severity_badges(self, staff_client, make_area, make_equipment, make_repair_record):
        """Kanban cards show severity badges."""
        area = make_area('Metalshop')
        eq = make_equipment('Welder', area=area)
        make_repair_record(equipment=eq, description='Broken', severity='Down')
        resp = staff_client.get('/repairs/kanban')
        assert b'bg-danger' in resp.data
        assert b'Down' in resp.data

    def test_kanban_empty_state(self, staff_client):
        """Shows empty state message when no open records."""
        resp = staff_client.get('/repairs/kanban')
        assert b'No open repair records' in resp.data
        assert b'All equipment is operational' in resp.data

    def test_kanban_card_links_to_detail(self, staff_client, make_area, make_equipment, make_repair_record):
        """Kanban cards link to repair detail page."""
        area = make_area('Woodshop')
        eq = make_equipment('Table Saw', area=area)
        record = make_repair_record(equipment=eq, description='Blade dull')
        resp = staff_client.get('/repairs/kanban')
        assert f'/repairs/{record.id}'.encode() in resp.data

    def test_kanban_card_displays_eta_when_set(
        self, staff_client, make_area, make_equipment, make_repair_record,
    ):
        area = make_area('Woodshop')
        eq = make_equipment('Table Saw', area=area)
        make_repair_record(
            equipment=eq, description='Blade dull', severity='Down',
            eta=date(2026, 6, 15),
        )
        resp = staff_client.get('/repairs/kanban')
        formatted = date(2026, 6, 15).strftime('%b %d, %Y').encode()
        assert b'ETA: ' + formatted in resp.data
        assert b', ETA ' + formatted in resp.data

    def test_kanban_card_omits_eta_when_unset(
        self, staff_client, make_area, make_equipment, make_repair_record,
    ):
        area = make_area('Woodshop')
        eq = make_equipment('Table Saw', area=area)
        make_repair_record(
            equipment=eq, description='Blade dull', severity='Down', eta=None,
        )
        resp = staff_client.get('/repairs/kanban')
        assert b'ETA:' not in resp.data
        assert b', ETA ' not in resp.data

    def test_login_redirects_staff_to_kanban(self, client, staff_user):
        """Staff login without next param redirects to /repairs/kanban."""
        resp = client.post('/auth/login', data={
            'username': 'staffuser',
            'password': 'testpass',
        }, follow_redirects=False)
        assert resp.status_code == 302
        assert '/repairs/kanban' in resp.headers['Location']

    def test_navbar_contains_kanban_link_for_staff(self, staff_client):
        """Navbar contains Kanban link for staff users."""
        resp = staff_client.get('/repairs/kanban')
        assert b'Kanban' in resp.data
        assert b'/repairs/kanban' in resp.data

    def test_responsive_layout_classes(self, staff_client):
        """Page contains desktop horizontal layout and mobile accordion layout."""
        resp = staff_client.get('/repairs/kanban')
        assert resp.status_code == 200
        assert b'kanban-container d-none d-lg-flex' in resp.data
        assert b'd-lg-none' in resp.data
        assert b'accordion' in resp.data
        assert b'accordion-item' in resp.data

    def test_aria_attributes_on_columns_and_cards(self, staff_client, make_area, make_equipment, make_repair_record):
        """Columns have role=region and aria-label; cards have tabindex=0."""
        area = make_area('Woodshop')
        eq = make_equipment('Table Saw', area=area)
        make_repair_record(equipment=eq, description='ARIA test')
        resp = staff_client.get('/repairs/kanban')
        assert resp.status_code == 200
        assert b'role="region"' in resp.data
        assert b'aria-label="Status: New' in resp.data
        assert b'tabindex="0"' in resp.data

    def test_time_title_shows_exact_datetime(self, staff_client, make_area, make_equipment):
        """Time-in-column title attribute shows exact datetime (format_datetime)."""
        area = make_area('Shop')
        eq = make_equipment('Drill', area=area)
        now = datetime.now(UTC)
        record = RepairRecord(
            equipment_id=eq.id, description='title test',
            status='New', created_at=now - timedelta(days=3),
        )
        _db.session.add(record)
        _db.session.commit()
        resp = staff_client.get('/repairs/kanban')
        # format_datetime outputs YYYY-MM-DD HH:MM format
        # The entered_at should be ~3 days ago, so the year should appear in the title
        html = resp.data.decode()
        assert 'title="20' in html  # starts with year prefix e.g. "2026-..."

    def test_aging_class_warm(self, staff_client, make_area, make_equipment):
        """Cards aged 3-5 days get kanban-card-warm class."""
        area = make_area('Shop')
        eq = make_equipment('Drill', area=area)
        now = datetime.now(UTC)
        record = RepairRecord(
            equipment_id=eq.id, description='aging warm',
            status='New', created_at=now - timedelta(days=4),
        )
        _db.session.add(record)
        _db.session.commit()
        resp = staff_client.get('/repairs/kanban')
        assert b'kanban-card-warm' in resp.data

    def test_aging_class_hot(self, staff_client, make_area, make_equipment):
        """Cards aged 6+ days get kanban-card-hot class."""
        area = make_area('Shop')
        eq = make_equipment('Drill', area=area)
        now = datetime.now(UTC)
        record = RepairRecord(
            equipment_id=eq.id, description='aging hot',
            status='New', created_at=now - timedelta(days=7),
        )
        _db.session.add(record)
        _db.session.commit()
        resp = staff_client.get('/repairs/kanban')
        assert b'kanban-card-hot' in resp.data

    def test_kanban_uses_container_fluid(self, staff_client):
        """Kanban page renders <main> with container-fluid so columns can use full viewport width (issue #9)."""
        resp = staff_client.get('/repairs/kanban')
        assert resp.status_code == 200
        classes = _main_element_classes(resp.data.decode())
        assert 'container-fluid' in classes
        assert 'container' not in classes

    def test_non_kanban_pages_use_default_container(self, staff_client):
        """Non-kanban pages retain the default fixed-width .container wrapper."""
        resp = staff_client.get('/equipment/')
        assert resp.status_code == 200
        classes = _main_element_classes(resp.data.decode())
        assert 'container' in classes
        assert 'container-fluid' not in classes
