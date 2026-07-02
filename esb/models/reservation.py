"""Reservation model for reservable equipment."""

from datetime import UTC, datetime

from esb.extensions import db


RESERVATION_STATUSES = ('active', 'canceled')
RESERVATION_CREATED_VIA = ('slack', 'admin')


class Reservation(db.Model):
    """A reservation of one equipment item by one user."""

    __tablename__ = 'reservations'

    id = db.Column(db.Integer, primary_key=True)
    equipment_id = db.Column(
        db.Integer, db.ForeignKey('equipment.id'), nullable=False, index=True
    )
    user_id = db.Column(
        db.Integer, db.ForeignKey('users.id'), nullable=False, index=True
    )
    starts_at = db.Column(db.DateTime, nullable=False, index=True)
    ends_at = db.Column(db.DateTime, nullable=False, index=True)
    status = db.Column(db.String(20), default='active', nullable=False, index=True)
    notes = db.Column(db.Text, nullable=True)
    created_via = db.Column(db.String(20), nullable=False)
    canceled_at = db.Column(db.DateTime, nullable=True)
    canceled_by_user_id = db.Column(
        db.Integer, db.ForeignKey('users.id'), nullable=True, index=True
    )
    created_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(UTC)
    )
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    equipment = db.relationship(
        'Equipment',
        back_populates='reservations',
    )
    user = db.relationship(
        'User',
        foreign_keys=[user_id],
        back_populates='reservations',
    )
    canceled_by_user = db.relationship(
        'User',
        foreign_keys=[canceled_by_user_id],
        back_populates='canceled_reservations',
    )

    def __repr__(self):
        return f'<Reservation {self.equipment_id} {self.starts_at!r}>'
