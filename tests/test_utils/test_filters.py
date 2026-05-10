"""Tests for Jinja2 custom template filters."""

from datetime import date, datetime, timedelta, timezone

from flask import Flask

from esb.utils.filters import (
    category_label,
    filesize,
    format_date,
    format_datetime,
    register_filters,
    relative_time,
)


class TestFormatDate:
    """Tests for format_date filter."""

    def test_default_format(self):
        dt = datetime(2026, 2, 14, 10, 30, 0)
        assert format_date(dt) == 'Feb 14, 2026'

    def test_custom_format(self):
        dt = datetime(2026, 2, 14, 10, 30, 0)
        assert format_date(dt, '%m/%d/%Y') == '02/14/2026'

    def test_none_returns_empty(self):
        assert format_date(None) == ''

    def test_format_date_accepts_date_object(self):
        assert format_date(date(2026, 3, 15)) == 'Mar 15, 2026'

    def test_format_date_accepts_iso_string(self):
        assert format_date('2026-03-15') == 'Mar 15, 2026'

    def test_format_date_returns_input_for_invalid_string(self):
        # Defensive: never crash a render on a malformed string.
        assert format_date('not-a-date') == 'not-a-date'

    def test_runtime_locale_produces_english_month_abbreviations(self):
        # Locale guard: if a future deployment pins a non-English LC_TIME,
        # this fails fast with a clear root-cause signal.
        assert date(2026, 1, 1).strftime('%b') == 'Jan'
        assert date(2026, 6, 15).strftime('%b') == 'Jun'


class TestFormatDatetime:
    """Tests for format_datetime filter."""

    def test_default_format(self):
        dt = datetime(2026, 2, 14, 10, 30, 0)
        assert format_datetime(dt) == '2026-02-14 10:30'

    def test_custom_format(self):
        dt = datetime(2026, 2, 14, 10, 30, 45)
        assert format_datetime(dt, '%H:%M:%S') == '10:30:45'

    def test_none_returns_empty(self):
        assert format_datetime(None) == ''


class TestRelativeTime:
    """Tests for relative_time filter."""

    def test_none_returns_empty(self):
        assert relative_time(None) == ''

    def test_just_now(self):
        now = datetime.now(timezone.utc)
        assert relative_time(now) == 'just now'

    def test_seconds_ago(self):
        dt = datetime.now(timezone.utc) - timedelta(seconds=30)
        assert relative_time(dt) == 'just now'

    def test_one_minute_ago(self):
        dt = datetime.now(timezone.utc) - timedelta(minutes=1)
        assert relative_time(dt) == '1 minute ago'

    def test_multiple_minutes_ago(self):
        dt = datetime.now(timezone.utc) - timedelta(minutes=45)
        assert relative_time(dt) == '45 minutes ago'

    def test_one_hour_ago(self):
        dt = datetime.now(timezone.utc) - timedelta(hours=1)
        assert relative_time(dt) == '1 hour ago'

    def test_multiple_hours_ago(self):
        dt = datetime.now(timezone.utc) - timedelta(hours=5)
        assert relative_time(dt) == '5 hours ago'

    def test_one_day_ago(self):
        dt = datetime.now(timezone.utc) - timedelta(days=1)
        assert relative_time(dt) == '1 day ago'

    def test_multiple_days_ago(self):
        dt = datetime.now(timezone.utc) - timedelta(days=15)
        assert relative_time(dt) == '15 days ago'

    def test_one_month_ago(self):
        dt = datetime.now(timezone.utc) - timedelta(days=35)
        assert relative_time(dt) == '1 month ago'

    def test_one_year_ago(self):
        dt = datetime.now(timezone.utc) - timedelta(days=400)
        assert relative_time(dt) == '1 year ago'

    def test_naive_datetime_treated_as_utc(self):
        """Timezone-naive datetimes are treated as UTC."""
        dt = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=2)
        result = relative_time(dt)
        assert 'hour' in result

    def test_future_time_returns_just_now(self):
        """Future timestamps return 'just now'."""
        dt = datetime.now(timezone.utc) + timedelta(hours=1)
        assert relative_time(dt) == 'just now'


class TestCategoryLabel:
    """Tests for category_label filter."""

    def test_known_category(self):
        assert category_label('owners_manual') == "Owner's Manual"

    def test_another_known_category(self):
        assert category_label('quick_start') == 'Quick Start Guide'

    def test_unknown_category_fallback(self):
        assert category_label('unknown_value') == 'Unknown Value'

    def test_none_returns_empty(self):
        assert category_label(None) == ''


class TestFilesize:
    """Tests for filesize filter."""

    def test_bytes(self):
        assert filesize(500) == '500.0 B'

    def test_kilobytes(self):
        assert filesize(1536) == '1.5 KB'

    def test_megabytes(self):
        assert filesize(5 * 1024 * 1024) == '5.0 MB'

    def test_zero(self):
        assert filesize(0) == '0 B'

    def test_none(self):
        assert filesize(None) == '0 B'


class TestRegisterFilters:
    """Tests for register_filters function."""

    def test_filters_registered(self):
        app = Flask(__name__)
        register_filters(app)
        assert 'format_date' in app.jinja_env.filters
        assert 'format_datetime' in app.jinja_env.filters
        assert 'relative_time' in app.jinja_env.filters
        assert 'category_label' in app.jinja_env.filters
        assert 'filesize' in app.jinja_env.filters
