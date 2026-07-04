"""Tests for EquipmentNote model."""

from datetime import UTC, datetime

import pytest
from sqlalchemy.exc import IntegrityError

from esb.extensions import db as _db
from esb.models.equipment_note import EquipmentNote


class TestEquipmentNoteCreation:
    """Tests for EquipmentNote model creation and fields."""

    def test_create_note_with_all_fields(self, app, make_equipment):
        """EquipmentNote created with all fields has correct values."""
        equipment = make_equipment()
        note = EquipmentNote(
            equipment_id=equipment.id,
            content='Replaced the belt.',
            author_id=None,
            author_name='staffuser',
        )
        _db.session.add(note)
        _db.session.commit()
        assert note.id is not None
        assert note.equipment_id == equipment.id
        assert note.content == 'Replaced the belt.'
        assert note.author_name == 'staffuser'

    def test_created_at_set_automatically(self, app, make_equipment):
        """created_at is set automatically on creation."""
        equipment = make_equipment()
        note = EquipmentNote(
            equipment_id=equipment.id,
            content='A note',
            author_name='staffuser',
        )
        _db.session.add(note)
        _db.session.commit()
        assert note.created_at is not None

    def test_repr(self, app, make_equipment):
        """EquipmentNote __repr__ includes id."""
        equipment = make_equipment()
        note = EquipmentNote(
            equipment_id=equipment.id,
            content='A note',
            author_name='staffuser',
        )
        _db.session.add(note)
        _db.session.commit()
        assert repr(note) == f'<EquipmentNote {note.id}>'


class TestEquipmentNoteConstraints:
    """Tests for EquipmentNote model constraints and relationships."""

    def test_content_not_nullable(self, app, make_equipment):
        """content column rejects NULL."""
        equipment = make_equipment()
        note = EquipmentNote(
            equipment_id=equipment.id,
            author_name='staffuser',
        )
        _db.session.add(note)
        with pytest.raises(IntegrityError):
            _db.session.commit()
        _db.session.rollback()

    def test_equipment_relationship(self, app, make_equipment):
        """EquipmentNote.equipment relationship returns the associated Equipment."""
        equipment = make_equipment(name='Laser Cutter')
        note = EquipmentNote(
            equipment_id=equipment.id,
            content='A note',
            author_name='staffuser',
        )
        _db.session.add(note)
        _db.session.commit()
        assert note.equipment.name == 'Laser Cutter'

    def test_author_relationship_and_backref(self, app, make_equipment):
        """EquipmentNote.author and User.equipment_notes backref resolve."""
        from tests.conftest import _create_user

        user = _create_user('staff', 'noteauthor')
        equipment = make_equipment()
        note = EquipmentNote(
            equipment_id=equipment.id,
            content='A note',
            author_id=user.id,
            author_name=user.username,
        )
        _db.session.add(note)
        _db.session.commit()
        assert note.author.username == 'noteauthor'
        assert user.equipment_notes.count() == 1

    def test_equipment_notes_backref_newest_first(self, app, make_equipment):
        """Equipment.notes backref returns notes newest-first (created_at desc, id desc)."""
        equipment = make_equipment()
        shared_time = datetime(2026, 7, 3, 12, 0, 0, tzinfo=UTC)
        note1 = EquipmentNote(
            equipment_id=equipment.id, content='First', author_name='staffuser',
            created_at=shared_time,
        )
        note2 = EquipmentNote(
            equipment_id=equipment.id, content='Second', author_name='staffuser',
            created_at=shared_time,
        )
        _db.session.add_all([note1, note2])
        _db.session.commit()

        notes = equipment.notes.all()
        assert notes[0].id > notes[1].id
        assert notes[0].content == 'Second'
