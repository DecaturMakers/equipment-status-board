"""Shared test fixtures for ESB application."""

import json
import logging
import os

import pytest

from esb import create_app
from esb.config import TestingConfig
from esb.extensions import db as _db
from esb.models.area import Area
from esb.models.equipment import Equipment
from esb.models.repair_record import RepairRecord
from esb.models.user import User
from esb.utils.logging import mutation_logger


@pytest.fixture(autouse=True)
def _isolate_qr_template_config(monkeypatch):
    """Shield tests from a host QR_TEMPLATE_CONFIG_PATH.

    Config classes bind env vars at import time, and create_app() consumes
    QR_TEMPLATE_CONFIG_PATH during startup — a host shell with this exported
    would otherwise activate a template in every test app (or fail startup
    outright). Autouse fixtures run before requested fixtures of the same
    scope, so this lands before the app fixture's create_app(). Tests that
    exercise the startup path monkeypatch this same attribute in their own
    bodies, which applies later and unwinds first.
    """
    monkeypatch.setattr(TestingConfig, 'QR_TEMPLATE_CONFIG_PATH', '')


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


def _create_area(name='Test Area', slack_channel='#test-area', sort_order=0):
    """Helper to create an area in the test database."""
    area = Area(name=name, slack_channel=slack_channel, sort_order=sort_order)
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


# The "safe drawable area" bboxes from GitHub Issue #57 for the example
# template fixture (tests/qr_code_template.png, 1500×1800).
QR_TEMPLATE_QR_BBOX = [509, 949, 1011, 1451]
QR_TEMPLATE_NAME_BBOX = [240, 540, 1259, 925]
QR_TEMPLATE_URL_BBOX = [140, 1490, 1359, 1675]


@pytest.fixture
def make_qr_template_config(app, tmp_path):
    """Factory fixture: write a QR template config JSON, load it, install it.

    Each call writes a distinct JSON file into tmp_path referencing the
    committed tests/qr_code_template.png (+ Poppins-Bold.ttf when font=True),
    loads it via qr_service.load_template_config(), installs the result on
    app.config['QR_TEMPLATE'], and returns the QRTemplate. Teardown restores
    the original config value.
    """
    from esb.services import qr_service

    tests_dir = os.path.dirname(os.path.abspath(__file__))
    original = app.config.get('QR_TEMPLATE')
    counter = {'n': 0}

    def _make(url_bbox=True, font=True):
        counter['n'] += 1
        config = {
            'image': os.path.relpath(os.path.join(tests_dir, 'qr_code_template.png'), tmp_path),
            'qr_bbox': QR_TEMPLATE_QR_BBOX,
            'name_bbox': QR_TEMPLATE_NAME_BBOX,
        }
        if font:
            config['font'] = os.path.relpath(os.path.join(tests_dir, 'Poppins-Bold.ttf'), tmp_path)
        if url_bbox:
            config['url_bbox'] = QR_TEMPLATE_URL_BBOX
        json_path = tmp_path / f'qr_template_config_{counter["n"]}.json'
        json_path.write_text(json.dumps(config))
        template = qr_service.load_template_config(str(json_path))
        app.config['QR_TEMPLATE'] = template
        return template

    yield _make
    app.config['QR_TEMPLATE'] = original


@pytest.fixture
def qr_template_config(make_qr_template_config):
    """Convenience: the default full template config (font + url_bbox)."""
    return make_qr_template_config()


@pytest.fixture
def configured_base_url(app):
    """Set ESB_BASE_URL for tests that need the QR feature enabled.

    Yields the configured value so tests can assert against it.
    """
    original = app.config.get('ESB_BASE_URL', '')
    app.config['ESB_BASE_URL'] = 'http://esb.test:5000'
    yield app.config['ESB_BASE_URL']
    app.config['ESB_BASE_URL'] = original
