"""Tests for status_service module."""

import pytest

from esb.services import status_service
from esb.utils.exceptions import AreaArchived, AreaNotFound, EquipmentNotFound


class TestComputeEquipmentStatus:
    """Tests for compute_equipment_status()."""

    def test_green_no_repair_records(self, app, make_equipment):
        """Equipment with no repair records returns green/Operational."""
        equipment = make_equipment()
        result = status_service.compute_equipment_status(equipment.id)
        assert result['color'] == 'green'
        assert result['label'] == 'Operational'
        assert result['issue_description'] is None
        assert result['severity'] is None

    def test_green_only_closed_records(self, app, make_equipment, make_repair_record):
        """Equipment with only closed repair records returns green/Operational."""
        equipment = make_equipment()
        make_repair_record(equipment=equipment, status='Resolved', severity='Down')
        make_repair_record(equipment=equipment, status='Closed - No Issue Found')
        make_repair_record(equipment=equipment, status='Closed - Duplicate', severity='Degraded')
        result = status_service.compute_equipment_status(equipment.id)
        assert result['color'] == 'green'
        assert result['label'] == 'Operational'
        assert result['issue_description'] is None
        assert result['severity'] is None

    def test_red_down_severity(self, app, make_equipment, make_repair_record):
        """Equipment with 'Down' severity open record returns red/Down."""
        equipment = make_equipment()
        make_repair_record(
            equipment=equipment, status='New', severity='Down',
            description='Motor burned out',
        )
        result = status_service.compute_equipment_status(equipment.id)
        assert result['color'] == 'red'
        assert result['label'] == 'Down'
        assert result['issue_description'] == 'Motor burned out'
        assert result['severity'] == 'Down'

    def test_yellow_degraded_severity(self, app, make_equipment, make_repair_record):
        """Equipment with 'Degraded' severity open record returns yellow/Degraded."""
        equipment = make_equipment()
        make_repair_record(
            equipment=equipment, status='In Progress', severity='Degraded',
            description='Belt slipping',
        )
        result = status_service.compute_equipment_status(equipment.id)
        assert result['color'] == 'yellow'
        assert result['label'] == 'Degraded'
        assert result['issue_description'] == 'Belt slipping'
        assert result['severity'] == 'Degraded'

    def test_yellow_not_sure_severity(self, app, make_equipment, make_repair_record):
        """Equipment with 'Not Sure' severity open record returns yellow/Degraded."""
        equipment = make_equipment()
        make_repair_record(
            equipment=equipment, status='New', severity='Not Sure',
            description='Making weird noise',
        )
        result = status_service.compute_equipment_status(equipment.id)
        assert result['color'] == 'yellow'
        assert result['label'] == 'Degraded'
        assert result['issue_description'] == 'Making weird noise'
        assert result['severity'] == 'Not Sure'

    def test_severity_priority_down_wins(self, app, make_equipment, make_repair_record):
        """'Down' severity takes priority over 'Degraded' and 'Not Sure'."""
        equipment = make_equipment()
        make_repair_record(
            equipment=equipment, status='New', severity='Not Sure',
            description='Minor issue',
        )
        make_repair_record(
            equipment=equipment, status='In Progress', severity='Degraded',
            description='Medium issue',
        )
        make_repair_record(
            equipment=equipment, status='Assigned', severity='Down',
            description='Critical failure',
        )
        result = status_service.compute_equipment_status(equipment.id)
        assert result['color'] == 'red'
        assert result['label'] == 'Down'
        assert result['issue_description'] == 'Critical failure'
        assert result['severity'] == 'Down'

    def test_issue_description_from_highest_severity(self, app, make_equipment, make_repair_record):
        """Issue description comes from the highest-severity open record."""
        equipment = make_equipment()
        make_repair_record(
            equipment=equipment, status='New', severity='Not Sure',
            description='Low priority issue',
        )
        make_repair_record(
            equipment=equipment, status='New', severity='Degraded',
            description='Important issue',
        )
        result = status_service.compute_equipment_status(equipment.id)
        assert result['issue_description'] == 'Important issue'
        assert result['severity'] == 'Degraded'

    def test_equipment_not_found(self, app):
        """Raises EquipmentNotFound for nonexistent equipment ID."""
        with pytest.raises(EquipmentNotFound):
            status_service.compute_equipment_status(99999)

    def test_open_records_no_severity(self, app, make_equipment, make_repair_record):
        """Equipment with open records but no severity set returns yellow/Degraded."""
        equipment = make_equipment()
        make_repair_record(
            equipment=equipment, status='New', severity=None,
            description='Unknown issue',
        )
        result = status_service.compute_equipment_status(equipment.id)
        assert result['color'] == 'yellow'
        assert result['label'] == 'Degraded'
        assert result['issue_description'] == 'Unknown issue'
        assert result['severity'] is None

    def test_eta_none_when_no_open_records(self, app, make_equipment):
        equipment = make_equipment()
        result = status_service.compute_equipment_status(equipment.id)
        assert result['eta'] is None

    def test_eta_returned_with_down_severity(self, app, make_equipment, make_repair_record):
        from datetime import date
        equipment = make_equipment()
        make_repair_record(
            equipment=equipment, status='New', severity='Down',
            description='broken', eta=date(2026, 6, 1),
        )
        result = status_service.compute_equipment_status(equipment.id)
        assert result['eta'] == date(2026, 6, 1)

    def test_eta_from_highest_severity_record(self, app, make_equipment, make_repair_record):
        from datetime import date
        equipment = make_equipment()
        make_repair_record(
            equipment=equipment, status='New', severity='Degraded',
            description='lower', eta=date(2026, 7, 1),
        )
        make_repair_record(
            equipment=equipment, status='New', severity='Down',
            description='higher', eta=date(2026, 5, 1),
        )
        result = status_service.compute_equipment_status(equipment.id)
        assert result['eta'] == date(2026, 5, 1)

    def test_eta_none_when_record_has_no_eta(self, app, make_equipment, make_repair_record):
        equipment = make_equipment()
        make_repair_record(
            equipment=equipment, status='New', severity='Down',
            description='broken', eta=None,
        )
        result = status_service.compute_equipment_status(equipment.id)
        assert result['eta'] is None

    def test_eta_fallback_when_no_severity_match(self, app, make_equipment, make_repair_record):
        from datetime import date
        equipment = make_equipment()
        make_repair_record(
            equipment=equipment, status='New', severity=None,
            description='unknown', eta=date(2026, 8, 1),
        )
        result = status_service.compute_equipment_status(equipment.id)
        assert result['eta'] == date(2026, 8, 1)

    def test_eta_tie_break_oldest_wins(self, app, make_equipment, make_repair_record):
        from datetime import date, datetime
        equipment = make_equipment()
        # Older Down record with eta=2026-05-01, newer Down record with eta=2026-08-01.
        make_repair_record(
            equipment=equipment, status='New', severity='Down',
            description='older', eta=date(2026, 5, 1),
            created_at=datetime(2026, 1, 1),
        )
        make_repair_record(
            equipment=equipment, status='New', severity='Down',
            description='newer', eta=date(2026, 8, 1),
            created_at=datetime(2026, 2, 1),
        )
        result = status_service.compute_equipment_status(equipment.id)
        assert result['eta'] == date(2026, 5, 1)


class TestGetAreaStatusDashboard:
    """Tests for get_area_status_dashboard()."""

    def test_returns_areas_with_equipment_and_statuses(
        self, app, make_area, make_equipment, make_repair_record,
    ):
        """Returns areas with equipment and computed statuses."""
        from datetime import date
        area = make_area(name='Workshop')
        equip = make_equipment(name='Lathe', area=area)
        make_repair_record(
            equipment=equip, status='New', severity='Down',
            description='Spindle broken', eta=date(2026, 6, 15),
        )

        result = status_service.get_area_status_dashboard()
        assert len(result) == 1
        assert result[0]['area'].name == 'Workshop'
        assert len(result[0]['equipment']) == 1
        assert result[0]['equipment'][0]['equipment'].name == 'Lathe'
        assert result[0]['equipment'][0]['status']['color'] == 'red'
        assert result[0]['equipment'][0]['status']['label'] == 'Down'
        assert result[0]['equipment'][0]['status']['issue_description'] == 'Spindle broken'
        assert result[0]['equipment'][0]['status']['eta'] == date(2026, 6, 15)

    def test_eta_none_when_no_open_records(self, app, make_area, make_equipment):
        area = make_area(name='Lab')
        make_equipment(name='Microscope', area=area)
        result = status_service.get_area_status_dashboard()
        assert result[0]['equipment'][0]['status']['eta'] is None

    def test_archived_equipment_excluded(self, app, make_area, make_equipment):
        """Archived equipment is not included in dashboard."""
        area = make_area(name='Shop')
        make_equipment(name='Active Tool', area=area)
        make_equipment(name='Old Tool', area=area, is_archived=True)

        result = status_service.get_area_status_dashboard()
        assert len(result) == 1
        equip_names = [e['equipment'].name for e in result[0]['equipment']]
        assert 'Active Tool' in equip_names
        assert 'Old Tool' not in equip_names

    def test_archived_areas_excluded(self, app, make_area, make_equipment):
        """Archived areas are not included in dashboard."""
        make_area(name='Active Area')
        from esb.models.area import Area
        from esb.extensions import db as _db
        archived = Area(name='Old Area', is_archived=True)
        _db.session.add(archived)
        _db.session.commit()
        make_equipment(name='Tool', area=archived)

        result = status_service.get_area_status_dashboard()
        area_names = [r['area'].name for r in result]
        assert 'Active Area' in area_names
        assert 'Old Area' not in area_names

    def test_empty_dashboard(self, app):
        """Returns empty list when no areas exist."""
        result = status_service.get_area_status_dashboard()
        assert result == []

    def test_green_equipment_no_open_records(self, app, make_area, make_equipment):
        """Equipment with no open records shows green/Operational."""
        area = make_area(name='Lab')
        make_equipment(name='Microscope', area=area)

        result = status_service.get_area_status_dashboard()
        assert len(result) == 1
        status = result[0]['equipment'][0]['status']
        assert status['color'] == 'green'
        assert status['label'] == 'Operational'

    def test_multiple_areas_sorted_by_name(self, app, make_area, make_equipment):
        """Areas are returned sorted by name."""
        make_area(name='Woodshop')
        make_area(name='Electronics Lab')
        make_area(name='Metal Shop')

        result = status_service.get_area_status_dashboard()
        area_names = [r['area'].name for r in result]
        assert area_names == ['Electronics Lab', 'Metal Shop', 'Woodshop']


class TestGetEquipmentStatusDetail:
    """Tests for get_equipment_status_detail()."""

    def test_green_no_open_records(self, app, make_equipment):
        """Green equipment returns None eta/assignee."""
        equipment = make_equipment()
        result = status_service.get_equipment_status_detail(equipment.id)
        assert result['color'] == 'green'
        assert result['label'] == 'Operational'
        assert result['eta'] is None
        assert result['assignee_name'] is None

    def test_down_with_eta(self, app, make_equipment, make_repair_record):
        """Down status includes eta from repair record."""
        from datetime import date
        equipment = make_equipment()
        make_repair_record(
            equipment=equipment, status='New', severity='Down',
            description='Motor burned out', eta=date(2026, 2, 20),
        )
        result = status_service.get_equipment_status_detail(equipment.id)
        assert result['color'] == 'red'
        assert result['label'] == 'Down'
        assert result['eta'] == date(2026, 2, 20)

    def test_down_with_assignee(self, app, make_equipment, make_repair_record):
        """Down status includes assignee_name."""
        from tests.conftest import _create_user
        tech = _create_user('technician', username='marcus')
        equipment = make_equipment()
        make_repair_record(
            equipment=equipment, status='Assigned', severity='Down',
            description='Motor issue', assignee_id=tech.id,
        )
        result = status_service.get_equipment_status_detail(equipment.id)
        assert result['color'] == 'red'
        assert result['assignee_name'] == 'marcus'

    def test_not_found(self, app):
        """Raises EquipmentNotFound for nonexistent equipment ID."""
        with pytest.raises(EquipmentNotFound):
            status_service.get_equipment_status_detail(99999)

    def test_multiple_records_highest_severity(self, app, make_equipment, make_repair_record):
        """Returns data from highest-severity record."""
        from datetime import date
        from tests.conftest import _create_user
        tech = _create_user('technician', username='techuser')
        equipment = make_equipment()
        make_repair_record(
            equipment=equipment, status='New', severity='Degraded',
            description='Minor issue', eta=date(2026, 3, 1),
        )
        make_repair_record(
            equipment=equipment, status='Assigned', severity='Down',
            description='Critical failure', eta=date(2026, 2, 20),
            assignee_id=tech.id,
        )
        result = status_service.get_equipment_status_detail(equipment.id)
        assert result['color'] == 'red'
        assert result['label'] == 'Down'
        assert result['issue_description'] == 'Critical failure'
        assert result['eta'] == date(2026, 2, 20)
        assert result['assignee_name'] == 'techuser'

    def test_returns_exact_key_set_with_open_record(
        self, app, make_equipment, make_repair_record,
    ):
        from datetime import date
        eq = make_equipment()
        make_repair_record(
            equipment=eq, status='New', severity='Down',
            description='x', eta=date(2026, 6, 15),
        )
        result = status_service.get_equipment_status_detail(eq.id)
        assert set(result.keys()) == {
            'color', 'label', 'issue_description', 'severity', 'eta', 'assignee_name',
        }

    def test_returns_exact_key_set_when_operational(self, app, make_equipment):
        # Equipment with no open records exercises the green/empty path.
        eq = make_equipment()
        result = status_service.get_equipment_status_detail(eq.id)
        assert set(result.keys()) == {
            'color', 'label', 'issue_description', 'severity', 'eta', 'assignee_name',
        }


class TestGetSingleAreaStatusDashboard:
    """Tests for get_single_area_status_dashboard()."""

    def test_returns_area_with_equipment_and_statuses(
        self, app, make_area, make_equipment, make_repair_record,
    ):
        """Returns the single area with equipment and computed statuses."""
        from datetime import date
        area = make_area(name='Wood Shop')
        equip = make_equipment(name='Lathe', area=area)
        make_repair_record(
            equipment=equip, status='New', severity='Down',
            description='Spindle broken', eta=date(2026, 6, 15),
        )

        result = status_service.get_single_area_status_dashboard(area.id)
        assert result['area'].id == area.id
        assert result['area'].name == 'Wood Shop'
        assert len(result['equipment']) == 1
        assert result['equipment'][0]['equipment'].name == 'Lathe'
        assert result['equipment'][0]['status']['color'] == 'red'
        assert result['equipment'][0]['status']['label'] == 'Down'
        assert result['equipment'][0]['status']['issue_description'] == 'Spindle broken'
        assert result['equipment'][0]['status']['eta'] == date(2026, 6, 15)

    def test_eta_present_for_degraded_equipment(
        self, app, make_area, make_equipment, make_repair_record,
    ):
        from datetime import date
        area = make_area(name='Lab')
        equip = make_equipment(name='Scope', area=area)
        make_repair_record(
            equipment=equip, status='New', severity='Degraded',
            description='flickering', eta=date(2026, 9, 1),
        )
        result = status_service.get_single_area_status_dashboard(area.id)
        assert result['equipment'][0]['status']['eta'] == date(2026, 9, 1)

    def test_raises_area_not_found_for_missing_id(self, app):
        """Raises AreaNotFound (not AreaArchived) for nonexistent area id."""
        with pytest.raises(AreaNotFound) as exc_info:
            status_service.get_single_area_status_dashboard(999999)
        assert type(exc_info.value) is AreaNotFound

    def test_raises_area_archived_for_archived_area(self, app, make_area):
        """Raises AreaArchived (subclass of AreaNotFound) for archived area."""
        from esb.extensions import db
        area = make_area(name='Old Wing')
        area.is_archived = True
        db.session.commit()

        with pytest.raises(AreaArchived) as exc_info:
            status_service.get_single_area_status_dashboard(area.id)
        assert type(exc_info.value) is AreaArchived

        # Subclass relationship: also catchable as AreaNotFound
        with pytest.raises(AreaNotFound):
            status_service.get_single_area_status_dashboard(area.id)

    def test_excludes_archived_equipment_in_area(
        self, app, make_area, make_equipment,
    ):
        """Archived equipment is not included in the per-area result."""
        area = make_area(name='Shop')
        make_equipment(name='Active Tool', area=area)
        make_equipment(name='Old Tool', area=area, is_archived=True)

        result = status_service.get_single_area_status_dashboard(area.id)
        names = [e['equipment'].name for e in result['equipment']]
        assert 'Active Tool' in names
        assert 'Old Tool' not in names

    def test_returns_empty_equipment_list_when_no_equipment(self, app, make_area):
        """Area with no equipment returns an empty equipment list."""
        area = make_area(name='Empty Room')
        result = status_service.get_single_area_status_dashboard(area.id)
        assert result['area'].id == area.id
        assert result['equipment'] == []

    def test_status_derivation_matches_repair_records(
        self, app, make_area, make_equipment, make_repair_record,
    ):
        """Status colors derive correctly: green / yellow / red."""
        area = make_area(name='Shop')
        green_eq = make_equipment(name='Good Tool', area=area)
        yellow_eq = make_equipment(name='Iffy Tool', area=area)
        red_eq = make_equipment(name='Broken Tool', area=area)
        make_repair_record(equipment=yellow_eq, status='New', severity='Degraded')
        make_repair_record(equipment=red_eq, status='New', severity='Down')

        result = status_service.get_single_area_status_dashboard(area.id)
        by_id = {e['equipment'].id: e['status']['color'] for e in result['equipment']}
        assert by_id[green_eq.id] == 'green'
        assert by_id[yellow_eq.id] == 'yellow'
        assert by_id[red_eq.id] == 'red'
