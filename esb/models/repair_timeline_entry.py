"""RepairTimelineEntry model for append-only repair record timeline."""

from datetime import UTC, datetime

from esb.extensions import db

TIMELINE_ENTRY_TYPES = [
    'creation',
    'note',
    'status_change',
    'assignee_change',
    'eta_update',
    'photo',
    'duplicated_repair_id_change',
]


class RepairTimelineEntry(db.Model):
    """Append-only log entry for a repair record's timeline."""

    __tablename__ = 'repair_timeline_entries'

    id = db.Column(db.Integer, primary_key=True)
    repair_record_id = db.Column(
        db.Integer, db.ForeignKey('repair_records.id'), nullable=False, index=True,
    )
    entry_type = db.Column(db.String(30), nullable=False)
    author_id = db.Column(
        db.Integer, db.ForeignKey('users.id'), nullable=True,
    )
    author_name = db.Column(db.String(200), nullable=True)
    content = db.Column(db.Text, nullable=True)
    old_value = db.Column(db.String(200), nullable=True)
    new_value = db.Column(db.String(200), nullable=True)
    created_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(UTC),
    )

    # Relationships
    repair_record = db.relationship(
        'RepairRecord',
        backref=db.backref('timeline_entries', lazy='dynamic', order_by='RepairTimelineEntry.created_at.desc()'),
    )
    author = db.relationship('User', backref=db.backref('timeline_entries', lazy='dynamic'))

    def __repr__(self):
        return f'<RepairTimelineEntry {self.id} [{self.entry_type}]>'
