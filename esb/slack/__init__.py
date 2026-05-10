"""Slack App handlers package."""

import atexit
import logging
import signal

logger = logging.getLogger(__name__)

# Module-level state (set during init_slack)
_bolt_app = None
_socket_handler = None
_socket_mode_intended: bool = False


def init_slack(app):
    """Initialize Slack Bolt app with Socket Mode.

    Skips initialization if SLACK_BOT_TOKEN or SLACK_APP_TOKEN is not configured.
    Skips Socket Mode connection if TESTING config is True or
    SLACK_SOCKET_MODE_CONNECT config is not 'true' (opt-in).
    Called from create_app() in esb/__init__.py.
    """
    global _bolt_app, _socket_handler, _socket_mode_intended
    # Reset all module-level state up front so re-entry (test fixtures, or any
    # caller that re-invokes init_slack with different config) cannot leave a
    # stale (_bolt_app, _socket_handler, _socket_mode_intended) tuple from the
    # previous call. Without this, an early-return path (no token / TESTING /
    # opt-out) would leave a previously-bound _socket_handler dangling, which
    # the metrics view would then report as connected=1, enabled=0 — an
    # impossible state by design that the alert rule cannot match.
    #
    # Call _shutdown_socket() FIRST so we close any prior live WebSocket
    # before dropping the reference. _shutdown_socket() is idempotent: if
    # _socket_handler is already None it is a no-op. Without this, a previous
    # successful init's WebSocket would leak — atexit/SIGTERM hooks no longer
    # have a reference to close.
    _shutdown_socket()
    _bolt_app = None
    _socket_mode_intended = False

    token = app.config.get('SLACK_BOT_TOKEN', '')
    app_token = app.config.get('SLACK_APP_TOKEN', '')

    if not token:
        logger.info('SLACK_BOT_TOKEN not configured, Slack module disabled')
        return

    if not app_token:
        logger.warning('SLACK_APP_TOKEN not configured, Slack module disabled')
        return

    from slack_bolt import App
    from slack_sdk import WebClient

    # Pin the Bolt-managed WebClient to the same 15s timeout used by the
    # service-layer call sites. Without this, slash-command handlers receive a
    # WebClient with slack_sdk's default timeout=30, which is too long for the
    # request path -- a Slack outage could wedge a handler thread.
    _bolt_app = App(token=token, client=WebClient(token=token, timeout=15))

    # Register command and view submission handlers
    from esb.slack.handlers import register_handlers
    register_handlers(_bolt_app, app)

    logger.info('Slack Bolt app initialized successfully')

    # Skip socket connection in tests
    if app.config.get('TESTING'):
        logger.info('Testing mode, skipping Socket Mode connection')
        return

    # Opt-in: only connect when SLACK_SOCKET_MODE_CONNECT is explicitly 'true'
    if app.config['SLACK_SOCKET_MODE_CONNECT'].lower() != 'true':
        logger.info('SLACK_SOCKET_MODE_CONNECT is not true, skipping Socket Mode connection')
        return

    # Unified Socket Mode setup: import, instantiation, and connect all live
    # inside the same try/except so the actionable failure mode
    # (enabled=1, connected=0) covers ImportError, instantiation errors, AND
    # connect errors with a single Failed-to-set-up warning.
    try:
        _socket_mode_intended = True   # set FIRST — before handler binding —
                                       # so there is no (False, True) window.
        from slack_bolt.adapter.socket_mode import SocketModeHandler
        _socket_handler = SocketModeHandler(app=_bolt_app, app_token=app_token)
        _socket_handler.connect()
        logger.info('Slack Socket Mode connected')
    except Exception:
        logger.warning(
            'Failed to set up Slack Socket Mode — app will run without Slack',
            exc_info=True,
        )
        _socket_handler = None
        return

    atexit.register(_shutdown_socket)

    # SIGTERM handler for environments that don't trigger atexit on SIGTERM
    # (e.g., Flask dev server). Gunicorn handles SIGTERM gracefully already,
    # but the explicit handler is harmless and covers other runtimes.
    # signal.signal() can only be called from the main thread.
    import threading
    if threading.current_thread() is threading.main_thread():
        prev_handler = signal.getsignal(signal.SIGTERM)

        def _sigterm_handler(signum, frame):
            _shutdown_socket()
            if callable(prev_handler) and prev_handler not in (signal.SIG_DFL, signal.SIG_IGN):
                prev_handler(signum, frame)

        signal.signal(signal.SIGTERM, _sigterm_handler)
    else:
        logger.debug('Not main thread, skipping SIGTERM handler registration')


def _shutdown_socket():
    """Cleanly close the Socket Mode WebSocket on shutdown.

    Intentionally idempotent — may be called from both the SIGTERM handler
    and atexit during the same shutdown sequence.
    """
    global _socket_handler
    if _socket_handler is not None:
        try:
            _socket_handler.close()
            logger.info('Slack Socket Mode disconnected')
        except Exception:
            logger.warning('Error closing Socket Mode connection', exc_info=True)
        _socket_handler = None


def is_socket_mode_enabled() -> bool:
    """True iff the most recent init_slack() call entered the Socket Mode setup
    block (tokens set, not TESTING, opt-in flag true). False on any of the four
    early-return paths or if the setup block was never reached."""
    return _socket_mode_intended


def is_socket_mode_connected() -> bool:
    """True iff a Bolt SocketModeHandler is currently bound. Transitions
    True→False at process shutdown via _shutdown_socket(). Slack Bolt does
    not expose mid-life WebSocket connection-state callbacks."""
    return _socket_handler is not None
