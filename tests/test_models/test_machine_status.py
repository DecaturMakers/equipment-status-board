"""Tests for the MachineStatus cache model."""

from datetime import UTC, datetime

import pytest
from sqlalchemy.exc import IntegrityError

from esb.extensions import db
from esb.models.machine_status import MachineStatus


class TestMachineStatus:
    def test_create_and_repr(self, app):
        row = MachineStatus(machine_name='planer', status='idle')
        db.session.add(row)
        db.session.commit()
        assert row.id is not None
        assert 'planer' in repr(row)
        assert 'idle' in repr(row)

    def test_machine_name_unique(self, app):
        db.session.add(MachineStatus(machine_name='planer', status='idle'))
        db.session.commit()
        db.session.add(MachineStatus(machine_name='planer', status='oops'))
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()

    def test_datetime_columns_roundtrip_naive(self, app):
        # db.DateTime stores naive; an aware value comes back naive (F7).
        aware = datetime.now(UTC)
        row = MachineStatus(
            machine_name='lathe', status='in_use', last_checkin=aware,
        )
        db.session.add(row)
        db.session.commit()
        db.session.refresh(row)
        assert row.last_checkin.tzinfo is None
