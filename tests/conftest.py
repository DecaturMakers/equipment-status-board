"""Shared test fixtures for ESB application."""

import logging

import pytest

from esb import create_app
from esb.extensions import db as _db
from esb.models.area import Area
from esb.models.equipment import Equipment
from esb.models.repair_record import RepairRecord
from esb.models.user import User
from esb.utils.logging import mutation_logger


class _CaptureHandler(logging.Handler):
    """Test handler that captures log records."""

    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)


@pytest.fixture
def capture():
    """Add a capture handler to the mutation logger for testing."""
    handler = _CaptureHandler()
    mutation_logger.addHandler(handler)
    yield handler
    mutation_logger.removeHandler(handler)


@pytest.fixture
def app():
    """Create a Flask application configured for testing."""
    app = create_app('testing')
    # Clear env-driven config that would otherwise leak in from the host shell
    # (e.g. a developer with CLOUDFRONT_DISTRIBUTION_ID set could see S3 push
    # tests start hitting the CloudFront client unexpectedly).
    app.config['CLOUDFRONT_DISTRIBUTION_ID'] = ''
    with app.app_context():
        _db.create_all()
        yield app
        _db.session.remove()
        _db.drop_all()


@pytest.fixture
def client(app):
    """Create a Flask test client."""
    return app.test_client()


@pytest.fixture
def db(app):
    """Provide the database session for tests."""
    return _db


def _create_user(role, username=None, password='testpass'):
    """Helper to create a user in the test database."""
    username = username or f'test_{role}'
    user = User(
        username=username,
        email=f'{username}@example.com',
        role=role,
    )
    user.set_password(password)
    _db.session.add(user)
    _db.session.commit()
    return user


def _create_area(name='Test Area', slack_channel='#test-area'):
    """Helper to create an area in the test database."""
    area = Area(name=name, slack_channel=slack_channel)
    _db.session.add(area)
    _db.session.commit()
    return area


@pytest.fixture
def make_area(app):
    """Factory fixture to create test areas."""
    return _create_area


def _create_equipment(name='Test Equipment', manufacturer='TestCo', model='Model X',
                      area=None, **kwargs):
    """Helper to create an equipment record in the test database."""
    if area is None:
        area = _create_area()
    equipment = Equipment(
        name=name, manufacturer=manufacturer, model=model,
        area_id=area.id, **kwargs,
    )
    _db.session.add(equipment)
    _db.session.commit()
    return equipment


@pytest.fixture
def make_equipment(app):
    """Factory fixture to create test equipment."""
    return _create_equipment


@pytest.fixture
def staff_user(app):
    """Create a staff user in the test database."""
    return _create_user('staff', 'staffuser')


@pytest.fixture
def tech_user(app):
    """Create a technician user in the test database."""
    return _create_user('technician', 'techuser')


@pytest.fixture
def staff_client(client, staff_user):
    """Return a test client logged in as a staff user."""
    client.post('/auth/login', data={
        'username': 'staffuser',
        'password': 'testpass',
    })
    return client


def _create_repair_record(equipment=None, status='New', description='Test issue', **kwargs):
    """Helper to create a repair record in the test database."""
    if equipment is None:
        area = _create_area()
        equipment = _create_equipment(area=area)
    record = RepairRecord(
        equipment_id=equipment.id,
        status=status,
        description=description,
        **kwargs,
    )
    _db.session.add(record)
    _db.session.commit()
    return record


@pytest.fixture
def make_repair_record(app):
    """Factory fixture to create test repair records."""
    return _create_repair_record


@pytest.fixture
def tech_client(client, tech_user):
    """Return a test client logged in as a technician user."""
    client.post('/auth/login', data={
        'username': 'techuser',
        'password': 'testpass',
    })
    return client


@pytest.fixture
def configured_base_url(app):
    """Set ESB_BASE_URL for tests that need the QR feature enabled.

    Yields the configured value so tests can assert against it.
    """
    original = app.config.get('ESB_BASE_URL', '')
    app.config['ESB_BASE_URL'] = 'http://esb.test:5000'
    yield app.config['ESB_BASE_URL']
    app.config['ESB_BASE_URL'] = original
