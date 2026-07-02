"""Reservation configuration for equipment."""

from datetime import UTC, datetime

from esb.extensions import db


DEFAULT_MIN_ADVANCE_NOTICE_MINUTES = 2 * 60
DEFAULT_MAX_ADVANCE_NOTICE_MINUTES = 14 * 24 * 60


class EquipmentReservationSettings(db.Model):
    """Scheduling settings for one reservable equipment item."""

    __tablename__ = 'equipment_reservation_settings'

    id = db.Column(db.Integer, primary_key=True)
    equipment_id = db.Column(
        db.Integer, db.ForeignKey('equipment.id'), unique=True, nullable=False, index=True
    )
    reservation_slug = db.Column(db.String(200), unique=True, nullable=False, index=True)
    reservations_enabled = db.Column(db.Boolean, default=True, nullable=False)
    min_advance_notice_minutes = db.Column(
        db.Integer,
        default=DEFAULT_MIN_ADVANCE_NOTICE_MINUTES,
        nullable=False,
    )
    max_advance_notice_minutes = db.Column(
        db.Integer,
        default=DEFAULT_MAX_ADVANCE_NOTICE_MINUTES,
        nullable=False,
    )
    min_duration_minutes = db.Column(db.Integer, nullable=False)
    max_duration_minutes = db.Column(db.Integer, nullable=False)
    slot_granularity_minutes = db.Column(db.Integer, nullable=False)
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
        back_populates='reservation_settings',
    )

    def __repr__(self):
        return f'<EquipmentReservationSettings {self.reservation_slug!r}>'
