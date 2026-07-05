"""MachineStatus model: DB-backed cache of live MAC machine status.

One row per MAC machine, keyed by the unique ``machine_name``. Written by BOTH
the inbound webhook (web process) and the periodic worker poll, so the upsert in
``mac_service`` must be race-safe (see mac_service.upsert_machine_status).
"""

from datetime import UTC, datetime

from esb.extensions import db

# Valid MAC machine statuses (mirrors MAC 0.15.0 status decision tree).
MAC_MACHINE_STATUSES = ['in_use', 'idle', 'oops', 'locked_out', 'unknown']


class MachineStatus(db.Model):
    """Cached live status of a single MAC machine."""

    __tablename__ = 'machine_status'

    id = db.Column(db.Integer, primary_key=True)
    machine_name = db.Column(db.String(200), nullable=False, unique=True, index=True)
    display_name = db.Column(db.String(200), nullable=True)
    status = db.Column(db.String(20), nullable=False)
    relay = db.Column(db.Boolean, nullable=False, default=False)
    oops = db.Column(db.Boolean, nullable=False, default=False)
    locked_out = db.Column(db.Boolean, nullable=False, default=False)
    current_user_account_id = db.Column(db.String(200), nullable=True)
    current_user_full_name = db.Column(db.String(200), nullable=True)
    # last_checkin / last_update are converted from MAC epoch floats to UTC
    # datetimes on write. Note: db.DateTime is not tz-aware storage -- values
    # come back naive on read (see mac_service epoch handling, F7).
    last_checkin = db.Column(db.DateTime, nullable=True)
    last_update = db.Column(db.DateTime, nullable=True)
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    def __repr__(self):
        return f'<MachineStatus {self.machine_name!r} [{self.status}]>'
