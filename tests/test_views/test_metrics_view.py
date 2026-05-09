"""Tests for the /metrics endpoint."""

import re
from datetime import UTC, datetime, timedelta

from esb.extensions import db as _db
from esb.models.pending_notification import PendingNotification


def _extract_metric(text: str, name: str) -> float | None:
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


class TestMetricsEndpoint:
    def test_unauthenticated_access_returns_200(self, client):
        response = client.get('/metrics')
        assert response.status_code == 200

    def test_returns_prometheus_content_type(self, client):
        response = client.get('/metrics')
        assert 'text/plain' in response.content_type

    def test_empty_table_emits_zero_count_and_omits_oldest(self, client):
        response = client.get('/metrics')
        text = response.data.decode()
        assert 'esb_pending_notifications_count 0.0' in text
        assert 'esb_oldest_pending_notification_timestamp_seconds' not in text

    def test_populated_table_emits_both_metrics(self, app, client):
        oldest = datetime.now(UTC) - timedelta(minutes=3)
        _make_pending(oldest)
        _make_pending(datetime.now(UTC))

        response = client.get('/metrics')
        text = response.data.decode()
        assert _extract_metric(text, 'esb_pending_notifications_count') == 2.0
        ts = _extract_metric(text, 'esb_oldest_pending_notification_timestamp_seconds')
        assert ts is not None
        assert abs(ts - oldest.timestamp()) < 0.001

    def test_only_pending_status_counted(self, app, client):
        _make_pending(datetime.now(UTC), status='delivered')
        _make_pending(datetime.now(UTC), status='failed')
        _make_pending(datetime.now(UTC), status='pending')

        response = client.get('/metrics')
        text = response.data.decode()
        assert 'esb_pending_notifications_count 1.0' in text
