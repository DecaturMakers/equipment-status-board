"""Configuration classes for ESB application."""

import os
from datetime import timedelta


def build_engine_options(database_url: str) -> dict:
    """Compute SQLAlchemy engine options tuned to the database URL.

    pool_pre_ping detects silently-dropped TCP connections (NAT/conntrack/
    firewall) before the next query blocks on recv() forever; pool_recycle
    bounds idle connection age. The MariaDB/MySQL connect_args provide
    socket-level timeouts so a wedged read cannot hang the worker
    indefinitely. The connect_args are MariaDB-specific and are omitted for
    other drivers (e.g. SQLite, which would raise TypeError on these kwargs).
    """
    options: dict = {
        'pool_pre_ping': True,
        'pool_recycle': 1800,
    }
    if database_url.startswith(('mysql', 'mariadb')):
        options['connect_args'] = {
            'connect_timeout': 10,
            'read_timeout': 30,
            'write_timeout': 30,
        }
    return options


class Config:
    """Base configuration."""

    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret-change-me')
    ESB_BASE_URL = os.environ.get('ESB_BASE_URL', '')
    QR_TEMPLATE_CONFIG_PATH = os.environ.get('QR_TEMPLATE_CONFIG_PATH', '')
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        'DATABASE_URL', 'mysql+pymysql://root:password@localhost/esb'
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = build_engine_options(SQLALCHEMY_DATABASE_URI)
    WORKER_HEARTBEAT_PATH = os.environ.get('WORKER_HEARTBEAT_PATH', '/tmp/worker_heartbeat')
    UPLOAD_PATH = os.environ.get('UPLOAD_PATH', 'uploads')
    UPLOAD_MAX_SIZE_MB = int(os.environ.get('UPLOAD_MAX_SIZE_MB', '500'))
    MAX_CONTENT_LENGTH = UPLOAD_MAX_SIZE_MB * 1024 * 1024
    PERMANENT_SESSION_LIFETIME = timedelta(hours=12)
    SLACK_BOT_TOKEN = os.environ.get('SLACK_BOT_TOKEN', '')
    SLACK_APP_TOKEN = os.environ.get('SLACK_APP_TOKEN', '')
    SLACK_OOPS_CHANNEL = os.environ.get('SLACK_OOPS_CHANNEL', '#oops')
    SLACK_SOCKET_MODE_CONNECT = os.environ.get('SLACK_SOCKET_MODE_CONNECT', '')
    STATIC_PAGE_PUSH_METHOD = os.environ.get('STATIC_PAGE_PUSH_METHOD', 'local')
    STATIC_PAGE_PUSH_TARGET = os.environ.get('STATIC_PAGE_PUSH_TARGET', '')
    CLOUDFRONT_DISTRIBUTION_ID = os.environ.get('CLOUDFRONT_DISTRIBUTION_ID', '')
    NEW_RELIC_LICENSE_KEY = os.environ.get('NEW_RELIC_LICENSE_KEY', '')
    NEW_RELIC_APP_NAME = os.environ.get('NEW_RELIC_APP_NAME', 'Equipment Status Board')


class DevelopmentConfig(Config):
    """Development configuration."""

    DEBUG = True


class TestingConfig(Config):
    """Testing configuration."""

    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    WTF_CSRF_ENABLED = False
    SQLALCHEMY_ENGINE_OPTIONS = build_engine_options(SQLALCHEMY_DATABASE_URI)


class SlackTestConfig(TestingConfig):
    """Config for testing Socket Mode init path (TESTING=False so connect() runs)."""

    TESTING = False


class ProductionConfig(Config):
    """Production configuration."""

    DEBUG = False


class ScreenshotConfig(Config):
    """Configuration for screenshot generation script."""

    SQLALCHEMY_DATABASE_URI = 'sqlite:////tmp/esb_screenshots.db'
    SQLALCHEMY_ENGINE_OPTIONS = build_engine_options(SQLALCHEMY_DATABASE_URI)


config = {
    'development': DevelopmentConfig,
    'testing': TestingConfig,
    'slack_test': SlackTestConfig,
    'production': ProductionConfig,
    'screenshot': ScreenshotConfig,
    'default': DevelopmentConfig,
}
