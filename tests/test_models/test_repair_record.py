"""Tests for RepairRecord model."""

from esb.extensions import db as _db
from esb.models.repair_record import REPAIR_SEVERITIES, REPAIR_STATUSES, RepairRecord


class TestRepairRecordCreation:
    """Tests for RepairRecord model creation and fields."""

    def test_create_with_required_fields(self, app, make_area, make_equipment):
        """RepairRecord created with required fields has correct values."""
        area = make_area()
        eq = make_equipment('Test Printer', area=area)
        record = RepairRecord(
            equipment_id=eq.id,
            description='Motor is making grinding noise',
        )
        _db.session.add(record)
        _db.session.commit()
        assert record.id is not None
        assert record.equipment_id == eq.id
        assert record.description == 'Motor is making grinding noise'

    def test_default_status_is_new(self, app, make_equipment):
        """Default status is 'New'."""
        eq = make_equipment()
        record = RepairRecord(equipment_id=eq.id, description='Broken')
        _db.session.add(record)
        _db.session.commit()
        assert record.status == 'New'

    def test_default_has_safety_risk_is_false(self, app, make_equipment):
        """Default has_safety_risk is False."""
        eq = make_equipment()
        record = RepairRecord(equipment_id=eq.id, description='Broken')
        _db.session.add(record)
        _db.session.commit()
        assert record.has_safety_risk is False

    def test_default_is_consumable_is_false(self, app, make_equipment):
        """Default is_consumable is False."""
        eq = make_equipment()
        record = RepairRecord(equipment_id=eq.id, description='Broken')
        _db.session.add(record)
        _db.session.commit()
        assert record.is_consumable is False

    def test_timestamps_auto_set(self, app, make_equipment):
        """created_at and updated_at are set automatically."""
        eq = make_equipment()
        record = RepairRecord(equipment_id=eq.id, description='Broken')
        _db.session.add(record)
        _db.session.commit()
        assert record.created_at is not None
        assert record.updated_at is not None

    def test_optional_fields_default_to_none(self, app, make_equipment):
        """Optional fields default to None when not provided."""
        eq = make_equipment()
        record = RepairRecord(equipment_id=eq.id, description='Broken')
        _db.session.add(record)
        _db.session.commit()
        assert record.severity is None
        assert record.reporter_name is None
        assert record.reporter_email is None
        assert record.assignee_id is None
        assert record.eta is None
        assert record.specialist_description is None

    def test_equipment_relationship(self, app, make_equipment):
        """Equipment relationship returns the associated Equipment."""
        eq = make_equipment('Laser Cutter')
        record = RepairRecord(equipment_id=eq.id, description='Broken')
        _db.session.add(record)
        _db.session.commit()
        assert record.equipment.name == 'Laser Cutter'

    def test_assignee_relationship(self, app, make_equipment, staff_user):
        """Assignee relationship returns the associated User when set."""
        eq = make_equipment()
        record = RepairRecord(
            equipment_id=eq.id, description='Broken', assignee_id=staff_user.id,
        )
        _db.session.add(record)
        _db.session.commit()
        assert record.assignee.username == 'staffuser'

    def test_assignee_nullable(self, app, make_equipment):
        """Assignee can be None (unassigned)."""
        eq = make_equipment()
        record = RepairRecord(equipment_id=eq.id, description='Broken')
        _db.session.add(record)
        _db.session.commit()
        assert record.assignee is None

    def test_repr(self, app, make_equipment):
        """__repr__ includes id and status."""
        eq = make_equipment()
        record = RepairRecord(equipment_id=eq.id, description='Broken')
        _db.session.add(record)
        _db.session.commit()
        assert repr(record) == f'<RepairRecord {record.id} [New]>'


class TestDuplicatedRepair:
    """Tests for the duplicated_repair_id column and self-relationship."""

    def test_duplicated_repair_id_nullable(self, app, make_equipment):
        eq = make_equipment()
        record = RepairRecord(equipment_id=eq.id, description='Broken')
        _db.session.add(record)
        _db.session.commit()
        assert record.duplicated_repair_id is None
        assert record.duplicated_repair is None

    def test_duplicated_repair_relationship(self, app, make_equipment):
        eq = make_equipment()
        original = RepairRecord(equipment_id=eq.id, description='Original')
        _db.session.add(original)
        _db.session.commit()
        dup = RepairRecord(
            equipment_id=eq.id,
            description='Same thing again',
            duplicated_repair_id=original.id,
        )
        _db.session.add(dup)
        _db.session.commit()
        _db.session.expire_all()
        fetched = _db.session.get(RepairRecord, dup.id)
        assert fetched.duplicated_repair_id == original.id
        assert fetched.duplicated_repair.id == original.id
        assert fetched.duplicated_repair.description == 'Original'

    def test_on_delete_set_null(self, app, make_equipment):
        """Deleting the target nulls the child's duplicated_repair_id (ON DELETE SET NULL)."""
        eq = make_equipment()
        target = RepairRecord(equipment_id=eq.id, description='Target')
        _db.session.add(target)
        _db.session.commit()
        child = RepairRecord(
            equipment_id=eq.id,
            description='Child',
            duplicated_repair_id=target.id,
        )
        _db.session.add(child)
        _db.session.commit()
        child_id = child.id
        _db.session.delete(target)
        _db.session.commit()
        _db.session.expire_all()
        refetched = _db.session.get(RepairRecord, child_id)
        assert refetched is not None
        assert refetched.duplicated_repair_id is None


class TestRepairRecordConstants:
    """Tests for module-level constants."""

    def test_repair_statuses_defined(self):
        """REPAIR_STATUSES contains expected values."""
        assert 'New' in REPAIR_STATUSES
        assert 'Resolved' in REPAIR_STATUSES
        assert len(REPAIR_STATUSES) == 10

    def test_repair_severities_defined(self):
        """REPAIR_SEVERITIES contains expected values."""
        assert REPAIR_SEVERITIES == ['Down', 'Degraded', 'Not Sure']
