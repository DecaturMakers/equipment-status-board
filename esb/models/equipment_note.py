"""EquipmentNote model for append-only free-form notes on equipment records."""

from datetime import UTC, datetime

from esb.extensions import db


class EquipmentNote(db.Model):
    """A free-form, append-only note attached to an equipment record.

    Mirrors ``ExternalLink`` (equipment child record with a ``created_at``
    default) and ``RepairTimelineEntry`` (author FK + cached ``author_name`` +
    ``content``). Attribution is preserved by the cached ``author_name`` -- a
    point-in-time snapshot that does not reflect later username changes -- not
    by the nullable ``author_id`` FK (which does not ``SET NULL`` on delete).
    """

    __tablename__ = 'equipment_notes'

    id = db.Column(db.Integer, primary_key=True)
    equipment_id = db.Column(
        db.Integer, db.ForeignKey('equipment.id'), nullable=False, index=True,
    )
    author_id = db.Column(
        db.Integer, db.ForeignKey('users.id'), nullable=True,
    )
    author_name = db.Column(db.String(200), nullable=True)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(UTC),
    )

    # Relationships
    equipment = db.relationship(
        'Equipment',
        backref=db.backref(
            'notes',
            lazy='dynamic',
            order_by='EquipmentNote.created_at.desc(), EquipmentNote.id.desc()',
        ),
    )
    author = db.relationship('User', backref=db.backref('equipment_notes', lazy='dynamic'))

    def __repr__(self):
        return f'<EquipmentNote {self.id}>'
