"""Smoke tests for ESB application."""

import json
import os

import pytest

from esb import create_app
from esb.config import TestingConfig


class TestAppFactory:
    """Tests for the app factory."""

    def test_app_creates(self):
        """App factory creates a Flask app."""
        app = create_app('testing')
        assert app is not None

    def test_testing_config(self):
        """App uses testing configuration."""
        app = create_app('testing')
        assert app.config['TESTING'] is True

    def test_health_endpoint(self, client):
        """Health endpoint responds with 200."""
        resp = client.get('/health')
        assert resp.status_code == 200
        assert resp.data == b'ok'

    def test_index_redirects_to_dashboard(self, client):
        """Index route redirects to public status dashboard."""
        resp = client.get('/')
        assert resp.status_code == 302
        assert '/public/' in resp.headers['Location']

    def test_blueprints_registered(self):
        """All expected blueprints are registered."""
        app = create_app('testing')
        expected = {'equipment', 'repairs', 'admin', 'public', 'auth'}
        assert expected.issubset(set(app.blueprints.keys()))

    def test_404_error(self, client):
        """Non-existent route returns 404."""
        resp = client.get('/nonexistent-route-that-does-not-exist')
        assert resp.status_code == 404

    def test_upload_path_is_absolute(self):
        """UPLOAD_PATH is normalized to an absolute path at startup.

        Ensures file serving works regardless of the process working directory,
        which differs between dev (project root) and Docker deployments (/app).
        """
        app = create_app('testing')
        with app.app_context():
            assert os.path.isabs(app.config['UPLOAD_PATH'])


class TestQRTemplateStartup:
    """Fail-fast QR template config validation in create_app.

    Config classes bind env vars at import time, so monkeypatch.setenv does
    NOT work here — patch the TestingConfig class attribute instead.
    """

    def test_unset_leaves_qr_template_none(self):
        app = create_app('testing')
        assert app.config['QR_TEMPLATE'] is None

    def test_missing_config_file_raises(self, monkeypatch, tmp_path):
        monkeypatch.setattr(
            TestingConfig, 'QR_TEMPLATE_CONFIG_PATH', str(tmp_path / 'missing.json'),
        )
        with pytest.raises(ValueError, match='unreadable'):
            create_app('testing')

    def test_invalid_config_file_raises(self, monkeypatch, tmp_path):
        bad = tmp_path / 'bad.json'
        bad.write_text('{not json!')
        monkeypatch.setattr(TestingConfig, 'QR_TEMPLATE_CONFIG_PATH', str(bad))
        with pytest.raises(ValueError, match='not valid JSON'):
            create_app('testing')

    def test_valid_config_populates_qr_template(self, monkeypatch, tmp_path):
        tests_dir = os.path.dirname(os.path.abspath(__file__))
        config = {
            'image': os.path.relpath(os.path.join(tests_dir, 'qr_code_template.png'), tmp_path),
            'font': os.path.relpath(os.path.join(tests_dir, 'Poppins-Bold.ttf'), tmp_path),
            'qr_bbox': [509, 949, 1011, 1451],
            'name_bbox': [240, 540, 1259, 925],
            'url_bbox': [140, 1490, 1359, 1675],
        }
        path = tmp_path / 'template_config.json'
        path.write_text(json.dumps(config))
        monkeypatch.setattr(TestingConfig, 'QR_TEMPLATE_CONFIG_PATH', str(path))
        app = create_app('testing')
        template = app.config['QR_TEMPLATE']
        assert template is not None
        assert template.qr_bbox == (509, 949, 1011, 1451)
        assert (template.image_w, template.image_h) == (1500, 1800)
