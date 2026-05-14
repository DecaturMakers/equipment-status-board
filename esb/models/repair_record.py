"""RepairRecord model for tracking equipment problems."""

from datetime import UTC, datetime

from esb.extensions import db

REPAIR_STATUSES = [
    'New',
    'Assigned',
    'In Progress',
    'Parts Needed',
    'Parts Ordered',
    'Parts Received',
    'Needs Specialist',
    'Resolved',
    'Closed - No Issue Found',
    'Closed - Duplicate',
]

REPAIR_SEVERITIES = ['Down', 'Degraded', 'Not Sure']


class RepairRecord(db.Model):
    """Tracks an equipment problem from report through resolution."""

    __tablename__ = 'repair_records'

    id = db.Column(db.Integer, primary_key=True)
    equipment_id = db.Column(
        db.Integer, db.ForeignKey('equipment.id'), nullable=False, index=True,
    )
    status = db.Column(db.String(50), nullable=False, default='New', index=True)
    severity = db.Column(db.String(20), nullable=True)
    description = db.Column(db.Text, nullable=False)
    reporter_name = db.Column(db.String(200), nullable=True)
    reporter_email = db.Column(db.String(255), nullable=True)
    assignee_id = db.Column(
        db.Integer, db.ForeignKey('users.id'), nullable=True, index=True,
    )
    eta = db.Column(db.Date, nullable=True)
    specialist_description = db.Column(db.Text, nullable=True)
    duplicated_repair_id = db.Column(
        db.Integer,
        db.ForeignKey('repair_records.id', ondelete='SET NULL'),
        nullable=True,
        index=True,
    )
    has_safety_risk = db.Column(db.Boolean, nullable=False, default=False)
    is_consumable = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(UTC),
    )
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    # Relationships
    equipment = db.relationship('Equipment', backref=db.backref('repair_records', lazy='dynamic'))
    assignee = db.relationship('User', backref=db.backref('assigned_repairs', lazy='dynamic'))
    duplicated_repair = db.relationship('RepairRecord', remote_side=[id])

    def __repr__(self):
        return f'<RepairRecord {self.id} [{self.status}]>'
