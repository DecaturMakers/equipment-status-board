"""Tests for esb.config -- focused on engine option wiring.

The engine options were introduced to fix a worker hang caused by silently
dropped DB connections; a regression here would silently re-introduce the
bug, so explicit tests guard the wiring.
"""

import importlib
import sys

from esb.config import (
    Config,
    ProductionConfig,
    ScreenshotConfig,
    TestingConfig,
    build_engine_options,
)


class TestBuildEngineOptions:
    def test_mysql_url_includes_socket_timeouts(self):
        opts = build_engine_options('mysql+pymysql://root:x@db/esb')
        assert opts['pool_pre_ping'] is True
        assert opts['pool_recycle'] == 1800
        assert opts['connect_args'] == {
            'connect_timeout': 10,
            'read_timeout': 30,
            'write_timeout': 30,
        }

    def test_mariadb_url_includes_socket_timeouts(self):
        opts = build_engine_options('mariadb+pymysql://root:x@db/esb')
        assert 'connect_args' in opts
        assert opts['connect_args']['read_timeout'] == 30

    def test_sqlite_url_omits_connect_args(self):
        # Critical: sqlite would raise TypeError on connect_timeout etc.
        opts = build_engine_options('sqlite:///:memory:')
        assert opts['pool_pre_ping'] is True
        assert opts['pool_recycle'] == 1800
        assert 'connect_args' not in opts

    def test_postgres_url_omits_connect_args(self):
        # Defensive: any non-MariaDB driver should not get MariaDB kwargs.
        opts = build_engine_options('postgresql://x@db/esb')
        assert 'connect_args' not in opts


class TestConfigEngineOptions:
    def test_production_config_options_match_its_uri(self):
        # ProductionConfig's options must be the same as build_engine_options()
        # would produce for its DATABASE_URI -- whatever that URI happens to be
        # (CI sets it to sqlite via env). This guards the wiring without
        # depending on environment.
        assert ProductionConfig.SQLALCHEMY_ENGINE_OPTIONS == build_engine_options(
            ProductionConfig.SQLALCHEMY_DATABASE_URI,
        )

    def test_pool_options_always_present(self):
        # Pool options should be present regardless of driver.
        for cfg in (Config, ProductionConfig, TestingConfig, ScreenshotConfig):
            opts = cfg.SQLALCHEMY_ENGINE_OPTIONS
            assert opts['pool_pre_ping'] is True
            assert opts['pool_recycle'] == 1800

    def test_base_config_engine_options_match_uri(self):
        # The base Config's options are computed from its URI.
        assert Config.SQLALCHEMY_ENGINE_OPTIONS == build_engine_options(
            Config.SQLALCHEMY_DATABASE_URI,
        )

    def test_testing_config_omits_connect_args(self):
        # SQLite -- must not have MariaDB kwargs.
        opts = TestingConfig.SQLALCHEMY_ENGINE_OPTIONS
        assert 'connect_args' not in opts

    def test_screenshot_config_omits_connect_args(self):
        opts = ScreenshotConfig.SQLALCHEMY_ENGINE_OPTIONS
        assert 'connect_args' not in opts

    def test_production_config_with_mysql_url_includes_connect_args(
        self, monkeypatch,
    ):
        """Reload esb.config under a MariaDB DATABASE_URL and verify that
        ProductionConfig actually carries the connect_args.

        The cheaper "options match build_engine_options(uri)" test passes
        trivially in CI (where DATABASE_URL is sqlite), so this reload-based
        test is what actually catches a regression that drops the wiring on
        the production path.
        """
        monkeypatch.setenv(
            'DATABASE_URL', 'mysql+pymysql://root:x@db/esb',
        )
        # esb/__init__.py does `from esb.config import config`, which
        # overrides the package's `.config` attribute with the dict, so
        # `esb.config` no longer points at the module. Reach for the module
        # via sys.modules instead.
        config_module = sys.modules['esb.config']
        reloaded = importlib.reload(config_module)
        try:
            opts = reloaded.ProductionConfig.SQLALCHEMY_ENGINE_OPTIONS
            assert opts['pool_pre_ping'] is True
            assert opts['pool_recycle'] == 1800
            assert opts['connect_args'] == {
                'connect_timeout': 10,
                'read_timeout': 30,
                'write_timeout': 30,
            }
        finally:
            # Restore the module under the original env so other tests are
            # not disturbed (monkeypatch restores the env var itself).
            importlib.reload(config_module)


class TestEngineOptionsAppliedToApp:
    def test_pool_pre_ping_applied_to_engine(self, app):
        """The configured pool options reach the SQLAlchemy engine.

        Tests with TestingConfig (sqlite); the relevant assertion is that
        the options dict actually flows through Flask-SQLAlchemy to the
        engine, not the specific MariaDB kwargs.
        """
        engine = app.extensions['sqlalchemy'].engine
        # pool_pre_ping is implemented as an event listener on the pool;
        # SQLAlchemy exposes it via the engine's pool's _pre_ping attr.
        assert engine.pool._pre_ping is True

    def test_pool_recycle_applied_to_engine(self, app):
        engine = app.extensions['sqlalchemy'].engine
        assert engine.pool._recycle == 1800
