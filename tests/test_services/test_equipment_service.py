"""Tests for equipment service (area and equipment management)."""

import json
from datetime import date
from decimal import Decimal

import pytest

from esb.extensions import db as _db
from esb.models.area import Area
from esb.models.equipment import Equipment
from esb.utils.exceptions import ValidationError


class TestListAreas:
    """Tests for equipment_service.list_areas()."""

    def test_returns_active_areas_ordered(self, app, make_area):
        """list_areas() returns active areas ordered by name."""
        from esb.services.equipment_service import list_areas

        make_area('Woodshop', '#woodshop')
        make_area('Electronics Lab', '#electronics')
        make_area('Metal Shop', '#metal')

        areas = list_areas()
        assert len(areas) == 3
        names = [a.name for a in areas]
        assert names == ['Electronics Lab', 'Metal Shop', 'Woodshop']

    def test_excludes_archived_areas(self, app, make_area):
        """list_areas() excludes archived areas."""
        from esb.services.equipment_service import list_areas

        make_area('Active Area', '#active')
        archived = make_area('Archived Area', '#archived')
        archived.is_archived = True
        _db.session.commit()

        areas = list_areas()
        assert len(areas) == 1
        assert areas[0].name == 'Active Area'

    def test_returns_empty_list_when_no_areas(self, app):
        """list_areas() returns empty list when no areas exist."""
        from esb.services.equipment_service import list_areas

        areas = list_areas()
        assert areas == []


class TestGetArea:
    """Tests for equipment_service.get_area()."""

    def test_returns_area_by_id(self, app, make_area):
        """get_area() returns area when found."""
        from esb.services.equipment_service import get_area

        area = make_area('Woodshop', '#woodshop')
        result = get_area(area.id)
        assert result.name == 'Woodshop'


class TestGetAreaByName:
    """Tests for equipment_service.get_area_by_name()."""

    def test_exact_match_returns_area(self, app, make_area):
        from esb.services.equipment_service import get_area_by_name

        area = make_area('Woodshop', '#woodshop')
        result = get_area_by_name('Woodshop')
        assert result is not None
        assert result.id == area.id

    def test_case_insensitive_match(self, app, make_area):
        from esb.services.equipment_service import get_area_by_name

        area = make_area('Woodshop', '#woodshop')
        assert get_area_by_name('woodshop').id == area.id
        assert get_area_by_name('WOODSHOP').id == area.id
        assert get_area_by_name('WoOdShOp').id == area.id

    def test_whitespace_padded_input_matches(self, app, make_area):
        from esb.services.equipment_service import get_area_by_name

        area = make_area('Woodshop', '#woodshop')
        assert get_area_by_name('  Woodshop  ').id == area.id
        assert get_area_by_name('\tWoodshop\n').id == area.id

    def test_no_match_returns_none(self, app, make_area):
        from esb.services.equipment_service import get_area_by_name

        make_area('Woodshop', '#woodshop')
        assert get_area_by_name('Nonexistent') is None

    def test_empty_or_whitespace_input_returns_none(self, app, make_area):
        from esb.services.equipment_service import get_area_by_name

        make_area('Woodshop', '#woodshop')
        assert get_area_by_name('') is None
        assert get_area_by_name('   ') is None
        assert get_area_by_name(None) is None

    def test_archived_area_excluded(self, app, make_area):
        from esb.services.equipment_service import get_area_by_name

        archived = make_area('Old Lab', '#old')
        archived.is_archived = True
        _db.session.commit()
        assert get_area_by_name('Old Lab') is None

    def test_partial_match_does_not_match(self, app, make_area):
        """Partial-name input should NOT match (exact-name only)."""
        from esb.services.equipment_service import get_area_by_name

        make_area('Woodshop', '#woodshop')
        assert get_area_by_name('Wood') is None
        assert get_area_by_name('shop') is None

    def test_exact_match_picks_correct_area_when_multiple_exist(self, app, make_area):
        from esb.services.equipment_service import get_area_by_name

        make_area('Woodshop', '#woodshop')
        metal = make_area('Metal Shop', '#metal')
        result = get_area_by_name('Metal Shop')
        assert result is not None
        assert result.id == metal.id

    def test_raises_on_not_found(self, app):
        """get_area() raises ValidationError when area not found."""
        from esb.services.equipment_service import get_area

        with pytest.raises(ValidationError, match='not found'):
            get_area(99999)


class TestCreateArea:
    """Tests for equipment_service.create_area()."""

    def test_creates_area_with_valid_data(self, app):
        """create_area() creates an area and returns it."""
        from esb.services.equipment_service import create_area

        area = create_area('Woodshop', '#woodshop', 'staffuser')
        assert area.name == 'Woodshop'
        assert area.slack_channel == '#woodshop'
        assert area.is_archived is False
        assert area.id is not None

    def test_area_persisted_to_db(self, app):
        """Created area is saved to the database."""
        from esb.services.equipment_service import create_area

        create_area('Woodshop', '#woodshop', 'staffuser')
        found = _db.session.execute(
            _db.select(Area).filter_by(name='Woodshop')
        ).scalar_one_or_none()
        assert found is not None
        assert found.slack_channel == '#woodshop'

    def test_duplicate_name_raises(self, app):
        """create_area() raises ValidationError on duplicate name."""
        from esb.services.equipment_service import create_area

        create_area('Woodshop', '#woodshop', 'staffuser')
        with pytest.raises(ValidationError, match='already exists'):
            create_area('Woodshop', '#woodshop2', 'staffuser')

    def test_duplicate_name_case_insensitive(self, app):
        """create_area() rejects duplicate names case-insensitively."""
        from esb.services.equipment_service import create_area

        create_area('Woodshop', '#woodshop', 'staffuser')
        with pytest.raises(ValidationError, match='already exists'):
            create_area('woodshop', '#woodshop2', 'staffuser')

    def test_logs_area_created_mutation(self, app, capture):
        """create_area() logs an area.created mutation event."""
        from esb.services.equipment_service import create_area

        create_area('Woodshop', '#woodshop', 'staffuser')
        created_entries = [
            json.loads(r.message) for r in capture.records
            if 'area.created' in r.message
        ]
        assert len(created_entries) == 1
        entry = created_entries[0]
        assert entry['event'] == 'area.created'
        assert entry['user'] == 'staffuser'
        assert entry['data']['name'] == 'Woodshop'
        assert entry['data']['slack_channel'] == '#woodshop'
        assert 'id' in entry['data']

    def test_duplicate_archived_name_shows_archived_message(self, app, make_area):
        """create_area() shows specific message when conflict is with archived area."""
        from esb.services.equipment_service import create_area

        area = make_area('Woodshop', '#woodshop')
        area.is_archived = True
        _db.session.commit()

        with pytest.raises(ValidationError, match='archived area'):
            create_area('Woodshop', '#new', 'staffuser')


class TestUpdateArea:
    """Tests for equipment_service.update_area()."""

    def test_updates_area_successfully(self, app, make_area):
        """update_area() updates area fields."""
        from esb.services.equipment_service import update_area

        area = make_area('Old Name', '#old')
        result = update_area(area.id, 'New Name', '#new', 'staffuser')
        assert result.name == 'New Name'
        assert result.slack_channel == '#new'

    def test_update_persists_to_db(self, app, make_area):
        """Area update is persisted to database."""
        from esb.services.equipment_service import update_area

        area = make_area('Old Name', '#old')
        update_area(area.id, 'New Name', '#new', 'staffuser')
        found = _db.session.get(Area, area.id)
        assert found.name == 'New Name'
        assert found.slack_channel == '#new'

    def test_not_found_raises(self, app):
        """update_area() raises ValidationError when area not found."""
        from esb.services.equipment_service import update_area

        with pytest.raises(ValidationError, match='not found'):
            update_area(99999, 'Name', '#channel', 'staffuser')

    def test_name_conflict_raises(self, app, make_area):
        """update_area() raises ValidationError on name conflict with another area."""
        from esb.services.equipment_service import update_area

        make_area('Existing', '#existing')
        area = make_area('Other', '#other')
        with pytest.raises(ValidationError, match='already exists'):
            update_area(area.id, 'Existing', '#other', 'staffuser')

    def test_same_name_allowed(self, app, make_area):
        """update_area() allows keeping the same name."""
        from esb.services.equipment_service import update_area

        area = make_area('Keep Name', '#channel')
        result = update_area(area.id, 'Keep Name', '#new-channel', 'staffuser')
        assert result.name == 'Keep Name'
        assert result.slack_channel == '#new-channel'

    def test_logs_area_updated_mutation(self, app, capture, make_area):
        """update_area() logs an area.updated mutation event with changes."""
        from esb.services.equipment_service import update_area

        area = make_area('Old Name', '#old')
        update_area(area.id, 'New Name', '#new', 'staffuser')
        updated_entries = [
            json.loads(r.message) for r in capture.records
            if 'area.updated' in r.message
        ]
        assert len(updated_entries) == 1
        entry = updated_entries[0]
        assert entry['event'] == 'area.updated'
        assert entry['user'] == 'staffuser'
        assert entry['data']['name'] == 'New Name'
        assert entry['data']['changes']['name'] == ['Old Name', 'New Name']
        assert entry['data']['changes']['slack_channel'] == ['#old', '#new']

    def test_no_log_when_no_changes(self, app, capture, make_area):
        """update_area() skips mutation log when nothing changed."""
        from esb.services.equipment_service import update_area

        area = make_area('Same', '#same')
        capture.records.clear()
        update_area(area.id, 'Same', '#same', 'staffuser')
        updated_entries = [
            json.loads(r.message) for r in capture.records
            if 'area.updated' in r.message
        ]
        assert len(updated_entries) == 0

    def test_name_conflict_with_archived_shows_archived_message(self, app, make_area):
        """update_area() shows specific message when conflict is with archived area."""
        from esb.services.equipment_service import update_area

        archived = make_area('Taken Name', '#old')
        archived.is_archived = True
        _db.session.commit()
        area = make_area('Current', '#current')

        with pytest.raises(ValidationError, match='archived area'):
            update_area(area.id, 'Taken Name', '#current', 'staffuser')


class TestArchiveArea:
    """Tests for equipment_service.archive_area()."""

    def test_archives_area_successfully(self, app, make_area):
        """archive_area() sets is_archived to True."""
        from esb.services.equipment_service import archive_area

        area = make_area('Woodshop', '#woodshop')
        result = archive_area(area.id, 'staffuser')
        assert result.is_archived is True

    def test_archive_persists_to_db(self, app, make_area):
        """Archive is persisted to database."""
        from esb.services.equipment_service import archive_area

        area = make_area('Woodshop', '#woodshop')
        archive_area(area.id, 'staffuser')
        found = _db.session.get(Area, area.id)
        assert found.is_archived is True

    def test_not_found_raises(self, app):
        """archive_area() raises ValidationError when area not found."""
        from esb.services.equipment_service import archive_area

        with pytest.raises(ValidationError, match='not found'):
            archive_area(99999, 'staffuser')

    def test_already_archived_raises(self, app, make_area):
        """archive_area() raises ValidationError when area already archived."""
        from esb.services.equipment_service import archive_area

        area = make_area('Woodshop', '#woodshop')
        area.is_archived = True
        _db.session.commit()

        with pytest.raises(ValidationError, match='already archived'):
            archive_area(area.id, 'staffuser')

    def test_logs_area_archived_mutation(self, app, capture, make_area):
        """archive_area() logs an area.archived mutation event."""
        from esb.services.equipment_service import archive_area

        area = make_area('Woodshop', '#woodshop')
        archive_area(area.id, 'staffuser')
        archived_entries = [
            json.loads(r.message) for r in capture.records
            if 'area.archived' in r.message
        ]
        assert len(archived_entries) == 1
        entry = archived_entries[0]
        assert entry['event'] == 'area.archived'
        assert entry['user'] == 'staffuser'
        assert entry['data']['id'] == area.id
        assert entry['data']['name'] == 'Woodshop'


class TestArchiveEquipment:
    """Tests for equipment_service.archive_equipment()."""

    def test_archives_equipment_successfully(self, app, make_equipment):
        """archive_equipment() sets is_archived to True."""
        from esb.services.equipment_service import archive_equipment

        eq = make_equipment('Laser', 'Epilog', 'Zing')
        result = archive_equipment(eq.id, 'staffuser')
        assert result.is_archived is True

    def test_archive_persists_to_db(self, app, make_equipment):
        """Archive is persisted to database."""
        from esb.services.equipment_service import archive_equipment

        eq = make_equipment('Laser', 'Epilog', 'Zing')
        archive_equipment(eq.id, 'staffuser')
        found = _db.session.get(Equipment, eq.id)
        assert found.is_archived is True

    def test_not_found_raises(self, app):
        """archive_equipment() raises ValidationError when equipment not found."""
        from esb.services.equipment_service import archive_equipment

        with pytest.raises(ValidationError, match='not found'):
            archive_equipment(99999, 'staffuser')

    def test_already_archived_raises(self, app, make_equipment):
        """archive_equipment() raises ValidationError when already archived."""
        from esb.services.equipment_service import archive_equipment

        eq = make_equipment('Laser', 'Epilog', 'Zing')
        eq.is_archived = True
        _db.session.commit()

        with pytest.raises(ValidationError, match='already archived'):
            archive_equipment(eq.id, 'staffuser')

    def test_logs_equipment_archived_mutation(self, app, capture, make_equipment):
        """archive_equipment() logs an equipment.archived mutation event."""
        from esb.services.equipment_service import archive_equipment

        eq = make_equipment('Laser', 'Epilog', 'Zing')
        capture.records.clear()
        archive_equipment(eq.id, 'staffuser')
        entries = [
            json.loads(r.message) for r in capture.records
            if 'equipment.archived' in r.message
        ]
        assert len(entries) == 1
        entry = entries[0]
        assert entry['event'] == 'equipment.archived'
        assert entry['user'] == 'staffuser'
        assert entry['data']['id'] == eq.id
        assert entry['data']['name'] == 'Laser'

    def test_archived_equipment_excluded_from_list(self, app, make_area, make_equipment):
        """Archived equipment is excluded from list_equipment()."""
        from esb.services.equipment_service import archive_equipment, list_equipment

        area = make_area('Shop', '#shop')
        eq = make_equipment('Laser', 'Epilog', 'Zing', area=area)
        make_equipment('CNC', 'ShopBot', 'Desktop', area=area)
        archive_equipment(eq.id, 'staffuser')

        result = list_equipment()
        assert len(result) == 1
        assert result[0].name == 'CNC'


# --- Equipment Service Tests ---


class TestListEquipment:
    """Tests for equipment_service.list_equipment()."""

    def test_returns_active_equipment(self, app, make_area, make_equipment):
        """list_equipment() returns active (non-archived) equipment."""
        from esb.services.equipment_service import list_equipment

        area = make_area('Woodshop', '#wood')
        make_equipment('Laser', 'Epilog', 'Zing', area=area)
        make_equipment('CNC', 'ShopBot', 'Desktop', area=area)

        result = list_equipment()
        assert len(result) == 2

    def test_excludes_archived_equipment(self, app, make_area, make_equipment):
        """list_equipment() excludes archived equipment."""
        from esb.services.equipment_service import list_equipment

        area = make_area('Woodshop', '#wood')
        make_equipment('Active', 'MakerCo', 'A1', area=area)
        eq = make_equipment('Archived', 'OldCo', 'B1', area=area)
        eq.is_archived = True
        _db.session.commit()

        result = list_equipment()
        assert len(result) == 1
        assert result[0].name == 'Active'

    def test_filters_by_area(self, app, make_area, make_equipment):
        """list_equipment(area_id) returns only equipment in that area."""
        from esb.services.equipment_service import list_equipment

        area1 = make_area('Woodshop', '#wood')
        area2 = make_area('Metal Shop', '#metal')
        make_equipment('Table Saw', 'SawStop', 'PCS', area=area1)
        make_equipment('Welder', 'Lincoln', '210MP', area=area2)

        result = list_equipment(area_id=area1.id)
        assert len(result) == 1
        assert result[0].name == 'Table Saw'

    def test_returns_empty_list_when_no_equipment(self, app):
        """list_equipment() returns empty list when no equipment exists."""
        from esb.services.equipment_service import list_equipment

        result = list_equipment()
        assert result == []


class TestGetEquipment:
    """Tests for equipment_service.get_equipment()."""

    def test_returns_equipment_by_id(self, app, make_equipment):
        """get_equipment() returns equipment when found."""
        from esb.services.equipment_service import get_equipment

        eq = make_equipment('Laser', 'Epilog', 'Zing')
        result = get_equipment(eq.id)
        assert result.name == 'Laser'

    def test_raises_on_not_found(self, app):
        """get_equipment() raises ValidationError when equipment not found."""
        from esb.services.equipment_service import get_equipment

        with pytest.raises(ValidationError, match='not found'):
            get_equipment(99999)


class TestCreateEquipment:
    """Tests for equipment_service.create_equipment()."""

    def test_creates_equipment_with_required_fields(self, app, make_area):
        """create_equipment() creates equipment and returns it."""
        from esb.services.equipment_service import create_equipment

        area = make_area('Woodshop', '#wood')
        eq = create_equipment(
            name='Table Saw', manufacturer='SawStop', model='PCS',
            area_id=area.id, created_by='staffuser',
        )
        assert eq.name == 'Table Saw'
        assert eq.manufacturer == 'SawStop'
        assert eq.model == 'PCS'
        assert eq.area_id == area.id
        assert eq.id is not None

    def test_creates_equipment_with_optional_fields(self, app, make_area):
        """create_equipment() stores optional fields."""
        from esb.services.equipment_service import create_equipment

        area = make_area('Woodshop', '#wood')
        eq = create_equipment(
            name='CNC', manufacturer='ShopBot', model='Desktop',
            area_id=area.id, created_by='staffuser',
            serial_number='SN-001',
            acquisition_date=date(2024, 1, 15),
            acquisition_source='Direct',
            acquisition_cost=Decimal('5000.00'),
            warranty_expiration=date(2026, 1, 15),
            description='A CNC router',
        )
        assert eq.serial_number == 'SN-001'
        assert eq.acquisition_date == date(2024, 1, 15)
        assert eq.acquisition_cost == Decimal('5000.00')
        assert eq.description == 'A CNC router'

    def test_invalid_area_raises(self, app):
        """create_equipment() raises ValidationError for invalid area_id."""
        from esb.services.equipment_service import create_equipment

        with pytest.raises(ValidationError, match='[Aa]rea'):
            create_equipment(
                name='Orphan', manufacturer='X', model='Y',
                area_id=99999, created_by='staffuser',
            )

    def test_archived_area_raises(self, app, make_area):
        """create_equipment() raises ValidationError for archived area."""
        from esb.services.equipment_service import create_equipment

        area = make_area('Old Shop', '#old')
        area.is_archived = True
        _db.session.commit()

        with pytest.raises(ValidationError, match='[Aa]rea'):
            create_equipment(
                name='Orphan', manufacturer='X', model='Y',
                area_id=area.id, created_by='staffuser',
            )

    def test_missing_name_raises(self, app, make_area):
        """create_equipment() raises ValidationError when name is empty."""
        from esb.services.equipment_service import create_equipment

        area = make_area('Shop', '#shop')
        with pytest.raises(ValidationError):
            create_equipment(
                name='', manufacturer='X', model='Y',
                area_id=area.id, created_by='staffuser',
            )

    def test_missing_manufacturer_raises(self, app, make_area):
        """create_equipment() raises ValidationError when manufacturer is empty."""
        from esb.services.equipment_service import create_equipment

        area = make_area('Shop', '#shop')
        with pytest.raises(ValidationError):
            create_equipment(
                name='Item', manufacturer='', model='Y',
                area_id=area.id, created_by='staffuser',
            )

    def test_missing_model_raises(self, app, make_area):
        """create_equipment() raises ValidationError when model is empty."""
        from esb.services.equipment_service import create_equipment

        area = make_area('Shop', '#shop')
        with pytest.raises(ValidationError):
            create_equipment(
                name='Item', manufacturer='X', model='',
                area_id=area.id, created_by='staffuser',
            )

    def test_logs_equipment_created_mutation(self, app, capture, make_area):
        """create_equipment() logs an equipment.created mutation event."""
        from esb.services.equipment_service import create_equipment

        area = make_area('Woodshop', '#wood')
        create_equipment(
            name='Table Saw', manufacturer='SawStop', model='PCS',
            area_id=area.id, created_by='staffuser',
        )
        created_entries = [
            json.loads(r.message) for r in capture.records
            if 'equipment.created' in r.message
        ]
        assert len(created_entries) == 1
        entry = created_entries[0]
        assert entry['event'] == 'equipment.created'
        assert entry['user'] == 'staffuser'
        assert entry['data']['name'] == 'Table Saw'
        assert entry['data']['manufacturer'] == 'SawStop'
        assert entry['data']['model'] == 'PCS'
        assert entry['data']['area_id'] == area.id
        assert 'id' in entry['data']

    def test_equipment_persisted_to_db(self, app, make_area):
        """Created equipment is saved to the database."""
        from esb.services.equipment_service import create_equipment

        area = make_area('Woodshop', '#wood')
        create_equipment(
            name='Drill Press', manufacturer='JET', model='JDP-17',
            area_id=area.id, created_by='staffuser',
        )
        found = _db.session.execute(
            _db.select(Equipment).filter_by(name='Drill Press')
        ).scalar_one_or_none()
        assert found is not None
        assert found.manufacturer == 'JET'


class TestUpdateEquipment:
    """Tests for equipment_service.update_equipment()."""

    def test_updates_equipment_successfully(self, app, make_equipment):
        """update_equipment() updates equipment fields."""
        from esb.services.equipment_service import update_equipment

        eq = make_equipment('Old Name', 'OldCo', 'OldModel')
        result = update_equipment(
            eq.id, updated_by='staffuser',
            name='New Name', manufacturer='NewCo',
        )
        assert result.name == 'New Name'
        assert result.manufacturer == 'NewCo'

    def test_update_persists_to_db(self, app, make_equipment):
        """Equipment update is persisted to database."""
        from esb.services.equipment_service import update_equipment

        eq = make_equipment('Old Name', 'OldCo', 'OldModel')
        update_equipment(eq.id, updated_by='staffuser', name='New Name')
        found = _db.session.get(Equipment, eq.id)
        assert found.name == 'New Name'

    def test_not_found_raises(self, app):
        """update_equipment() raises ValidationError when equipment not found."""
        from esb.services.equipment_service import update_equipment

        with pytest.raises(ValidationError, match='not found'):
            update_equipment(99999, updated_by='staffuser', name='X')

    def test_invalid_area_id_raises(self, app, make_equipment):
        """update_equipment() raises ValidationError for invalid area_id."""
        from esb.services.equipment_service import update_equipment

        eq = make_equipment('Item', 'Co', 'M')
        with pytest.raises(ValidationError, match='[Aa]rea'):
            update_equipment(eq.id, updated_by='staffuser', area_id=99999)

    def test_archived_area_id_raises(self, app, make_area, make_equipment):
        """update_equipment() raises ValidationError for archived area_id."""
        from esb.services.equipment_service import update_equipment

        eq = make_equipment('Item', 'Co', 'M')
        archived = make_area('Old Shop', '#old')
        archived.is_archived = True
        _db.session.commit()

        with pytest.raises(ValidationError, match='[Aa]rea'):
            update_equipment(eq.id, updated_by='staffuser', area_id=archived.id)

    def test_logs_equipment_updated_mutation(self, app, capture, make_equipment):
        """update_equipment() logs an equipment.updated mutation event with changes."""
        from esb.services.equipment_service import update_equipment

        eq = make_equipment('Old Name', 'OldCo', 'OldModel')
        capture.records.clear()
        update_equipment(eq.id, updated_by='staffuser', name='New Name')
        updated_entries = [
            json.loads(r.message) for r in capture.records
            if 'equipment.updated' in r.message
        ]
        assert len(updated_entries) == 1
        entry = updated_entries[0]
        assert entry['event'] == 'equipment.updated'
        assert entry['user'] == 'staffuser'
        assert entry['data']['name'] == 'New Name'
        assert entry['data']['changes']['name'] == ['Old Name', 'New Name']

    def test_no_log_when_no_changes(self, app, capture, make_equipment):
        """update_equipment() skips mutation log when nothing changed."""
        from esb.services.equipment_service import update_equipment

        eq = make_equipment('Same', 'SameCo', 'SameModel')
        capture.records.clear()
        update_equipment(eq.id, updated_by='staffuser')
        updated_entries = [
            json.loads(r.message) for r in capture.records
            if 'equipment.updated' in r.message
        ]
        assert len(updated_entries) == 0

    def test_update_optional_fields(self, app, make_equipment):
        """update_equipment() can update optional fields."""
        from esb.services.equipment_service import update_equipment

        eq = make_equipment('Item', 'Co', 'M')
        result = update_equipment(
            eq.id, updated_by='staffuser',
            serial_number='SN-NEW',
            description='Updated description',
        )
        assert result.serial_number == 'SN-NEW'
        assert result.description == 'Updated description'

    def test_empty_name_raises(self, app, make_equipment):
        """update_equipment() raises ValidationError when name set to empty."""
        from esb.services.equipment_service import update_equipment

        eq = make_equipment('Item', 'Co', 'M')
        with pytest.raises(ValidationError, match='Name is required'):
            update_equipment(eq.id, updated_by='staffuser', name='')

    def test_empty_manufacturer_raises(self, app, make_equipment):
        """update_equipment() raises ValidationError when manufacturer set to empty."""
        from esb.services.equipment_service import update_equipment

        eq = make_equipment('Item', 'Co', 'M')
        with pytest.raises(ValidationError, match='Manufacturer is required'):
            update_equipment(eq.id, updated_by='staffuser', manufacturer='')

    def test_empty_model_raises(self, app, make_equipment):
        """update_equipment() raises ValidationError when model set to empty."""
        from esb.services.equipment_service import update_equipment

        eq = make_equipment('Item', 'Co', 'M')
        with pytest.raises(ValidationError, match='Model is required'):
            update_equipment(eq.id, updated_by='staffuser', model='')

    def test_whitespace_only_name_raises(self, app, make_equipment):
        """update_equipment() raises ValidationError when name is whitespace only."""
        from esb.services.equipment_service import update_equipment

        eq = make_equipment('Item', 'Co', 'M')
        with pytest.raises(ValidationError, match='Name is required'):
            update_equipment(eq.id, updated_by='staffuser', name='   ')

    def test_mutation_log_serializes_date_fields(self, app, capture, make_equipment):
        """update_equipment() serializes date/Decimal in mutation log without crash."""
        from esb.services.equipment_service import update_equipment

        eq = make_equipment('Item', 'Co', 'M')
        capture.records.clear()
        update_equipment(
            eq.id, updated_by='staffuser',
            acquisition_date=date(2025, 6, 15),
            acquisition_cost=Decimal('1234.56'),
        )
        updated_entries = [
            json.loads(r.message) for r in capture.records
            if 'equipment.updated' in r.message
        ]
        assert len(updated_entries) == 1
        changes = updated_entries[0]['data']['changes']
        assert changes['acquisition_date'] == [None, '2025-06-15']
        assert changes['acquisition_cost'] == [None, '1234.56']


# --- External Link Service Tests ---


class TestAddEquipmentLink:
    """Tests for equipment_service.add_equipment_link()."""

    def test_add_link_success(self, app, make_equipment, capture):
        """add_equipment_link() creates link and returns it."""
        from esb.services.equipment_service import add_equipment_link

        eq = make_equipment('Laser', 'Epilog', 'Zing')
        link = add_equipment_link(eq.id, 'Manual', 'https://example.com/manual', 'staffuser')
        assert link.id is not None
        assert link.equipment_id == eq.id
        assert link.title == 'Manual'
        assert link.url == 'https://example.com/manual'
        assert link.created_by == 'staffuser'

    def test_add_link_strips_whitespace(self, app, make_equipment):
        """add_equipment_link() strips title and URL whitespace."""
        from esb.services.equipment_service import add_equipment_link

        eq = make_equipment()
        link = add_equipment_link(eq.id, '  Manual  ', '  https://example.com  ', 'staffuser')
        assert link.title == 'Manual'
        assert link.url == 'https://example.com'

    def test_add_link_invalid_equipment_raises(self, app):
        """add_equipment_link() raises ValidationError for invalid equipment_id."""
        from esb.services.equipment_service import add_equipment_link

        with pytest.raises(ValidationError, match='not found'):
            add_equipment_link(99999, 'Title', 'https://example.com', 'staffuser')

    def test_add_link_empty_title_raises(self, app, make_equipment):
        """add_equipment_link() raises ValidationError when title is empty."""
        from esb.services.equipment_service import add_equipment_link

        eq = make_equipment()
        with pytest.raises(ValidationError, match='Title is required'):
            add_equipment_link(eq.id, '', 'https://example.com', 'staffuser')

    def test_add_link_empty_url_raises(self, app, make_equipment):
        """add_equipment_link() raises ValidationError when URL is empty."""
        from esb.services.equipment_service import add_equipment_link

        eq = make_equipment()
        with pytest.raises(ValidationError, match='URL is required'):
            add_equipment_link(eq.id, 'Title', '', 'staffuser')

    def test_add_link_logs_mutation(self, app, capture, make_equipment):
        """add_equipment_link() logs an equipment_link.created mutation."""
        from esb.services.equipment_service import add_equipment_link

        eq = make_equipment()
        capture.records.clear()
        add_equipment_link(eq.id, 'Support', 'https://support.example.com', 'staffuser')
        entries = [
            json.loads(r.message) for r in capture.records
            if 'equipment_link.created' in r.message
        ]
        assert len(entries) == 1
        entry = entries[0]
        assert entry['event'] == 'equipment_link.created'
        assert entry['user'] == 'staffuser'
        assert entry['data']['title'] == 'Support'
        assert entry['data']['url'] == 'https://support.example.com'


class TestDeleteEquipmentLink:
    """Tests for equipment_service.delete_equipment_link()."""

    def test_delete_link_success(self, app, make_equipment, capture):
        """delete_equipment_link() removes link from database."""
        from esb.services.equipment_service import add_equipment_link, delete_equipment_link

        eq = make_equipment()
        link = add_equipment_link(eq.id, 'Link', 'https://example.com', 'staffuser')
        link_id = link.id
        capture.records.clear()

        delete_equipment_link(link_id, 'staffuser')

        from esb.models.external_link import ExternalLink
        assert _db.session.get(ExternalLink, link_id) is None

    def test_delete_link_not_found_raises(self, app):
        """delete_equipment_link() raises ValidationError when link not found."""
        from esb.services.equipment_service import delete_equipment_link

        with pytest.raises(ValidationError, match='not found'):
            delete_equipment_link(99999, 'staffuser')

    def test_delete_link_wrong_equipment_raises(self, app, make_equipment, make_area):
        """delete_equipment_link rejects if equipment_id doesn't match."""
        from esb.services.equipment_service import add_equipment_link, delete_equipment_link

        area = make_area('Shop', '#shop')
        eq1 = make_equipment('Eq1', 'Co', 'M', area=area)
        eq2 = make_equipment('Eq2', 'Co', 'M', area=area)
        link = add_equipment_link(eq1.id, 'Link', 'https://example.com', 'staffuser')

        with pytest.raises(ValidationError, match='not found'):
            delete_equipment_link(link.id, 'staffuser', equipment_id=eq2.id)

    def test_delete_link_logs_mutation(self, app, capture, make_equipment):
        """delete_equipment_link() logs an equipment_link.deleted mutation."""
        from esb.services.equipment_service import add_equipment_link, delete_equipment_link

        eq = make_equipment()
        link = add_equipment_link(eq.id, 'To Delete', 'https://example.com', 'staffuser')
        capture.records.clear()

        delete_equipment_link(link.id, 'staffuser')

        entries = [
            json.loads(r.message) for r in capture.records
            if 'equipment_link.deleted' in r.message
        ]
        assert len(entries) == 1
        entry = entries[0]
        assert entry['event'] == 'equipment_link.deleted'
        assert entry['data']['title'] == 'To Delete'


class TestGetEquipmentLinks:
    """Tests for equipment_service.get_equipment_links()."""

    def test_returns_links_for_equipment(self, app, make_equipment):
        """get_equipment_links() returns links for the given equipment."""
        from esb.services.equipment_service import add_equipment_link, get_equipment_links

        eq = make_equipment()
        add_equipment_link(eq.id, 'Link 1', 'https://example.com/1', 'staffuser')
        add_equipment_link(eq.id, 'Link 2', 'https://example.com/2', 'staffuser')

        result = get_equipment_links(eq.id)
        assert len(result) == 2

    def test_does_not_return_other_equipment_links(self, app, make_equipment, make_area):
        """get_equipment_links() only returns links for the specified equipment."""
        from esb.services.equipment_service import add_equipment_link, get_equipment_links

        area = make_area('Shop', '#shop')
        eq1 = make_equipment('Eq1', 'Co', 'M', area=area)
        eq2 = make_equipment('Eq2', 'Co', 'M', area=area)
        add_equipment_link(eq1.id, 'Link 1', 'https://example.com/1', 'staffuser')
        add_equipment_link(eq2.id, 'Link 2', 'https://example.com/2', 'staffuser')

        result = get_equipment_links(eq1.id)
        assert len(result) == 1
        assert result[0].title == 'Link 1'

    def test_returns_empty_list_when_none(self, app, make_equipment):
        """get_equipment_links() returns empty list when no links exist."""
        from esb.services.equipment_service import get_equipment_links

        eq = make_equipment()
        result = get_equipment_links(eq.id)
        assert result == []


class TestSearchEquipmentByName:
    """Tests for equipment_service.search_equipment_by_name()."""

    def test_exact_match(self, app, make_area, make_equipment):
        """search_equipment_by_name() returns equipment on exact name match."""
        from esb.services.equipment_service import search_equipment_by_name

        area = make_area('Woodshop', '#wood')
        make_equipment('SawStop', 'SawStop', 'PCS', area=area)

        result = search_equipment_by_name('SawStop')
        assert len(result) == 1
        assert result[0].name == 'SawStop'

    def test_partial_match(self, app, make_area, make_equipment):
        """search_equipment_by_name() returns equipment on partial name match."""
        from esb.services.equipment_service import search_equipment_by_name

        area = make_area('Woodshop', '#wood')
        make_equipment('SawStop #1', 'SawStop', 'PCS', area=area)

        result = search_equipment_by_name('Stop')
        assert len(result) == 1
        assert result[0].name == 'SawStop #1'

    def test_case_insensitive(self, app, make_area, make_equipment):
        """search_equipment_by_name() is case-insensitive."""
        from esb.services.equipment_service import search_equipment_by_name

        area = make_area('Woodshop', '#wood')
        make_equipment('SawStop', 'SawStop', 'PCS', area=area)

        result = search_equipment_by_name('sawstop')
        assert len(result) == 1
        assert result[0].name == 'SawStop'

    def test_multiple_matches(self, app, make_area, make_equipment):
        """search_equipment_by_name() returns all matching equipment."""
        from esb.services.equipment_service import search_equipment_by_name

        area = make_area('Woodshop', '#wood')
        make_equipment('Band Saw', 'Jet', 'JWBS', area=area)
        make_equipment('SawStop #1', 'SawStop', 'PCS', area=area)
        make_equipment('Scroll Saw', 'DeWalt', 'DW788', area=area)
        make_equipment('Drill Press', 'JET', 'JDP-17', area=area)

        result = search_equipment_by_name('Saw')
        assert len(result) == 3
        names = [e.name for e in result]
        assert names == ['Band Saw', 'SawStop #1', 'Scroll Saw']

    def test_no_match(self, app, make_area, make_equipment):
        """search_equipment_by_name() returns empty list when nothing matches."""
        from esb.services.equipment_service import search_equipment_by_name

        area = make_area('Woodshop', '#wood')
        make_equipment('SawStop', 'SawStop', 'PCS', area=area)

        result = search_equipment_by_name('Welder')
        assert result == []

    def test_excludes_archived(self, app, make_area, make_equipment):
        """search_equipment_by_name() excludes archived equipment."""
        from esb.services.equipment_service import search_equipment_by_name

        area = make_area('Woodshop', '#wood')
        make_equipment('Active Saw', 'SawStop', 'PCS', area=area)
        make_equipment('Archived Saw', 'OldCo', 'Old', area=area, is_archived=True)

        result = search_equipment_by_name('Saw')
        assert len(result) == 1
        assert result[0].name == 'Active Saw'

    def test_like_wildcards_escaped(self, app, make_area, make_equipment):
        """search_equipment_by_name() treats % and _ as literal characters."""
        from esb.services.equipment_service import search_equipment_by_name

        area = make_area('Woodshop', '#wood')
        make_equipment('SawStop', 'SawStop', 'PCS', area=area)
        make_equipment('Band Saw', 'Jet', 'JWBS', area=area)

        # '%' should not act as a wildcard matching everything
        result = search_equipment_by_name('%')
        assert result == []

        # '_' should not act as a single-char wildcard
        result = search_equipment_by_name('_')
        assert result == []


class TestExportEquipmentCsv:
    """Tests for equipment_service.export_equipment_csv(username='tester')."""

    def test_returns_header_only_when_empty(self, app):
        """Empty equipment set returns only the CSV header."""
        from esb.services.equipment_service import export_equipment_csv, CSV_EXPORT_COLUMNS

        csv_text = export_equipment_csv(username='tester')
        lines = csv_text.strip().splitlines()
        assert len(lines) == 1
        assert lines[0] == ','.join(CSV_EXPORT_COLUMNS)

    def test_header_column_order_is_stable(self, app, make_area, make_equipment):
        """Header row matches CSV_EXPORT_COLUMNS exactly, including order."""
        import csv as _csv
        import io as _io
        from esb.services.equipment_service import export_equipment_csv, CSV_EXPORT_COLUMNS

        area = make_area('Woodshop', '#wood')
        make_equipment('Table Saw', 'SawStop', 'PCS', area=area)

        reader = _csv.reader(_io.StringIO(export_equipment_csv(username='tester')))
        header = next(reader)
        assert header == CSV_EXPORT_COLUMNS

    def test_formula_injection_is_defused(self, app, make_area, make_equipment):
        """Fields starting with formula triggers are prefixed with a single quote."""
        import csv as _csv
        import io as _io
        from esb.services.equipment_service import export_equipment_csv

        area = make_area('Woodshop', '#wood')
        make_equipment(
            '=SUM(A1:A9)', 'SawStop', 'PCS', area=area,
            description='@cmd|/c calc',
            serial_number='+1234',
            acquisition_source='-bad',
        )
        rows = list(_csv.DictReader(_io.StringIO(export_equipment_csv(username='tester'))))
        row = rows[0]
        assert row['name'].startswith("'=")
        assert row['description'].startswith("'@")
        assert row['serial_number'].startswith("'+")
        assert row['acquisition_source'].startswith("'-")

    def test_formula_injection_defused_with_leading_whitespace(
        self, app, make_area, make_equipment,
    ):
        """Formula triggers preceded by whitespace are still defused."""
        import csv as _csv
        import io as _io
        from esb.services.equipment_service import export_equipment_csv

        area = make_area('Woodshop', '#wood')
        make_equipment(
            ' =SUM(A1:A9)', 'SawStop', 'PCS', area=area,
            description='\t=BAD()',
        )
        rows = list(_csv.DictReader(_io.StringIO(export_equipment_csv(username='tester'))))
        row = rows[0]
        # Original leading whitespace preserved, quote prepended
        assert row['name'] == "' =SUM(A1:A9)"
        assert row['description'].startswith("'")
        assert '=BAD()' in row['description']

    def test_export_is_audit_logged_by_service(
        self, app, make_area, make_equipment, capture,
    ):
        """Service emits equipment.exported_csv mutation with username/filters/row count."""
        import json as _json
        from esb.services.equipment_service import export_equipment_csv

        area = make_area('Woodshop', '#wood')
        make_equipment('Table Saw', 'SawStop', 'PCS', area=area)
        make_equipment('Drill Press', 'JET', 'JDP-17', area=area)
        capture.records.clear()

        export_equipment_csv(username='alice', area_id=area.id, include_archived=True)

        entries = [
            _json.loads(r.message) for r in capture.records
            if 'equipment.exported_csv' in r.message
        ]
        assert len(entries) == 1
        entry = entries[0]
        assert entry['user'] == 'alice'
        assert entry['data']['area_id'] == area.id
        assert entry['data']['include_archived'] is True
        assert entry['data']['row_count'] == 2

    def test_export_does_not_n_plus_one_on_area(
        self, app, make_area, make_equipment, db,
    ):
        """Area name is eager-loaded; export does not fire a query per row."""
        from sqlalchemy import event
        from esb.services.equipment_service import export_equipment_csv

        area = make_area('Woodshop', '#wood')
        for i in range(5):
            make_equipment(f'Item {i}', 'Co', 'M', area=area)

        # Detach loaded equipment/area instances so the export fires fresh queries.
        db.session.expire_all()

        query_count = 0

        def _count(conn, cursor, statement, params, context, executemany):
            nonlocal query_count
            query_count += 1

        engine = db.engine
        event.listen(engine, 'before_cursor_execute', _count)
        try:
            export_equipment_csv(username='tester')
        finally:
            event.remove(engine, 'before_cursor_execute', _count)

        # One SELECT for equipment + area (joinedload); no per-row lazy loads.
        assert query_count <= 2, f'expected eager-loaded export, saw {query_count} queries'

    def test_includes_all_active_equipment(self, app, make_area, make_equipment):
        """All non-archived equipment appears in export, ordered by name."""
        import csv as _csv
        import io as _io
        from esb.services.equipment_service import export_equipment_csv

        area = make_area('Woodshop', '#wood')
        make_equipment('Band Saw', 'Jet', 'JWBS', area=area)
        make_equipment('Table Saw', 'SawStop', 'PCS', area=area)
        make_equipment('Drill Press', 'JET', 'JDP-17', area=area)

        csv_text = export_equipment_csv(username='tester')
        reader = _csv.DictReader(_io.StringIO(csv_text))
        rows = list(reader)
        assert [r['name'] for r in rows] == ['Band Saw', 'Drill Press', 'Table Saw']

    def test_populates_all_relevant_fields(self, app, make_area, make_equipment):
        """Each required field is exported correctly."""
        import csv as _csv
        import io as _io
        from decimal import Decimal
        from datetime import date
        from esb.services.equipment_service import export_equipment_csv

        area = make_area('Woodshop', '#wood')
        make_equipment(
            'Table Saw', 'SawStop', 'PCS', area=area,
            serial_number='SN123',
            acquisition_date=date(2022, 5, 10),
            acquisition_source='Donation',
            acquisition_cost=Decimal('1234.56'),
            warranty_expiration=date(2025, 5, 10),
            description='Main table saw',
        )

        csv_text = export_equipment_csv(username='tester')
        rows = list(_csv.DictReader(_io.StringIO(csv_text)))
        assert len(rows) == 1
        row = rows[0]
        assert row['name'] == 'Table Saw'
        assert row['manufacturer'] == 'SawStop'
        assert row['model'] == 'PCS'
        assert row['serial_number'] == 'SN123'
        assert row['area'] == 'Woodshop'
        assert row['acquisition_date'] == '2022-05-10'
        assert row['acquisition_source'] == 'Donation'
        assert row['acquisition_cost'] == '1234.56'
        assert row['warranty_expiration'] == '2025-05-10'
        assert row['description'] == 'Main table saw'
        assert row['is_archived'] == 'false'
        assert row['created_at']
        assert row['updated_at']

    def test_null_fields_exported_as_empty(self, app, make_area, make_equipment):
        """None-valued optional fields are exported as empty strings."""
        import csv as _csv
        import io as _io
        from esb.services.equipment_service import export_equipment_csv

        area = make_area('Woodshop', '#wood')
        make_equipment('Basic Tool', 'Co', 'M1', area=area)

        rows = list(_csv.DictReader(_io.StringIO(export_equipment_csv(username='tester'))))
        row = rows[0]
        assert row['serial_number'] == ''
        assert row['acquisition_date'] == ''
        assert row['acquisition_source'] == ''
        assert row['acquisition_cost'] == ''
        assert row['warranty_expiration'] == ''
        assert row['description'] == ''

    def test_excludes_archived_by_default(self, app, make_area, make_equipment):
        """Archived equipment is not included unless requested."""
        import csv as _csv
        import io as _io
        from esb.services.equipment_service import export_equipment_csv

        area = make_area('Woodshop', '#wood')
        make_equipment('Active', 'Co', 'M', area=area)
        make_equipment('Retired', 'Co', 'M', area=area, is_archived=True)

        rows = list(_csv.DictReader(_io.StringIO(export_equipment_csv(username='tester'))))
        names = [r['name'] for r in rows]
        assert names == ['Active']

    def test_include_archived_option(self, app, make_area, make_equipment):
        """include_archived=True yields archived rows too."""
        import csv as _csv
        import io as _io
        from esb.services.equipment_service import export_equipment_csv

        area = make_area('Woodshop', '#wood')
        make_equipment('Active', 'Co', 'M', area=area)
        make_equipment('Retired', 'Co', 'M', area=area, is_archived=True)

        rows = list(_csv.DictReader(_io.StringIO(export_equipment_csv(username='tester', include_archived=True))))
        names = sorted(r['name'] for r in rows)
        assert names == ['Active', 'Retired']
        archived_row = next(r for r in rows if r['name'] == 'Retired')
        assert archived_row['is_archived'] == 'true'

    def test_area_filter(self, app, make_area, make_equipment):
        """area_id filter restricts output to equipment in that area."""
        import csv as _csv
        import io as _io
        from esb.services.equipment_service import export_equipment_csv

        wood = make_area('Woodshop', '#wood')
        metal = make_area('Metal Shop', '#metal')
        make_equipment('Table Saw', 'SawStop', 'PCS', area=wood)
        make_equipment('Welder', 'Lincoln', '210MP', area=metal)

        rows = list(_csv.DictReader(_io.StringIO(export_equipment_csv(username='tester', area_id=wood.id))))
        assert [r['name'] for r in rows] == ['Table Saw']

    def test_field_with_comma_is_quoted(self, app, make_area, make_equipment):
        """Fields containing commas are properly quoted."""
        from esb.services.equipment_service import export_equipment_csv

        area = make_area('Woodshop', '#wood')
        make_equipment(
            'Saw', 'Co', 'M', area=area,
            description='Model A, with stand',
        )
        csv_text = export_equipment_csv(username='tester')
        assert '"Model A, with stand"' in csv_text
