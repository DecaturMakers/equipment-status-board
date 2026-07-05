"""Tests for the MachineActivityEvent append-only model."""

from datetime import UTC, datetime

from esb.extensions import db
from esb.models.machine_activity_event import MAC_EVENT_TYPES, MachineActivityEvent


class TestMachineActivityEvent:
    def test_append_and_repr(self, app):
        ts = datetime.now(UTC)
        event = MachineActivityEvent(
            machine_name='planer', event_type='oops', status='oops',
            event_timestamp=ts,
        )
        db.session.add(event)
        db.session.commit()
        assert event.id is not None
        assert 'planer' in repr(event)
        assert 'oops' in repr(event)

    def test_mac_event_types_complete(self):
        # Mirrors MAC 0.15.0's emitted event strings.
        assert 'oops' in MAC_EVENT_TYPES
        assert 'unoops' in MAC_EVENT_TYPES
        assert 'lockout' in MAC_EVENT_TYPES
        assert len(MAC_EVENT_TYPES) == 10

    def test_dedup_composite_query(self, app):
        ts = datetime(2026, 7, 1, 12, 0, 0)
        db.session.add(MachineActivityEvent(
            machine_name='planer', event_type='oops', event_timestamp=ts,
        ))
        db.session.commit()
        match = db.session.execute(
            db.select(MachineActivityEvent).filter_by(
                machine_name='planer', event_type='oops', event_timestamp=ts,
            )
        ).scalar_one_or_none()
        assert match is not None
