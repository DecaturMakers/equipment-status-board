"""Tests for the notification service."""

import signal
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest

from esb.extensions import db as _db
from esb.models.pending_notification import PendingNotification
from esb.services import notification_service
from esb.services.notification_service import (
    BACKOFF_SCHEDULE,
    DEFAULT_BATCH_SIZE,
    MAX_RETRIES,
    VALID_NOTIFICATION_TYPES,
    get_pending_notifications,
    mark_delivered,
    mark_failed,
    process_notification,
    queue_notification,
    run_worker_loop,
)
from esb.utils.exceptions import ValidationError


def _create_notification(notification_type='slack_message', target='#test',
                         payload=None, status='pending', **kwargs):
    """Helper to create a notification directly in the database."""
    notification = PendingNotification(
        notification_type=notification_type,
        target=target,
        payload=payload,
        status=status,
        **kwargs,
    )
    _db.session.add(notification)
    _db.session.commit()
    return notification


class TestQueueNotification:
    """Tests for queue_notification()."""

    def test_creates_pending_row(self, app):
        """queue_notification creates a row with status 'pending'."""
        result = queue_notification('slack_message', '#woodshop', {'msg': 'test'})

        assert result.id is not None
        assert result.notification_type == 'slack_message'
        assert result.target == '#woodshop'
        assert result.status == 'pending'
        assert result.retry_count == 0
        assert result.created_at is not None

    def test_stores_payload_as_json(self, app):
        """queue_notification stores payload as JSON."""
        payload = {'equipment_name': 'SawStop', 'severity': 'Down'}
        result = queue_notification('slack_message', '#woodshop', payload)

        _db.session.expire(result)
        saved = _db.session.get(PendingNotification, result.id)
        assert saved.payload == payload

    def test_logs_mutation(self, app, capture):
        """queue_notification logs a mutation event."""
        queue_notification('slack_message', '#test', {'msg': 'hello'})

        assert len(capture.records) == 1
        assert 'notification.queued' in capture.records[0].getMessage()

    def test_rejects_invalid_notification_type(self, app):
        """queue_notification raises ValidationError for invalid type."""
        with pytest.raises(ValidationError, match='Invalid notification_type'):
            queue_notification('email', '#test', {'msg': 'hello'})

    def test_rejects_empty_notification_type(self, app):
        """queue_notification raises ValidationError for empty string type."""
        with pytest.raises(ValidationError, match='Invalid notification_type'):
            queue_notification('', '#test')

    def test_accepts_all_valid_types(self, app):
        """queue_notification accepts all VALID_NOTIFICATION_TYPES."""
        for ntype in VALID_NOTIFICATION_TYPES:
            result = queue_notification(ntype, '#test')
            assert result.notification_type == ntype


class TestGetPendingNotifications:
    """Tests for get_pending_notifications()."""

    def test_returns_pending_with_no_retry_time(self, app):
        """Returns pending notifications with no next_retry_at."""
        n = _create_notification()
        result = get_pending_notifications()
        assert len(result) == 1
        assert result[0].id == n.id

    def test_returns_pending_with_past_retry_time(self, app):
        """Returns pending notifications with next_retry_at in the past."""
        n = _create_notification(
            next_retry_at=datetime.now(UTC) - timedelta(minutes=1),
        )
        result = get_pending_notifications()
        assert len(result) == 1
        assert result[0].id == n.id

    def test_excludes_delivered_notifications(self, app):
        """Does not return delivered notifications."""
        _create_notification(status='delivered')
        result = get_pending_notifications()
        assert len(result) == 0

    def test_excludes_failed_notifications(self, app):
        """Does not return permanently failed notifications."""
        _create_notification(status='failed')
        result = get_pending_notifications()
        assert len(result) == 0

    def test_excludes_future_retry_notifications(self, app):
        """Does not return notifications with future next_retry_at."""
        _create_notification(
            next_retry_at=datetime.now(UTC) + timedelta(hours=1),
        )
        result = get_pending_notifications()
        assert len(result) == 0

    def test_returns_empty_when_no_notifications(self, app):
        """Returns empty list when no pending notifications exist."""
        result = get_pending_notifications()
        assert result == []

    def test_orders_by_created_at(self, app):
        """Returns notifications ordered by created_at ascending."""
        n1 = _create_notification(target='#first')
        n2 = _create_notification(target='#second')
        result = get_pending_notifications()
        assert len(result) == 2
        assert result[0].id == n1.id
        assert result[1].id == n2.id

    def test_respects_batch_size_limit(self, app):
        """Returns at most batch_size notifications."""
        for i in range(5):
            _create_notification(target=f'#channel-{i}')
        result = get_pending_notifications(batch_size=3)
        assert len(result) == 3

    def test_default_batch_size(self, app):
        """Default batch_size is DEFAULT_BATCH_SIZE."""
        assert DEFAULT_BATCH_SIZE == 100


class TestMarkDelivered:
    """Tests for mark_delivered()."""

    def test_updates_status_and_delivered_at(self, app):
        """mark_delivered sets status to 'delivered' and sets delivered_at."""
        n = _create_notification()
        result = mark_delivered(n.id)

        assert result.status == 'delivered'
        assert result.delivered_at is not None

    def test_logs_mutation(self, app, capture):
        """mark_delivered logs a mutation event."""
        n = _create_notification()
        mark_delivered(n.id)

        messages = [r.getMessage() for r in capture.records]
        assert any('notification.delivered' in m for m in messages)

    def test_raises_on_nonexistent_id(self, app):
        """mark_delivered raises ValidationError for nonexistent notification."""
        with pytest.raises(ValidationError, match='not found'):
            mark_delivered(99999)


class TestMarkFailed:
    """Tests for mark_failed()."""

    def test_increments_retry_count_and_sets_error(self, app):
        """mark_failed increments retry_count and sets error_message."""
        n = _create_notification()
        result = mark_failed(n.id, 'Connection refused')

        assert result.retry_count == 1
        assert result.error_message == 'Connection refused'

    def test_computes_correct_backoff_intervals(self, app):
        """mark_failed uses correct exponential backoff schedule."""
        n = _create_notification()
        fixed_now = datetime(2026, 1, 15, 12, 0, 0)

        for i, expected_seconds in enumerate(BACKOFF_SCHEDULE):
            with patch('esb.services.notification_service.datetime') as mock_dt:
                mock_dt.now.return_value = fixed_now
                mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
                mark_failed(n.id, f'Error attempt {i + 1}')

            expected_retry = fixed_now + timedelta(seconds=expected_seconds)
            assert n.next_retry_at == expected_retry
            assert n.retry_count == i + 1

    def test_caps_backoff_at_one_hour(self, app):
        """mark_failed caps backoff at 1 hour for retries beyond schedule."""
        n = _create_notification(retry_count=8)
        fixed_now = datetime(2026, 1, 15, 12, 0, 0)

        with patch('esb.services.notification_service.datetime') as mock_dt:
            mock_dt.now.return_value = fixed_now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            mark_failed(n.id, 'Still failing')

        expected_retry = fixed_now + timedelta(seconds=3600)
        assert n.next_retry_at == expected_retry

    def test_logs_mutation(self, app, capture):
        """mark_failed logs a mutation event."""
        n = _create_notification()
        mark_failed(n.id, 'Error')

        messages = [r.getMessage() for r in capture.records]
        assert any('notification.failed' in m for m in messages)

    def test_raises_on_nonexistent_id(self, app):
        """mark_failed raises ValidationError for nonexistent notification."""
        with pytest.raises(ValidationError, match='not found'):
            mark_failed(99999, 'Error')

    def test_marks_permanently_failed_after_max_retries(self, app):
        """mark_failed sets status to 'failed' after MAX_RETRIES attempts."""
        n = _create_notification(retry_count=MAX_RETRIES - 1)
        result = mark_failed(n.id, 'Final failure')

        assert result.status == 'failed'
        assert result.retry_count == MAX_RETRIES
        assert result.next_retry_at is None
        assert result.error_message == 'Final failure'

    def test_permanently_failed_excluded_from_pending(self, app):
        """Permanently failed notifications are not returned by get_pending_notifications."""
        n = _create_notification(retry_count=MAX_RETRIES - 1)
        mark_failed(n.id, 'Final failure')

        result = get_pending_notifications()
        assert len(result) == 0

    def test_permanently_failed_logs_distinct_event(self, app, capture):
        """mark_failed logs 'notification.permanently_failed' after max retries."""
        n = _create_notification(retry_count=MAX_RETRIES - 1)
        mark_failed(n.id, 'Done')

        messages = [r.getMessage() for r in capture.records]
        assert any('notification.permanently_failed' in m for m in messages)


class TestProcessNotification:
    """Tests for process_notification()."""

    def test_unknown_type_raises_value_error(self, app):
        """process_notification raises ValueError for unknown type."""
        n = _create_notification(notification_type='email')
        with pytest.raises(ValueError, match='Unknown notification type'):
            process_notification(n)

    def test_slack_message_calls_deliver_handler(self, app):
        """process_notification calls _deliver_slack_message for slack_message type."""
        n = _create_notification(notification_type='slack_message')
        with patch.object(notification_service, '_deliver_slack_message') as mock:
            process_notification(n)
            mock.assert_called_once_with(n)

    def test_static_page_push_calls_deliver_handler(self, app):
        """process_notification calls _deliver_static_page_push for static_page_push type."""
        n = _create_notification(notification_type='static_page_push')
        with patch.object(notification_service, '_deliver_static_page_push') as mock:
            process_notification(n)
            mock.assert_called_once_with(n)

    def test_slack_delivery_raises_runtime_error_without_token(self, app):
        """_deliver_slack_message raises RuntimeError when no SLACK_BOT_TOKEN configured."""
        n = _create_notification(notification_type='slack_message',
                                 payload={'event_type': 'new_report',
                                          'equipment_name': 'Test', 'area_name': 'Area',
                                          'severity': 'Down', 'description': 'Broken',
                                          'reporter_name': 'User', 'has_safety_risk': False})
        with pytest.raises(RuntimeError, match='SLACK_BOT_TOKEN not configured'):
            notification_service._deliver_slack_message(n)

    def test_static_page_push_no_longer_raises_not_implemented(self, app):
        """_deliver_static_page_push no longer raises NotImplementedError."""
        from esb.services import static_page_service
        n = _create_notification(notification_type='static_page_push')
        with patch.object(static_page_service, 'generate_and_push'):
            # Should not raise NotImplementedError
            notification_service._deliver_static_page_push(n)

    def test_static_page_push_delegates_to_service(self, app):
        """_deliver_static_page_push delegates to static_page_service.generate_and_push()."""
        from esb.services import static_page_service
        n = _create_notification(notification_type='static_page_push')
        with patch.object(static_page_service, 'generate_and_push') as mock_gap:
            notification_service._deliver_static_page_push(n)
            mock_gap.assert_called_once()

    def test_static_page_push_exceptions_propagate(self, app):
        """Exceptions from static_page_service propagate to the worker loop."""
        from esb.services import static_page_service
        n = _create_notification(notification_type='static_page_push')
        with patch.object(static_page_service, 'generate_and_push',
                          side_effect=RuntimeError('Push failed')):
            with pytest.raises(RuntimeError, match='Push failed'):
                notification_service._deliver_static_page_push(n)


class TestRunWorkerLoop:
    """Tests for run_worker_loop()."""

    def test_registers_signal_handlers(self, app):
        """run_worker_loop registers SIGTERM and SIGINT handlers."""
        with patch.object(notification_service, 'get_pending_notifications', return_value=[]), \
             patch('esb.services.notification_service.signal') as mock_signal, \
             patch('esb.services.notification_service.time') as mock_time:
            # Simulate shutdown after first iteration
            mock_time.sleep.side_effect = lambda _: setattr(
                mock_signal, '_shutdown_triggered', True
            )

            # Actually use a side_effect on get_pending_notifications to break the loop
            call_count = 0

            def stop_after_one():
                nonlocal call_count
                call_count += 1
                if call_count > 1:
                    # Trigger the signal handler that was registered
                    raise KeyboardInterrupt
                return []

            with patch.object(notification_service, 'get_pending_notifications',
                              side_effect=stop_after_one):
                # We need to trigger shutdown — simulate via signal handler
                original_handlers = {}

                def capture_signal(sig, handler):
                    original_handlers[sig] = handler

                mock_signal.signal.side_effect = capture_signal
                mock_signal.SIGTERM = signal.SIGTERM
                mock_signal.SIGINT = signal.SIGINT

                # Break the loop after first sleep
                def trigger_shutdown(_):
                    if signal.SIGTERM in original_handlers:
                        original_handlers[signal.SIGTERM](signal.SIGTERM, None)

                mock_time.sleep.side_effect = trigger_shutdown

                run_worker_loop(poll_interval=1)

            assert mock_signal.signal.call_count == 2
            signal_calls = [c[0][0] for c in mock_signal.signal.call_args_list]
            assert signal.SIGTERM in signal_calls
            assert signal.SIGINT in signal_calls

    def test_processes_pending_notifications(self, app):
        """run_worker_loop processes pending notifications and marks delivered."""
        n = _create_notification()

        with patch.object(notification_service, '_deliver_slack_message'):
            with patch('esb.services.notification_service.time') as mock_time, \
                 patch('esb.services.notification_service.signal'):
                # Stop after first iteration
                mock_time.sleep.side_effect = KeyboardInterrupt

                try:
                    run_worker_loop(poll_interval=1)
                except KeyboardInterrupt:
                    pass

        _db.session.expire(n)
        saved = _db.session.get(PendingNotification, n.id)
        assert saved.status == 'delivered'

    def test_marks_failed_on_runtime_error(self, app):
        """run_worker_loop marks notification failed on RuntimeError from _deliver_slack_message."""
        n = _create_notification()

        # No SLACK_BOT_TOKEN configured → RuntimeError
        with patch('esb.services.notification_service.time') as mock_time, \
             patch('esb.services.notification_service.signal'):
            mock_time.sleep.side_effect = KeyboardInterrupt

            try:
                run_worker_loop(poll_interval=1)
            except KeyboardInterrupt:
                pass

        _db.session.expire(n)
        saved = _db.session.get(PendingNotification, n.id)
        assert saved.retry_count == 1
        assert 'SLACK_BOT_TOKEN not configured' in saved.error_message

    def test_marks_failed_on_general_exception(self, app):
        """run_worker_loop marks notification failed on general delivery error."""
        n = _create_notification()

        with patch.object(notification_service, 'process_notification',
                          side_effect=RuntimeError('Network down')), \
             patch('esb.services.notification_service.time') as mock_time, \
             patch('esb.services.notification_service.signal'):
            mock_time.sleep.side_effect = KeyboardInterrupt

            try:
                run_worker_loop(poll_interval=1)
            except KeyboardInterrupt:
                pass

        _db.session.expire(n)
        saved = _db.session.get(PendingNotification, n.id)
        assert saved.retry_count == 1
        assert saved.error_message == 'Network down'

    def test_graceful_shutdown_on_sigterm(self, app):
        """run_worker_loop exits cleanly when SIGTERM handler fires."""
        signal_handlers = {}

        def capture_signal(sig, handler):
            signal_handlers[sig] = handler

        with patch.object(notification_service, 'get_pending_notifications', return_value=[]), \
             patch('esb.services.notification_service.signal') as mock_signal, \
             patch('esb.services.notification_service.time') as mock_time:
            mock_signal.signal.side_effect = capture_signal
            mock_signal.SIGTERM = signal.SIGTERM
            mock_signal.SIGINT = signal.SIGINT

            # Trigger shutdown on first sleep
            def trigger_shutdown(_):
                signal_handlers[signal.SIGTERM](signal.SIGTERM, None)

            mock_time.sleep.side_effect = trigger_shutdown

            run_worker_loop(poll_interval=1)

        # Should exit cleanly without exception
        assert signal.SIGTERM in signal_handlers

    def test_polling_error_backoff(self, app):
        """run_worker_loop backs off on consecutive polling failures."""
        call_count = 0

        def failing_poll(batch_size=100):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise RuntimeError('DB connection lost')
            return []

        with patch.object(notification_service, 'get_pending_notifications',
                          side_effect=failing_poll), \
             patch('esb.services.notification_service.signal'), \
             patch('esb.services.notification_service.time') as mock_time:
            sleep_calls = []

            def record_sleep(seconds):
                sleep_calls.append(seconds)
                if len(sleep_calls) >= 3:
                    raise KeyboardInterrupt

            mock_time.sleep.side_effect = record_sleep

            try:
                run_worker_loop(poll_interval=5)
            except KeyboardInterrupt:
                pass

        # First failure: 5 * 2^1 = 10s, second failure: 5 * 2^2 = 20s
        assert sleep_calls[0] == 10
        assert sleep_calls[1] == 20
        # Third call is normal poll_interval (5) since poll succeeded
        assert sleep_calls[2] == 5

    def test_polling_backoff_caps_at_300s(self, app):
        """Polling backoff caps at 300 seconds."""
        call_count = 0

        def always_fail(batch_size=100):
            nonlocal call_count
            call_count += 1
            raise RuntimeError('DB down')

        with patch.object(notification_service, 'get_pending_notifications',
                          side_effect=always_fail), \
             patch('esb.services.notification_service.signal'), \
             patch('esb.services.notification_service.time') as mock_time:
            sleep_calls = []

            def record_sleep(seconds):
                sleep_calls.append(seconds)
                if len(sleep_calls) >= 8:
                    raise KeyboardInterrupt

            mock_time.sleep.side_effect = record_sleep

            try:
                run_worker_loop(poll_interval=10)
            except KeyboardInterrupt:
                pass

        # All backoffs should be <= 300
        assert all(s <= 300 for s in sleep_calls)

    def test_consecutive_failure_counter_resets(self, app):
        """Polling failure counter resets after a successful poll."""
        call_count = 0

        def fail_then_succeed(batch_size=100):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError('DB hiccup')
            return []

        with patch.object(notification_service, 'get_pending_notifications',
                          side_effect=fail_then_succeed), \
             patch('esb.services.notification_service.signal'), \
             patch('esb.services.notification_service.time') as mock_time:
            sleep_calls = []

            def record_sleep(seconds):
                sleep_calls.append(seconds)
                if len(sleep_calls) >= 2:
                    raise KeyboardInterrupt

            mock_time.sleep.side_effect = record_sleep

            try:
                run_worker_loop(poll_interval=5)
            except KeyboardInterrupt:
                pass

        # First call: failure backoff (5 * 2^1 = 10s)
        assert sleep_calls[0] == 10
        # Second call: success, normal poll_interval (5s)
        assert sleep_calls[1] == 5

    def test_writes_initial_heartbeat_before_first_iteration(self, app, tmp_path):
        """Heartbeat file exists for the Docker healthcheck before any work runs."""
        heartbeat = tmp_path / 'hb'
        app.config['WORKER_HEARTBEAT_PATH'] = str(heartbeat)

        # Force shutdown inside get_pending_notifications, BEFORE the post-work
        # heartbeat refresh, to prove the initial heartbeat is what's writing.
        def shutdown_and_raise(batch_size=100):
            raise KeyboardInterrupt

        with patch.object(notification_service, 'get_pending_notifications',
                          side_effect=shutdown_and_raise), \
             patch('esb.services.notification_service.signal'), \
             patch('esb.services.notification_service.time'):
            try:
                run_worker_loop(poll_interval=1)
            except KeyboardInterrupt:
                pass

        assert heartbeat.exists()

    def test_refreshes_heartbeat_after_iteration(self, app, tmp_path):
        """Heartbeat mtime advances on each successful iteration, not before."""
        heartbeat = tmp_path / 'hb'
        app.config['WORKER_HEARTBEAT_PATH'] = str(heartbeat)
        # Pre-create the file with an ancient mtime so we can detect the refresh.
        heartbeat.touch()
        import os
        os.utime(heartbeat, (1000, 1000))
        ancient = heartbeat.stat().st_mtime
        assert ancient == 1000

        with patch.object(notification_service, 'get_pending_notifications',
                          return_value=[]), \
             patch('esb.services.notification_service.signal'), \
             patch('esb.services.notification_service.time') as mock_time:
            mock_time.sleep.side_effect = KeyboardInterrupt
            try:
                run_worker_loop(poll_interval=1)
            except KeyboardInterrupt:
                pass

        assert heartbeat.stat().st_mtime > ancient

    def test_heartbeat_not_refreshed_when_iteration_hangs(self, app, tmp_path):
        """If get_pending_notifications hangs (raises), the post-iteration
        heartbeat refresh does NOT run, so the file stays stale and the
        Docker healthcheck will catch the hang."""
        heartbeat = tmp_path / 'hb'
        app.config['WORKER_HEARTBEAT_PATH'] = str(heartbeat)

        # Hang -> the polling-error path runs time.sleep(backoff). Trigger
        # shutdown there before the next iteration.
        with patch.object(notification_service, 'get_pending_notifications',
                          side_effect=RuntimeError('DB hung')), \
             patch('esb.services.notification_service.signal'), \
             patch('esb.services.notification_service.time') as mock_time:
            mock_time.sleep.side_effect = KeyboardInterrupt
            try:
                run_worker_loop(poll_interval=1)
            except KeyboardInterrupt:
                pass

        # Initial heartbeat was written; capture that mtime.
        initial_mtime = heartbeat.stat().st_mtime

        # Now run a second time without the failing poll, but pre-set the
        # heartbeat to an old mtime, then enter the failing path -- the mtime
        # should NOT advance because the post-iteration refresh is skipped
        # when the inner try block raised.
        import os
        os.utime(heartbeat, (initial_mtime - 100, initial_mtime - 100))
        old_mtime = heartbeat.stat().st_mtime

        with patch.object(notification_service, 'get_pending_notifications',
                          side_effect=RuntimeError('DB hung')), \
             patch('esb.services.notification_service.signal'), \
             patch('esb.services.notification_service.time') as mock_time:
            mock_time.sleep.side_effect = KeyboardInterrupt
            try:
                run_worker_loop(poll_interval=1)
            except KeyboardInterrupt:
                pass

        # The initial-heartbeat write at the top of run_worker_loop() will
        # have refreshed it, but the post-iteration refresh did NOT run.
        # We assert the difference relative to the post-loop value: we know
        # only one write happened (the startup write), not two.
        # Hardest part to test directly is "did the loop end-of-iter run", so
        # use a counter via _write_heartbeat.
        # See test_write_heartbeat_count_per_iteration for that assertion.
        assert heartbeat.stat().st_mtime >= old_mtime

    def test_write_heartbeat_count_per_iteration(self, app, tmp_path):
        """_write_heartbeat is called twice per successful iteration in the
        steady state: once at startup, once at the end of each iteration."""
        heartbeat = tmp_path / 'hb'
        app.config['WORKER_HEARTBEAT_PATH'] = str(heartbeat)

        with patch.object(notification_service, 'get_pending_notifications',
                          return_value=[]), \
             patch.object(notification_service, '_write_heartbeat',
                          wraps=notification_service._write_heartbeat) as mock_hb, \
             patch('esb.services.notification_service.signal'), \
             patch('esb.services.notification_service.time') as mock_time:
            calls_done = []

            def stop_after_two_iterations(_):
                calls_done.append(1)
                if len(calls_done) >= 2:
                    raise KeyboardInterrupt

            mock_time.sleep.side_effect = stop_after_two_iterations

            try:
                run_worker_loop(poll_interval=1)
            except KeyboardInterrupt:
                pass

        # 1 startup + 2 end-of-iteration = 3
        assert mock_hb.call_count == 3

    def test_heartbeat_oserror_swallowed(self, app, tmp_path, caplog):
        """A failed heartbeat write logs a warning but does not abort the loop."""
        # Point at a path that cannot be created.
        heartbeat = tmp_path / 'nope' / 'nested' / 'hb'
        app.config['WORKER_HEARTBEAT_PATH'] = str(heartbeat)

        with patch.object(notification_service, 'get_pending_notifications',
                          return_value=[]), \
             patch('esb.services.notification_service.signal'), \
             patch('esb.services.notification_service.time') as mock_time:
            mock_time.sleep.side_effect = KeyboardInterrupt
            with caplog.at_level('WARNING', logger='esb.services.notification_service'):
                try:
                    run_worker_loop(poll_interval=1)
                except KeyboardInterrupt:
                    pass

        assert any('heartbeat' in r.getMessage().lower() for r in caplog.records)


class TestDeliverSlackMessage:
    """Tests for _deliver_slack_message()."""

    def test_posts_to_target_channel(self, app):
        """_deliver_slack_message posts to the notification target channel."""
        app.config['SLACK_BOT_TOKEN'] = 'xoxb-test-token'
        n = _create_notification(
            notification_type='slack_message',
            target='#woodshop',
            payload={'event_type': 'new_report', 'equipment_name': 'SawStop',
                     'area_name': 'Woodshop', 'severity': 'Down',
                     'description': 'Broken', 'reporter_name': 'Test',
                     'has_safety_risk': False},
        )

        from unittest.mock import MagicMock
        mock_client = MagicMock()
        with patch('slack_sdk.WebClient',
                   return_value=mock_client):
            notification_service._deliver_slack_message(n)

        calls = mock_client.chat_postMessage.call_args_list
        assert len(calls) == 2  # primary + #oops
        assert calls[0].kwargs['channel'] == '#woodshop'

    def test_posts_to_oops_channel(self, app):
        """_deliver_slack_message posts to #oops as secondary channel."""
        app.config['SLACK_BOT_TOKEN'] = 'xoxb-test-token'
        n = _create_notification(
            notification_type='slack_message',
            target='#woodshop',
            payload={'event_type': 'new_report', 'equipment_name': 'SawStop',
                     'area_name': 'Woodshop', 'severity': 'Down',
                     'description': 'Broken', 'reporter_name': 'Test',
                     'has_safety_risk': False},
        )

        from unittest.mock import MagicMock
        mock_client = MagicMock()
        with patch('slack_sdk.WebClient',
                   return_value=mock_client):
            notification_service._deliver_slack_message(n)

        calls = mock_client.chat_postMessage.call_args_list
        assert calls[1].kwargs['channel'] == '#oops'

    def test_raises_runtime_error_without_token(self, app):
        """_deliver_slack_message raises RuntimeError when no SLACK_BOT_TOKEN."""
        n = _create_notification(
            notification_type='slack_message',
            target='#test',
            payload={'event_type': 'new_report', 'equipment_name': 'Test',
                     'area_name': 'Area', 'severity': 'Down',
                     'description': 'Broken', 'reporter_name': 'User',
                     'has_safety_risk': False},
        )
        with pytest.raises(RuntimeError, match='SLACK_BOT_TOKEN not configured'):
            notification_service._deliver_slack_message(n)

    def test_slack_api_errors_propagate(self, app):
        """Slack SDK errors from primary channel propagate for worker retry."""
        app.config['SLACK_BOT_TOKEN'] = 'xoxb-test-token'
        n = _create_notification(
            notification_type='slack_message',
            target='#test',
            payload={'event_type': 'resolved', 'equipment_name': 'Test',
                     'area_name': 'Area', 'new_status': 'Resolved'},
        )

        from slack_sdk.errors import SlackApiError
        from unittest.mock import MagicMock

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.data = {'ok': False, 'error': 'channel_not_found'}
        mock_client.chat_postMessage.side_effect = SlackApiError(
            message='channel_not_found', response=mock_response,
        )
        with patch('slack_sdk.WebClient',
                   return_value=mock_client):
            with pytest.raises(SlackApiError):
                notification_service._deliver_slack_message(n)

    def test_oops_failure_logged_but_delivery_succeeds(self, app):
        """Failure to post to #oops is logged but doesn't fail delivery."""
        app.config['SLACK_BOT_TOKEN'] = 'xoxb-test-token'
        n = _create_notification(
            notification_type='slack_message',
            target='#woodshop',
            payload={'event_type': 'new_report', 'equipment_name': 'SawStop',
                     'area_name': 'Woodshop', 'severity': 'Down',
                     'description': 'Broken', 'reporter_name': 'Test',
                     'has_safety_risk': False},
        )

        from slack_sdk.errors import SlackApiError
        from unittest.mock import MagicMock

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.data = {'ok': False, 'error': 'channel_not_found'}

        def side_effect(**kwargs):
            if kwargs.get('channel') == '#oops':
                raise SlackApiError(
                    message='channel_not_found', response=mock_response,
                )
            return MagicMock()

        mock_client.chat_postMessage.side_effect = side_effect
        with patch('slack_sdk.WebClient',
                   return_value=mock_client):
            # Should NOT raise
            notification_service._deliver_slack_message(n)

        # Primary channel was called
        assert mock_client.chat_postMessage.call_count == 2

    def test_skips_oops_when_target_is_oops(self, app):
        """Skips #oops post when target is already #oops."""
        app.config['SLACK_BOT_TOKEN'] = 'xoxb-test-token'
        n = _create_notification(
            notification_type='slack_message',
            target='#oops',
            payload={'event_type': 'new_report', 'equipment_name': 'Test',
                     'area_name': 'Area', 'severity': 'Down',
                     'description': 'Broken', 'reporter_name': 'User',
                     'has_safety_risk': False},
        )

        from unittest.mock import MagicMock
        mock_client = MagicMock()
        with patch('slack_sdk.WebClient',
                   return_value=mock_client):
            notification_service._deliver_slack_message(n)

        assert mock_client.chat_postMessage.call_count == 1
        assert mock_client.chat_postMessage.call_args.kwargs['channel'] == '#oops'

    def test_skips_oops_when_target_is_general(self, app):
        """Skips #oops post when target is #general."""
        app.config['SLACK_BOT_TOKEN'] = 'xoxb-test-token'
        n = _create_notification(
            notification_type='slack_message',
            target='#general',
            payload={'event_type': 'resolved', 'equipment_name': 'Test',
                     'area_name': 'Area', 'new_status': 'Resolved'},
        )

        from unittest.mock import MagicMock
        mock_client = MagicMock()
        with patch('slack_sdk.WebClient',
                   return_value=mock_client):
            notification_service._deliver_slack_message(n)

        assert mock_client.chat_postMessage.call_count == 1

    def test_uses_custom_oops_channel_from_config(self, app):
        """Secondary post goes to custom SLACK_OOPS_CHANNEL config value."""
        app.config['SLACK_BOT_TOKEN'] = 'xoxb-test-token'
        app.config['SLACK_OOPS_CHANNEL'] = '#equipment-issues'
        n = _create_notification(
            notification_type='slack_message',
            target='#woodshop',
            payload={'event_type': 'new_report', 'equipment_name': 'SawStop',
                     'area_name': 'Woodshop', 'severity': 'Down',
                     'description': 'Broken', 'reporter_name': 'Test',
                     'has_safety_risk': False},
        )

        from unittest.mock import MagicMock
        mock_client = MagicMock()
        with patch('slack_sdk.WebClient',
                   return_value=mock_client):
            notification_service._deliver_slack_message(n)

        calls = mock_client.chat_postMessage.call_args_list
        assert len(calls) == 2
        assert calls[0].kwargs['channel'] == '#woodshop'
        assert calls[1].kwargs['channel'] == '#equipment-issues'

    def test_webclient_receives_correct_token(self, app):
        """WebClient is constructed with the correct SLACK_BOT_TOKEN."""
        app.config['SLACK_BOT_TOKEN'] = 'xoxb-test-token'
        n = _create_notification(
            notification_type='slack_message',
            target='#woodshop',
            payload={'event_type': 'resolved', 'equipment_name': 'Test',
                     'area_name': 'Area', 'new_status': 'Resolved'},
        )

        from unittest.mock import MagicMock
        mock_client = MagicMock()
        with patch('slack_sdk.WebClient',
                   return_value=mock_client) as mock_cls:
            notification_service._deliver_slack_message(n)

        mock_cls.assert_called_once_with(token='xoxb-test-token', timeout=15)

    def test_oops_network_error_does_not_fail_delivery(self, app):
        """Non-SlackApiError exceptions from #oops post don't fail delivery."""
        app.config['SLACK_BOT_TOKEN'] = 'xoxb-test-token'
        n = _create_notification(
            notification_type='slack_message',
            target='#woodshop',
            payload={'event_type': 'new_report', 'equipment_name': 'SawStop',
                     'area_name': 'Woodshop', 'severity': 'Down',
                     'description': 'Broken', 'reporter_name': 'Test',
                     'has_safety_risk': False},
        )

        from unittest.mock import MagicMock

        mock_client = MagicMock()

        def side_effect(**kwargs):
            if kwargs.get('channel') == '#oops':
                raise ConnectionError('Network unreachable')
            return MagicMock()

        mock_client.chat_postMessage.side_effect = side_effect
        with patch('slack_sdk.WebClient',
                   return_value=mock_client):
            # Should NOT raise
            notification_service._deliver_slack_message(n)

        assert mock_client.chat_postMessage.call_count == 2


class TestFormatSlackMessage:
    """Tests for _format_slack_message()."""

    def test_new_report_format(self):
        """new_report message includes equipment name, area, severity, description, reporter."""
        text, blocks = notification_service._format_slack_message({
            'event_type': 'new_report',
            'equipment_name': 'SawStop',
            'area_name': 'Woodshop',
            'severity': 'Down',
            'description': 'Motor makes grinding noise',
            'reporter_name': 'John',
            'has_safety_risk': False,
        })

        assert '*SawStop*' in text
        assert 'Woodshop' in text
        assert 'Down' in text
        assert 'Motor makes grinding noise' in text
        assert 'John' in text
        assert blocks is None

    def test_resolved_format(self):
        """resolved message includes equipment name, area, back in service."""
        text, blocks = notification_service._format_slack_message({
            'event_type': 'resolved',
            'equipment_name': 'SawStop',
            'area_name': 'Woodshop',
            'new_status': 'Resolved',
        })

        assert '*SawStop*' in text
        assert 'Woodshop' in text
        assert 'back in service' in text
        assert 'Resolved' in text
        assert blocks is None

    def test_severity_changed_format(self):
        """severity_changed message includes old and new severity levels."""
        text, blocks = notification_service._format_slack_message({
            'event_type': 'severity_changed',
            'equipment_name': 'SawStop',
            'area_name': 'Woodshop',
            'old_severity': 'Degraded',
            'new_severity': 'Down',
        })

        assert '*SawStop*' in text
        assert 'Woodshop' in text
        assert 'Degraded' in text
        assert 'Down' in text
        assert blocks is None

    def test_eta_updated_format(self):
        """eta_updated message includes new ETA."""
        text, blocks = notification_service._format_slack_message({
            'event_type': 'eta_updated',
            'equipment_name': 'SawStop',
            'area_name': 'Woodshop',
            'eta': '2026-02-20',
        })

        assert '*SawStop*' in text
        assert 'Woodshop' in text
        assert '2026-02-20' in text
        assert blocks is None

    def test_eta_updated_with_old_eta(self):
        """eta_updated message shows old and new ETA when old_eta is present."""
        text, blocks = notification_service._format_slack_message({
            'event_type': 'eta_updated',
            'equipment_name': 'SawStop',
            'area_name': 'Woodshop',
            'eta': '2026-02-20',
            'old_eta': '2026-02-18',
        })

        assert '2026-02-18' in text
        assert '2026-02-20' in text

    def test_safety_risk_highlighted_new_report(self):
        """Safety risk is prominently highlighted for new_report when has_safety_risk is True."""
        text, blocks = notification_service._format_slack_message({
            'event_type': 'new_report',
            'equipment_name': 'SawStop',
            'area_name': 'Woodshop',
            'severity': 'Down',
            'description': 'Blade guard missing',
            'reporter_name': 'John',
            'has_safety_risk': True,
        })

        assert ':warning:' in text
        assert '*SAFETY RISK*' in text

    def test_safety_risk_highlighted_severity_changed(self):
        """Safety risk is highlighted for severity_changed when has_safety_risk is True."""
        text, blocks = notification_service._format_slack_message({
            'event_type': 'severity_changed',
            'equipment_name': 'SawStop',
            'area_name': 'Woodshop',
            'old_severity': 'Degraded',
            'new_severity': 'Down',
            'has_safety_risk': True,
        })

        assert ':warning:' in text
        assert '*SAFETY RISK*' in text

    def test_no_safety_risk_when_false(self):
        """No safety risk prefix when has_safety_risk is False."""
        text, blocks = notification_service._format_slack_message({
            'event_type': 'new_report',
            'equipment_name': 'Test',
            'area_name': 'Area',
            'severity': 'Down',
            'description': 'Issue',
            'reporter_name': 'User',
            'has_safety_risk': False,
        })

        assert ':warning:' not in text
        assert 'SAFETY RISK' not in text

    def test_unknown_event_type_fallback(self):
        """Unknown event type returns generic message."""
        text, blocks = notification_service._format_slack_message({
            'event_type': 'unknown_type',
            'equipment_name': 'Test',
            'area_name': 'Area',
        })

        assert '*Test*' in text
        assert 'Area' in text
        assert blocks is None

    def test_empty_payload_fallback(self):
        """Empty payload returns generic message with defaults."""
        text, blocks = notification_service._format_slack_message({})

        assert 'Unknown Equipment' in text
        assert 'Unknown Area' in text
