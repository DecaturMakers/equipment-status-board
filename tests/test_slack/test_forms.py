"""Tests for Slack Block Kit modal builder functions (esb/slack/forms.py)."""

import pytest

from tests.conftest import _create_area, _create_equipment, _create_user


class TestBuildEquipmentOptions:
    """Tests for build_equipment_options()."""

    @pytest.fixture(autouse=True)
    def setup(self, app, db):
        self.app = app
        self.db = db

    def test_returns_non_archived_equipment(self):
        area = _create_area(name='Woodshop')
        _create_equipment(name='SawStop', area=area)
        _create_equipment(name='Drill Press', area=area)

        from esb.slack.forms import build_equipment_options
        options = build_equipment_options()

        assert len(options) == 2
        texts = [o['text']['text'] for o in options]
        assert 'Drill Press (Woodshop)' in texts
        assert 'SawStop (Woodshop)' in texts

    def test_excludes_archived_equipment(self):
        area = _create_area(name='Metalshop')
        _create_equipment(name='Active Lathe', area=area)
        _create_equipment(name='Old Mill', area=area, is_archived=True)

        from esb.slack.forms import build_equipment_options
        options = build_equipment_options()

        assert len(options) == 1
        assert options[0]['text']['text'] == 'Active Lathe (Metalshop)'

    def test_returns_correct_option_format(self):
        area = _create_area(name='Lab')
        equip = _create_equipment(name='Oscilloscope', area=area)

        from esb.slack.forms import build_equipment_options
        options = build_equipment_options()

        assert len(options) == 1
        opt = options[0]
        assert opt['text']['type'] == 'plain_text'
        assert opt['text']['text'] == 'Oscilloscope (Lab)'
        assert opt['value'] == str(equip.id)

    def test_returns_empty_list_when_no_equipment(self):
        from esb.slack.forms import build_equipment_options
        options = build_equipment_options()
        assert options == []

    def test_options_ordered_by_name(self):
        area = _create_area(name='Shop')
        _create_equipment(name='Zebra Saw', area=area)
        _create_equipment(name='Alpha Drill', area=area)
        _create_equipment(name='Mike Lathe', area=area)

        from esb.slack.forms import build_equipment_options
        options = build_equipment_options()

        texts = [o['text']['text'] for o in options]
        assert texts == ['Alpha Drill (Shop)', 'Mike Lathe (Shop)', 'Zebra Saw (Shop)']

    def test_truncates_long_names(self):
        area = _create_area(name='A' * 50)
        _create_equipment(name='B' * 50, area=area)

        from esb.slack.forms import build_equipment_options
        options = build_equipment_options()

        assert len(options[0]['text']['text']) <= 75


class TestBuildUserOptions:
    """Tests for build_user_options()."""

    @pytest.fixture(autouse=True)
    def setup(self, app, db):
        self.app = app
        self.db = db

    def test_returns_active_tech_and_staff(self):
        _create_user('staff', username='admin1')
        _create_user('technician', username='tech1')

        from esb.slack.forms import build_user_options
        options = build_user_options()

        assert len(options) == 2
        texts = [o['text']['text'] for o in options]
        assert 'admin1 (staff)' in texts
        assert 'tech1 (technician)' in texts

    def test_excludes_member_role(self):
        _create_user('staff', username='staffuser')
        _create_user('member', username='memberuser')

        from esb.slack.forms import build_user_options
        options = build_user_options()

        assert len(options) == 1
        assert options[0]['text']['text'] == 'staffuser (staff)'

    def test_excludes_inactive_users(self):
        user = _create_user('technician', username='inactive_tech')
        user.is_active = False
        self.db.session.commit()

        from esb.slack.forms import build_user_options
        options = build_user_options()

        assert len(options) == 0

    def test_returns_correct_option_format(self):
        user = _create_user('staff', username='admin2')

        from esb.slack.forms import build_user_options
        options = build_user_options()

        assert len(options) == 1
        opt = options[0]
        assert opt['text']['type'] == 'plain_text'
        assert opt['value'] == str(user.id)

    def test_ordered_by_username(self):
        _create_user('staff', username='zara')
        _create_user('technician', username='alice')
        _create_user('staff', username='mike')

        from esb.slack.forms import build_user_options
        options = build_user_options()

        texts = [o['text']['text'] for o in options]
        assert texts[0].startswith('alice')
        assert texts[1].startswith('mike')
        assert texts[2].startswith('zara')


class TestBuildProblemReportModal:
    """Tests for build_problem_report_modal()."""

    def test_returns_valid_modal_structure(self):
        from esb.slack.forms import build_problem_report_modal

        options = [{'text': {'type': 'plain_text', 'text': 'Saw (Shop)'}, 'value': '1'}]
        modal = build_problem_report_modal(options)

        assert modal['type'] == 'modal'
        assert modal['callback_id'] == 'problem_report_submission'
        assert modal['title']['text'] == 'Report a Problem'
        assert modal['submit']['text'] == 'Submit Report'
        assert modal['close']['text'] == 'Cancel'

    def test_has_correct_blocks(self):
        from esb.slack.forms import build_problem_report_modal

        options = [{'text': {'type': 'plain_text', 'text': 'Saw (Shop)'}, 'value': '1'}]
        modal = build_problem_report_modal(options)

        block_ids = [b['block_id'] for b in modal['blocks']]
        assert 'equipment_block' in block_ids
        assert 'name_block' in block_ids
        assert 'description_block' in block_ids
        assert 'severity_block' in block_ids
        assert 'safety_risk_block' in block_ids
        assert 'consumable_block' in block_ids

    def test_severity_defaults_to_not_sure(self):
        from esb.slack.forms import build_problem_report_modal

        options = [{'text': {'type': 'plain_text', 'text': 'Saw (Shop)'}, 'value': '1'}]
        modal = build_problem_report_modal(options)

        severity_block = [b for b in modal['blocks'] if b['block_id'] == 'severity_block'][0]
        initial = severity_block['element']['initial_option']
        assert initial['value'] == 'Not Sure'

    def test_equipment_options_passed_through(self):
        from esb.slack.forms import build_problem_report_modal

        options = [
            {'text': {'type': 'plain_text', 'text': 'Saw (Shop)'}, 'value': '1'},
            {'text': {'type': 'plain_text', 'text': 'Drill (Lab)'}, 'value': '2'},
        ]
        modal = build_problem_report_modal(options)

        equip_block = [b for b in modal['blocks'] if b['block_id'] == 'equipment_block'][0]
        assert equip_block['element']['options'] == options


class TestBuildRepairCreateModal:
    """Tests for build_repair_create_modal()."""

    def test_returns_valid_modal_structure(self):
        from esb.slack.forms import build_repair_create_modal

        equip_opts = [{'text': {'type': 'plain_text', 'text': 'Saw (Shop)'}, 'value': '1'}]
        user_opts = [{'text': {'type': 'plain_text', 'text': 'admin (staff)'}, 'value': '1'}]
        modal = build_repair_create_modal(equip_opts, user_opts)

        assert modal['type'] == 'modal'
        assert modal['callback_id'] == 'repair_create_submission'
        assert modal['title']['text'] == 'Create Repair Record'

    def test_has_equipment_and_user_selectors(self):
        from esb.slack.forms import build_repair_create_modal

        equip_opts = [{'text': {'type': 'plain_text', 'text': 'Saw (Shop)'}, 'value': '1'}]
        user_opts = [{'text': {'type': 'plain_text', 'text': 'admin (staff)'}, 'value': '1'}]
        modal = build_repair_create_modal(equip_opts, user_opts)

        block_ids = [b['block_id'] for b in modal['blocks']]
        assert 'equipment_block' in block_ids
        assert 'description_block' in block_ids
        assert 'severity_block' in block_ids
        assert 'assignee_block' in block_ids
        assert 'status_block' in block_ids

    def test_status_defaults_to_new(self):
        from esb.slack.forms import build_repair_create_modal

        equip_opts = [{'text': {'type': 'plain_text', 'text': 'Saw'}, 'value': '1'}]
        user_opts = [{'text': {'type': 'plain_text', 'text': 'admin'}, 'value': '1'}]
        modal = build_repair_create_modal(equip_opts, user_opts)

        status_block = [b for b in modal['blocks'] if b['block_id'] == 'status_block'][0]
        assert status_block['element']['initial_option']['value'] == 'New'

    def test_all_statuses_available(self):
        from esb.models.repair_record import REPAIR_STATUSES
        from esb.slack.forms import build_repair_create_modal

        equip_opts = [{'text': {'type': 'plain_text', 'text': 'Saw'}, 'value': '1'}]
        user_opts = [{'text': {'type': 'plain_text', 'text': 'admin'}, 'value': '1'}]
        modal = build_repair_create_modal(equip_opts, user_opts)

        status_block = [b for b in modal['blocks'] if b['block_id'] == 'status_block'][0]
        status_values = [o['value'] for o in status_block['element']['options']]
        # Closed - Duplicate is filtered out of the create modal: a repair
        # cannot be created already-duplicate (the dup-target dropdown lives on
        # the action modal). See tech-spec Technical Decisions §10.
        assert status_values == [s for s in REPAIR_STATUSES if s != 'Closed - Duplicate']

    def test_no_assignee_block_when_no_users(self):
        """L2: Assignee block is excluded when no users available."""
        from esb.slack.forms import build_repair_create_modal

        equip_opts = [{'text': {'type': 'plain_text', 'text': 'Saw'}, 'value': '1'}]
        modal = build_repair_create_modal(equip_opts, [])

        block_ids = [b['block_id'] for b in modal['blocks']]
        assert 'assignee_block' not in block_ids


class TestBuildRepairUpdateModal:
    """Tests for build_repair_update_modal()."""

    @pytest.fixture(autouse=True)
    def setup(self, app, db):
        self.app = app
        self.db = db

    def _make_record(self, **kwargs):
        area = _create_area(name='Shop')
        equip = _create_equipment(name='Saw', area=area)
        defaults = {
            'equipment_id': equip.id,
            'status': 'In Progress',
            'severity': 'Down',
            'description': 'Broken blade',
        }
        defaults.update(kwargs)
        from esb.models.repair_record import RepairRecord
        record = RepairRecord(**defaults)
        self.db.session.add(record)
        self.db.session.commit()
        return record

    def test_returns_valid_modal_with_prepopulated_values(self):
        from esb.models.repair_record import REPAIR_SEVERITIES, REPAIR_STATUSES
        from esb.slack.forms import build_repair_update_modal

        record = self._make_record()
        status_opts = [{'text': {'type': 'plain_text', 'text': s}, 'value': s} for s in REPAIR_STATUSES]
        severity_opts = [{'text': {'type': 'plain_text', 'text': s}, 'value': s} for s in REPAIR_SEVERITIES]
        user_opts = [{'text': {'type': 'plain_text', 'text': 'admin (staff)'}, 'value': '1'}]

        modal = build_repair_update_modal(record, status_opts, severity_opts, user_opts)

        assert modal['type'] == 'modal'
        assert modal['callback_id'] == 'repair_update_submission'
        assert modal['private_metadata'] == str(record.id)

    def test_status_prepopulated(self):
        from esb.models.repair_record import REPAIR_SEVERITIES, REPAIR_STATUSES
        from esb.slack.forms import build_repair_update_modal

        record = self._make_record(status='Parts Needed')
        status_opts = [{'text': {'type': 'plain_text', 'text': s}, 'value': s} for s in REPAIR_STATUSES]
        severity_opts = [{'text': {'type': 'plain_text', 'text': s}, 'value': s} for s in REPAIR_SEVERITIES]

        modal = build_repair_update_modal(record, status_opts, severity_opts, [])

        status_block = [b for b in modal['blocks'] if b['block_id'] == 'status_block'][0]
        assert status_block['element']['initial_option']['value'] == 'Parts Needed'

    def test_severity_prepopulated_when_present(self):
        from esb.models.repair_record import REPAIR_SEVERITIES, REPAIR_STATUSES
        from esb.slack.forms import build_repair_update_modal

        record = self._make_record(severity='Degraded')
        status_opts = [{'text': {'type': 'plain_text', 'text': s}, 'value': s} for s in REPAIR_STATUSES]
        severity_opts = [{'text': {'type': 'plain_text', 'text': s}, 'value': s} for s in REPAIR_SEVERITIES]

        modal = build_repair_update_modal(record, status_opts, severity_opts, [])

        severity_block = [b for b in modal['blocks'] if b['block_id'] == 'severity_block'][0]
        assert severity_block['element']['initial_option']['value'] == 'Degraded'

    def test_severity_not_prepopulated_when_none(self):
        from esb.models.repair_record import REPAIR_SEVERITIES, REPAIR_STATUSES
        from esb.slack.forms import build_repair_update_modal

        record = self._make_record(severity=None)
        status_opts = [{'text': {'type': 'plain_text', 'text': s}, 'value': s} for s in REPAIR_STATUSES]
        severity_opts = [{'text': {'type': 'plain_text', 'text': s}, 'value': s} for s in REPAIR_SEVERITIES]

        modal = build_repair_update_modal(record, status_opts, severity_opts, [])

        severity_block = [b for b in modal['blocks'] if b['block_id'] == 'severity_block'][0]
        assert 'initial_option' not in severity_block['element']

    def test_eta_prepopulated_when_present(self):
        from datetime import date

        from esb.models.repair_record import REPAIR_SEVERITIES, REPAIR_STATUSES
        from esb.slack.forms import build_repair_update_modal

        record = self._make_record(eta=date(2026, 3, 15))
        status_opts = [{'text': {'type': 'plain_text', 'text': s}, 'value': s} for s in REPAIR_STATUSES]
        severity_opts = [{'text': {'type': 'plain_text', 'text': s}, 'value': s} for s in REPAIR_SEVERITIES]

        modal = build_repair_update_modal(record, status_opts, severity_opts, [])

        eta_block = [b for b in modal['blocks'] if b['block_id'] == 'eta_block'][0]
        assert eta_block['element']['initial_date'] == '2026-03-15'

    def test_specialist_description_prepopulated(self):
        from esb.models.repair_record import REPAIR_SEVERITIES, REPAIR_STATUSES
        from esb.slack.forms import build_repair_update_modal

        record = self._make_record(specialist_description='Needs electrician')
        status_opts = [{'text': {'type': 'plain_text', 'text': s}, 'value': s} for s in REPAIR_STATUSES]
        severity_opts = [{'text': {'type': 'plain_text', 'text': s}, 'value': s} for s in REPAIR_SEVERITIES]

        modal = build_repair_update_modal(record, status_opts, severity_opts, [])

        specialist_block = [b for b in modal['blocks'] if b['block_id'] == 'specialist_block'][0]
        assert specialist_block['element']['initial_value'] == 'Needs electrician'

    def test_assignee_prepopulated_when_present(self):
        from esb.models.repair_record import REPAIR_SEVERITIES, REPAIR_STATUSES
        from esb.slack.forms import build_repair_update_modal

        user = _create_user('technician', username='tech_assign')
        record = self._make_record(assignee_id=user.id)
        status_opts = [{'text': {'type': 'plain_text', 'text': s}, 'value': s} for s in REPAIR_STATUSES]
        severity_opts = [{'text': {'type': 'plain_text', 'text': s}, 'value': s} for s in REPAIR_SEVERITIES]
        user_opts = [{'text': {'type': 'plain_text', 'text': f'{user.username} (technician)'}, 'value': str(user.id)}]

        modal = build_repair_update_modal(record, status_opts, severity_opts, user_opts)

        assignee_block = [b for b in modal['blocks'] if b['block_id'] == 'assignee_block'][0]
        assert assignee_block['element']['initial_option']['value'] == str(user.id)

    def test_note_block_always_empty(self):
        from esb.models.repair_record import REPAIR_SEVERITIES, REPAIR_STATUSES
        from esb.slack.forms import build_repair_update_modal

        record = self._make_record()
        status_opts = [{'text': {'type': 'plain_text', 'text': s}, 'value': s} for s in REPAIR_STATUSES]
        severity_opts = [{'text': {'type': 'plain_text', 'text': s}, 'value': s} for s in REPAIR_SEVERITIES]

        modal = build_repair_update_modal(record, status_opts, severity_opts, [])

        note_block = [b for b in modal['blocks'] if b['block_id'] == 'note_block'][0]
        assert 'initial_value' not in note_block['element']


class TestFormatStatusSummary:
    """Tests for format_status_summary()."""

    def test_multiple_areas(self, app, make_area, make_equipment, make_repair_record):
        """Formats all areas with correct counts."""
        from esb.services import status_service
        from esb.slack.forms import format_status_summary

        area1 = make_area('Woodshop', '#wood')
        area2 = make_area('Metal Shop', '#metal')
        make_equipment('SawStop', 'SawStop', 'PCS', area=area1)
        eq2 = make_equipment('Band Saw', 'Jet', 'JWBS', area=area1)
        make_repair_record(equipment=eq2, status='New', severity='Degraded', description='Belt issue')
        make_equipment('Welder', 'Lincoln', '210MP', area=area2)

        dashboard = status_service.get_area_status_dashboard()
        result = format_status_summary(dashboard)

        assert 'Equipment Status Summary' in result
        assert 'Woodshop' in result
        assert 'Metal Shop' in result
        assert '1 :white_check_mark: operational' in result
        assert '1 :warning: degraded' in result

    def test_empty(self, app):
        """Returns 'No equipment' for empty dashboard."""
        from esb.slack.forms import format_status_summary

        result = format_status_summary([])
        assert result == 'No equipment has been registered yet.'

    def test_all_green(self, app, make_area, make_equipment):
        """All counts show 0 for degraded/down when all green."""
        from esb.services import status_service
        from esb.slack.forms import format_status_summary

        area = make_area('Lab', '#lab')
        make_equipment('Scope', 'Tek', 'TDS', area=area)
        make_equipment('DMM', 'Fluke', '87V', area=area)

        dashboard = status_service.get_area_status_dashboard()
        result = format_status_summary(dashboard)

        assert '2 :white_check_mark: operational' in result
        assert '0 :warning: degraded' in result
        assert '0 :x: down' in result

    def test_non_green_items_listed_under_area(self, app, make_area, make_equipment, make_repair_record):
        """AC 7: each non-green equipment is listed as a bullet under its area's count line."""
        from esb.services import status_service
        from esb.slack.forms import format_status_summary

        area = make_area('Woodshop', '#wood')
        eq_down = make_equipment('SawStop', 'SawStop', 'PCS', area=area)
        eq_degraded = make_equipment('Band Saw', 'Jet', 'JWBS', area=area)
        make_equipment('Drill Press', 'Jet', 'DP', area=area)  # green
        make_repair_record(equipment=eq_down, status='New', severity='Down', description='Motor burned out')
        make_repair_record(equipment=eq_degraded, status='New', severity='Degraded', description='Belt slipping')

        dashboard = status_service.get_area_status_dashboard()
        result = format_status_summary(dashboard)

        # Bullets for each non-green item appear under the area count line.
        assert ':x: *SawStop*' in result
        assert ':warning: *Band Saw*' in result
        assert 'Motor burned out' in result
        assert 'Belt slipping' in result
        # Green item does not get a bullet.
        assert '*Drill Press*' not in result

    def test_truncates_long_description_at_80(self, app, make_area, make_equipment, make_repair_record):
        """Descriptions longer than 80 chars are truncated with an ellipsis."""
        from esb.services import status_service
        from esb.slack.forms import format_status_summary

        area = make_area('Lab', '#lab')
        eq = make_equipment('Tool', 'TC', 'TM', area=area)
        long_desc = 'X' * 200
        make_repair_record(equipment=eq, status='New', severity='Down', description=long_desc)

        dashboard = status_service.get_area_status_dashboard()
        result = format_status_summary(dashboard)

        # Should not contain the full 200 X's but should contain a truncated form.
        assert 'X' * 200 not in result
        assert '\u2026' in result  # ellipsis

    def test_eta_shown_when_present(self, app, make_area, make_equipment, make_repair_record):
        """ETA is shown when present in status."""
        from datetime import date
        from esb.services import status_service
        from esb.slack.forms import format_status_summary

        area = make_area('Shop', '#shop')
        eq = make_equipment('Lathe', 'X', 'M', area=area)
        make_repair_record(equipment=eq, status='New', severity='Down', description='broken', eta=date(2026, 6, 15))

        dashboard = status_service.get_area_status_dashboard()
        result = format_status_summary(dashboard)
        assert 'Jun 15, 2026' in result

    def test_footer_hint_present(self, app, make_area, make_equipment):
        """AC 8: footer hint appears at the end of the summary."""
        from esb.services import status_service
        from esb.slack.forms import format_status_summary

        area = make_area('Lab', '#lab')
        make_equipment('Scope', 'Tek', 'TDS', area=area)
        dashboard = status_service.get_area_status_dashboard()
        result = format_status_summary(dashboard)
        assert '/esb-status <area name>' in result
        assert 'full details on one area' in result

    def test_all_green_area_no_equipment_bullets(self, app, make_area, make_equipment):
        """AC 36: area with all-green equipment shows count line, no bullets beneath."""
        from esb.services import status_service
        from esb.slack.forms import format_status_summary

        area = make_area('Lab', '#lab')
        make_equipment('Scope', 'Tek', 'TDS', area=area)
        make_equipment('DMM', 'Fluke', '87V', area=area)
        dashboard = status_service.get_area_status_dashboard()
        result = format_status_summary(dashboard)
        # The count line is present.
        assert 'Lab' in result
        # And no equipment item is rendered as a bullet (no per-item lines).
        assert '*Scope*' not in result
        assert '*DMM*' not in result

    def test_empty_returns_unchanged_text(self, app):
        """AC 7 empty-state preservation."""
        from esb.slack.forms import format_status_summary
        assert format_status_summary([]) == 'No equipment has been registered yet.'

    def test_format_status_summary_respects_area_sort_order(
        self, app, make_area, make_equipment,
    ):
        """Per-area lines follow (sort_order, name) ordering."""
        from esb.services import status_service
        from esb.slack.forms import format_status_summary

        area_a = make_area('Area A', '#a', sort_order=10)
        area_b = make_area('Area B', '#b', sort_order=5)
        area_c = make_area('Area C', '#c', sort_order=5)
        make_equipment('Tool A', 'X', 'M', area=area_a)
        make_equipment('Tool B', 'X', 'M', area=area_b)
        make_equipment('Tool C', 'X', 'M', area=area_c)

        summary = format_status_summary(status_service.get_area_status_dashboard())
        pos_b = summary.find('Area B')
        pos_c = summary.find('Area C')
        pos_a = summary.find('Area A')
        assert pos_b >= 0 and pos_c >= 0 and pos_a >= 0, summary
        assert pos_b < pos_c < pos_a


class TestFormatAreaStatusDetail:
    """Tests for format_area_status_detail()."""

    def test_all_green_area_has_header_and_per_item_lines(self, app, make_area, make_equipment):
        from esb.services import status_service
        from esb.slack.forms import format_area_status_detail

        area = make_area('Lab', '#lab')
        make_equipment('Scope', 'Tek', 'TDS', area=area)
        make_equipment('DMM', 'Fluke', '87V', area=area)
        area_data = status_service.get_single_area_status_dashboard(area.id)

        result = format_area_status_detail(area_data)
        assert ':bar_chart:' in result
        assert '*Lab*' in result
        assert ':white_check_mark: *DMM* \u2014 Operational' in result
        assert ':white_check_mark: *Scope* \u2014 Operational' in result

    def test_mixed_area_shows_detail_for_non_green(self, app, make_area, make_equipment, make_repair_record):
        from datetime import date
        from esb.services import status_service
        from esb.slack.forms import format_area_status_detail
        from tests.conftest import _create_user

        tech = _create_user('technician', username='alice')
        area = make_area('Shop', '#shop')
        red_eq = make_equipment('SawStop', 'SS', 'PCS', area=area)
        yellow_eq = make_equipment('Band Saw', 'Jet', 'JWBS', area=area)
        make_equipment('Drill', 'Jet', 'DP', area=area)  # green
        make_repair_record(
            equipment=red_eq, status='Assigned', severity='Down',
            description='Motor down', eta=date(2026, 6, 15), assignee_id=tech.id,
        )
        make_repair_record(
            equipment=yellow_eq, status='New', severity='Degraded',
            description='Belt slip',
        )

        area_data = status_service.get_single_area_status_dashboard(area.id)
        result = format_area_status_detail(area_data)
        assert ':x: *SawStop* \u2014 Down' in result
        assert '> Motor down' in result
        assert '> ETA: Jun 15, 2026' in result
        assert '> Assigned to: alice' in result
        assert ':warning: *Band Saw* \u2014 Degraded' in result
        assert '> Belt slip' in result
        assert ':white_check_mark: *Drill* \u2014 Operational' in result

    def test_empty_area(self, app, make_area):
        from esb.services import status_service
        from esb.slack.forms import format_area_status_detail

        area = make_area('Empty', '#empty')
        area_data = status_service.get_single_area_status_dashboard(area.id)
        result = format_area_status_detail(area_data)
        assert ':bar_chart:' in result
        assert 'Empty' in result
        assert 'No equipment' in result


class TestBuildRepairDispatcherModal:
    """Tests for build_repair_dispatcher_modal()."""

    def test_modal_metadata(self, app, make_area, make_equipment, make_repair_record):
        from esb.services import repair_service
        from esb.slack.forms import build_repair_dispatcher_modal

        area = make_area('Woodshop', '#wood')
        eq = make_equipment('SawStop', 'SS', 'PCS', area=area)
        make_repair_record(equipment=eq, status='New', severity='Down', description='broken')

        records = repair_service.get_repair_queue()
        modal = build_repair_dispatcher_modal(records)
        assert modal['callback_id'] == 'repair_dispatcher_submission'
        assert modal['submit']['text'] == 'Continue'
        assert len(modal['blocks']) == 1
        block = modal['blocks'][0]
        assert block['block_id'] == 'repair_select_block'
        assert block['element']['action_id'] == 'repair_select'
        assert block['element']['type'] == 'static_select'

    def test_option_groups_by_area_sorted_by_sort_order_then_name(
        self, app, make_area, make_equipment, make_repair_record,
    ):
        """Area groups across the dispatcher modal follow (sort_order, name)."""
        from esb.services import repair_service
        from esb.slack.forms import build_repair_dispatcher_modal

        # Mixed sort_order so the result distinguishes (sort_order, name)
        # from a plain alphabetical sort.
        area_a = make_area('A', '#a', sort_order=10)
        area_b = make_area('B', '#b', sort_order=5)
        area_c = make_area('C', '#c', sort_order=5)
        eq_a = make_equipment('A-tool', 'X', 'M', area=area_a)
        eq_b = make_equipment('B-tool', 'X', 'M', area=area_b)
        eq_c = make_equipment('C-tool', 'X', 'M', area=area_c)
        make_repair_record(equipment=eq_a, status='New', severity='Down', description='a')
        make_repair_record(equipment=eq_b, status='New', severity='Down', description='b')
        make_repair_record(equipment=eq_c, status='New', severity='Down', description='c')

        records = repair_service.get_repair_queue()
        modal = build_repair_dispatcher_modal(records)
        groups = modal['blocks'][0]['element']['option_groups']
        labels = [g['label']['text'] for g in groups]
        assert labels == ['B', 'C', 'A']

    def test_within_group_preserves_caller_order(self, app, make_area, make_equipment, make_repair_record):
        """AC 31: within an area group, options preserve the caller's input order
        (severity_priority then created_at_asc as supplied by get_repair_queue())."""
        from esb.services import repair_service
        from esb.slack.forms import build_repair_dispatcher_modal

        area = make_area('Shop', '#shop')
        # Two Down records (older first) and one Degraded record. get_repair_queue
        # returns ordered by (Down=0, Degraded=1) then created_at asc.
        eq1 = make_equipment('Old-Down', 'X', 'M', area=area)
        eq2 = make_equipment('New-Down', 'X', 'M', area=area)
        eq3 = make_equipment('Degraded-Tool', 'X', 'M', area=area)
        # Insert older Down first
        rec1 = make_repair_record(equipment=eq1, status='New', severity='Down', description='oldest')
        rec3 = make_repair_record(equipment=eq3, status='New', severity='Degraded', description='deg')
        rec2 = make_repair_record(equipment=eq2, status='New', severity='Down', description='newer')

        records = repair_service.get_repair_queue()
        # Sanity: queue is severity-priority then created_at asc.
        assert [r.id for r in records] == [rec1.id, rec2.id, rec3.id]

        modal = build_repair_dispatcher_modal(records)
        # Single group ('Shop'); option order preserves the caller's order.
        options = modal['blocks'][0]['element']['option_groups'][0]['options']
        values = [o['value'] for o in options]
        assert values == [str(rec1.id), str(rec2.id), str(rec3.id)]

    def test_option_format(self, app, make_area, make_equipment, make_repair_record):
        from esb.services import repair_service
        from esb.slack.forms import build_repair_dispatcher_modal
        from tests.conftest import _create_user

        tech = _create_user('technician', username='alice')
        area = make_area('Woodshop', '#wood')
        eq = make_equipment('SawStop', 'SS', 'PCS', area=area)
        rec = make_repair_record(
            equipment=eq, status='Assigned', severity='Down',
            description='broken', assignee_id=tech.id,
        )

        records = repair_service.get_repair_queue()
        modal = build_repair_dispatcher_modal(records)
        opt = modal['blocks'][0]['element']['option_groups'][0]['options'][0]
        # text starts with #<id>
        assert opt['text']['text'].startswith(f'#{rec.id} ')
        assert 'SawStop' in opt['text']['text']
        assert 'Assigned' in opt['text']['text']
        # description shows severity | assignee
        assert opt['description']['text'] == 'Down | alice'
        assert opt['value'] == str(rec.id)

    def test_option_label_truncated_to_75_chars(self, app, make_area, make_equipment, make_repair_record):
        from esb.services import repair_service
        from esb.slack.forms import build_repair_dispatcher_modal

        area = make_area('Shop', '#shop')
        eq = make_equipment('A' * 80, 'X', 'M', area=area)
        make_repair_record(equipment=eq, status='New', severity='Down', description='x')

        records = repair_service.get_repair_queue()
        modal = build_repair_dispatcher_modal(records)
        opt = modal['blocks'][0]['element']['option_groups'][0]['options'][0]
        assert len(opt['text']['text']) <= 75

    def test_option_description_unassigned_when_no_assignee(self, app, make_area, make_equipment, make_repair_record):
        from esb.services import repair_service
        from esb.slack.forms import build_repair_dispatcher_modal

        area = make_area('Shop', '#shop')
        eq = make_equipment('Tool', 'X', 'M', area=area)
        make_repair_record(equipment=eq, status='New', description='broken')

        records = repair_service.get_repair_queue()
        modal = build_repair_dispatcher_modal(records)
        opt = modal['blocks'][0]['element']['option_groups'][0]['options'][0]
        assert 'Unassigned' in opt['description']['text']


class TestBuildRepairActionModal:
    """Tests for build_repair_action_modal()."""

    def test_modal_metadata_and_private_metadata(self, app, make_area, make_equipment, make_repair_record):
        from esb.slack.forms import build_repair_action_modal

        area = make_area('Shop', '#shop')
        eq = make_equipment('Tool', 'X', 'M', area=area)
        rec = make_repair_record(equipment=eq, status='New', severity='Down', description='broken')

        modal = build_repair_action_modal(rec)
        assert modal['callback_id'] == 'repair_action_submission'
        assert modal['private_metadata'] == str(rec.id)
        assert f'Repair #{rec.id}' in modal['title']['text']
        assert modal['submit']['text'] == 'Apply'

    def test_action_radio_has_all_four_values(self, app, make_area, make_equipment, make_repair_record):
        from esb.slack.forms import build_repair_action_modal

        area = make_area('Shop', '#shop')
        eq = make_equipment('Tool', 'X', 'M', area=area)
        rec = make_repair_record(equipment=eq, status='New', severity='Down', description='broken')

        modal = build_repair_action_modal(rec)
        action_block = next(b for b in modal['blocks'] if b.get('block_id') == 'action_block')
        assert action_block['element']['type'] == 'radio_buttons'
        values = [o['value'] for o in action_block['element']['options']]
        assert values == ['claim', 'set_eta', 'set_status', 'resolve_with_note']
        # No initial_option -- force the user to pick.
        assert 'initial_option' not in action_block['element']

    def test_eta_status_note_blocks_optional(self, app, make_area, make_equipment, make_repair_record):
        from esb.slack.forms import build_repair_action_modal

        area = make_area('Shop', '#shop')
        eq = make_equipment('Tool', 'X', 'M', area=area)
        rec = make_repair_record(equipment=eq, status='New', severity='Down', description='broken')

        modal = build_repair_action_modal(rec)
        for bid in ('eta_block', 'status_block', 'note_block'):
            block = next(b for b in modal['blocks'] if b.get('block_id') == bid)
            assert block.get('optional') is True

    def test_status_select_has_three_permitted_values(self, app, make_area, make_equipment, make_repair_record):
        from esb.slack.forms import build_repair_action_modal

        area = make_area('Shop', '#shop')
        eq = make_equipment('Tool', 'X', 'M', area=area)
        rec = make_repair_record(equipment=eq, status='New', severity='Down', description='broken')
        # Need a sibling so duplicate-candidates is non-empty -- otherwise the
        # builder filters Closed - Duplicate out of the status options.
        make_repair_record(equipment=eq, status='New', severity='Down', description='sibling')

        modal = build_repair_action_modal(rec)
        status_block = next(b for b in modal['blocks'] if b.get('block_id') == 'status_block')
        values = [o['value'] for o in status_block['element']['options']]
        assert values == ['In Progress', 'Closed - Duplicate', 'Closed - No Issue Found']

    def test_eta_initial_date_when_repair_has_eta(self, app, make_area, make_equipment, make_repair_record):
        from datetime import date
        from esb.slack.forms import build_repair_action_modal

        area = make_area('Shop', '#shop')
        eq = make_equipment('Tool', 'X', 'M', area=area)
        rec = make_repair_record(
            equipment=eq, status='New', severity='Down',
            description='broken', eta=date(2026, 7, 4),
        )

        modal = build_repair_action_modal(rec)
        eta_block = next(b for b in modal['blocks'] if b.get('block_id') == 'eta_block')
        assert eta_block['element']['initial_date'] == '2026-07-04'

    def test_duplicate_block_when_candidates_exist(
        self, app, make_area, make_equipment, make_repair_record,
    ):
        """AC-19: duplicate_block present with each sibling repair as an option."""
        from esb.slack.forms import build_repair_action_modal

        area = make_area('Shop', '#shop')
        eq = make_equipment('Tool', 'X', 'M', area=area)
        rec1 = make_repair_record(equipment=eq, status='New', severity='Down', description='r1')
        rec2 = make_repair_record(equipment=eq, status='In Progress', severity='Down', description='r2')

        modal = build_repair_action_modal(rec1)
        dup_block = next(
            (b for b in modal['blocks'] if b.get('block_id') == 'duplicate_block'),
            None,
        )
        assert dup_block is not None
        values = [o['value'] for o in dup_block['element']['options']]
        assert str(rec2.id) in values
        # First option text starts with #ID [Status]
        first_opt = dup_block['element']['options'][0]
        assert first_opt['text']['text'].startswith(f'#{rec2.id} [In Progress]')

    def test_no_duplicate_block_and_no_closed_duplicate_option_when_no_candidates(
        self, app, make_area, make_equipment, make_repair_record,
    ):
        """AC-20: lone repair has no duplicate_block AND status options exclude Closed - Duplicate."""
        from esb.slack.forms import build_repair_action_modal

        area = make_area('Shop', '#shop')
        eq = make_equipment('Tool', 'X', 'M', area=area)
        rec = make_repair_record(equipment=eq, status='New', severity='Down', description='r1')

        modal = build_repair_action_modal(rec)
        assert all(b.get('block_id') != 'duplicate_block' for b in modal['blocks'])
        status_block = next(b for b in modal['blocks'] if b.get('block_id') == 'status_block')
        values = [o['value'] for o in status_block['element']['options']]
        assert 'Closed - Duplicate' not in values

    def test_duplicate_option_label_budget(
        self, app, make_area, make_equipment, make_repair_record,
    ):
        """No duplicate-option's text.text exceeds Slack's 75-char limit."""
        from esb.slack.forms import build_repair_action_modal

        area = make_area('Shop', '#shop')
        eq = make_equipment('Tool', 'X', 'M', area=area)
        rec1 = make_repair_record(equipment=eq, status='New', severity='Down', description='target')
        # Very long description to force truncation
        make_repair_record(
            equipment=eq, status='In Progress', severity='Down',
            description='X' * 500,
        )

        modal = build_repair_action_modal(rec1)
        dup_block = next(b for b in modal['blocks'] if b.get('block_id') == 'duplicate_block')
        for opt in dup_block['element']['options']:
            assert len(opt['text']['text']) <= 75


class TestRepairCreateModalStatusFilter:
    """AC-21: Closed - Duplicate filtered out of create-modal status options."""

    def test_closed_duplicate_excluded_from_create_modal_status(self, app):
        from esb.slack.forms import build_repair_create_modal

        modal = build_repair_create_modal([], [])
        status_block = next(b for b in modal['blocks'] if b.get('block_id') == 'status_block')
        values = [o['value'] for o in status_block['element']['options']]
        assert 'Closed - Duplicate' not in values


class TestFormatEquipmentStatusDetail:
    """Tests for format_equipment_status_detail()."""

    def test_green(self, app, make_equipment):
        """Green shows emoji + name + Operational, no issue block."""
        from esb.slack.forms import format_equipment_status_detail

        equip = make_equipment('SawStop #1', 'SawStop', 'PCS')
        detail = {
            'color': 'green', 'label': 'Operational',
            'issue_description': None, 'severity': None,
            'eta': None, 'assignee_name': None,
        }
        result = format_equipment_status_detail(equip, detail)
        assert ':white_check_mark:' in result
        assert 'SawStop #1' in result
        assert 'Operational' in result
        assert '>' not in result  # No blockquote lines

    def test_down_with_details(self, app, make_equipment):
        """Down shows description, ETA, assignee."""
        from datetime import date
        from esb.slack.forms import format_equipment_status_detail

        equip = make_equipment('SawStop #1', 'SawStop', 'PCS')
        detail = {
            'color': 'red', 'label': 'Down',
            'issue_description': 'Motor makes grinding noise',
            'severity': 'Down',
            'eta': date(2026, 2, 20),
            'assignee_name': 'Marcus',
        }
        result = format_equipment_status_detail(equip, detail)
        assert ':x:' in result
        assert 'Down' in result
        assert '> Motor makes grinding noise' in result
        assert '> ETA: Feb 20, 2026' in result
        assert '> Assigned to: Marcus' in result

    def test_degraded_no_eta(self, app, make_equipment):
        """Degraded shows description but no ETA line."""
        from esb.slack.forms import format_equipment_status_detail

        equip = make_equipment('Band Saw', 'Jet', 'JWBS')
        detail = {
            'color': 'yellow', 'label': 'Degraded',
            'issue_description': 'Belt slipping',
            'severity': 'Degraded',
            'eta': None, 'assignee_name': None,
        }
        result = format_equipment_status_detail(equip, detail)
        assert ':warning:' in result
        assert 'Degraded' in result
        assert '> Belt slipping' in result
        assert 'ETA' not in result


class TestFormatEquipmentList:
    """Tests for format_equipment_list()."""

    def test_lists_matches(self, app, make_area, make_equipment):
        """Lists matching equipment with area names."""
        from esb.slack.forms import format_equipment_list

        area = make_area('Woodshop', '#wood')
        eq1 = make_equipment('Band Saw', 'Jet', 'JWBS', area=area)
        eq2 = make_equipment('SawStop #1', 'SawStop', 'PCS', area=area)

        result = format_equipment_list([eq1, eq2], 'saw')
        assert 'Multiple equipment items match "saw"' in result
        assert 'Band Saw (Woodshop)' in result
        assert 'SawStop #1 (Woodshop)' in result
        assert '/esb-status' in result
