"""Jinja2 custom template filters for ESB application."""

import logging
from datetime import date, datetime, timezone

from esb.models.document import DOCUMENT_CATEGORIES

_CATEGORY_LABELS = dict(DOCUMENT_CATEGORIES)

logger = logging.getLogger(__name__)


def format_date(value, fmt='%b %d, %Y'):
    """Format a date/datetime object or ISO date string as a date string.

    Args:
        value: A ``date``/``datetime`` instance, an ISO-format date string
            (``'YYYY-MM-DD'``), or ``None``.
        fmt: strftime format string.
    """
    if value is None:
        return ''
    if isinstance(value, str):
        try:
            return date.fromisoformat(value).strftime(fmt)
        except ValueError:
            logger.warning('format_date: could not parse ISO date string %r', value)
            return value
    return value.strftime(fmt)


def format_datetime(value, fmt='%Y-%m-%d %H:%M'):
    """Format a datetime object as a date+time string.

    Args:
        value: A datetime object.
        fmt: strftime format string.
    """
    if value is None:
        return ''
    return value.strftime(fmt)


def relative_time(value):
    """Return a human-readable relative time string (e.g., '2 hours ago').

    Args:
        value: A datetime object (assumed UTC).
    """
    if value is None:
        return ''

    now = datetime.now(timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)

    diff = now - value
    seconds = int(diff.total_seconds())

    if seconds < 0:
        return 'just now'
    if seconds < 60:
        return 'just now'
    if seconds < 3600:
        minutes = seconds // 60
        return f'{minutes} minute{"s" if minutes != 1 else ""} ago'
    if seconds < 86400:
        hours = seconds // 3600
        return f'{hours} hour{"s" if hours != 1 else ""} ago'
    if seconds < 2592000:  # 30 days
        days = seconds // 86400
        return f'{days} day{"s" if days != 1 else ""} ago'
    if seconds < 31536000:  # 365 days
        months = seconds // 2592000
        return f'{months} month{"s" if months != 1 else ""} ago'
    years = seconds // 31536000
    return f'{years} year{"s" if years != 1 else ""} ago'


def category_label(value):
    """Return the display label for a document category value."""
    if value is None:
        return ''
    return _CATEGORY_LABELS.get(value, value.replace('_', ' ').title())


def filesize(value):
    """Format bytes as human-readable file size."""
    if value is None or value == 0:
        return '0 B'
    size = float(value)
    for unit in ('B', 'KB', 'MB', 'GB'):
        if abs(size) < 1024:
            return f'{size:.1f} {unit}'
        size /= 1024
    return f'{size:.1f} TB'


def register_filters(app):
    """Register all custom Jinja2 filters with the Flask app."""
    app.jinja_env.filters['format_date'] = format_date
    app.jinja_env.filters['format_datetime'] = format_datetime
    app.jinja_env.filters['relative_time'] = relative_time
    app.jinja_env.filters['category_label'] = category_label
    app.jinja_env.filters['filesize'] = filesize
