"""MachineActivityEvent model: append-only log of MAC webhook events.

Keyed by machine ``name`` (not an equipment FK) because events arrive before or
independently of an equipment link. Append-only (no ``updated_at``), capped per
machine by ``mac_service.prune_activity_events`` (driven by the worker poll, not
per-insert). The composite ``(machine_name, event_type, event_timestamp)`` index
supports the idempotency dedup lookup (F4).
"""

from datetime import UTC, datetime

from esb.extensions import db

# Webhook event strings emitted by MAC 0.15.0 (src/dm_mac/models/machine.py).
MAC_EVENT_TYPES = [
    'login', 'logout', 'unauthorized', 'unknown_fob', 'override_login',
    'oops', 'unoops', 'lockout', 'unlock', 'reboot',
]


class MachineActivityEvent(db.Model):
    """A single MAC status-change event, persisted from an inbound webhook."""

    __tablename__ = 'machine_activity_events'
    __table_args__ = (
        # UNIQUE so a concurrent duplicate delivery loses the INSERT race and is
        # rejected at the DB (the SELECT-then-INSERT dedup is only the fast path).
        db.Index(
            'ix_machine_activity_events_dedup',
            'machine_name', 'event_type', 'event_timestamp',
            unique=True,
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    machine_name = db.Column(db.String(200), nullable=False, index=True)
    event_type = db.Column(db.String(30), nullable=False)
    status = db.Column(db.String(20), nullable=True)
    user_account_id = db.Column(db.String(200), nullable=True)
    user_full_name = db.Column(db.String(200), nullable=True)
    # Converted from the webhook's epoch-seconds `timestamp` to a UTC datetime.
    event_timestamp = db.Column(db.DateTime, nullable=False)
    created_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(UTC),
    )
    raw_payload = db.Column(db.JSON, nullable=True)

    def __repr__(self):
        return f'<MachineActivityEvent {self.id} {self.machine_name!r} [{self.event_type}]>'
