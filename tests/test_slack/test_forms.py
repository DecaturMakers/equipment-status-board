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


class TestBuildStatusSummaryModal:
    """Tests for build_status_summary_modal()."""

    def test_modal_structure_and_area_buttons(self, app, make_area, make_equipment, make_repair_record):
        """Summary modal has one section per non-empty area with a 'View details' button."""
        from esb.services import status_service
        from esb.slack.forms import build_status_summary_modal

        area1 = make_area('Woodshop', '#wood')
        area2 = make_area('Metal Shop', '#metal')
        make_equipment('SawStop', 'SawStop', 'PCS', area=area1)  # green
        eq_down = make_equipment('Band Saw', 'Jet', 'JWBS', area=area1)
        make_repair_record(equipment=eq_down, status='New', severity='Down', description='Motor dead')
        make_equipment('Welder', 'Lincoln', '210MP', area=area2)  # green

        dashboard = status_service.get_area_status_dashboard()
        modal = build_status_summary_modal(dashboard)

        assert modal['type'] == 'modal'
        assert modal['callback_id'] == 'esb_status_summary'
        assert modal['title']['text'] == 'Equipment Status'
        assert 'submit' not in modal

        # First block is the header section.
        assert 'Equipment Status Summary' in modal['blocks'][0]['text']['text']

        # Each area section carries a distinct block_id and a View details button.
        area_sections = [b for b in modal['blocks'] if b.get('block_id', '').startswith('esb_status_area_')]
        assert len(area_sections) == 2
        for section in area_sections:
            accessory = section['accessory']
            assert accessory['type'] == 'button'
            assert accessory['action_id'] == 'esb_status_view_area'
            assert accessory['text']['text'] == 'View details'

        # The value of each button is the corresponding area id.
        values = {s['accessory']['value'] for s in area_sections}
        assert values == {str(area1.id), str(area2.id)}

        # Non-green item name is present in the summary text.
        assert any('Band Saw' in b['text']['text'] for b in area_sections)

        # Block Kit limits (F9): modals allow ≤100 blocks and ≤3000 chars per
        # section text.
        assert len(modal['blocks']) <= 100
        for block in modal['blocks']:
            if block['type'] == 'section':
                assert len(block['text']['text']) <= 3000

    def test_empty_areas_skipped(self, app, make_area, make_equipment):
        """Areas with no equipment produce no section."""
        from esb.services import status_service
        from esb.slack.forms import build_status_summary_modal

        area1 = make_area('Lab', '#lab')
        make_area('Empty', '#empty')  # no equipment
        make_equipment('Scope', 'Tek', 'TDS', area=area1)

        dashboard = status_service.get_area_status_dashboard()
        modal = build_status_summary_modal(dashboard)

        block_ids = {b.get('block_id') for b in modal['blocks']}
        assert f'esb_status_area_{area1.id}_block' in block_ids
        area_sections = [b for b in modal['blocks'] if b.get('block_id', '').startswith('esb_status_area_')]
        assert len(area_sections) == 1

    def test_empty_dashboard(self, app):
        """Empty dashboard renders a single 'No equipment' section."""
        from esb.slack.forms import build_status_summary_modal

        modal = build_status_summary_modal([])
        assert modal['callback_id'] == 'esb_status_summary'
        assert len(modal['blocks']) == 1
        assert 'No equipment has been registered yet.' in modal['blocks'][0]['text']['text']

    def test_oversized_area_section_truncated_to_3000(self, app, make_area, make_equipment, make_repair_record):
        """A verbose repair description cannot push a section past Slack's 3000-char cap."""
        from esb.services import status_service
        from esb.slack.forms import build_status_summary_modal

        area = make_area('Woodshop', '#wood')
        eq_down = make_equipment('SawStop', 'SawStop', 'PCS', area=area)
        make_repair_record(equipment=eq_down, status='New', severity='Down', description='X' * 5000)

        dashboard = status_service.get_area_status_dashboard()
        modal = build_status_summary_modal(dashboard)

        area_sections = [b for b in modal['blocks'] if b.get('block_id', '').startswith('esb_status_area_')]
        assert area_sections
        for section in area_sections:
            assert len(section['text']['text']) <= 3000


class TestBuildAreaStatusModal:
    """Tests for build_area_status_modal()."""

    def test_area_detail_modal(self, app, make_area, make_equipment, make_repair_record):
        """Area modal title, detail text, and back button are correct."""
        from esb.services import status_service
        from esb.slack.forms import build_area_status_modal, format_area_status_detail

        area = make_area('Woodshop', '#wood')
        eq_down = make_equipment('SawStop', 'SawStop', 'PCS', area=area)
        make_repair_record(equipment=eq_down, status='New', severity='Down', description='Motor dead')

        area_data = status_service.get_single_area_status_dashboard(area.id)
        modal = build_area_status_modal(area_data)

        assert modal['type'] == 'modal'
        assert modal['callback_id'] == 'esb_status_area_detail'
        assert modal['title']['text'] == 'Woodshop'
        assert len(modal['title']['text']) <= 24

        # Detail section reuses the existing formatter (byte-identical).
        assert modal['blocks'][0]['text']['text'] == format_area_status_detail(area_data)

        # Block Kit limits (F9): ≤100 blocks, ≤3000 chars per section text.
        assert len(modal['blocks']) <= 100
        for block in modal['blocks']:
            if block['type'] == 'section':
                assert len(block['text']['text']) <= 3000

        # A 'Back to summary' button is present.
        buttons = [
            el
            for b in modal['blocks']
            if b['type'] == 'actions'
            for el in b['elements']
        ]
        assert any(btn['action_id'] == 'esb_status_back_to_summary' for btn in buttons)

    def test_long_area_name_truncated_to_24(self, app, make_area, make_equipment):
        """Area names longer than 24 chars are truncated in the modal title."""
        from esb.services import status_service
        from esb.slack.forms import build_area_status_modal

        area = make_area('A' * 40, '#long')
        make_equipment('Tool', 'TC', 'TM', area=area)

        area_data = status_service.get_single_area_status_dashboard(area.id)
        modal = build_area_status_modal(area_data)
        assert len(modal['title']['text']) == 24

    def test_oversized_detail_section_truncated_to_3000(self, app, make_area, make_equipment, make_repair_record):
        """A verbose repair description cannot push the detail section past 3000 chars."""
        from esb.services import status_service
        from esb.slack.forms import build_area_status_modal

        area = make_area('Woodshop', '#wood')
        eq_down = make_equipment('SawStop', 'SawStop', 'PCS', area=area)
        make_repair_record(equipment=eq_down, status='New', severity='Down', description='X' * 5000)

        area_data = status_service.get_single_area_status_dashboard(area.id)
        modal = build_area_status_modal(area_data)

        for block in modal['blocks']:
            if block['type'] == 'section':
                assert len(block['text']['text']) <= 3000
