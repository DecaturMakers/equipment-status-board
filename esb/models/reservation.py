"""Reservation model for reservable equipment."""

from datetime import UTC, datetime

from esb.extensions import db


RESERVATION_STATUS_ACTIVE = "active"
RESERVATION_STATUS_CANCELED = "canceled"
RESERVATION_STATUSES = (RESERVATION_STATUS_ACTIVE, RESERVATION_STATUS_CANCELED)
RESERVATION_CREATED_VIA = ('slack', 'admin')
RESERVATION_TYPE_MEMBER = "member"
RESERVATION_TYPE_ADMIN_HOLD = "admin_hold"
RESERVATION_TYPES = (RESERVATION_TYPE_MEMBER, RESERVATION_TYPE_ADMIN_HOLD)


class Reservation(db.Model):
    """A member reservation or administrative hold for one equipment item."""

    __tablename__ = 'reservations'
    __table_args__ = (
        db.CheckConstraint(
            "reservation_type IN ('member', 'admin_hold')",
            name="ck_reservations_type",
        ),
        db.CheckConstraint(
            "(reservation_type = 'member' AND user_id IS NOT NULL) "
            "OR (reservation_type = 'admin_hold' AND user_id IS NULL)",
            name="ck_reservations_type_owner",
        ),
        db.CheckConstraint("ends_at > starts_at", name="ck_reservations_valid_interval"),
    )

    id = db.Column(db.Integer, primary_key=True)
    equipment_id = db.Column(db.Integer, db.ForeignKey("equipment.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
    starts_at = db.Column(db.DateTime, nullable=False, index=True)
    ends_at = db.Column(db.DateTime, nullable=False, index=True)
    status = db.Column(db.String(20), default='active', nullable=False, index=True)
    notes = db.Column(db.Text, nullable=True)
    created_via = db.Column(db.String(20), nullable=False)
    reservation_type = db.Column(
        db.String(20),
        nullable=False,
        default=RESERVATION_TYPE_MEMBER,
        index=True,
    )
    created_by_user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    replaces_reservation_id = db.Column(
        db.Integer,
        db.ForeignKey("reservations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    overridden_policy_codes = db.Column(db.JSON, nullable=False, default=list)
    canceled_at = db.Column(db.DateTime, nullable=True)
    canceled_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(UTC))
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
    created_by_user = db.relationship(
        "User",
        foreign_keys=[created_by_user_id],
        back_populates="created_reservations",
    )
    replaces_reservation = db.relationship(
        "Reservation",
        remote_side=[id],
        foreign_keys=[replaces_reservation_id],
        backref=db.backref("replacement_reservations", lazy="dynamic"),
    )

    @property
    def is_admin_hold(self) -> bool:
        """Return whether this row blocks equipment without a member owner."""
        return self.reservation_type == RESERVATION_TYPE_ADMIN_HOLD

    def __repr__(self):
        return f'<Reservation {self.equipment_id} {self.starts_at!r}>'
