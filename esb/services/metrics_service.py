"""Prometheus metrics for the notification queue.

Exposes two gauges that, together, catch a stuck worker, a bad Slack token,
or a Slack outage:

- ``esb_pending_notifications_count`` — count of rows with status='pending'.
- ``esb_oldest_pending_notification_timestamp_seconds`` — Unix epoch seconds
  of the oldest pending row's ``created_at``. **Omitted entirely** when the
  table has no pending rows; Prometheus alert rules should use ``absent()``
  rather than a sentinel value.

Alert rules belong in Prometheus, not here. Example::

    time() - esb_oldest_pending_notification_timestamp_seconds > 300
"""

from datetime import UTC

from prometheus_client import CollectorRegistry, generate_latest
from prometheus_client.core import GaugeMetricFamily
from prometheus_client.exposition import CONTENT_TYPE_LATEST

from esb.extensions import db
from esb.models.pending_notification import PendingNotification


def _query_pending_stats() -> tuple[int, float | None]:
    """Return (pending_count, oldest_created_at_unix_seconds_or_None).

    Both aggregates come from a single SELECT so the count and oldest
    timestamp are guaranteed to be drawn from the same row snapshot
    (under any isolation level) and so each scrape is one DB round-trip
    rather than two.
    """
    count, oldest = db.session.execute(
        db.select(
            db.func.count(PendingNotification.id),
            db.func.min(PendingNotification.created_at),
        )
        .where(PendingNotification.status == 'pending')
    ).one()

    if oldest is None:
        return count, None

    # SQLAlchemy may return naive datetimes (SQLite) or aware datetimes
    # (MariaDB driver). Treat naive values as UTC -- created_at is always
    # written as datetime.now(UTC) by the model.
    if oldest.tzinfo is None:
        oldest = oldest.replace(tzinfo=UTC)

    return count, oldest.timestamp()


class _PendingNotificationsCollector:
    """Custom collector so the oldest-timestamp metric can be omitted entirely
    when the queue is empty (rather than emitting a misleading 0 sample).

    Each scrape runs one combined aggregate query against the live DB. With
    the default Dockerfile gunicorn config (1 worker, 2 threads) this is at
    most one query per scrape interval. If gunicorn is scaled to N workers
    the DB load multiplies by N, since each worker handles its own scrape
    with its own request-scoped DB session.
    """

    def collect(self):
        count, oldest_ts = _query_pending_stats()

        yield GaugeMetricFamily(
            'esb_pending_notifications_count',
            'Number of notifications in the queue with status=pending.',
            value=count,
        )

        if oldest_ts is not None:
            yield GaugeMetricFamily(
                'esb_oldest_pending_notification_timestamp_seconds',
                'Unix timestamp (seconds) of the oldest pending notification. '
                'Omitted when the queue is empty.',
                value=oldest_ts,
            )


def render_metrics() -> tuple[bytes, str]:
    """Render the Prometheus exposition payload and content-type.

    Returns:
        Tuple of (body, content_type) suitable for a Flask response.
    """
    registry = CollectorRegistry()
    registry.register(_PendingNotificationsCollector())
    return generate_latest(registry), CONTENT_TYPE_LATEST
