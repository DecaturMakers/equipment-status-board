"""Tests for the Prometheus metrics service."""

import re
from datetime import UTC, datetime, timedelta

from esb.extensions import db as _db
from esb.models.pending_notification import PendingNotification
from esb.services import metrics_service


def _extract_metric(text: str, name: str) -> float | None:
    """Extract the value of an unlabelled metric from exposition text."""
    match = re.search(rf'^{re.escape(name)} (\S+)$', text, re.MULTILINE)
    return float(match.group(1)) if match else None


def _make_pending(created_at, status='pending'):
    n = PendingNotification(
        notification_type='slack_message',
        target='#test',
        payload={'msg': 'x'},
        status=status,
        created_at=created_at,
    )
    _db.session.add(n)
    _db.session.commit()
    return n


class TestQueryPendingStats:
    def test_empty_table_returns_zero_and_none(self, app):
        count, oldest_ts = metrics_service._query_pending_stats()
        assert count == 0
        assert oldest_ts is None

    def test_only_delivered_rows_returns_zero_and_none(self, app):
        _make_pending(datetime.now(UTC) - timedelta(minutes=5), status='delivered')
        _make_pending(datetime.now(UTC) - timedelta(minutes=2), status='failed')
        count, oldest_ts = metrics_service._query_pending_stats()
        assert count == 0
        assert oldest_ts is None

    def test_counts_only_pending(self, app):
        _make_pending(datetime.now(UTC), status='pending')
        _make_pending(datetime.now(UTC), status='pending')
        _make_pending(datetime.now(UTC), status='delivered')
        count, _ = metrics_service._query_pending_stats()
        assert count == 2

    def test_oldest_timestamp_is_min_created_at(self, app):
        oldest = datetime.now(UTC) - timedelta(minutes=10)
        middle = datetime.now(UTC) - timedelta(minutes=5)
        newest = datetime.now(UTC)
        _make_pending(middle)
        _make_pending(oldest)
        _make_pending(newest)
        _, oldest_ts = metrics_service._query_pending_stats()
        # Allow a tiny float tolerance, but values come from datetime.timestamp()
        # so should match exactly.
        assert oldest_ts == oldest.timestamp()

    def test_oldest_timestamp_ignores_non_pending(self, app):
        # An older delivered row must not affect the oldest pending value.
        _make_pending(datetime.now(UTC) - timedelta(hours=1), status='delivered')
        pending_at = datetime.now(UTC) - timedelta(minutes=2)
        _make_pending(pending_at)
        _, oldest_ts = metrics_service._query_pending_stats()
        assert oldest_ts == pending_at.timestamp()


class TestRenderMetrics:
    def test_content_type_is_prometheus_exposition(self, app):
        _, content_type = metrics_service.render_metrics()
        assert 'text/plain' in content_type

    def test_empty_table_omits_oldest_metric(self, app):
        body, _ = metrics_service.render_metrics()
        text = body.decode()
        assert 'esb_pending_notifications_count 0.0' in text
        assert 'esb_oldest_pending_notification_timestamp_seconds' not in text

    def test_populated_table_includes_both_metrics(self, app):
        oldest = datetime.now(UTC) - timedelta(minutes=7)
        _make_pending(oldest)
        _make_pending(datetime.now(UTC))

        body, _ = metrics_service.render_metrics()
        text = body.decode()
        assert _extract_metric(text, 'esb_pending_notifications_count') == 2.0
        # prometheus_client formats large floats in scientific notation, so
        # parse the value rather than matching the literal.
        ts = _extract_metric(text, 'esb_oldest_pending_notification_timestamp_seconds')
        assert ts is not None
        assert abs(ts - oldest.timestamp()) < 0.001

    def test_help_and_type_lines_present(self, app):
        body, _ = metrics_service.render_metrics()
        text = body.decode()
        assert '# HELP esb_pending_notifications_count' in text
        assert '# TYPE esb_pending_notifications_count gauge' in text
