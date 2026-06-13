"""Tests for the static page service."""

import json
import os
import re
from datetime import UTC, date, datetime, tzinfo
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest
from jinja2.exceptions import TemplateNotFound

from esb.services import static_page_service


class TestGenerate:
    """Tests for generate()."""

    def test_returns_html_with_area_and_equipment(self, app, make_area, make_equipment):
        """generate() renders HTML with area and equipment data."""
        area = make_area(name='Woodshop')
        make_equipment(name='SawStop', area=area)

        html = static_page_service.generate()

        assert 'Woodshop' in html
        assert 'SawStop' in html

    def test_produces_self_contained_html(self, app, make_area, make_equipment):
        """generate() produces HTML with no external CSS/JS links."""
        area = make_area(name='TestArea')
        make_equipment(name='TestEquip', area=area)

        html = static_page_service.generate()

        assert '<link' not in html
        assert '<script src=' not in html
        assert '<!DOCTYPE html>' in html

    def test_includes_status_dot_classes(self, app, make_area, make_equipment):
        """generate() includes status dot CSS classes."""
        area = make_area(name='TestArea')
        make_equipment(name='TestEquip', area=area)

        html = static_page_service.generate()

        assert 'status-green' in html

    def test_includes_generated_timestamp(self, app, make_area, make_equipment):
        """generate() includes a generation timestamp in the expected position and format."""
        area = make_area(name='TestArea')
        make_equipment(name='TestEquip', area=area)

        html = static_page_service.generate()

        assert 'Generated:' in html
        # Pin format end-to-end: the helper output must actually be interpolated
        # into the .generated-at sub-heading (not just exist somewhere on the page).
        assert re.search(
            r'<div class="generated-at">Generated: \d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} \S+</div>',
            html,
        )

    def test_generated_at_style_is_centered_and_black(self, app, make_area, make_equipment):
        """The .generated-at rule centers the timestamp and renders it black (Issue #52)."""
        area = make_area(name='TestArea')
        make_equipment(name='TestEquip', area=area)

        html = static_page_service.generate()

        rule = re.search(r'\.generated-at \{[^}]*\}', html)
        assert rule is not None
        rule_text = rule.group(0)
        assert 'text-align: center' in rule_text
        assert 'color: #000' in rule_text
        assert 'text-align: right' not in rule_text

    def test_csp_meta_tag_directive_unchanged(self, app, make_area, make_equipment):
        """generate() includes the exact CSP directive on the meta tag (no policy weakening)."""
        area = make_area(name='TestArea')
        make_equipment(name='TestEquip', area=area)

        html = static_page_service.generate()

        # Pin the directive to the <meta> element to catch a regression that
        # moves the same string into a comment / data attribute / unrelated tag.
        assert (
            '<meta http-equiv="Content-Security-Policy" '
            'content="default-src \'none\'; style-src \'unsafe-inline\';">'
        ) in html

    def test_renders_yellow_status_for_degraded_equipment(self, app, make_area, make_equipment, make_repair_record):
        """generate() renders status-yellow for equipment with Degraded severity repair."""
        area = make_area(name='TestArea')
        equip = make_equipment(name='DegradedEquip', area=area)
        make_repair_record(equipment=equip, severity='Degraded')

        html = static_page_service.generate()

        assert 'status-yellow' in html
        assert 'DegradedEquip' in html

    def test_renders_red_status_for_down_equipment(self, app, make_area, make_equipment, make_repair_record):
        """generate() renders status-red for equipment with Down severity repair."""
        area = make_area(name='TestArea')
        equip = make_equipment(name='DownEquip', area=area)
        make_repair_record(equipment=equip, severity='Down')

        html = static_page_service.generate()

        assert 'status-red' in html
        assert 'DownEquip' in html

    def test_renders_no_equipment_message_for_empty_area(self, app, make_area):
        """generate() renders fallback text for an area with no equipment."""
        make_area(name='EmptyArea')

        html = static_page_service.generate()

        assert 'EmptyArea' in html
        assert 'No equipment in this area.' in html

    def test_generate_includes_eta_when_set(self, app, make_area, make_equipment, make_repair_record):
        from datetime import date
        area = make_area(name='Lab')
        eq = make_equipment(name='Microscope', area=area)
        make_repair_record(
            equipment=eq, status='New', severity='Down',
            description='Broken', eta=date(2026, 6, 15),
        )
        html = static_page_service.generate()
        expected = 'ETA: ' + date(2026, 6, 15).strftime('%b %d, %Y')
        assert expected in html
        assert 'eta-label' in html

    def test_generate_omits_eta_when_unset(self, app, make_area, make_equipment, make_repair_record):
        area = make_area(name='Lab')
        eq = make_equipment(name='Microscope', area=area)
        make_repair_record(
            equipment=eq, status='New', severity='Down', description='Broken',
        )
        html = static_page_service.generate()
        assert 'ETA:' not in html

    def test_generated_at_subheading_renders_above_areas(self, app, make_area, make_equipment):
        """The generated-at sub-heading renders below the <h1> and above the first area."""
        area = make_area(name='TestArea')
        make_equipment(name='TestEquip', area=area)

        html = static_page_service.generate()

        h1_close = html.find('</h1>')
        gen_at = html.find('<div class="generated-at">')
        first_area = html.find('<div class="area">')
        assert h1_close != -1
        assert gen_at != -1
        assert first_area != -1
        assert h1_close < gen_at < first_area

    def test_generated_at_uses_local_timezone_helper(self, app, make_area, make_equipment):
        """generate() interpolates the helper's timestamp string and year."""
        area = make_area(name='TestArea')
        make_equipment(name='TestEquip', area=area)

        with patch.object(
            static_page_service,
            '_compute_generated_at',
            return_value=('2026-05-11 14:32:15 EDT', 2026),
        ):
            html = static_page_service.generate()

        assert 'Generated: 2026-05-11 14:32:15 EDT' in html
        # Scope the year check to <footer> with the entity prefix so a regression
        # to a wrong footer year isn't masked by the timestamp's '2026'.
        footer_start = html.find('<footer class="site-footer"')
        footer_end = html.find('</footer>', footer_start)
        assert footer_start != -1 and footer_end != -1
        assert '&copy; 2026 Jason Antman' in html[footer_start:footer_end]

    def test_compute_generated_at_formats_tzname(self, app):
        """_compute_generated_at() formats datetime + tzname correctly."""
        fixed_dt = datetime(2026, 7, 15, 14, 32, 15, tzinfo=ZoneInfo('America/New_York'))
        with patch.object(static_page_service, 'datetime') as mock_datetime:
            mock_datetime.now.return_value.astimezone.return_value = fixed_dt
            result = static_page_service._compute_generated_at()
        assert result == ('2026-07-15 14:32:15 EDT', 2026)

    def test_compute_generated_at_raises_on_empty_tzname(self, app):
        """_compute_generated_at() raises RuntimeError on empty/missing tzname."""

        class _EmptyTZ(tzinfo):
            def utcoffset(self, dt):
                from datetime import timedelta
                return timedelta(0)

            def tzname(self, dt):
                return ''

            def dst(self, dt):
                from datetime import timedelta
                return timedelta(0)

        fixed_dt = datetime(2026, 1, 1, 12, 0, 0, tzinfo=_EmptyTZ())
        with patch.object(static_page_service, 'datetime') as mock_datetime:
            mock_datetime.now.return_value.astimezone.return_value = fixed_dt
            with pytest.raises(RuntimeError, match='tzname'):
                static_page_service._compute_generated_at()

    def test_compute_generated_at_raises_on_none_tzname(self, app):
        """AC 7c covers both None and empty-string; pin the None branch too."""

        class _NoneTZ(tzinfo):
            def utcoffset(self, dt):
                from datetime import timedelta
                return timedelta(0)

            def tzname(self, dt):
                return None

            def dst(self, dt):
                from datetime import timedelta
                return timedelta(0)

        fixed_dt = datetime(2026, 1, 1, 12, 0, 0, tzinfo=_NoneTZ())
        with patch.object(static_page_service, 'datetime') as mock_datetime:
            mock_datetime.now.return_value.astimezone.return_value = fixed_dt
            with pytest.raises(RuntimeError, match='tzname'):
                static_page_service._compute_generated_at()

    def test_compute_generated_at_format_matches_regex(self, app):
        """End-to-end (unpatched) helper output matches the expected format."""
        result = static_page_service._compute_generated_at()
        assert re.fullmatch(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} \S+', result[0])

    def test_open_records_listed_for_non_green_equipment(
        self, app, make_area, make_equipment, make_repair_record,
    ):
        """A non-green equipment item renders its open records nested under it."""
        area = make_area(name='Shop')
        eq = make_equipment(name='Lathe', area=area)
        make_repair_record(
            equipment=eq, status='In Progress', severity='Down',
            description='Belt slipping', eta=date(2026, 6, 1),
        )

        html = static_page_service.generate()

        # Scope per-record assertions to inside the open-records-list so they
        # don't accidentally match the equipment-row eta-label (which mirrors
        # the same date via item.status.eta).
        list_start = html.find('<ul class="open-records-list">')
        list_end = html.find('</ul>', list_start)
        assert list_start != -1 and list_end != -1
        record_block = html[list_start:list_end]

        assert 'In Progress' in record_block
        assert '[Down]' in record_block
        assert 'Belt slipping' in record_block
        eta_str = date(2026, 6, 1).strftime('%b %d, %Y')
        assert f'<span class="record-eta">ETA: {eta_str}</span>' in record_block
        assert 'class="open-record open-record-red"' in record_block

    def test_open_records_omitted_for_green_equipment(
        self, app, make_area, make_equipment,
    ):
        """Green equipment items do not render an <ul class=\"open-records-list\">."""
        area = make_area(name='Shop')
        make_equipment(name='Lathe', area=area)

        html = static_page_service.generate()

        # The class name appears in the inline CSS rule; only the element
        # presence is meaningful, so match the rendered element form.
        assert '<ul class="open-records-list">' not in html

    def test_open_records_uses_yellow_class_for_degraded_and_not_sure(
        self, app, make_area, make_equipment, make_repair_record,
    ):
        """Degraded and Not Sure both render with the yellow severity class and a text badge."""
        area = make_area(name='Shop')
        eq1 = make_equipment(name='ToolA', area=area)
        eq2 = make_equipment(name='ToolB', area=area)
        make_repair_record(equipment=eq1, severity='Degraded', description='deg-issue')
        make_repair_record(equipment=eq2, severity='Not Sure', description='ns-issue')

        html = static_page_service.generate()

        # Anchor to the rendered element form, not the bare class name (which
        # also appears in the inline CSS rule .open-record-yellow { ... }).
        assert html.count('class="open-record open-record-yellow"') == 2
        assert '[Degraded]' in html
        assert '[Not Sure]' in html

    def test_open_records_uses_gray_class_for_no_severity(
        self, app, make_area, make_equipment, make_repair_record,
    ):
        """severity=None renders the gray class and suppresses the text badge (R3F3)."""
        area = make_area(name='Shop')
        eq = make_equipment(name='ToolN', area=area)
        make_repair_record(equipment=eq, severity=None, description='no-sev-issue')

        html = static_page_service.generate()

        # Scope to the open-records-list and anchor on the rendered element
        # form, not the bare class name (which also appears in the inline
        # CSS rule .open-record-gray { ... }).
        list_start = html.find('<ul class="open-records-list">')
        list_end = html.find('</ul>', list_start)
        assert list_start != -1 and list_end != -1
        record_block = html[list_start:list_end]

        assert 'class="open-record open-record-gray"' in record_block
        assert '<span class="record-severity">' not in record_block

    def test_open_records_uses_gray_class_and_suppresses_badge_for_unknown_severity(
        self, app, make_area, make_equipment, make_repair_record,
    ):
        """Unknown severity strings render gray with no text badge (R3F3)."""
        area = make_area(name='Shop')
        eq = make_equipment(name='ToolU', area=area)
        make_repair_record(equipment=eq, severity='Critical', description='unknown-sev')

        html = static_page_service.generate()

        # Scope to the open-records-list and anchor on the rendered element
        # form, not the bare class name (which also appears in the inline
        # CSS rule .open-record-gray { ... }).
        list_start = html.find('<ul class="open-records-list">')
        list_end = html.find('</ul>', list_start)
        assert list_start != -1 and list_end != -1
        record_block = html[list_start:list_end]

        assert 'class="open-record open-record-gray"' in record_block
        assert '<span class="record-severity">' not in record_block
        assert '[Critical]' not in record_block

    def test_open_records_omits_eta_when_unset(
        self, app, make_area, make_equipment, make_repair_record,
    ):
        """Records with eta=None render no <span class=\"record-eta\">."""
        area = make_area(name='Shop')
        eq = make_equipment(name='OnlyOne', area=area)
        make_repair_record(equipment=eq, severity='Down', eta=None)

        html = static_page_service.generate()

        # The class name appears in the inline CSS rule; only the element
        # presence is meaningful, so match the rendered element form.
        assert '<span class="record-eta">' not in html

    def test_open_records_sorted_by_severity_priority_then_created_at(
        self, app, make_area, make_equipment, make_repair_record,
    ):
        """Open records are rendered in (severity priority, created_at) ASC order."""
        area = make_area(name='Shop')
        eq = make_equipment(name='OneTool', area=area)
        make_repair_record(
            equipment=eq, severity='Down',
            created_at=datetime(2026, 5, 1, tzinfo=UTC),
            description='down-newer',
        )
        make_repair_record(
            equipment=eq, severity='Not Sure',
            created_at=datetime(2026, 4, 1, tzinfo=UTC),
            description='notsure-older',
        )
        make_repair_record(
            equipment=eq, severity='Degraded',
            created_at=datetime(2026, 4, 15, tzinfo=UTC),
            description='degraded-mid',
        )

        html = static_page_service.generate()

        i_down = html.find('down-newer')
        i_deg = html.find('degraded-mid')
        i_ns = html.find('notsure-older')
        assert -1 < i_down < i_deg < i_ns

    def test_site_footer_replaces_old_generated_line(
        self, app, make_area, make_equipment,
    ):
        """Footer markup pins role, aria-labels, and link text; old <div class=\"footer\"> is gone."""
        area = make_area(name='Shop')
        make_equipment(name='Tool', area=area)

        html = static_page_service.generate()

        assert '<footer class="site-footer"' in html
        assert 'role="contentinfo"' in html
        assert 'aria-label="Site copyright and license"' in html
        assert '<small>' in html
        assert 'Jason Antman' in html
        assert 'aria-label="Source code on GitHub"' in html
        assert 'aria-label="MIT License (opensource.org)"' in html
        assert 'github.com/DecaturMakers/equipment-status-board' in html
        assert 'MIT licensed' in html
        assert '<div class="footer">' not in html

    def test_footer_renders_local_tz_year_as_entity(
        self, app, make_area, make_equipment,
    ):
        """The footer renders the local-tz year with a literal &copy; entity (Jinja does not decode)."""
        area = make_area(name='Shop')
        make_equipment(name='Tool', area=area)

        with patch.object(
            static_page_service,
            '_compute_generated_at',
            return_value=('2027-01-01 00:00:00 EST', 2027),
        ):
            html = static_page_service.generate()

        # Scope to inside <footer> so a regression that leaks the copyright
        # text into .generated-at (or elsewhere) doesn't accidentally pass.
        footer_start = html.find('<footer class="site-footer"')
        footer_end = html.find('</footer>', footer_start)
        assert footer_start != -1 and footer_end != -1
        assert '&copy; 2027 Jason Antman' in html[footer_start:footer_end]

    def test_footer_text_pin(self, app, make_area, make_equipment):
        """The static page contains the load-bearing substrings from _footer.html (R3F13)."""
        area = make_area(name='Shop')
        make_equipment(name='Tool', area=area)

        try:
            source = app.jinja_env.loader.get_source(
                app.jinja_env, 'components/_footer.html',
            )[0]
        except TemplateNotFound as e:
            raise AssertionError(
                "_footer.html not found — has it been moved or renamed? "
                "Update this pin test's path."
            ) from e

        # Sanity: the substrings we are pinning actually appear in the source.
        for needle in (
            'Jason Antman',
            'https://github.com/DecaturMakers/equipment-status-board',
            'https://opensource.org/license/mit',
        ):
            assert needle in source

        html = static_page_service.generate()
        for needle in (
            'Jason Antman',
            'https://github.com/DecaturMakers/equipment-status-board',
            'https://opensource.org/license/mit',
        ):
            assert needle in html

    def test_description_is_html_escaped(
        self, app, make_area, make_equipment, make_repair_record,
    ):
        """Repair-record descriptions are HTML-escaped (XSS defense)."""
        area = make_area(name='Shop')
        eq = make_equipment(name='Tool', area=area)
        make_repair_record(
            equipment=eq, severity='Down',
            description='<script>alert(1)</script><img src=x onerror=y>',
        )

        html = static_page_service.generate()

        assert '&lt;script&gt;' in html
        assert '<script>alert(1)</script>' not in html

    def test_description_escapes_entity_content(
        self, app, make_area, make_equipment, make_repair_record,
    ):
        """Entity-content in descriptions is autoescaped (R3F11)."""
        area = make_area(name='Shop')
        eq = make_equipment(name='Tool', area=area)
        make_repair_record(
            equipment=eq, severity='Down',
            description='Bob & Alice broke it; price was 50%<',
        )

        html = static_page_service.generate()

        assert 'Bob &amp; Alice broke it' in html
        assert '50%&lt;' in html
        assert 'Bob & Alice' not in html

    def test_equipment_row_keeps_dot_name_label_on_one_line(
        self, app, make_area, make_equipment,
    ):
        """The dot/name/label substrings appear within the equipment-row wrapper in order."""
        area = make_area(name='Shop')
        make_equipment(name='Tool', area=area)

        html = static_page_service.generate()

        row_start = html.find('<div class="equipment-row">')
        assert row_start != -1
        row_end = html.find('</div>', row_start)
        assert row_end != -1
        slice_ = html[row_start:row_end]
        i_dot = slice_.find('status-dot')
        i_name = slice_.find('equipment-name')
        i_label = slice_.find('status-label')
        assert -1 < i_dot < i_name < i_label

    def test_description_uses_prewrap_styles(self, app):
        """The pre-wrap CSS rule appears verbatim in the inline style block."""
        html = static_page_service.generate()
        assert (
            '.record-description { white-space: pre-wrap; overflow-wrap: anywhere; }'
            in html
        )

    def test_archived_areas_and_equipment_are_excluded(
        self, app, make_area, make_equipment,
    ):
        """Archived areas and archived equipment do not appear in the rendered HTML."""
        # Archived area, with one equipment item, should not appear.
        from esb.extensions import db as _db
        from esb.models.area import Area

        archived_area = Area(name='Archived Area', is_archived=True)
        _db.session.add(archived_area)
        _db.session.commit()
        make_equipment(name='Archived Tool', area=archived_area)

        active_area = make_area(name='Active Area')
        make_equipment(name='Active Tool', area=active_area)

        html = static_page_service.generate()
        assert 'Active Area' in html
        assert 'Archived Area' not in html

        # Within an active area: archived equipment is excluded.
        area = make_area(name='Visible Area', slack_channel='#visible')
        make_equipment(name='Visible Tool', area=area)
        make_equipment(name='Retired Tool', area=area, is_archived=True)

        html2 = static_page_service.generate()
        assert 'Visible Tool' in html2
        assert 'Retired Tool' not in html2

    def test_empty_dashboard_renders_skeleton(self, app):
        """With no non-archived areas, the page still renders the skeleton."""
        html = static_page_service.generate()

        assert '<h1>Equipment Status</h1>' in html
        assert '<div class="generated-at">' in html
        assert '<footer class="site-footer"' in html
        assert '<div class="area">' not in html

    def test_two_equipment_with_same_name_in_different_areas(
        self, app, make_area, make_equipment, make_repair_record,
    ):
        """Same equipment name in different areas: records appear under correct area."""
        area_a = make_area(name='Area A', slack_channel='#area-a')
        area_b = make_area(name='Area B', slack_channel='#area-b')
        eq_a = make_equipment(name='Drill Press', area=area_a)
        eq_b = make_equipment(name='Drill Press', area=area_b)
        make_repair_record(equipment=eq_a, severity='Down', description='a-issue')
        make_repair_record(equipment=eq_b, severity='Down', description='b-issue')

        html = static_page_service.generate()

        i_a = html.find('Area A')
        i_a_issue = html.find('a-issue')
        i_b = html.find('Area B')
        i_b_issue = html.find('b-issue')
        assert -1 < i_a < i_a_issue < i_b < i_b_issue

    def test_generate_orders_areas_by_sort_order_then_name(
        self, app, make_area, make_equipment,
    ):
        """Static export renders area sections by (sort_order, name)."""
        area_a = make_area(name='Area A', slack_channel='#a', sort_order=10)
        area_b = make_area(name='Area B', slack_channel='#b', sort_order=5)
        area_c = make_area(name='Area C', slack_channel='#c', sort_order=5)
        make_equipment(name='Tool A', area=area_a)
        make_equipment(name='Tool B', area=area_b)
        make_equipment(name='Tool C', area=area_c)

        html = static_page_service.generate()
        pos_b = html.find('Area B')
        pos_c = html.find('Area C')
        pos_a = html.find('Area A')
        assert pos_b >= 0 and pos_c >= 0 and pos_a >= 0, (
            'area names missing from rendered HTML'
        )
        assert pos_b < pos_c < pos_a


class TestPushLocal:
    """Tests for push() with method='local'."""

    def test_writes_file_to_target_directory(self, app, tmp_path):
        """push() with method='local' writes index.html to target directory."""
        app.config['STATIC_PAGE_PUSH_METHOD'] = 'local'
        app.config['STATIC_PAGE_PUSH_TARGET'] = str(tmp_path)

        static_page_service.push('<html>test</html>')

        output_file = tmp_path / 'index.html'
        assert output_file.exists()
        assert output_file.read_text() == '<html>test</html>'

    def test_creates_directory_if_needed(self, app, tmp_path, capture):
        """push() with method='local' creates target directory if it doesn't exist."""
        target = str(tmp_path / 'new_subdir')
        app.config['STATIC_PAGE_PUSH_METHOD'] = 'local'
        app.config['STATIC_PAGE_PUSH_TARGET'] = target

        static_page_service.push('<html>test</html>')

        assert os.path.exists(os.path.join(target, 'index.html'))

    def test_os_error_raises_runtime_error(self, app):
        """push() with method='local' raises RuntimeError when OS write fails."""
        app.config['STATIC_PAGE_PUSH_METHOD'] = 'local'
        app.config['STATIC_PAGE_PUSH_TARGET'] = '/tmp/test-esb-local'

        with patch('esb.services.static_page_service.os.makedirs',
                   side_effect=OSError('Permission denied')):
            with pytest.raises(RuntimeError, match='Failed to write static page'):
                static_page_service.push('<html>test</html>')


class TestPushS3:
    """Tests for push() with method='s3'."""

    def test_calls_boto3_put_object(self, app, capture):
        """push() with method='s3' calls boto3 put_object with correct params."""
        app.config['STATIC_PAGE_PUSH_METHOD'] = 's3'
        app.config['STATIC_PAGE_PUSH_TARGET'] = 'my-bucket/status/index.html'

        import boto3
        mock_s3 = MagicMock()

        with patch.object(boto3, 'client', return_value=mock_s3) as mock_client:
            static_page_service.push('<html>test</html>')

            mock_client.assert_called_once_with('s3')
            mock_s3.put_object.assert_called_once_with(
                Bucket='my-bucket',
                Key='status/index.html',
                Body=b'<html>test</html>',
                ContentType='text/html; charset=utf-8',
                CacheControl='no-cache, no-store, must-revalidate',
            )

    def test_handles_client_error(self, app):
        """push() with method='s3' handles ClientError by raising RuntimeError."""
        app.config['STATIC_PAGE_PUSH_METHOD'] = 's3'
        app.config['STATIC_PAGE_PUSH_TARGET'] = 'my-bucket/index.html'

        import boto3
        from botocore.exceptions import ClientError

        mock_s3 = MagicMock()
        error_response = {'Error': {'Code': 'AccessDenied', 'Message': 'Access Denied'}}
        mock_s3.put_object.side_effect = ClientError(error_response, 'PutObject')

        with patch.object(boto3, 'client', return_value=mock_s3):
            with pytest.raises(RuntimeError, match='S3 upload failed'):
                static_page_service.push('<html>test</html>')

    def test_handles_no_credentials_error(self, app):
        """push() with method='s3' handles NoCredentialsError by raising RuntimeError."""
        app.config['STATIC_PAGE_PUSH_METHOD'] = 's3'
        app.config['STATIC_PAGE_PUSH_TARGET'] = 'my-bucket/index.html'

        import boto3
        from botocore.exceptions import NoCredentialsError

        mock_s3 = MagicMock()
        mock_s3.put_object.side_effect = NoCredentialsError()

        with patch.object(boto3, 'client', return_value=mock_s3):
            with pytest.raises(RuntimeError, match='AWS credentials not configured'):
                static_page_service.push('<html>test</html>')

    def test_empty_bucket_raises_runtime_error(self, app):
        """push() with method='s3' and target starting with / raises RuntimeError for empty bucket."""
        app.config['STATIC_PAGE_PUSH_METHOD'] = 's3'
        app.config['STATIC_PAGE_PUSH_TARGET'] = '/key/path'

        with pytest.raises(RuntimeError, match='bucket name is empty'):
            static_page_service.push('<html>test</html>')

    def test_default_key_when_no_path(self, app, capture):
        """push() with method='s3' defaults key to index.html when target has no path."""
        app.config['STATIC_PAGE_PUSH_METHOD'] = 's3'
        app.config['STATIC_PAGE_PUSH_TARGET'] = 'my-bucket'

        import boto3
        mock_s3 = MagicMock()

        with patch.object(boto3, 'client', return_value=mock_s3):
            static_page_service.push('<html>test</html>')

            call_kwargs = mock_s3.put_object.call_args[1]
            assert call_kwargs['Bucket'] == 'my-bucket'
            assert call_kwargs['Key'] == 'index.html'


class TestPushS3CloudFrontInvalidation:
    """Tests for CloudFront invalidation triggered by push() with method='s3'."""

    @staticmethod
    def _boto_client_factory(s3_mock, cf_mock):
        def factory(service):
            if service == 's3':
                return s3_mock
            if service == 'cloudfront':
                return cf_mock
            raise ValueError(f'unexpected boto3 client {service!r}')
        return factory

    def test_no_invalidation_when_distribution_id_unset(self, app):
        """No CloudFront client used when CLOUDFRONT_DISTRIBUTION_ID is empty."""
        app.config['STATIC_PAGE_PUSH_METHOD'] = 's3'
        app.config['STATIC_PAGE_PUSH_TARGET'] = 'my-bucket/index.html'
        app.config['CLOUDFRONT_DISTRIBUTION_ID'] = ''

        import boto3
        mock_s3 = MagicMock()
        mock_cf = MagicMock()

        with patch.object(boto3, 'client', side_effect=self._boto_client_factory(mock_s3, mock_cf)):
            static_page_service.push('<html>test</html>')

        mock_cf.create_invalidation.assert_not_called()

    def test_invalidates_after_successful_push(self, app):
        """CloudFront invalidation created after every successful S3 upload when distribution set."""
        app.config['STATIC_PAGE_PUSH_METHOD'] = 's3'
        app.config['STATIC_PAGE_PUSH_TARGET'] = 'my-bucket/status/index.html'
        app.config['CLOUDFRONT_DISTRIBUTION_ID'] = 'EDFDVBD6EXAMPLE'

        import boto3
        mock_s3 = MagicMock()
        mock_cf = MagicMock()
        mock_cf.create_invalidation.return_value = {'Invalidation': {'Id': 'I1234'}}

        with patch.object(boto3, 'client', side_effect=self._boto_client_factory(mock_s3, mock_cf)):
            static_page_service.push('<html>x</html>')

        mock_s3.put_object.assert_called_once()
        mock_cf.create_invalidation.assert_called_once()
        call_kwargs = mock_cf.create_invalidation.call_args[1]
        assert call_kwargs['DistributionId'] == 'EDFDVBD6EXAMPLE'
        assert call_kwargs['InvalidationBatch']['Paths'] == {
            'Quantity': 1, 'Items': ['/status/index.html'],
        }
        assert call_kwargs['InvalidationBatch']['CallerReference'].startswith('esb-')

    def test_invalidation_path_url_encodes_special_characters(self, app):
        """Invalidation path URL-encodes special characters in the S3 key."""
        app.config['STATIC_PAGE_PUSH_METHOD'] = 's3'
        app.config['STATIC_PAGE_PUSH_TARGET'] = 'my-bucket/status pages/page+v2.html'
        app.config['CLOUDFRONT_DISTRIBUTION_ID'] = 'EDFDVBD6EXAMPLE'

        import boto3
        mock_s3 = MagicMock()
        mock_cf = MagicMock()
        mock_cf.create_invalidation.return_value = {'Invalidation': {'Id': 'I1'}}

        with patch.object(boto3, 'client', side_effect=self._boto_client_factory(mock_s3, mock_cf)):
            static_page_service.push('<html>x</html>')

        items = mock_cf.create_invalidation.call_args[1]['InvalidationBatch']['Paths']['Items']
        # Slash in the key is preserved, but space and `+` are percent-encoded.
        assert items == ['/status%20pages/page%2Bv2.html']

    def test_caller_reference_unique_across_calls(self, app):
        """Successive invalidations get distinct CallerReference values (uuid-based)."""
        app.config['STATIC_PAGE_PUSH_METHOD'] = 's3'
        app.config['STATIC_PAGE_PUSH_TARGET'] = 'my-bucket/index.html'
        app.config['CLOUDFRONT_DISTRIBUTION_ID'] = 'EDFDVBD6EXAMPLE'

        import boto3
        mock_s3 = MagicMock()
        mock_cf = MagicMock()
        mock_cf.create_invalidation.side_effect = [
            {'Invalidation': {'Id': 'I1'}},
            {'Invalidation': {'Id': 'I2'}},
        ]

        with patch.object(boto3, 'client', side_effect=self._boto_client_factory(mock_s3, mock_cf)):
            static_page_service.push('<html>x</html>')
            static_page_service.push('<html>x</html>')

        refs = [
            call.kwargs['InvalidationBatch']['CallerReference']
            for call in mock_cf.create_invalidation.call_args_list
        ]
        assert refs[0] != refs[1]

    def test_invalidation_client_error_raises_runtime_error(self, app):
        """CloudFront ClientError surfaces as RuntimeError."""
        app.config['STATIC_PAGE_PUSH_METHOD'] = 's3'
        app.config['STATIC_PAGE_PUSH_TARGET'] = 'my-bucket/index.html'
        app.config['CLOUDFRONT_DISTRIBUTION_ID'] = 'EDFDVBD6EXAMPLE'

        import boto3
        from botocore.exceptions import ClientError

        mock_s3 = MagicMock()
        mock_cf = MagicMock()
        mock_cf.create_invalidation.side_effect = ClientError(
            {'Error': {'Code': 'AccessDenied', 'Message': 'denied'}}, 'CreateInvalidation'
        )

        with patch.object(boto3, 'client', side_effect=self._boto_client_factory(mock_s3, mock_cf)):
            with pytest.raises(RuntimeError, match='CloudFront invalidation failed'):
                static_page_service.push('<html>x</html>')

    def test_invalidation_no_credentials_raises_runtime_error(self, app):
        """CloudFront NoCredentialsError surfaces as RuntimeError."""
        app.config['STATIC_PAGE_PUSH_METHOD'] = 's3'
        app.config['STATIC_PAGE_PUSH_TARGET'] = 'my-bucket/index.html'
        app.config['CLOUDFRONT_DISTRIBUTION_ID'] = 'EDFDVBD6EXAMPLE'

        import boto3
        from botocore.exceptions import NoCredentialsError

        mock_s3 = MagicMock()
        mock_cf = MagicMock()
        mock_cf.create_invalidation.side_effect = NoCredentialsError()

        with patch.object(boto3, 'client', side_effect=self._boto_client_factory(mock_s3, mock_cf)):
            with pytest.raises(RuntimeError, match='AWS credentials not configured for CloudFront invalidation'):
                static_page_service.push('<html>x</html>')

    def test_audit_log_includes_invalidation_id(self, app, capture):
        """The static_page.pushed audit event records the CloudFront invalidation ID."""
        app.config['STATIC_PAGE_PUSH_METHOD'] = 's3'
        app.config['STATIC_PAGE_PUSH_TARGET'] = 'my-bucket/index.html'
        app.config['CLOUDFRONT_DISTRIBUTION_ID'] = 'EDFDVBD6EXAMPLE'

        import boto3
        mock_s3 = MagicMock()
        mock_cf = MagicMock()
        mock_cf.create_invalidation.return_value = {'Invalidation': {'Id': 'IABCDEF'}}

        with patch.object(boto3, 'client', side_effect=self._boto_client_factory(mock_s3, mock_cf)):
            static_page_service.push('<html>x</html>')

        assert len(capture.records) == 1
        log_data = json.loads(capture.records[0].message)
        assert log_data['event'] == 'static_page.pushed'
        assert log_data['data']['method'] == 's3'
        assert log_data['data']['cloudfront_invalidation_id'] == 'IABCDEF'

    def test_audit_log_omits_invalidation_id_when_distribution_unset(self, app, capture):
        """The audit event does not include cloudfront_invalidation_id when distribution is unset."""
        app.config['STATIC_PAGE_PUSH_METHOD'] = 's3'
        app.config['STATIC_PAGE_PUSH_TARGET'] = 'my-bucket/index.html'
        app.config['CLOUDFRONT_DISTRIBUTION_ID'] = ''

        import boto3
        mock_s3 = MagicMock()
        mock_cf = MagicMock()

        with patch.object(boto3, 'client', side_effect=self._boto_client_factory(mock_s3, mock_cf)):
            static_page_service.push('<html>x</html>')

        log_data = json.loads(capture.records[0].message)
        assert 'cloudfront_invalidation_id' not in log_data['data']


class TestPushGCS:
    """Tests for push() with method='gcs'."""

    def test_calls_gcs_upload_from_string(self, app, capture):
        """push() with method='gcs' calls GCS upload_from_string with correct params."""
        app.config['STATIC_PAGE_PUSH_METHOD'] = 'gcs'
        app.config['STATIC_PAGE_PUSH_TARGET'] = 'my-bucket/status/index.html'

        from google.cloud import storage
        mock_client = MagicMock()
        mock_bucket = MagicMock()
        mock_blob = MagicMock()
        mock_client.bucket.return_value = mock_bucket
        mock_bucket.blob.return_value = mock_blob

        with patch.object(storage, 'Client', return_value=mock_client) as mock_cls:
            static_page_service.push('<html>test</html>')

            mock_cls.assert_called_once()
            mock_client.bucket.assert_called_once_with('my-bucket')
            mock_bucket.blob.assert_called_once_with('status/index.html')
            assert mock_blob.cache_control == 'no-cache, no-store, must-revalidate'
            mock_blob.upload_from_string.assert_called_once_with(
                '<html>test</html>', content_type='text/html; charset=utf-8'
            )

    def test_handles_google_api_error(self, app):
        """push() with method='gcs' handles GoogleAPIError by raising RuntimeError."""
        app.config['STATIC_PAGE_PUSH_METHOD'] = 'gcs'
        app.config['STATIC_PAGE_PUSH_TARGET'] = 'my-bucket/index.html'

        from google.api_core.exceptions import GoogleAPIError
        from google.cloud import storage
        mock_client = MagicMock()
        mock_bucket = MagicMock()
        mock_blob = MagicMock()
        mock_client.bucket.return_value = mock_bucket
        mock_bucket.blob.return_value = mock_blob
        mock_blob.upload_from_string.side_effect = GoogleAPIError('Forbidden')

        with patch.object(storage, 'Client', return_value=mock_client):
            with pytest.raises(RuntimeError, match='GCS upload failed'):
                static_page_service.push('<html>test</html>')

    def test_handles_default_credentials_error(self, app):
        """push() with method='gcs' handles DefaultCredentialsError by raising RuntimeError."""
        app.config['STATIC_PAGE_PUSH_METHOD'] = 'gcs'
        app.config['STATIC_PAGE_PUSH_TARGET'] = 'my-bucket/index.html'

        from google.auth.exceptions import DefaultCredentialsError
        from google.cloud import storage

        with patch.object(storage, 'Client', side_effect=DefaultCredentialsError('msg')):
            with pytest.raises(RuntimeError, match='Google Cloud credentials not configured'):
                static_page_service.push('<html>test</html>')

    def test_empty_bucket_raises_runtime_error(self, app):
        """push() with method='gcs' and target starting with / raises RuntimeError for empty bucket."""
        app.config['STATIC_PAGE_PUSH_METHOD'] = 'gcs'
        app.config['STATIC_PAGE_PUSH_TARGET'] = '/key/path'

        with pytest.raises(RuntimeError, match='bucket name is empty'):
            static_page_service.push('<html>test</html>')

    def test_default_key_when_no_path(self, app, capture):
        """push() with method='gcs' defaults key to index.html when target has no path."""
        app.config['STATIC_PAGE_PUSH_METHOD'] = 'gcs'
        app.config['STATIC_PAGE_PUSH_TARGET'] = 'my-bucket'

        from google.cloud import storage
        mock_client = MagicMock()
        mock_bucket = MagicMock()
        mock_blob = MagicMock()
        mock_client.bucket.return_value = mock_bucket
        mock_bucket.blob.return_value = mock_blob

        with patch.object(storage, 'Client', return_value=mock_client):
            static_page_service.push('<html>test</html>')

            mock_bucket.blob.assert_called_once_with('index.html')

    def test_trailing_slash_defaults_key_to_index_html(self, app, capture):
        """push() with method='gcs' and trailing slash target defaults key to index.html."""
        app.config['STATIC_PAGE_PUSH_METHOD'] = 'gcs'
        app.config['STATIC_PAGE_PUSH_TARGET'] = 'my-bucket/'

        from google.cloud import storage
        mock_client = MagicMock()
        mock_bucket = MagicMock()
        mock_blob = MagicMock()
        mock_client.bucket.return_value = mock_bucket
        mock_bucket.blob.return_value = mock_blob

        with patch.object(storage, 'Client', return_value=mock_client):
            static_page_service.push('<html>test</html>')

            mock_client.bucket.assert_called_once_with('my-bucket')
            mock_bucket.blob.assert_called_once_with('index.html')

    def test_import_error_raises_runtime_error(self, app):
        """push() with method='gcs' raises RuntimeError when google-cloud-storage not installed."""
        app.config['STATIC_PAGE_PUSH_METHOD'] = 'gcs'
        app.config['STATIC_PAGE_PUSH_TARGET'] = 'my-bucket/index.html'

        with patch.dict('sys.modules', {'google.cloud': None, 'google.api_core': None,
                                         'google.api_core.exceptions': None, 'google.auth': None,
                                         'google.auth.exceptions': None, 'google.cloud.storage': None,
                                         'google': None}):
            with pytest.raises(RuntimeError, match='google-cloud-storage is required'):
                static_page_service.push('<html>test</html>')


class TestPushErrors:
    """Tests for push() error handling."""

    def test_empty_target_raises_runtime_error(self, app):
        """push() with empty target raises RuntimeError."""
        app.config['STATIC_PAGE_PUSH_METHOD'] = 'local'
        app.config['STATIC_PAGE_PUSH_TARGET'] = ''

        with pytest.raises(RuntimeError, match='STATIC_PAGE_PUSH_TARGET is not configured'):
            static_page_service.push('<html>test</html>')

    def test_unknown_method_raises_runtime_error(self, app):
        """push() with unknown method raises RuntimeError."""
        app.config['STATIC_PAGE_PUSH_METHOD'] = 'ftp'
        app.config['STATIC_PAGE_PUSH_TARGET'] = '/tmp/test'

        with pytest.raises(RuntimeError, match='Unknown STATIC_PAGE_PUSH_METHOD'):
            static_page_service.push('<html>test</html>')


class TestPushMutationLogging:
    """Tests for mutation logging on push."""

    def test_logs_mutation_on_local_push(self, app, tmp_path, capture):
        """push() logs a mutation event on successful local push."""
        app.config['STATIC_PAGE_PUSH_METHOD'] = 'local'
        app.config['STATIC_PAGE_PUSH_TARGET'] = str(tmp_path)

        static_page_service.push('<html>test</html>')

        assert len(capture.records) == 1
        log_data = json.loads(capture.records[0].message)
        assert log_data['event'] == 'static_page.pushed'
        assert log_data['data']['method'] == 'local'

    def test_logs_mutation_on_gcs_push(self, app, capture):
        """push() logs a mutation event on successful GCS push."""
        app.config['STATIC_PAGE_PUSH_METHOD'] = 'gcs'
        app.config['STATIC_PAGE_PUSH_TARGET'] = 'my-bucket/index.html'

        from google.cloud import storage
        mock_client = MagicMock()
        mock_bucket = MagicMock()
        mock_blob = MagicMock()
        mock_client.bucket.return_value = mock_bucket
        mock_bucket.blob.return_value = mock_blob

        with patch.object(storage, 'Client', return_value=mock_client):
            static_page_service.push('<html>test</html>')

        assert len(capture.records) == 1
        log_data = json.loads(capture.records[0].message)
        assert log_data['event'] == 'static_page.pushed'
        assert log_data['data']['method'] == 'gcs'


class TestGenerateAndPush:
    """Tests for generate_and_push()."""

    def test_calls_generate_then_push(self, app):
        """generate_and_push() calls generate() then push()."""
        with patch.object(static_page_service, 'generate', return_value='<html>mock</html>') as mock_gen, \
             patch.object(static_page_service, 'push') as mock_push:
            static_page_service.generate_and_push()

            mock_gen.assert_called_once()
            mock_push.assert_called_once_with('<html>mock</html>')
