"""User model for authentication and RBAC."""

from datetime import UTC, datetime

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from esb.extensions import db


class User(UserMixin, db.Model):
    """Application user with role-based access control."""

    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    email = db.Column(db.String(255), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(20), nullable=False, default='technician')
    slack_handle = db.Column(db.String(80), nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(UTC)
    )
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    reservations = db.relationship(
        'Reservation',
        foreign_keys='Reservation.user_id',
        back_populates='user',
        lazy='dynamic',
    )
    canceled_reservations = db.relationship(
        'Reservation',
        foreign_keys='Reservation.canceled_by_user_id',
        back_populates='canceled_by_user',
        lazy='dynamic',
    )

    @property
    def display_name(self):
        """Human-friendly fallback display name derived from username."""
        words = self.username.replace('_', ' ').replace('-', ' ').replace('.', ' ')
        return ' '.join(word.capitalize() for word in words.split()) or self.username

    def set_password(self, password):
        """Hash and store the password using Werkzeug defaults (scrypt)."""
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        """Verify a plaintext password against the stored hash."""
        return check_password_hash(self.password_hash, password)

    def __repr__(self):
        return f'<User {self.username!r}>'
