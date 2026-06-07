"""ESB application package."""

import os
from datetime import datetime, timezone

from flask import Flask, flash, redirect, render_template, request, session, url_for

from esb.config import config
from esb.extensions import csrf, db, login_manager, migrate
from esb.services.repair_service import CLOSED_STATUSES
from esb.utils.filters import register_filters
from esb.views import register_blueprints

_newrelic_initialized = False


def create_app(config_name='default'):
    """Create and configure the Flask application.

    Args:
        config_name: Configuration key ('development', 'testing', 'production', 'default').
    """
    global _newrelic_initialized
    nr_license = os.environ.get('NEW_RELIC_LICENSE_KEY', '')
    if nr_license and not _newrelic_initialized:
        import newrelic.agent
        settings = newrelic.agent.global_settings()
        settings.license_key = nr_license
        settings.app_name = os.environ.get('NEW_RELIC_APP_NAME', 'Equipment Status Board')
        settings.browser_monitoring.auto_instrument = False
        newrelic.agent.initialize()
        _newrelic_initialized = True

    app = Flask(__name__)
    app.config.from_object(config[config_name])

    # Normalize UPLOAD_PATH to absolute so file serving is not sensitive to
    # the process working directory (which can differ between dev and Docker).
    _upload_path = app.config.get('UPLOAD_PATH', 'uploads')
    if not os.path.isabs(_upload_path):
        app.config['UPLOAD_PATH'] = os.path.abspath(_upload_path)

    # Fail fast on an invalid QR template config — a misconfigured template
    # should stop startup with a specific message, not surface per-request.
    _qr_template_config_path = app.config.get('QR_TEMPLATE_CONFIG_PATH', '')
    if _qr_template_config_path:
        from esb.services import qr_service
        app.config['QR_TEMPLATE'] = qr_service.load_template_config(_qr_template_config_path)
    else:
        app.config['QR_TEMPLATE'] = None

    # Initialize extensions
    db.init_app(app)
    login_manager.init_app(app)
    migrate.init_app(app, db)
    csrf.init_app(app)

    # Import models so Alembic can detect them
    import esb.models  # noqa: F401

    from esb.services import auth_service

    @login_manager.user_loader
    def load_user(user_id):
        return auth_service.load_user(user_id)

    login_manager.login_message_category = 'warning'

    @app.before_request
    def enforce_permanent_session():
        session.permanent = True

    # Register blueprints
    register_blueprints(app)

    # Initialize Slack integration (conditional on SLACK_BOT_TOKEN and SLACK_APP_TOKEN)
    from esb.slack import init_slack
    init_slack(app)

    # Register custom Jinja2 filters
    register_filters(app)

    @app.context_processor
    def inject_current_year():
        return {'current_year': datetime.now(timezone.utc).year}

    @app.context_processor
    def inject_repair_constants():
        return {'CLOSED_STATUSES': CLOSED_STATUSES}

    # New Relic browser monitoring context processor
    if nr_license:
        @app.context_processor
        def newrelic_browser_snippets():
            import newrelic.agent
            return {
                'newrelic_browser_header': newrelic.agent.get_browser_timing_header(),
            }

    # Register error handlers
    @app.errorhandler(403)
    def forbidden(e):
        return render_template('errors/403.html'), 403

    @app.errorhandler(404)
    def not_found(e):
        return render_template('errors/404.html'), 404

    @app.errorhandler(413)
    def request_entity_too_large(e):
        flash(
            f'File is too large. Maximum size is {app.config["UPLOAD_MAX_SIZE_MB"]} MB.',
            'danger',
        )
        return redirect(request.referrer or url_for('equipment.index')), 302

    @app.errorhandler(500)
    def internal_error(e):
        return render_template('errors/500.html'), 500

    # Health / index route
    @app.route('/')
    def index():
        return redirect(url_for('public.status_dashboard'))

    @app.route('/health')
    def health():
        return 'ok'

    # Unauthenticated Prometheus metrics endpoint. Exposes two gauges from
    # the pending_notifications table so a stuck worker, a bad Slack token,
    # or a Slack outage shows up as queue growth / staleness in Prometheus.
    @app.route('/metrics')
    def metrics():
        from flask import Response

        from esb.services import metrics_service

        body, content_type = metrics_service.render_metrics()
        # Use content_type (not mimetype) so the full Prometheus exposition
        # Content-Type header (which includes 'version=...; charset=utf-8')
        # is preserved verbatim. Flask's mimetype= drops parameters.
        return Response(body, content_type=content_type)

    # CLI commands
    _register_cli(app)

    return app


def _register_cli(app):
    """Register Flask CLI commands."""
    import click

    from esb.extensions import db as _db
    from esb.models.user import User

    @app.cli.group()
    def worker():
        """Background worker commands."""
        pass

    @worker.command('run')
    @click.option('--poll-interval', default=30, type=int,
                  help='Seconds between polling cycles (default: 30)')
    def worker_run(poll_interval):
        """Run the background notification worker."""
        from esb.services import notification_service

        click.echo(f'Starting notification worker (poll interval: {poll_interval}s)')
        notification_service.run_worker_loop(poll_interval=poll_interval)

    @app.cli.command('seed-admin')
    @click.argument('username')
    @click.argument('email')
    @click.option('--password', prompt=True, hide_input=True,
                  confirmation_prompt=True, help='Password for the new admin user.')
    @click.option('--slack-handle', default=None,
                  help='Slack handle for the new admin user (e.g. @username).')
    def seed_admin(username, email, password, slack_handle):
        """Create an initial staff user if none exists."""
        existing = _db.session.execute(
            _db.select(User).filter_by(role='staff')
        ).scalars().first()
        if existing:
            click.echo(f'Staff user already exists: {existing.username}')
            return
        normalized_slack_handle = slack_handle.strip() if slack_handle else None
        if normalized_slack_handle == '':
            normalized_slack_handle = None
        elif normalized_slack_handle is not None and len(normalized_slack_handle) > 80:
            raise click.ClickException('Slack handle must be 80 characters or fewer.')
        user = User(username=username, email=email, role='staff', slack_handle=normalized_slack_handle)
        user.set_password(password)
        _db.session.add(user)
        _db.session.commit()
        click.echo(f'Created staff user: {username}')
