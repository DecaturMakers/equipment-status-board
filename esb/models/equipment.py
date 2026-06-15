"""Equipment model for the equipment registry."""

from datetime import UTC, datetime

from esb.extensions import db


class Equipment(db.Model):
    """Equipment registry entry."""

    __tablename__ = 'equipment'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False, index=True)
    manufacturer = db.Column(db.String(200), nullable=False)
    model = db.Column(db.String(200), nullable=False)
    area_id = db.Column(
        db.Integer, db.ForeignKey('areas.id'), nullable=False, index=True
    )
    serial_number = db.Column(db.String(200), nullable=True)
    acquisition_date = db.Column(db.Date, nullable=True)
    acquisition_source = db.Column(db.String(200), nullable=True)
    acquisition_cost = db.Column(db.Numeric(10, 2), nullable=True)
    warranty_expiration = db.Column(db.Date, nullable=True)
    description = db.Column(db.Text, nullable=True)
    is_archived = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(UTC)
    )
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    # Relationships
    area = db.relationship('Area', backref=db.backref('equipment', lazy='dynamic'))
    reservation_settings = db.relationship(
        'EquipmentReservationSettings',
        back_populates='equipment',
        uselist=False,
        cascade='all, delete-orphan',
    )
    reservations = db.relationship(
        'Reservation',
        back_populates='equipment',
        lazy='dynamic',
    )

    def __repr__(self):
        return f'<Equipment {self.name!r}>'
