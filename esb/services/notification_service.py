"""Notification queue management and background worker."""

import logging
import signal
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from esb.extensions import db
from esb.models.app_config import AppConfig
from esb.models.pending_notification import PendingNotification
from esb.utils.exceptions import ValidationError
from esb.utils.logging import log_mutation

logger = logging.getLogger(__name__)

# Outbound Slack message emoji prefixes (event-type indicators on the leading
# character of a notification). The status-indicator emoji set lives in
# esb/slack/forms.py::_STATUS_EMOJI; these are intentionally distinct surfaces
# even when they reuse the same glyph (e.g., :white_check_mark: appears here
# for "resolved" and there for "Operational").
_NEW_REPORT_PREFIX = ':rotating_light: '
_SAFETY_RISK_PREFIX = ':warning: *SAFETY RISK* :warning: '
_SEVERITY_PREFIX = ':wrench: '
_STATUS_PREFIX = ':arrows_counterclockwise: '
_ETA_PREFIX = ':calendar: '
_RESOLVED_PREFIX = ':white_check_mark: '
_ASSIGNEE_PREFIX = ':bust_in_silhouette: '

# Exponential backoff schedule (in seconds): 30s, 1m, 2m, 5m, 15m, 1h max
BACKOFF_SCHEDULE = [30, 60, 120, 300, 900, 3600]

# Maximum retry attempts before marking a notification as permanently failed
MAX_RETRIES = 10

# Valid notification types accepted by the queue
VALID_NOTIFICATION_TYPES = {'slack_message', 'static_page_push'}

# Default batch size for polling queries
DEFAULT_BATCH_SIZE = 100


def _write_heartbeat(path: Path) -> None:
    """Touch the worker heartbeat file. Logged-but-swallowed on OSError so a
    transient filesystem hiccup cannot abort the loop."""
    try:
        path.touch()
    except OSError:
        logger.warning(
            'Failed to update worker heartbeat at %s', path, exc_info=True,
        )


def _record_iteration_timestamp() -> None:
    """Upsert the worker's last-iteration timestamp into AppConfig.

    Catches SQLAlchemyError (covers OperationalError from transient DB drops
    and ProgrammingError from a missing app_config table on pre-migration
    deployments — both subclasses of SQLAlchemyError). On error: rollback
    the session and log a warning. Do not propagate.
    """
    now_iso = datetime.now(UTC).isoformat()
    try:
        row = db.session.execute(
            select(AppConfig).where(AppConfig.key == 'worker_last_iteration_at')
        ).scalar_one_or_none()
        if row is None:
            db.session.add(AppConfig(key='worker_last_iteration_at', value=now_iso))
        else:
            row.value = now_iso
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        logger.warning('Failed to update worker last-iteration timestamp', exc_info=True)


def queue_notification(
    notification_type: str,
    target: str,
    payload: dict | None = None,
) -> PendingNotification:
    """Insert a notification into the queue for background delivery.

    Args:
        notification_type: Type of notification ('slack_message', 'static_page_push').
        target: Delivery target (Slack channel name, push destination).
        payload: JSON-serializable data for the notification.

    Returns:
        The created PendingNotification.
    """
    if notification_type not in VALID_NOTIFICATION_TYPES:
        raise ValidationError(
            f'Invalid notification_type: {notification_type!r}. '
            f'Must be one of: {", ".join(sorted(VALID_NOTIFICATION_TYPES))}'
        )

    notification = PendingNotification(
        notification_type=notification_type,
        target=target,
        payload=payload,
        status='pending',
    )
    db.session.add(notification)
    db.session.commit()

    log_mutation('notification.queued', 'system', {
        'id': notification.id,
        'type': notification_type,
        'target': target,
    })

    return notification


def get_pending_notifications(batch_size: int = DEFAULT_BATCH_SIZE) -> list[PendingNotification]:
    """Get notifications ready for delivery.

    Returns notifications where status is 'pending' and either
    next_retry_at is NULL (first attempt) or next_retry_at <= now.

    Args:
        batch_size: Maximum number of notifications to return per poll cycle.
    """
    now = datetime.now(UTC)
    return list(
        db.session.execute(
            db.select(PendingNotification)
            .filter_by(status='pending')
            .filter(
                db.or_(
                    PendingNotification.next_retry_at.is_(None),
                    PendingNotification.next_retry_at <= now,
                )
            )
            .order_by(PendingNotification.created_at.asc())
            .limit(batch_size)
        ).scalars().all()
    )


def mark_delivered(notification_id: int) -> PendingNotification:
    """Mark a notification as successfully delivered."""
    notification = db.session.get(PendingNotification, notification_id)
    if notification is None:
        raise ValidationError(f'Notification {notification_id} not found')
    notification.status = 'delivered'
    notification.delivered_at = datetime.now(UTC)
    db.session.commit()

    log_mutation('notification.delivered', 'system', {
        'id': notification.id,
        'type': notification.notification_type,
        'target': notification.target,
    })

    return notification


def mark_failed(notification_id: int, error_message: str) -> PendingNotification:
    """Mark a notification delivery as failed with exponential backoff.

    Backoff schedule: 30s, 1m, 2m, 5m, 15m, max 1h.
    After MAX_RETRIES attempts, marks the notification as permanently 'failed'.
    """
    notification = db.session.get(PendingNotification, notification_id)
    if notification is None:
        raise ValidationError(f'Notification {notification_id} not found')
    notification.retry_count += 1
    notification.error_message = error_message

    if notification.retry_count >= MAX_RETRIES:
        # Permanently failed — stop retrying
        notification.status = 'failed'
        notification.next_retry_at = None
        db.session.commit()

        log_mutation('notification.permanently_failed', 'system', {
            'id': notification.id,
            'type': notification.notification_type,
            'target': notification.target,
            'retry_count': notification.retry_count,
            'error': error_message,
        })

        return notification

    # Compute backoff delay
    backoff_index = min(notification.retry_count - 1, len(BACKOFF_SCHEDULE) - 1)
    backoff_seconds = BACKOFF_SCHEDULE[backoff_index]
    notification.next_retry_at = datetime.now(UTC) + timedelta(seconds=backoff_seconds)

    db.session.commit()

    log_mutation('notification.failed', 'system', {
        'id': notification.id,
        'type': notification.notification_type,
        'target': notification.target,
        'retry_count': notification.retry_count,
        'error': error_message,
        'next_retry_at': notification.next_retry_at.isoformat(),
    })

    return notification


def process_notification(notification: PendingNotification) -> None:
    """Dispatch a notification to the appropriate delivery handler.

    Args:
        notification: The PendingNotification to process.

    Raises:
        ValueError: For unknown notification types.
    """
    handlers = {
        'slack_message': _deliver_slack_message,
        'static_page_push': _deliver_static_page_push,
    }

    handler = handlers.get(notification.notification_type)
    if handler is None:
        raise ValueError(f'Unknown notification type: {notification.notification_type!r}')

    handler(notification)


def _deliver_slack_message(notification: PendingNotification) -> None:
    """Deliver a Slack message notification via WebClient.

    Posts the message to the notification's target channel and also to
    the configured #oops channel (for visibility).

    Raises:
        RuntimeError: if SLACK_BOT_TOKEN is not configured.
        slack_sdk.errors.SlackApiError: on Slack API errors (worker will retry).
    """
    from flask import current_app

    token = current_app.config.get('SLACK_BOT_TOKEN', '')
    if not token:
        raise RuntimeError(
            'SLACK_BOT_TOKEN not configured -- cannot deliver Slack messages'
        )

    from slack_sdk import WebClient

    # timeout caps each Slack HTTP call so a hung connection cannot wedge the
    # worker loop indefinitely.
    client = WebClient(token=token, timeout=15)
    # Copy the payload: notification.payload aliases the ORM db.JSON attribute,
    # and the assignee_display we add below must not mutate the persisted model.
    payload = dict(notification.payload or {})

    # Delivery-time mention resolution: turn the queued assignee identity into a
    # real Slack @mention (<@U...>) when possible, falling back to the plain
    # username. Only the NEW assignee is resolved; the old one stays plain text.
    if payload.get('assignee_username'):
        if payload.get('assignee_has_slack') and payload.get('assignee_email'):
            try:
                result = client.users_lookupByEmail(email=payload['assignee_email'])
                slack_user_id = result['user']['id']
                payload['assignee_display'] = f'<@{slack_user_id}>'
            except Exception:
                # Any Slack API error / missing id degrades to the plain
                # username. The lookup must never raise out of delivery.
                logger.info(
                    'Assignee Slack lookup failed for notification=%d, '
                    'falling back to username', notification.id, exc_info=True,
                )
                payload['assignee_display'] = payload['assignee_username']
        else:
            # No Slack handle (or, defensively, no email) -- use plain username.
            payload['assignee_display'] = payload['assignee_username']

    text, blocks = _format_slack_message(payload)

    # Post to primary target channel (area-specific or #general)
    client.chat_postMessage(
        channel=notification.target,
        text=text,
        blocks=blocks,
    )
    logger.info(
        'Slack message delivered to %s (notification=%d)',
        notification.target, notification.id,
    )

    # Post to #oops for cross-area visibility
    oops_channel = current_app.config.get('SLACK_OOPS_CHANNEL', '#oops')
    if notification.target not in (oops_channel, '#general'):
        try:
            client.chat_postMessage(
                channel=oops_channel,
                text=text,
                blocks=blocks,
            )
            logger.info(
                'Slack message also delivered to %s (notification=%d)',
                oops_channel, notification.id,
            )
        except Exception:
            logger.warning(
                'Failed to post to %s (notification=%d), primary delivery succeeded',
                oops_channel, notification.id,
                exc_info=True,
            )


def _format_slack_message(payload: dict) -> tuple[str, list | None]:
    """Format a Slack notification message based on event type.

    Args:
        payload: Notification payload dict with 'event_type' and event-specific fields.

    Returns:
        Tuple of (text, blocks) where text is the fallback and blocks is the rich format.
        blocks may be None if simple text is sufficient.
    """
    event_type = payload.get('event_type', 'unknown')
    equipment_name = payload.get('equipment_name', 'Unknown Equipment')
    area_name = payload.get('area_name', 'Unknown Area')

    if event_type == 'new_report':
        prefix = _SAFETY_RISK_PREFIX if payload.get('has_safety_risk') else _NEW_REPORT_PREFIX
        severity = payload.get('severity', 'Unknown')
        description = payload.get('description', '')
        reporter = payload.get('reporter_name', 'Unknown')
        text = (
            f'{prefix}New problem report: *{equipment_name}* ({area_name})\n'
            f'Severity: {severity} | Reported by: {reporter}\n'
            f'{description}'
        )
        # Enriched when created already assigned. Detection is by key presence;
        # creation never unassigns, so assignee_username/assignee_display are
        # always truthy/set here.
        if 'assignee_username' in payload:
            text += f'\nAssigned to: {payload.get("assignee_display")}'

    elif event_type == 'resolved':
        new_status = payload.get('new_status', 'Resolved')
        if new_status == 'Resolved':
            text = (
                f'{_RESOLVED_PREFIX}*{equipment_name}* ({area_name}) is back in service\n'
                f'Status: {new_status}'
            )
        else:
            # Closed-as-Duplicate / Closed-as-No-Issue-Found etc. -- closure, not "back in service"
            text = (
                f'{_RESOLVED_PREFIX}*{equipment_name}* ({area_name}) closed: {new_status}\n'
                f'Status: {new_status}'
            )

    elif event_type == 'severity_changed':
        prefix = _SAFETY_RISK_PREFIX if payload.get('has_safety_risk') else _SEVERITY_PREFIX
        old_severity = payload.get('old_severity', 'Unknown')
        new_severity = payload.get('new_severity', 'Unknown')
        text = (
            f'{prefix}Severity changed: *{equipment_name}* ({area_name})\n'
            f'{old_severity} -> {new_severity}'
        )

    elif event_type == 'status_changed':
        old_status = payload.get('old_status', 'Unknown')
        new_status = payload.get('new_status', 'Unknown')
        text = (
            f'{_STATUS_PREFIX}Status changed: *{equipment_name}* ({area_name})\n'
            f'{old_status} -> {new_status}'
        )
        # Enriched assignee line when the assignee changed in the same update.
        # Detect by KEY PRESENCE (not truthiness) so unassignment still renders.
        # NOTE: the reassignment wording here intentionally differs from the
        # assignee_changed branch below -- do not factor into a shared helper.
        if 'assignee_username' in payload:
            old_assignee = payload.get('old_assignee_username')
            if payload.get('assignee_username') is None:
                text += f'\nUnassigned (was {old_assignee})'
            elif not old_assignee:
                text += f'\nAssigned to: {payload.get("assignee_display")}'
            else:
                text += f'\nAssigned to: {payload.get("assignee_display")} (was {old_assignee})'

    elif event_type == 'assignee_changed':
        old_assignee = payload.get('old_assignee_username')
        heading = f'{_ASSIGNEE_PREFIX}Assignee changed: *{equipment_name}* ({area_name})'
        if payload.get('assignee_username') is None:
            text = f'{heading}\nUnassigned (was {old_assignee})'
        elif not old_assignee:
            text = f'{heading}\nAssigned to: {payload.get("assignee_display")}'
        else:
            text = f'{heading}\nReassigned: {old_assignee} -> {payload.get("assignee_display")}'

    elif event_type == 'eta_updated':
        eta = payload.get('eta', 'Unknown')
        old_eta = payload.get('old_eta')
        eta_text = f'ETA: {eta}'
        if old_eta:
            eta_text = f'ETA updated: {old_eta} -> {eta}'
        text = f'{_ETA_PREFIX}ETA update: *{equipment_name}* ({area_name})\n{eta_text}'

    else:
        text = f'Equipment notification: *{equipment_name}* ({area_name})'

    return text, None  # blocks=None for v1 -- plain text with mrkdwn formatting


def _deliver_static_page_push(notification: PendingNotification) -> None:
    """Generate and push the static status page.

    Called by the background worker when processing a static_page_push
    notification. Delegates to static_page_service for rendering and push.

    Raises:
        RuntimeError: if generation or push fails (worker will retry).
    """
    from esb.services import static_page_service

    logger.info(
        'Static page push triggered (notification=%d, payload=%s)',
        notification.id, notification.payload,
    )
    static_page_service.generate_and_push()


def run_worker_loop(poll_interval: int = 30) -> None:
    """Main worker polling loop.

    Polls the pending_notifications table every `poll_interval` seconds
    and processes each ready notification. Handles errors gracefully by
    marking failed notifications for retry.

    Args:
        poll_interval: Seconds between polling cycles (default 30).
    """
    from flask import current_app

    _shutdown = False

    def _handle_signal(signum, frame):
        nonlocal _shutdown
        logger.info('Received signal %s, shutting down gracefully...', signum)
        _shutdown = True

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    heartbeat_path = Path(current_app.config['WORKER_HEARTBEAT_PATH'])

    # Write an initial heartbeat so the file exists for the Docker healthcheck
    # before the first iteration completes. After this, the heartbeat is
    # refreshed at every point of forward progress: after the DB poll returns,
    # and after each notification is processed (success or recorded failure).
    # A hang inside get_pending_notifications() or inside a single
    # process_notification() call leaves the file stale, so the healthcheck
    # (and autoheal) will catch it. Refreshing per-notification matters because
    # a large batch of slow Slack calls (DEFAULT_BATCH_SIZE=100 * 15s timeout)
    # can otherwise legitimately exceed the 180s healthcheck threshold.
    _write_heartbeat(heartbeat_path)

    logger.info(
        'Worker started, polling every %d seconds (heartbeat=%s)',
        poll_interval, heartbeat_path,
    )

    consecutive_poll_failures = 0

    while not _shutdown:
        try:
            notifications = get_pending_notifications()
            # Refresh after the DB poll returns: an idle iteration with no
            # pending rows still represents forward progress.
            _write_heartbeat(heartbeat_path)
            consecutive_poll_failures = 0  # Reset on successful poll
            if notifications:
                logger.info('Processing %d pending notification(s)', len(notifications))

            for notification in notifications:
                if _shutdown:
                    break
                try:
                    logger.info(
                        'Processing notification %d (type=%s, target=%s)',
                        notification.id, notification.notification_type, notification.target,
                    )
                    process_notification(notification)
                    mark_delivered(notification.id)
                    logger.info('Notification %d delivered successfully', notification.id)
                except NotImplementedError as e:
                    mark_failed(notification.id, str(e))
                    logger.warning('Notification %d: %s', notification.id, e)
                except Exception as e:
                    mark_failed(notification.id, str(e))
                    logger.error(
                        'Notification %d delivery failed: %s', notification.id, e,
                        exc_info=True,
                    )
                # Refresh after each notification regardless of outcome -- a
                # long but progressing batch of slow Slack calls must not be
                # mistaken for a hang.
                _write_heartbeat(heartbeat_path)

            # Record the iteration timestamp AFTER the for-loop, not before.
            # The helper's commit() with Flask-SQLAlchemy's default
            # expire_on_commit=True would otherwise expire every loaded
            # PendingNotification ORM instance, forcing a per-row refresh
            # SELECT on the next attribute access inside the for-loop. Placing
            # it post-loop also gives more meaningful "successful iteration"
            # semantics: ESBWorkerStalled fires when an iteration didn't
            # complete, not just when a poll succeeded but processing stalled.
            #
            # Defensive wrapper. The helper already catches SQLAlchemyError;
            # the only thing it can raise is a programming bug. Don't let that
            # abort the loop — log loudly and continue.
            try:
                _record_iteration_timestamp()
            except Exception:
                # CRITICAL: roll back the session before continuing. The
                # helper does db.session.add(AppConfig(...)) BEFORE
                # db.session.commit(). A non-SQLAlchemyError exception
                # (programming bug) raised between those two lines leaves an
                # unflushed AppConfig insert pending in the session. Without
                # this rollback, a subsequent commit in the next iteration
                # could commit that half-baked row as a side effect.
                # The rollback itself is wrapped: if it raises, we do NOT
                # want the exception to escalate into the outer poll-failure
                # except-clause and trigger exponential backoff. The
                # defensive wrapper's whole purpose is to absorb helper bugs.
                try:
                    db.session.rollback()
                except Exception:
                    logger.error(
                        'BUG: rollback after _record_iteration_timestamp '
                        'failure ALSO raised — session may be wedged',
                        exc_info=True,
                    )
                logger.error(
                    'BUG: _record_iteration_timestamp raised unexpectedly '
                    '— iteration metric will be stale',
                    exc_info=True,
                )

        except Exception:
            consecutive_poll_failures += 1
            backoff = min(poll_interval * (2 ** consecutive_poll_failures), 300)
            logger.error(
                'Error in worker polling loop (failure #%d, backoff %ds)',
                consecutive_poll_failures, backoff, exc_info=True,
            )
            if not _shutdown:
                time.sleep(backoff)
                continue

        if not _shutdown:
            time.sleep(poll_interval)

    logger.info('Worker shut down cleanly')
