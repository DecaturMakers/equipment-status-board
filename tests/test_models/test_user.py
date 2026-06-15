"""Tests for User model."""

import pytest

from esb.extensions import db as _db
from esb.models.user import User


class TestUserCreation:
    """Tests for User model creation and fields."""

    def test_create_user_defaults(self, app):
        """User created with defaults has correct role and is_active."""
        user = User(username='alice', email='alice@example.com', password_hash='x')
        _db.session.add(user)
        _db.session.commit()
        assert user.id is not None
        assert user.role == 'technician'
        assert user.is_active is True

    def test_create_staff_user(self, app):
        """User created with staff role."""
        user = User(
            username='bob', email='bob@example.com', password_hash='x', role='staff'
        )
        _db.session.add(user)
        _db.session.commit()
        assert user.role == 'staff'

    def test_timestamps_set_on_create(self, app):
        """created_at and updated_at are set automatically."""
        user = User(username='carol', email='carol@example.com', password_hash='x')
        _db.session.add(user)
        _db.session.commit()
        assert user.created_at is not None
        assert user.updated_at is not None

    def test_slack_handle_nullable(self, app):
        """slack_handle defaults to None."""
        user = User(username='dave', email='dave@example.com', password_hash='x')
        _db.session.add(user)
        _db.session.commit()
        assert user.slack_handle is None

    def test_slack_handle_stored(self, app):
        """slack_handle is stored when provided."""
        user = User(
            username='eve',
            email='eve@example.com',
            password_hash='x',
            slack_handle='@eve',
        )
        _db.session.add(user)
        _db.session.commit()
        assert user.slack_handle == '@eve'

    def test_repr(self, app):
        """User __repr__ includes username."""
        user = User(username='frank', email='frank@example.com', password_hash='x')
        assert repr(user) == "<User 'frank'>"


class TestUserUniqueConstraints:
    """Tests for unique constraints on User model."""

    def test_duplicate_username_rejected(self, app):
        """Duplicate username raises IntegrityError."""
        u1 = User(username='alice', email='a1@example.com', password_hash='x')
        u2 = User(username='alice', email='a2@example.com', password_hash='x')
        _db.session.add(u1)
        _db.session.commit()
        _db.session.add(u2)
        with pytest.raises(Exception):
            _db.session.commit()
        _db.session.rollback()

    def test_duplicate_email_rejected(self, app):
        """Duplicate email raises IntegrityError."""
        u1 = User(username='bob1', email='same@example.com', password_hash='x')
        u2 = User(username='bob2', email='same@example.com', password_hash='x')
        _db.session.add(u1)
        _db.session.commit()
        _db.session.add(u2)
        with pytest.raises(Exception):
            _db.session.commit()
        _db.session.rollback()

class TestUserPassword:
    """Tests for password hashing and verification."""

    def test_set_password_hashes(self, app):
        """set_password stores a hash, not plaintext."""
        user = User(username='alice', email='alice@example.com', password_hash='temp')
        user.set_password('secret123')
        assert user.password_hash != 'secret123'
        assert user.password_hash != 'temp'

    def test_check_password_correct(self, app):
        """check_password returns True for correct password."""
        user = User(username='alice', email='alice@example.com', password_hash='temp')
        user.set_password('secret123')
        assert user.check_password('secret123') is True

    def test_check_password_wrong(self, app):
        """check_password returns False for wrong password."""
        user = User(username='alice', email='alice@example.com', password_hash='temp')
        user.set_password('secret123')
        assert user.check_password('wrong') is False

    def test_different_passwords_different_hashes(self, app):
        """Different passwords produce different hashes."""
        u1 = User(username='a', email='a@example.com', password_hash='temp')
        u2 = User(username='b', email='b@example.com', password_hash='temp')
        u1.set_password('password1')
        u2.set_password('password2')
        assert u1.password_hash != u2.password_hash


class TestUserMixin:
    """Tests for Flask-Login UserMixin integration."""

    def test_is_authenticated(self, app):
        """UserMixin provides is_authenticated (delegates to is_active)."""
        user = User(username='alice', email='alice@example.com', password_hash='x')
        _db.session.add(user)
        _db.session.commit()
        assert user.is_authenticated is True

    def test_is_active_reflects_column(self, app):
        """is_active reflects the database column value."""
        user = User(
            username='alice',
            email='alice@example.com',
            password_hash='x',
            is_active=False,
        )
        assert user.is_active is False

    def test_get_id_returns_string(self, app):
        """get_id returns the user ID as a string."""
        user = User(username='alice', email='alice@example.com', password_hash='x')
        _db.session.add(user)
        _db.session.commit()
        assert user.get_id() == str(user.id)
