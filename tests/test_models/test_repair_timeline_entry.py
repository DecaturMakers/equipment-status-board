"""Tests for RepairTimelineEntry model."""

from esb.extensions import db as _db
from esb.models.repair_record import RepairRecord
from esb.models.repair_timeline_entry import TIMELINE_ENTRY_TYPES, RepairTimelineEntry


class TestRepairTimelineEntryCreation:
    """Tests for RepairTimelineEntry model creation and fields."""

    def _make_record(self, equipment):
        record = RepairRecord(equipment_id=equipment.id, description='Test issue')
        _db.session.add(record)
        _db.session.commit()
        return record

    def test_create_with_required_fields(self, app, make_equipment):
        """Entry created with required fields has correct values."""
        eq = make_equipment()
        record = self._make_record(eq)
        entry = RepairTimelineEntry(
            repair_record_id=record.id,
            entry_type='creation',
        )
        _db.session.add(entry)
        _db.session.commit()
        assert entry.id is not None
        assert entry.repair_record_id == record.id
        assert entry.entry_type == 'creation'

    def test_optional_fields_nullable(self, app, make_equipment):
        """Optional fields default to None."""
        eq = make_equipment()
        record = self._make_record(eq)
        entry = RepairTimelineEntry(
            repair_record_id=record.id,
            entry_type='note',
        )
        _db.session.add(entry)
        _db.session.commit()
        assert entry.content is None
        assert entry.old_value is None
        assert entry.new_value is None
        assert entry.author_id is None
        assert entry.author_name is None

    def test_author_name_stored(self, app, make_equipment):
        """author_name is stored for anonymous reporters."""
        eq = make_equipment()
        record = self._make_record(eq)
        entry = RepairTimelineEntry(
            repair_record_id=record.id,
            entry_type='creation',
            author_name='John Doe',
        )
        _db.session.add(entry)
        _db.session.commit()
        assert entry.author_name == 'John Doe'

    def test_timestamp_auto_set(self, app, make_equipment):
        """created_at is set automatically."""
        eq = make_equipment()
        record = self._make_record(eq)
        entry = RepairTimelineEntry(
            repair_record_id=record.id,
            entry_type='creation',
        )
        _db.session.add(entry)
        _db.session.commit()
        assert entry.created_at is not None

    def test_repair_record_relationship(self, app, make_equipment):
        """Repair record relationship returns associated RepairRecord."""
        eq = make_equipment()
        record = self._make_record(eq)
        entry = RepairTimelineEntry(
            repair_record_id=record.id,
            entry_type='creation',
        )
        _db.session.add(entry)
        _db.session.commit()
        assert entry.repair_record.id == record.id

    def test_author_relationship(self, app, make_equipment, staff_user):
        """Author relationship returns User when author_id set."""
        eq = make_equipment()
        record = self._make_record(eq)
        entry = RepairTimelineEntry(
            repair_record_id=record.id,
            entry_type='note',
            author_id=staff_user.id,
        )
        _db.session.add(entry)
        _db.session.commit()
        assert entry.author.username == 'staffuser'

    def test_repr(self, app, make_equipment):
        """__repr__ includes id and entry_type."""
        eq = make_equipment()
        record = self._make_record(eq)
        entry = RepairTimelineEntry(
            repair_record_id=record.id,
            entry_type='status_change',
        )
        _db.session.add(entry)
        _db.session.commit()
        assert repr(entry) == f'<RepairTimelineEntry {entry.id} [status_change]>'


class TestTimelineEntryConstants:
    """Tests for module-level constants."""

    def test_entry_types_defined(self):
        """TIMELINE_ENTRY_TYPES contains expected values."""
        assert 'creation' in TIMELINE_ENTRY_TYPES
        assert 'note' in TIMELINE_ENTRY_TYPES
        assert 'status_change' in TIMELINE_ENTRY_TYPES
        assert 'duplicated_repair_id_change' in TIMELINE_ENTRY_TYPES
        assert len(TIMELINE_ENTRY_TYPES) == 7
