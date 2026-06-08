"""Tests for Slack module initialization (esb/slack/__init__.py)."""

import signal
from unittest.mock import MagicMock, patch

import pytest

from esb import create_app
from esb.config import Config, SlackTestConfig


class TestSlackDisabled:
    """Tests for when Slack is NOT configured (default TestingConfig)."""

    @pytest.fixture(autouse=True)
    def setup_app(self):
        """Create app without Slack configured."""
        self.app = create_app('testing')
        with self.app.app_context():
            from esb.extensions import db
            db.create_all()
            yield
            db.session.remove()
            db.drop_all()

    def test_app_starts_cleanly_without_slack(self):
        """App starts normally when SLACK_BOT_TOKEN is empty."""
        client = self.app.test_client()
        resp = client.get('/health')
        assert resp.status_code == 200

    def test_no_slack_bolt_app_when_disabled(self):
        """Bolt app is None when Slack is not configured."""
        import esb.slack as slack_mod
        assert slack_mod._bolt_app is None

    def test_no_slack_routes_when_disabled(self):
        """No /slack/events route when Slack is not configured."""
        client = self.app.test_client()
        resp = client.post('/slack/events')
        assert resp.status_code == 404


class TestSlackEnabled:
    """Tests for when Slack IS configured with Socket Mode."""

    @pytest.fixture(autouse=True)
    def setup_app(self):
        """Create app with Slack configured (mocking Bolt App and SocketModeHandler)."""
        import esb.slack as slack_mod
        slack_mod._bolt_app = None
        slack_mod._socket_handler = None

        self.mock_bolt_app = MagicMock()
        self.mock_socket_handler = MagicMock()

        with patch.object(SlackTestConfig, 'SLACK_BOT_TOKEN', 'xoxb-test-token'), \
             patch.object(SlackTestConfig, 'SLACK_APP_TOKEN', 'xapp-test-token'), \
             patch.object(SlackTestConfig, 'SLACK_SOCKET_MODE_CONNECT', 'true'), \
             patch('slack_bolt.App', return_value=self.mock_bolt_app) as self.mock_app_cls, \
             patch('slack_bolt.adapter.socket_mode.SocketModeHandler',
                   return_value=self.mock_socket_handler), \
             patch('atexit.register') as self.mock_atexit, \
             patch('signal.signal') as self.mock_signal:
            self.app = create_app('slack_test')

            with self.app.app_context():
                from esb.extensions import db
                db.create_all()
                yield
                db.session.remove()
                db.drop_all()

        slack_mod._bolt_app = None
        slack_mod._socket_handler = None

    def test_slack_module_loads_when_configured(self):
        """Slack module initializes when tokens are configured."""
        import esb.slack as slack_mod
        assert slack_mod._bolt_app is not None
        assert slack_mod._socket_handler is not None

    def test_socket_mode_connect_called(self):
        """SocketModeHandler.connect() is called during init."""
        self.mock_socket_handler.connect.assert_called_once()

    def test_atexit_registered(self):
        """atexit.register is called with _shutdown_socket."""
        import esb.slack as slack_mod
        self.mock_atexit.assert_called_once_with(slack_mod._shutdown_socket)

    def test_sigterm_handler_registered(self):
        """SIGTERM signal handler is registered."""
        sigterm_calls = [c for c in self.mock_signal.call_args_list if c[0][0] == signal.SIGTERM]
        assert len(sigterm_calls) == 1
        # The second argument should be a callable (the _sigterm_handler function)
        assert callable(sigterm_calls[0][0][1])

    def test_register_handlers_called(self):
        """register_handlers is called during init_slack() when Slack is enabled."""
        assert self.mock_bolt_app.command.called

    def test_command_handlers_registered(self):
        """Command handlers are registered on the Bolt app."""
        command_calls = [call[0][0] for call in self.mock_bolt_app.command.call_args_list]
        assert '/esb-report' in command_calls
        assert '/esb-repair' in command_calls
        assert '/esb-status' in command_calls
        assert '/esb-update' not in command_calls

    def test_view_handlers_registered(self):
        """View submission handlers are registered on the Bolt app."""
        view_calls = [call[0][0] for call in self.mock_bolt_app.view.call_args_list]
        assert 'problem_report_submission' in view_calls
        assert 'repair_create_submission' in view_calls
        assert 'repair_update_submission' not in view_calls

    def test_app_starts_cleanly_with_slack(self):
        """App starts and responds to health check with Slack configured."""
        client = self.app.test_client()
        resp = client.get('/health')
        assert resp.status_code == 200

    def test_no_http_slack_route(self):
        """No /slack/events HTTP route exists in Socket Mode."""
        rules = [rule.rule for rule in self.app.url_map.iter_rules()]
        assert '/slack/events' not in rules


class TestSlackMissingAppToken:
    """Tests for when SLACK_BOT_TOKEN is set but SLACK_APP_TOKEN is missing."""

    def test_slack_disabled_without_app_token(self):
        """Slack module is not loaded when SLACK_APP_TOKEN is missing."""
        import esb.slack as slack_mod

        with patch.object(Config, 'SLACK_BOT_TOKEN', 'xoxb-test-token'), \
             patch.object(Config, 'SLACK_APP_TOKEN', ''), \
             patch('slack_bolt.adapter.socket_mode.SocketModeHandler') as mock_smh:
            app = create_app('testing')
            with app.app_context():
                from esb.extensions import db
                db.create_all()

                assert slack_mod._bolt_app is None
                assert slack_mod._socket_handler is None
                mock_smh.assert_not_called()

                db.session.remove()
                db.drop_all()

        slack_mod._bolt_app = None
        slack_mod._socket_handler = None


class TestSlackTestingModeSkipsConnect:
    """Verify TESTING=True skips SocketModeHandler construction."""

    def test_testing_mode_skips_connect(self):
        """Bolt app is initialized but SocketModeHandler is never constructed in testing mode."""
        import esb.slack as slack_mod
        slack_mod._bolt_app = None
        slack_mod._socket_handler = None

        mock_bolt_app = MagicMock()

        with patch.object(Config, 'SLACK_BOT_TOKEN', 'xoxb-test-token'), \
             patch.object(Config, 'SLACK_APP_TOKEN', 'xapp-test-token'), \
             patch('slack_bolt.App', return_value=mock_bolt_app), \
             patch('slack_bolt.adapter.socket_mode.SocketModeHandler') as mock_smh:
            app = create_app('testing')
            with app.app_context():
                from esb.extensions import db
                db.create_all()

                assert slack_mod._bolt_app is not None
                assert slack_mod._socket_handler is None
                mock_smh.assert_not_called()

                db.session.remove()
                db.drop_all()

        slack_mod._bolt_app = None
        slack_mod._socket_handler = None


class TestSlackConnectSkippedWhenNotOptedIn:
    """Verify socket connection is skipped when SLACK_SOCKET_MODE_CONNECT is not 'true'."""

    def test_connect_skipped_when_not_opted_in(self):
        """Bolt app is initialized but no socket connection when SLACK_SOCKET_MODE_CONNECT is empty."""
        import esb.slack as slack_mod
        slack_mod._bolt_app = None
        slack_mod._socket_handler = None

        mock_bolt_app = MagicMock()

        with patch.object(SlackTestConfig, 'SLACK_BOT_TOKEN', 'xoxb-test-token'), \
             patch.object(SlackTestConfig, 'SLACK_APP_TOKEN', 'xapp-test-token'), \
             patch.object(SlackTestConfig, 'SLACK_SOCKET_MODE_CONNECT', ''), \
             patch('slack_bolt.App', return_value=mock_bolt_app), \
             patch('slack_bolt.adapter.socket_mode.SocketModeHandler') as mock_smh:
            app = create_app('slack_test')
            with app.app_context():
                from esb.extensions import db
                db.create_all()

                assert slack_mod._bolt_app is not None
                assert slack_mod._socket_handler is None
                mock_smh.assert_not_called()

                db.session.remove()
                db.drop_all()

        slack_mod._bolt_app = None
        slack_mod._socket_handler = None


class TestSlackConnectFailure:
    """Verify graceful degradation when SocketModeHandler.connect() fails."""

    def test_connect_failure_does_not_crash_app(self):
        """App starts cleanly even if Socket Mode connect() raises an exception."""
        import esb.slack as slack_mod
        slack_mod._bolt_app = None
        slack_mod._socket_handler = None

        mock_bolt_app = MagicMock()
        mock_handler = MagicMock()
        mock_handler.connect.side_effect = Exception('Network error')

        with patch.object(SlackTestConfig, 'SLACK_BOT_TOKEN', 'xoxb-test-token'), \
             patch.object(SlackTestConfig, 'SLACK_APP_TOKEN', 'xapp-test-token'), \
             patch.object(SlackTestConfig, 'SLACK_SOCKET_MODE_CONNECT', 'true'), \
             patch('slack_bolt.App', return_value=mock_bolt_app), \
             patch('slack_bolt.adapter.socket_mode.SocketModeHandler',
                   return_value=mock_handler):
            app = create_app('slack_test')
            with app.app_context():
                from esb.extensions import db
                db.create_all()

                assert slack_mod._bolt_app is not None
                assert slack_mod._socket_handler is None

                client = app.test_client()
                resp = client.get('/health')
                assert resp.status_code == 200

                db.session.remove()
                db.drop_all()

        slack_mod._bolt_app = None
        slack_mod._socket_handler = None
