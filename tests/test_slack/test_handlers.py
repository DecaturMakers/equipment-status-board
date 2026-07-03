"""Tests for Slack command and view submission handlers (esb/slack/handlers.py)."""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from esb.models.equipment_reservation_settings import EquipmentReservationSettings
from esb.models.reservation import Reservation
from tests.conftest import _create_area, _create_equipment, _create_repair_record, _create_user


def _register_and_capture(app):
    """Register handlers on a mock Bolt app and capture the handler functions."""
    from esb.slack.handlers import register_handlers

    handlers = {}

    def capture_command(cmd):
        def decorator(fn):
            handlers[f'command:{cmd}'] = fn
            return fn
        return decorator

    def capture_view(callback_id):
        def decorator(fn):
            handlers[f'view:{callback_id}'] = fn
            return fn
        return decorator

    def capture_action(action_id):
        def decorator(fn):
            handlers[f'action:{action_id}'] = fn
            return fn
        return decorator

    bolt_app = MagicMock()
    bolt_app.command = capture_command
    bolt_app.view = capture_view
    bolt_app.action = capture_action
    register_handlers(bolt_app, app)
    return handlers


class TestEsbReportCommand:
    """Tests for /esb-report command handler."""

    @pytest.fixture(autouse=True)
    def setup(self, app, db):
        self.app = app
        self.db = db
        self.area = _create_area(name='Woodshop', slack_channel='#woodshop')
        self.equipment = _create_equipment(name='SawStop', area=self.area)
        self.handlers = _register_and_capture(app)

    def test_report_command_calls_ack_and_opens_modal(self):
        """5.1: /esb-report calls ack() and opens modal via client.views_open()."""
        ack = MagicMock()
        client = MagicMock()
        body = {
            'trigger_id': 'T123',
            'user_id': 'U123',
            'user_name': 'testuser',
            'channel_id': 'C123',
        }

        self.handlers['command:/esb-report'](ack=ack, body=body, client=client)

        ack.assert_called_once()
        client.views_open.assert_called_once()
        modal = client.views_open.call_args.kwargs['view']
        assert modal['callback_id'] == 'problem_report_submission'

    def test_report_command_no_equipment_posts_error(self):
        """Report command posts error when no equipment available."""
        # Delete all equipment
        from esb.models.equipment import Equipment
        Equipment.query.delete()
        self.db.session.commit()

        ack = MagicMock()
        client = MagicMock()
        body = {'trigger_id': 'T123', 'user_id': 'U123', 'channel_id': 'C123'}

        self.handlers['command:/esb-report'](ack=ack, body=body, client=client)

        ack.assert_called_once()
        client.chat_postEphemeral.assert_called_once()
        assert 'No equipment' in client.chat_postEphemeral.call_args.kwargs['text']
        client.views_open.assert_not_called()


class TestEsbReserveCommand:
    """Tests for /esb-reserve command handler."""

    @pytest.fixture(autouse=True)
    def setup(self, app, db):
        self.app = app
        self.db = db
        self.area = _create_area(name='Reservation Lab', slack_channel='#reservations')
        self.laser = _create_equipment(name='Laser Cutter', area=self.area)
        self.cnc = _create_equipment(name='CNC Router', area=self.area)
        self.disabled = _create_equipment(name='3D Printer', area=self.area)
        self.ordinary = _create_equipment(name='Bench Tool', area=self.area)
        self.user = _create_user('member', username='reserve_member')
        self._settings(self.laser, slug='laser-cutter')
        self._settings(self.cnc, slug='cnc-router')
        self._settings(self.disabled, slug='3d-printer', enabled=False)
        now = datetime.now(UTC).replace(second=0, microsecond=0)
        self.cnc_reservation_ends_at = now + timedelta(minutes=45)
        reservation = Reservation(
            equipment_id=self.cnc.id,
            user_id=self.user.id,
            starts_at=(now - timedelta(minutes=15)).replace(tzinfo=None),
            ends_at=self.cnc_reservation_ends_at.replace(tzinfo=None),
            status='active',
            notes='private note',
            created_via='slack',
        )
        self.db.session.add(reservation)
        self.db.session.commit()
        self.app.config['STATIC_PAGE_PUBLIC_URL'] = 'https://status.example.com/reservations/'
        self.handlers = _register_and_capture(app)

    def _settings(self, equipment, *, slug, enabled=True):
        settings = EquipmentReservationSettings(
            equipment_id=equipment.id,
            reservation_slug=slug,
            reservations_enabled=enabled,
            min_advance_notice_minutes=2 * 60,
            max_advance_notice_minutes=14 * 24 * 60,
            min_duration_minutes=30,
            max_duration_minutes=120,
            slot_granularity_minutes=30,
        )
        self.db.session.add(settings)
        self.db.session.commit()
        return settings

    def test_reserve_command_calls_ack_and_opens_landing_modal(self):
        """/esb-reserve opens Flow 1 populated from reservation database data."""
        ack = MagicMock()
        client = MagicMock()
        body = {
            'trigger_id': 'T123',
            'user_id': 'U123',
            'channel_id': 'C123',
        }

        self.handlers['command:/esb-reserve'](ack=ack, body=body, client=client)

        ack.assert_called_once()
        client.views_open.assert_called_once()
        modal = client.views_open.call_args.kwargs['view']
        assert modal['callback_id'] == 'reservation_landing'
        assert modal['title']['text'] == 'Makerspace Tools'
        assert 'submit' not in modal

        block_ids = [block['block_id'] for block in modal['blocks'] if 'block_id' in block]
        assert 'reservation_intro_block' in block_ids
        assert f'reservation_tool_{self.laser.id}_status_block' in block_ids
        assert f'reservation_tool_{self.cnc.id}_status_block' in block_ids
        assert f'reservation_tool_{self.disabled.id}_status_block' not in block_ids
        assert f'reservation_tool_{self.ordinary.id}_status_block' not in block_ids
        assert 'reservation_member_actions_block' in block_ids

        rendered_text = '\n'.join(
            block['text']['text']
            for block in modal['blocks']
            if block.get('type') == 'section'
        )
        assert 'Choose a tool to view availability or start a reservation.' in rendered_text
        assert '*Laser Cutter*\nStatus: Available now' in rendered_text
        assert '*CNC Router*\nStatus: Reserved until ' in rendered_text
        assert '3D Printer' not in rendered_text
        assert 'Bench Tool' not in rendered_text

        laser_actions = [
            block for block in modal['blocks']
            if block.get('block_id') == f'reservation_tool_{self.laser.id}_actions_block'
        ][0]
        assert [element['text']['text'] for element in laser_actions['elements']] == ['Reserve', 'Availability']
        assert laser_actions['elements'][0]['value'] == str(self.laser.id)
        assert laser_actions['elements'][1]['url'] == 'https://status.example.com/reservations/'

        cnc_actions = [
            block for block in modal['blocks']
            if block.get('block_id') == f'reservation_tool_{self.cnc.id}_actions_block'
        ][0]
        assert [element['text']['text'] for element in cnc_actions['elements']] == ['Reserve', 'Availability']
        assert cnc_actions['elements'][0]['value'] == str(self.cnc.id)
        assert cnc_actions['elements'][1]['url'] == 'https://status.example.com/reservations/'

        member_actions = [
            block for block in modal['blocks']
            if block.get('block_id') == 'reservation_member_actions_block'
        ][0]
        assert member_actions['elements'][0]['text']['text'] == 'My reservations'
        assert member_actions['elements'][0]['action_id'] == 'reservation_view_mine'

    def test_reserve_landing_hides_availability_buttons_without_public_url(self):
        """/esb-reserve omits inert Availability buttons when no URL is configured."""
        self.app.config['STATIC_PAGE_PUBLIC_URL'] = ''
        ack = MagicMock()
        client = MagicMock()
        body = {
            'trigger_id': 'T123',
            'user_id': 'U123',
            'channel_id': 'C123',
        }

        self.handlers['command:/esb-reserve'](ack=ack, body=body, client=client)

        ack.assert_called_once()
        modal = client.views_open.call_args.kwargs['view']
        action_blocks = [
            block for block in modal['blocks']
            if block.get('block_id', '').startswith('reservation_tool_')
            and block.get('type') == 'actions'
        ]
        assert action_blocks
        for block in action_blocks:
            assert [element['text']['text'] for element in block['elements']] == ['Reserve']

    def test_reserve_button_updates_to_one_tool_availability_modal(self):
        """Flow 2: clicking Reserve updates to the selected tool availability modal."""
        ack = MagicMock()
        client = MagicMock()
        body = {
            'trigger_id': 'T456',
            'user': {'id': 'U123'},
            'view': {'id': 'V123'},
            'actions': [{'value': str(self.cnc.id)}],
        }

        self.handlers['action:reservation_start_reserve'](ack=ack, body=body, client=client)

        ack.assert_called_once()
        client.views_update.assert_called_once()
        assert client.views_update.call_args.kwargs['view_id'] == 'V123'
        modal = client.views_update.call_args.kwargs['view']
        assert modal['callback_id'] == 'reservation_availability'
        assert modal['title']['text'] == 'Reserve CNC Router'
        assert modal['submit']['text'] == 'Reserve'
        assert modal['private_metadata'] == str(self.cnc.id)

        rendered_text = '\n'.join(
            block['text']['text']
            for block in modal['blocks']
            if block.get('type') == 'section'
        )
        rendered_context = '\n'.join(
            element['text']
            for block in modal['blocks']
            if block.get('type') == 'context'
            for element in block.get('elements', [])
        )
        rendered_headers = '\n'.join(
            block['text']['text']
            for block in modal['blocks']
            if block.get('type') == 'header'
        )
        assert '*Limits:* 30 min-2 hours reservations; 2 hours-14 days advance notice.' in rendered_context
        assert 'Existing Reservations' in rendered_headers
        assert 'Reservation Request' in rendered_headers
        assert '*Today*' in rendered_text
        assert '*Tomorrow*' in rendered_text
        assert 'No existing reservations' in rendered_text
        assert 'Unavailable: ' in rendered_text

        today_block = [
            block for block in modal['blocks']
            if block.get('block_id') == 'reservation_booked_day_0_block'
        ][0]
        assert 'No existing reservations' not in today_block['text']['text']

        input_blocks = {
            block['block_id']: block
            for block in modal['blocks']
            if block.get('type') == 'input'
        }
        input_block_ids = [
            block['block_id']
            for block in modal['blocks']
            if block.get('type') == 'input'
        ]
        assert input_block_ids == [
            'reservation_notes_block',
            'reservation_start_at_block',
            'reservation_end_at_block',
        ]
        assert sorted(input_blocks) == [
            'reservation_end_at_block',
            'reservation_notes_block',
            'reservation_start_at_block',
        ]
        assert input_blocks['reservation_start_at_block']['element']['type'] == 'datetimepicker'
        assert input_blocks['reservation_start_at_block']['element']['action_id'] == 'reservation_start_at'
        assert 'initial_date_time' in input_blocks['reservation_start_at_block']['element']
        assert input_blocks['reservation_start_at_block']['label']['text'] == 'Requested Start'
        assert input_blocks['reservation_end_at_block']['element']['type'] == 'datetimepicker'
        assert input_blocks['reservation_end_at_block']['element']['action_id'] == 'reservation_end_at'
        start_initial = input_blocks['reservation_start_at_block']['element']['initial_date_time']
        end_initial = input_blocks['reservation_end_at_block']['element']['initial_date_time']
        assert (
            end_initial
            - start_initial
            == 30 * 60
        )
        assert datetime.fromtimestamp(start_initial, UTC).minute in (0, 30)
        assert datetime.fromtimestamp(end_initial, UTC).minute in (0, 30)
        assert input_blocks['reservation_end_at_block']['label']['text'] == 'Requested End'
        assert 'optional' not in input_blocks['reservation_notes_block']
        assert input_blocks['reservation_notes_block']['element']['type'] == 'plain_text_input'
        assert input_blocks['reservation_notes_block']['element']['multiline'] is True
        assert input_blocks['reservation_notes_block']['label']['text'] == 'Note'

    def test_availability_modal_groups_bookings_by_start_day(self):
        """Flow 2: midnight-crossing reservations appear only on their start day."""
        from esb.slack.reservation_forms import build_reservation_availability_modal

        now = datetime(2026, 6, 20, 12, 0, tzinfo=UTC)
        local_tz = now.astimezone().tzinfo
        local_midnight = datetime.combine(
            now.astimezone().date() + timedelta(days=1),
            datetime.min.time(),
            tzinfo=local_tz,
        )
        starts_at = local_midnight - timedelta(minutes=30)
        ends_at = local_midnight + timedelta(minutes=30)
        item = {
            'id': self.laser.id,
            'name': self.laser.name,
            'min_advance_notice_minutes': 120,
            'max_advance_notice_minutes': 14 * 24 * 60,
            'min_duration_minutes': 30,
            'max_duration_minutes': 120,
            'slot_granularity_minutes': 30,
            'reservations': [
                {
                    'starts_at': starts_at.astimezone(UTC).isoformat(),
                    'ends_at': ends_at.astimezone(UTC).isoformat(),
                },
            ],
        }

        modal = build_reservation_availability_modal(
            item,
            now=now,
        )

        today_block = [
            block for block in modal['blocks']
            if block.get('block_id') == 'reservation_booked_day_0_block'
        ][0]
        tomorrow_block = [
            block for block in modal['blocks']
            if block.get('block_id') == 'reservation_booked_day_1_block'
        ][0]
        assert 'Unavailable: 11:30 PM-12:30 AM' in today_block['text']['text']
        assert 'Unavailable: 11:30 PM-12:30 AM' not in tomorrow_block['text']['text']
        assert 'No existing reservations' in tomorrow_block['text']['text']

    def test_availability_modal_defaults_follow_reservation_settings(self):
        """Flow 2: default picker times align to the tool's configured policy."""
        from esb.slack.reservation_forms import build_reservation_availability_modal

        item = {
            'id': self.laser.id,
            'name': self.laser.name,
            'min_advance_notice_minutes': 180,
            'max_advance_notice_minutes': 14 * 24 * 60,
            'min_duration_minutes': 120,
            'max_duration_minutes': 240,
            'slot_granularity_minutes': 60,
            'reservations': [],
        }

        modal = build_reservation_availability_modal(
            item,
            now=datetime(2026, 6, 20, 12, 45, tzinfo=UTC),
        )
        booked_blocks = [
            block for block in modal['blocks']
            if block.get('block_id', '').startswith('reservation_booked_')
        ]
        assert [block['block_id'] for block in booked_blocks] == [
            'reservation_booked_empty_block',
        ]
        assert booked_blocks[0]['text']['text'] == 'No existing reservations'

        input_blocks = {
            block['block_id']: block
            for block in modal['blocks']
            if block.get('type') == 'input'
        }
        start_initial = input_blocks['reservation_start_at_block']['element']['initial_date_time']
        end_initial = input_blocks['reservation_end_at_block']['element']['initial_date_time']

        start = datetime.fromtimestamp(start_initial, UTC)
        end = datetime.fromtimestamp(end_initial, UTC)
        assert start.minute == 0
        assert start.hour == 16
        assert end - start == timedelta(minutes=120)

    def _future_aligned_window(self, *, hours_from_now=2, duration_minutes=60):
        now = datetime.now(UTC).replace(second=0, microsecond=0)
        minutes_to_next_half_hour = (30 - (now.minute % 30)) % 30
        starts_at = now + timedelta(minutes=minutes_to_next_half_hour, hours=hours_from_now)
        ends_at = starts_at + timedelta(minutes=duration_minutes)
        return int(starts_at.timestamp()), int(ends_at.timestamp())

    def _reservation_submission_view(self, equipment_id, start_timestamp, end_timestamp, notes='Table saw checkout'):
        return {
            'private_metadata': str(equipment_id),
            'state': {
                'values': {
                    'reservation_notes_block': {
                        'reservation_notes': {'value': notes},
                    },
                    'reservation_start_at_block': {
                        'reservation_start_at': {'selected_date_time': start_timestamp},
                    },
                    'reservation_end_at_block': {
                        'reservation_end_at': {'selected_date_time': end_timestamp},
                    },
                },
            },
        }

    def test_reservation_submission_updates_modal_to_confirmation(self):
        """Flow 3: successful reservation submit updates the modal to confirmation."""
        start_timestamp, end_timestamp = self._future_aligned_window()
        ack = MagicMock()
        client = MagicMock()
        def users_info_side_effect(user):
            assert ack.called
            return {'user': {'profile': {'email': self.user.email}}}
        client.users_info.side_effect = users_info_side_effect
        body = {'user': {'id': 'U123'}, 'view': {'id': 'V123'}}
        view = self._reservation_submission_view(self.laser.id, start_timestamp, end_timestamp)

        self.handlers['view:reservation_availability'](ack=ack, body=body, client=client, view=view)

        ack.assert_called_once()
        kwargs = ack.call_args.kwargs
        assert kwargs['response_action'] == 'update'
        assert kwargs['view']['callback_id'] == 'reservation_processing'
        client.views_update.assert_called_once()
        assert client.views_update.call_args.kwargs['view_id'] == 'V123'
        modal = client.views_update.call_args.kwargs['view']
        assert modal['callback_id'] == 'reservation_confirmation'
        rendered_text = modal['blocks'][0]['text']['text']
        assert '*Reservation confirmed*' in rendered_text
        assert 'Tool: Laser Cutter' in rendered_text
        assert 'Note: Table saw checkout' in rendered_text
        actions = modal['blocks'][1]['elements']
        assert actions[0]['text']['text'] == 'Cancel reservation'
        assert actions[0]['action_id'] == 'reservation_cancel_start'
        assert actions[1]['text']['text'] == 'View my reservations'
        assert actions[1]['action_id'] == 'reservation_view_mine'

        from esb.models.reservation import Reservation
        reservations = Reservation.query.filter_by(equipment_id=self.laser.id).all()
        assert len(reservations) == 1
        assert reservations[0].user_id == self.user.id
        assert reservations[0].notes == 'Table saw checkout'
        assert reservations[0].created_via == 'slack'
        assert actions[0]['value'] == str(reservations[0].id)

    def test_reservation_submission_updates_modal_to_unavailable_on_conflict(self):
        """Flow 3: conflicting reservation submit shows retry modal."""
        start_timestamp, end_timestamp = self._future_aligned_window(hours_from_now=4)
        existing = Reservation(
            equipment_id=self.laser.id,
            user_id=self.user.id,
            starts_at=datetime.fromtimestamp(start_timestamp, UTC).replace(tzinfo=None),
            ends_at=datetime.fromtimestamp(end_timestamp, UTC).replace(tzinfo=None),
            status='active',
            notes='future conflict',
            created_via='slack',
        )
        self.db.session.add(existing)
        self.db.session.commit()
        ack = MagicMock()
        client = MagicMock()
        client.users_info.return_value = {
            'user': {'profile': {'email': self.user.email}},
        }
        body = {'user': {'id': 'U123'}, 'view': {'id': 'V123'}}
        view = self._reservation_submission_view(self.laser.id, start_timestamp, end_timestamp)

        self.handlers['view:reservation_availability'](ack=ack, body=body, client=client, view=view)

        ack.assert_called_once()
        kwargs = ack.call_args.kwargs
        assert kwargs['response_action'] == 'update'
        assert kwargs['view']['callback_id'] == 'reservation_processing'
        client.views_update.assert_called_once()
        assert client.views_update.call_args.kwargs['view_id'] == 'V123'
        modal = client.views_update.call_args.kwargs['view']
        assert modal['callback_id'] == 'reservation_unavailable'
        assert modal['private_metadata'] == str(self.laser.id)
        rendered_text = modal['blocks'][0]['text']['text']
        assert '*That time is no longer available*' in rendered_text
        assert 'Reservation overlaps an existing reservation' in rendered_text
        retry_actions = modal['blocks'][1]['elements']
        assert retry_actions[0]['text']['text'] == 'Choose another time'
        assert retry_actions[0]['action_id'] == 'reservation_choose_another_time'

    def test_choose_another_time_updates_error_modal_back_to_time_picker(self):
        """Unavailable modal retry button returns to Flow 2 for the selected tool."""
        ack = MagicMock()
        client = MagicMock()
        body = {
            'user': {'id': 'U123'},
            'view': {'id': 'V123'},
            'actions': [{'value': str(self.cnc.id)}],
        }

        self.handlers['action:reservation_choose_another_time'](ack=ack, body=body, client=client)

        ack.assert_called_once()
        client.views_update.assert_called_once()
        assert client.views_update.call_args.kwargs['view_id'] == 'V123'
        modal = client.views_update.call_args.kwargs['view']
        assert modal['callback_id'] == 'reservation_availability'
        rendered_headers = '\n'.join(
            block['text']['text']
            for block in modal['blocks']
            if block.get('type') == 'header'
        )
        assert 'Reservation Request' in rendered_headers

    def test_view_my_reservations_pushes_upcoming_reservations_modal(self):
        """Flow 4: shared View my reservations action lists the user's future reservations."""
        start_timestamp, end_timestamp = self._future_aligned_window(hours_from_now=5)
        future = Reservation(
            equipment_id=self.laser.id,
            user_id=self.user.id,
            starts_at=datetime.fromtimestamp(start_timestamp, UTC).replace(tzinfo=None),
            ends_at=datetime.fromtimestamp(end_timestamp, UTC).replace(tzinfo=None),
            status='active',
            notes='future reservation',
            created_via='slack',
        )
        self.db.session.add(future)
        self.db.session.commit()

        ack = MagicMock()
        client = MagicMock()
        client.users_info.return_value = {
            'user': {'profile': {'email': self.user.email}},
        }
        body = {
            'trigger_id': 'T789',
            'user': {'id': 'U123'},
            'view': {'id': 'V123'},
            'actions': [{'value': 'stub-my-reservations'}],
        }

        self.handlers['action:reservation_view_mine'](ack=ack, body=body, client=client)

        ack.assert_called_once()
        client.views_update.assert_called_once()
        assert client.views_update.call_args.kwargs['view_id'] == 'V123'
        modal = client.views_update.call_args.kwargs['view']
        assert modal['callback_id'] == 'reservation_mine'
        assert modal['title']['text'] == 'My Reservations'
        rendered_text = '\n'.join(
            block['text']['text']
            for block in modal['blocks']
            if block.get('type') == 'section'
        )
        assert '*Laser Cutter*' in rendered_text
        assert 'future reservation' not in rendered_text
        actions = [
            block for block in modal['blocks']
            if block.get('block_id') == f'reservation_{future.id}_actions_block'
        ][0]
        assert actions['elements'][0]['text']['text'] == 'Cancel'
        assert actions['elements'][0]['action_id'] == 'reservation_cancel_start'

        footer_actions = [
            block for block in modal['blocks']
            if block.get('block_id') == 'reservation_mine_actions_block'
        ][0]
        assert footer_actions['elements'][0]['text']['text'] == 'Reserve another tool'
        assert footer_actions['elements'][0]['action_id'] == 'reservation_reserve_another'

    def test_view_my_reservations_unlinked_user_updates_to_error_modal(self):
        """Flow 4: modal action errors do not require a Slack channel."""
        ack = MagicMock()
        client = MagicMock()
        client.users_info.return_value = {
            'user': {'profile': {'email': 'missing@example.test'}},
        }
        body = {
            'user': {'id': 'U123'},
            'view': {'id': 'V123'},
            'actions': [{'value': 'stub-my-reservations'}],
        }

        self.handlers['action:reservation_view_mine'](ack=ack, body=body, client=client)

        ack.assert_called_once()
        client.chat_postEphemeral.assert_not_called()
        client.views_update.assert_called_once()
        assert client.views_update.call_args.kwargs['view_id'] == 'V123'
        modal = client.views_update.call_args.kwargs['view']
        assert modal['callback_id'] == 'reservation_error'
        assert 'Your Slack account is not linked to an ESB user.' in modal['blocks'][0]['text']['text']

    def test_reserve_another_tool_updates_to_landing_modal(self):
        """Flow 4 footer action returns to Flow 1 tool selection."""
        ack = MagicMock()
        client = MagicMock()
        body = {
            'user': {'id': 'U123'},
            'view': {'id': 'V123'},
            'actions': [{'value': 'reserve-another-tool'}],
        }

        self.handlers['action:reservation_reserve_another'](ack=ack, body=body, client=client)

        ack.assert_called_once()
        client.views_update.assert_called_once()
        assert client.views_update.call_args.kwargs['view_id'] == 'V123'
        modal = client.views_update.call_args.kwargs['view']
        assert modal['callback_id'] == 'reservation_landing'
        assert modal['title']['text'] == 'Makerspace Tools'
        rendered_text = '\n'.join(
            block['text']['text']
            for block in modal['blocks']
            if block.get('type') == 'section'
        )
        assert '*Laser Cutter*' in rendered_text
        assert '*CNC Router*' in rendered_text

    def test_cancel_button_updates_to_cancel_confirmation_modal(self):
        """Flow 5: clicking Cancel asks for confirmation before canceling."""
        start_timestamp, end_timestamp = self._future_aligned_window(hours_from_now=5)
        future = Reservation(
            equipment_id=self.laser.id,
            user_id=self.user.id,
            starts_at=datetime.fromtimestamp(start_timestamp, UTC).replace(tzinfo=None),
            ends_at=datetime.fromtimestamp(end_timestamp, UTC).replace(tzinfo=None),
            status='active',
            notes='future reservation',
            created_via='slack',
        )
        self.db.session.add(future)
        self.db.session.commit()

        ack = MagicMock()
        client = MagicMock()
        client.users_info.return_value = {
            'user': {'profile': {'email': self.user.email}},
        }
        body = {
            'user': {'id': 'U123'},
            'view': {'id': 'V123'},
            'actions': [{'value': str(future.id)}],
        }

        self.handlers['action:reservation_cancel_start'](ack=ack, body=body, client=client)

        ack.assert_called_once()
        client.views_update.assert_called_once()
        modal = client.views_update.call_args.kwargs['view']
        assert modal['callback_id'] == 'reservation_cancel_confirm'
        assert modal['private_metadata'] == str(future.id)
        assert modal['title']['text'] == 'Cancel reservation?'
        rendered_text = modal['blocks'][0]['text']['text']
        assert '*Laser Cutter*' in rendered_text
        assert 'This will make the time available to other members.' in rendered_text
        actions = modal['blocks'][1]['elements']
        assert actions[0]['text']['text'] == 'Keep reservation'
        assert actions[0]['action_id'] == 'reservation_cancel_keep'
        assert actions[1]['text']['text'] == 'Cancel it'
        assert actions[1]['action_id'] == 'reservation_cancel_confirm'

    def test_cancel_stale_reservation_updates_to_error_modal(self):
        """Flow 5: stale cancel buttons update the modal instead of posting ephemerally."""
        ack = MagicMock()
        client = MagicMock()
        client.users_info.return_value = {
            'user': {'profile': {'email': self.user.email}},
        }
        body = {
            'user': {'id': 'U123'},
            'view': {'id': 'V123'},
            'actions': [{'value': '999999'}],
        }

        self.handlers['action:reservation_cancel_start'](ack=ack, body=body, client=client)

        ack.assert_called_once()
        client.chat_postEphemeral.assert_not_called()
        client.views_update.assert_called_once()
        modal = client.views_update.call_args.kwargs['view']
        assert modal['callback_id'] == 'reservation_error'
        assert 'That reservation is no longer available to cancel.' in modal['blocks'][0]['text']['text']

    def test_keep_reservation_returns_to_my_reservations(self):
        """Flow 5: keeping a reservation returns to the user's reservation list."""
        start_timestamp, end_timestamp = self._future_aligned_window(hours_from_now=5)
        future = Reservation(
            equipment_id=self.laser.id,
            user_id=self.user.id,
            starts_at=datetime.fromtimestamp(start_timestamp, UTC).replace(tzinfo=None),
            ends_at=datetime.fromtimestamp(end_timestamp, UTC).replace(tzinfo=None),
            status='active',
            notes='future reservation',
            created_via='slack',
        )
        self.db.session.add(future)
        self.db.session.commit()

        ack = MagicMock()
        client = MagicMock()
        client.users_info.return_value = {
            'user': {'profile': {'email': self.user.email}},
        }
        body = {
            'user': {'id': 'U123'},
            'view': {'id': 'V123'},
            'actions': [{'value': str(future.id)}],
        }

        self.handlers['action:reservation_cancel_keep'](ack=ack, body=body, client=client)

        ack.assert_called_once()
        client.views_update.assert_called_once()
        modal = client.views_update.call_args.kwargs['view']
        assert modal['callback_id'] == 'reservation_mine'
        rendered_text = '\n'.join(
            block['text']['text']
            for block in modal['blocks']
            if block.get('type') == 'section'
        )
        assert '*Laser Cutter*' in rendered_text

    def test_cancel_confirmation_cancels_reservation_and_shows_result(self):
        """Flow 5: confirming cancellation marks the reservation canceled."""
        self.app.config['STATIC_PAGE_PUBLIC_URL'] = 'http://example.test/status'
        start_timestamp, end_timestamp = self._future_aligned_window(hours_from_now=5)
        future = Reservation(
            equipment_id=self.laser.id,
            user_id=self.user.id,
            starts_at=datetime.fromtimestamp(start_timestamp, UTC).replace(tzinfo=None),
            ends_at=datetime.fromtimestamp(end_timestamp, UTC).replace(tzinfo=None),
            status='active',
            notes='future reservation',
            created_via='slack',
        )
        self.db.session.add(future)
        self.db.session.commit()

        ack = MagicMock()
        client = MagicMock()
        client.users_info.return_value = {
            'user': {'profile': {'email': self.user.email}},
        }
        body = {
            'user': {'id': 'U123'},
            'view': {'id': 'V123'},
            'actions': [{'value': str(future.id)}],
        }

        self.handlers['action:reservation_cancel_confirm'](ack=ack, body=body, client=client)

        ack.assert_called_once()
        self.db.session.refresh(future)
        assert future.status == 'canceled'
        assert future.canceled_by_user_id == self.user.id
        client.views_update.assert_called_once()
        modal = client.views_update.call_args.kwargs['view']
        assert modal['callback_id'] == 'reservation_canceled'
        rendered_text = modal['blocks'][0]['text']['text']
        assert '*Reservation canceled*' in rendered_text
        assert 'Laser Cutter is no longer reserved for' in rendered_text
        actions = modal['blocks'][1]['elements']
        assert actions[0]['text']['text'] == 'Reserve another tool'
        assert actions[0]['action_id'] == 'reservation_reserve_another'
        assert actions[1]['text']['text'] == 'View availability'
        assert actions[1]['url'] == 'http://example.test/status'


class TestProblemReportSubmission:
    """Tests for problem_report_submission view handler."""

    @pytest.fixture(autouse=True)
    def setup(self, app, db):
        self.app = app
        self.db = db
        self.area = _create_area(name='Woodshop', slack_channel='#woodshop')
        self.equipment = _create_equipment(name='SawStop', area=self.area)
        self.handlers = _register_and_capture(app)

    def _build_view(self, equipment_id=None, description='Machine is broken',
                    reporter_name='Test User', severity='Down',
                    safety_risk=False, consumable=False):
        equipment_id = equipment_id or self.equipment.id
        safety_options = [{'value': 'safety_risk'}] if safety_risk else []
        consumable_options = [{'value': 'consumable'}] if consumable else []
        return {
            'state': {
                'values': {
                    'equipment_block': {'equipment_select': {'selected_option': {'value': str(equipment_id)}}},
                    'name_block': {'reporter_name': {'value': reporter_name}},
                    'description_block': {'description': {'value': description}},
                    'severity_block': {'severity': {'selected_option': {'value': severity}}},
                    'safety_risk_block': {'safety_risk': {'selected_options': safety_options}},
                    'consumable_block': {'consumable': {'selected_options': consumable_options}},
                },
            },
        }

    def test_submission_creates_repair_record(self):
        """5.2: Problem report submission creates repair record via repair_service."""
        ack = MagicMock()
        client = MagicMock()
        view = self._build_view()
        body = {'user': {'id': 'U12345', 'username': 'testuser'}}

        self.handlers['view:problem_report_submission'](ack=ack, body=body, client=client, view=view)

        ack.assert_called_once_with()

        from esb.models.repair_record import RepairRecord
        records = RepairRecord.query.all()
        assert len(records) == 1
        assert records[0].description == 'Machine is broken'
        assert records[0].severity == 'Down'
        assert records[0].reporter_name == 'Test User'
        assert records[0].status == 'New'

    def test_submission_posts_ephemeral_confirmation(self):
        """5.3: Problem report submission posts ephemeral confirmation."""
        ack = MagicMock()
        client = MagicMock()
        view = self._build_view()
        body = {'user': {'id': 'U12345', 'username': 'testuser'}}

        self.handlers['view:problem_report_submission'](ack=ack, body=body, client=client, view=view)

        client.chat_postEphemeral.assert_called_once()
        msg = client.chat_postEphemeral.call_args.kwargs['text']
        assert 'Problem report submitted' in msg
        assert 'SawStop' in msg

    def test_submission_with_safety_risk(self):
        """Safety risk checkbox is correctly passed to service."""
        ack = MagicMock()
        client = MagicMock()
        view = self._build_view(safety_risk=True)
        body = {'user': {'id': 'U12345', 'username': 'testuser'}}

        self.handlers['view:problem_report_submission'](ack=ack, body=body, client=client, view=view)

        from esb.models.repair_record import RepairRecord
        record = RepairRecord.query.first()
        assert record.has_safety_risk is True

    def test_submission_with_consumable(self):
        """Consumable checkbox is correctly passed to service."""
        ack = MagicMock()
        client = MagicMock()
        view = self._build_view(consumable=True)
        body = {'user': {'id': 'U12345', 'username': 'testuser'}}

        self.handlers['view:problem_report_submission'](ack=ack, body=body, client=client, view=view)

        from esb.models.repair_record import RepairRecord
        record = RepairRecord.query.first()
        assert record.is_consumable is True

    def test_validation_error_returns_slack_error(self):
        """5.13: ValidationError in view handler returns Slack-formatted error."""
        ack = MagicMock()
        client = MagicMock()
        view = self._build_view(description='')  # Empty description triggers validation error
        body = {'user': {'id': 'U12345', 'username': 'testuser'}}

        self.handlers['view:problem_report_submission'](ack=ack, body=body, client=client, view=view)

        ack.assert_called_once_with(response_action='errors', errors={'description_block': 'Description is required'})
        client.chat_postEphemeral.assert_not_called()


class TestEsbRepairCommand:
    """Tests for /esb-repair command handler."""

    @pytest.fixture(autouse=True)
    def setup(self, app, db):
        self.app = app
        self.db = db
        self.area = _create_area(name='Woodshop', slack_channel='#woodshop')
        self.equipment = _create_equipment(name='SawStop', area=self.area)
        self.staff_user = _create_user('staff', username='admin1')
        self.handlers = _register_and_capture(app)

    def test_rejects_non_tech_staff_users(self):
        """5.4: /esb-repair rejects non-tech/staff users with ephemeral error."""
        ack = MagicMock()
        client = MagicMock()
        client.users_info.return_value = {
            'user': {'profile': {'email': 'nobody@test.com'}},
        }
        body = {'trigger_id': 'T123', 'user_id': 'U999', 'channel_id': 'C123'}

        self.handlers['command:/esb-repair'](ack=ack, body=body, client=client)

        ack.assert_called_once()
        client.chat_postEphemeral.assert_called_once()
        assert 'Technician or Staff' in client.chat_postEphemeral.call_args.kwargs['text']
        client.views_open.assert_not_called()

    def test_opens_modal_for_authorized_user(self):
        """/esb-repair <equipment-name> opens the create-record modal for authorized users."""
        ack = MagicMock()
        client = MagicMock()
        client.users_info.return_value = {
            'user': {'profile': {'email': self.staff_user.email}},
        }
        body = {
            'trigger_id': 'T123', 'user_id': 'U123', 'channel_id': 'C123',
            'text': 'SawStop',
        }

        self.handlers['command:/esb-repair'](ack=ack, body=body, client=client)

        ack.assert_called_once()
        client.views_open.assert_called_once()
        modal = client.views_open.call_args.kwargs['view']
        assert modal['callback_id'] == 'repair_create_submission'

    def test_rejects_member_role(self):
        """Member role users are rejected from /esb-repair."""
        member = _create_user('member', username='member1')
        ack = MagicMock()
        client = MagicMock()
        client.users_info.return_value = {
            'user': {'profile': {'email': member.email}},
        }
        body = {'trigger_id': 'T123', 'user_id': 'U123', 'channel_id': 'C123'}

        self.handlers['command:/esb-repair'](ack=ack, body=body, client=client)

        client.chat_postEphemeral.assert_called_once()
        client.views_open.assert_not_called()

    def test_repair_command_no_equipment_posts_error(self):
        """/esb-repair <name> with no equipment in DB posts the no-equipment error."""
        from esb.models.equipment import Equipment
        Equipment.query.delete()
        self.db.session.commit()

        ack = MagicMock()
        client = MagicMock()
        client.users_info.return_value = {
            'user': {'profile': {'email': self.staff_user.email}},
        }
        body = {
            'trigger_id': 'T123', 'user_id': 'U123', 'channel_id': 'C123',
            'text': 'SawStop',
        }

        self.handlers['command:/esb-repair'](ack=ack, body=body, client=client)

        ack.assert_called_once()
        client.chat_postEphemeral.assert_called_once()
        assert 'No equipment' in client.chat_postEphemeral.call_args.kwargs['text']
        client.views_open.assert_not_called()


class TestRepairCreateSubmission:
    """Tests for repair_create_submission view handler."""

    @pytest.fixture(autouse=True)
    def setup(self, app, db):
        self.app = app
        self.db = db
        self.area = _create_area(name='Woodshop', slack_channel='#woodshop')
        self.equipment = _create_equipment(name='SawStop', area=self.area)
        self.staff_user = _create_user('staff', username='admin1')
        self.handlers = _register_and_capture(app)

    def _build_view(self, equipment_id=None, description='Broken blade',
                    severity=None, assignee_id=None, status='New'):
        equipment_id = equipment_id or self.equipment.id
        severity_opt = {'selected_option': {'value': severity}} if severity else {'selected_option': None}
        assignee_opt = {'selected_option': {'value': str(assignee_id)}} if assignee_id else {'selected_option': None}
        status_opt = {'selected_option': {'value': status}}
        return {
            'state': {
                'values': {
                    'equipment_block': {'equipment_select': {'selected_option': {'value': str(equipment_id)}}},
                    'description_block': {'description': {'value': description}},
                    'severity_block': {'severity': severity_opt},
                    'assignee_block': {'assignee': assignee_opt},
                    'status_block': {'status': status_opt},
                },
            },
        }

    def test_creates_record_with_correct_author_id(self):
        """5.6: Repair creation submission creates record with correct author_id."""
        ack = MagicMock()
        client = MagicMock()
        client.users_info.return_value = {
            'user': {'profile': {'email': self.staff_user.email}},
        }
        view = self._build_view()
        body = {'user': {'id': 'U123', 'username': 'slackuser'}}

        self.handlers['view:repair_create_submission'](ack=ack, body=body, client=client, view=view)

        ack.assert_called_once_with()

        from esb.models.repair_record import RepairRecord
        records = RepairRecord.query.all()
        assert len(records) == 1
        assert records[0].description == 'Broken blade'
        assert records[0].status == 'New'

    def test_posts_ephemeral_confirmation(self):
        """Repair creation posts ephemeral confirmation."""
        ack = MagicMock()
        client = MagicMock()
        client.users_info.return_value = {
            'user': {'profile': {'email': self.staff_user.email}},
        }
        view = self._build_view()
        body = {'user': {'id': 'U123', 'username': 'slackuser'}}

        self.handlers['view:repair_create_submission'](ack=ack, body=body, client=client, view=view)

        client.chat_postEphemeral.assert_called_once()
        msg = client.chat_postEphemeral.call_args.kwargs['text']
        assert 'Repair record #' in msg
        assert 'SawStop' in msg

    def test_creates_record_with_non_default_status(self):
        """M3: Repair creation with non-New status creates and then updates."""
        ack = MagicMock()
        client = MagicMock()
        client.users_info.return_value = {
            'user': {'profile': {'email': self.staff_user.email}},
        }
        view = self._build_view(status='In Progress')
        body = {'user': {'id': 'U123', 'username': 'slackuser'}}

        self.handlers['view:repair_create_submission'](ack=ack, body=body, client=client, view=view)

        ack.assert_called_once_with()

        from esb.models.repair_record import RepairRecord
        records = RepairRecord.query.all()
        assert len(records) == 1
        assert records[0].status == 'In Progress'


class TestResolveEsbUser:
    """Tests for _resolve_esb_user() helper."""

    @pytest.fixture(autouse=True)
    def setup(self, app, db):
        self.app = app
        self.db = db
        self.staff_user = _create_user('staff', username='admin1')

    def test_maps_slack_user_to_esb_user_via_email(self):
        """5.11: _resolve_esb_user() maps Slack user to ESB user via email."""
        from esb.slack.handlers import _resolve_esb_user

        client = MagicMock()
        client.users_info.return_value = {
            'user': {'profile': {'email': self.staff_user.email}},
        }

        user = _resolve_esb_user(client, 'U12345')

        assert user is not None
        assert user.id == self.staff_user.id
        assert user.username == 'admin1'

    def test_returns_none_for_unmapped_user(self):
        """5.12: _resolve_esb_user() returns None for unmapped user."""
        from esb.slack.handlers import _resolve_esb_user

        client = MagicMock()
        client.users_info.return_value = {
            'user': {'profile': {'email': 'nobody@notfound.com'}},
        }

        user = _resolve_esb_user(client, 'U99999')

        assert user is None

    def test_returns_none_when_api_fails(self):
        """_resolve_esb_user() returns None when Slack API call fails."""
        from esb.slack.handlers import _resolve_esb_user

        client = MagicMock()
        client.users_info.side_effect = Exception('API error')

        user = _resolve_esb_user(client, 'U12345')

        assert user is None

    def test_returns_none_for_no_email(self):
        """_resolve_esb_user() returns None when user has no email in profile."""
        from esb.slack.handlers import _resolve_esb_user

        client = MagicMock()
        client.users_info.return_value = {
            'user': {'profile': {}},
        }

        user = _resolve_esb_user(client, 'U12345')

        assert user is None

    def test_returns_none_for_inactive_user(self):
        """_resolve_esb_user() returns None for inactive ESB user."""
        self.staff_user.is_active = False
        self.db.session.commit()

        from esb.slack.handlers import _resolve_esb_user

        client = MagicMock()
        client.users_info.return_value = {
            'user': {'profile': {'email': self.staff_user.email}},
        }

        user = _resolve_esb_user(client, 'U12345')

        assert user is None


def _section_texts(view):
    """Collect all section mrkdwn/plain_text strings from a modal view dict."""
    texts = []
    for block in view.get('blocks', []):
        text = block.get('text')
        if isinstance(text, dict) and 'text' in text:
            texts.append(text['text'])
    return texts


class TestEsbStatusCommand:
    """Tests for /esb-status command handler (modal rework, issue #70)."""

    @pytest.fixture(autouse=True)
    def setup(self, app, db):
        self.app = app
        self.db = db
        self.area = _create_area(name='Woodshop', slack_channel='#woodshop')
        self.equipment = _create_equipment(name='SawStop', area=self.area)
        self.handlers = _register_and_capture(app)

    def test_handler_registered(self):
        """Verify /esb-status is registered on bolt_app."""
        assert 'command:/esb-status' in self.handlers

    def test_no_args_opens_summary_modal(self):
        """AC 1: /esb-status with no args opens the summary modal (no ephemeral)."""
        ack = MagicMock()
        client = MagicMock()
        body = {'trigger_id': 'T123', 'user_id': 'U123', 'channel_id': 'C123', 'text': ''}

        self.handlers['command:/esb-status'](ack=ack, body=body, client=client, respond=MagicMock())

        ack.assert_called_once()
        client.views_open.assert_called_once()
        client.chat_postEphemeral.assert_not_called()
        view = client.views_open.call_args.kwargs['view']
        assert view['callback_id'] == 'esb_status_summary'
        assert any('Equipment Status Summary' in t for t in _section_texts(view))

    def test_single_equipment_opens_area_detail_modal(self):
        """AC 6: single equipment match opens that equipment's area-detail modal."""
        ack = MagicMock()
        client = MagicMock()
        body = {'trigger_id': 'T123', 'user_id': 'U123', 'channel_id': 'C123', 'text': 'SawStop'}

        self.handlers['command:/esb-status'](ack=ack, body=body, client=client, respond=MagicMock())

        client.views_open.assert_called_once()
        view = client.views_open.call_args.kwargs['view']
        assert view['callback_id'] == 'esb_status_area_detail'
        assert view['title']['text'] == 'Woodshop'

    def test_no_match_opens_summary_modal(self):
        """AC 7: no match falls back to the summary modal (no error text)."""
        ack = MagicMock()
        client = MagicMock()
        body = {'trigger_id': 'T123', 'user_id': 'U123', 'channel_id': 'C123', 'text': 'NonexistentThing'}

        self.handlers['command:/esb-status'](ack=ack, body=body, client=client, respond=MagicMock())

        client.views_open.assert_called_once()
        view = client.views_open.call_args.kwargs['view']
        assert view['callback_id'] == 'esb_status_summary'

    def test_multiple_matches_opens_summary_modal(self):
        """AC 7: multiple matches fall back to the summary modal, not a list."""
        _create_equipment(name='Band Saw', area=self.area)

        ack = MagicMock()
        client = MagicMock()
        body = {'trigger_id': 'T123', 'user_id': 'U123', 'channel_id': 'C123', 'text': 'Saw'}

        self.handlers['command:/esb-status'](ack=ack, body=body, client=client, respond=MagicMock())

        client.views_open.assert_called_once()
        view = client.views_open.call_args.kwargs['view']
        assert view['callback_id'] == 'esb_status_summary'
        client.chat_postEphemeral.assert_not_called()

    def test_ack_called_before_views_open(self):
        """AC 9: ack() is called before views_open (trigger_id used promptly)."""
        call_order = []
        ack = MagicMock(side_effect=lambda: call_order.append('ack'))
        client = MagicMock()
        client.views_open = MagicMock(side_effect=lambda **kwargs: call_order.append('views_open'))
        body = {'trigger_id': 'T123', 'user_id': 'U123', 'channel_id': 'C123', 'text': ''}

        self.handlers['command:/esb-status'](ack=ack, body=body, client=client, respond=MagicMock())

        assert call_order[0] == 'ack'
        assert 'views_open' in call_order

    def test_service_error_responds_via_response_url_and_no_modal(self):
        """AC 10: an unexpected service error replies via response_url and opens no modal.

        Bolt's ``respond`` posts to the slash command's response_url, which works
        even when the bot is not a member of the invoking channel — the exact
        limitation this feature fixes. No channel ephemeral is posted.
        """
        from unittest.mock import patch

        ack = MagicMock()
        client = MagicMock()
        respond = MagicMock()
        body = {'trigger_id': 'T123', 'user_id': 'U123', 'channel_id': 'C123', 'text': 'SawStop'}

        with patch(
            'esb.services.equipment_service.search_equipment_by_name',
            side_effect=Exception('DB error'),
        ):
            self.handlers['command:/esb-status'](ack=ack, body=body, client=client, respond=respond)

        ack.assert_called_once()
        client.views_open.assert_not_called()
        client.chat_postEphemeral.assert_not_called()
        respond.assert_called_once()
        kwargs = respond.call_args.kwargs
        assert 'error occurred' in kwargs['text'].lower()
        assert kwargs['response_type'] == 'ephemeral'

    def test_views_open_failure_responds_via_response_url(self):
        """F8: if views_open itself rejects the view, the error reply still fires."""
        ack = MagicMock()
        client = MagicMock()
        client.views_open = MagicMock(side_effect=Exception('invalid_blocks'))
        respond = MagicMock()
        body = {'trigger_id': 'T123', 'user_id': 'U123', 'channel_id': 'C123', 'text': ''}

        self.handlers['command:/esb-status'](ack=ack, body=body, client=client, respond=respond)

        respond.assert_called_once()
        assert 'error occurred' in respond.call_args.kwargs['text'].lower()

    def test_empty_dashboard_opens_summary_modal(self):
        """AC 8: no equipment registered → summary modal with a 'No equipment' section."""
        from esb.models.equipment import Equipment
        Equipment.query.delete()
        self.db.session.commit()

        ack = MagicMock()
        client = MagicMock()
        body = {'trigger_id': 'T123', 'user_id': 'U123', 'channel_id': 'C123', 'text': ''}

        self.handlers['command:/esb-status'](ack=ack, body=body, client=client, respond=MagicMock())

        client.views_open.assert_called_once()
        view = client.views_open.call_args.kwargs['view']
        assert view['callback_id'] == 'esb_status_summary'
        assert any('No equipment' in t for t in _section_texts(view))

    def test_area_name_opens_area_detail_modal(self):
        """AC 4: exact case-insensitive area name opens the area-detail modal."""
        ack = MagicMock()
        client = MagicMock()
        body = {'trigger_id': 'T', 'user_id': 'U', 'channel_id': 'C', 'text': 'woodshop'}

        self.handlers['command:/esb-status'](ack=ack, body=body, client=client, respond=MagicMock())

        view = client.views_open.call_args.kwargs['view']
        assert view['callback_id'] == 'esb_status_area_detail'
        assert view['title']['text'] == 'Woodshop'

    def test_area_name_takes_precedence_over_equipment(self):
        """AC 5: area name match wins over an equipment name containing the same substring."""
        _create_equipment(name='Woodshop Helper', area=self.area)

        ack = MagicMock()
        client = MagicMock()
        body = {'trigger_id': 'T', 'user_id': 'U', 'channel_id': 'C', 'text': 'Woodshop'}

        self.handlers['command:/esb-status'](ack=ack, body=body, client=client, respond=MagicMock())

        view = client.views_open.call_args.kwargs['view']
        assert view['callback_id'] == 'esb_status_area_detail'
        assert view['title']['text'] == 'Woodshop'

    def test_archived_area_deep_link_falls_back_to_summary(self):
        """AC 12: equipment whose area is archived deep-links to the summary, not an error."""
        from esb.services import equipment_service

        equipment_service.archive_area(self.area.id, archived_by='tester')
        # Pin the mechanism (F14): the equipment is still resolvable by name and
        # its area_id points at the now-archived area — so resolution reaches the
        # AreaArchived branch, not merely "no match".
        matches = equipment_service.search_equipment_by_name('SawStop')
        assert len(matches) == 1
        assert matches[0].area_id == self.area.id

        ack = MagicMock()
        client = MagicMock()
        body = {'trigger_id': 'T', 'user_id': 'U', 'channel_id': 'C', 'text': 'SawStop'}

        self.handlers['command:/esb-status'](ack=ack, body=body, client=client, respond=MagicMock())

        client.views_open.assert_called_once()
        view = client.views_open.call_args.kwargs['view']
        assert view['callback_id'] == 'esb_status_summary'
        client.chat_postEphemeral.assert_not_called()



class TestEsbStatusActions:
    """Tests for the /esb-status modal button action handlers."""

    @pytest.fixture(autouse=True)
    def setup(self, app, db):
        self.app = app
        self.db = db
        self.area = _create_area(name='Woodshop', slack_channel='#woodshop')
        self.equipment = _create_equipment(name='SawStop', area=self.area)
        self.handlers = _register_and_capture(app)

    def test_action_handlers_registered(self):
        assert 'action:esb_status_view_area' in self.handlers
        assert 'action:esb_status_back_to_summary' in self.handlers

    def test_view_area_updates_to_area_detail(self):
        """AC 2: clicking 'View details' updates the modal to that area's detail."""
        ack = MagicMock()
        client = MagicMock()
        body = {
            'actions': [{'value': str(self.area.id)}],
            'view': {'id': 'V1'},
            'user': {'id': 'U1'},
            'channel': {'id': 'C1'},
        }

        self.handlers['action:esb_status_view_area'](ack=ack, body=body, client=client)

        ack.assert_called_once()
        client.views_update.assert_called_once()
        kwargs = client.views_update.call_args.kwargs
        assert kwargs['view_id'] == 'V1'
        assert kwargs['view']['callback_id'] == 'esb_status_area_detail'
        assert kwargs['view']['title']['text'] == 'Woodshop'

    def test_view_area_error_shows_error_modal(self):
        """AC 13: a failing 'View details' re-query updates to a close-only error modal."""
        from unittest.mock import patch

        ack = MagicMock()
        client = MagicMock()
        body = {
            'actions': [{'value': str(self.area.id)}],
            'view': {'id': 'V1'},
            'user': {'id': 'U1'},
            'channel': {'id': 'C1'},
        }

        with patch(
            'esb.services.status_service.get_single_area_status_dashboard',
            side_effect=Exception('DB error'),
        ):
            self.handlers['action:esb_status_view_area'](ack=ack, body=body, client=client)

        client.views_update.assert_called_once()
        view = client.views_update.call_args.kwargs['view']
        assert any('Could not load' in t for t in _section_texts(view))
        client.chat_postEphemeral.assert_not_called()

    def test_back_to_summary_updates_to_summary(self):
        """AC 3: clicking 'Back to summary' updates the modal to the summary view."""
        ack = MagicMock()
        client = MagicMock()
        body = {'view': {'id': 'V1'}, 'user': {'id': 'U1'}, 'channel': {'id': 'C1'}}

        self.handlers['action:esb_status_back_to_summary'](ack=ack, body=body, client=client)

        ack.assert_called_once()
        client.views_update.assert_called_once()
        kwargs = client.views_update.call_args.kwargs
        assert kwargs['view_id'] == 'V1'
        assert kwargs['view']['callback_id'] == 'esb_status_summary'

    def test_back_to_summary_error_shows_error_modal(self):
        """AC 13 (F6): a failing 'Back to summary' re-query updates to the error modal."""
        from unittest.mock import patch

        ack = MagicMock()
        client = MagicMock()
        body = {'view': {'id': 'V1'}, 'user': {'id': 'U1'}, 'channel': {'id': 'C1'}}

        with patch(
            'esb.services.status_service.get_area_status_dashboard',
            side_effect=Exception('DB error'),
        ):
            self.handlers['action:esb_status_back_to_summary'](ack=ack, body=body, client=client)

        client.views_update.assert_called_once()
        view = client.views_update.call_args.kwargs['view']
        assert any('Could not load' in t for t in _section_texts(view))
        client.chat_postEphemeral.assert_not_called()


class TestEsbRepairDispatcher:
    """Tests for /esb-repair no-args dispatcher path."""

    @pytest.fixture(autouse=True)
    def setup(self, app, db):
        self.app = app
        self.db = db
        self.area = _create_area(name='Woodshop', slack_channel='#woodshop')
        self.equipment = _create_equipment(name='SawStop', area=self.area)
        self.staff_user = _create_user('staff', username='admin1')
        self.handlers = _register_and_capture(app)

    def test_no_args_opens_dispatcher_modal(self):
        """AC 12: empty text + at least one open repair → dispatcher modal opens."""
        _create_repair_record(
            equipment=self.equipment, status='New', severity='Down',
            description='broken',
        )
        ack = MagicMock()
        client = MagicMock()
        client.users_info.return_value = {'user': {'profile': {'email': self.staff_user.email}}}
        body = {'trigger_id': 'T', 'user_id': 'U', 'channel_id': 'C', 'text': ''}

        self.handlers['command:/esb-repair'](ack=ack, body=body, client=client)

        client.views_open.assert_called_once()
        modal = client.views_open.call_args.kwargs['view']
        assert modal['callback_id'] == 'repair_dispatcher_submission'

    def test_no_open_repairs_posts_ephemeral(self):
        """AC 13: empty text + no open repairs → ephemeral, no modal."""
        ack = MagicMock()
        client = MagicMock()
        client.users_info.return_value = {'user': {'profile': {'email': self.staff_user.email}}}
        body = {'trigger_id': 'T', 'user_id': 'U', 'channel_id': 'C', 'text': ''}

        self.handlers['command:/esb-repair'](ack=ack, body=body, client=client)

        client.views_open.assert_not_called()
        client.chat_postEphemeral.assert_called_once()
        text = client.chat_postEphemeral.call_args.kwargs['text']
        assert ':wrench:' in text
        assert 'No open repairs' in text

    def test_with_args_opens_create_modal(self):
        """AC 14 (regression): non-empty text → create-record modal."""
        ack = MagicMock()
        client = MagicMock()
        client.users_info.return_value = {'user': {'profile': {'email': self.staff_user.email}}}
        body = {'trigger_id': 'T', 'user_id': 'U', 'channel_id': 'C', 'text': 'SawStop'}

        self.handlers['command:/esb-repair'](ack=ack, body=body, client=client)

        client.views_open.assert_called_once()
        modal = client.views_open.call_args.kwargs['view']
        assert modal['callback_id'] == 'repair_create_submission'

    def test_with_args_prefills_equipment_on_exact_match(self):
        """AC 40: exact equipment-name match preselects in the create-record modal."""
        ack = MagicMock()
        client = MagicMock()
        client.users_info.return_value = {'user': {'profile': {'email': self.staff_user.email}}}
        body = {'trigger_id': 'T', 'user_id': 'U', 'channel_id': 'C', 'text': 'SawStop'}

        self.handlers['command:/esb-repair'](ack=ack, body=body, client=client)
        modal = client.views_open.call_args.kwargs['view']
        eq_block = next(b for b in modal['blocks'] if b['block_id'] == 'equipment_block')
        # Initial option is set to the SawStop equipment.
        assert 'initial_option' in eq_block['element']
        assert eq_block['element']['initial_option']['value'] == str(self.equipment.id)

    def test_with_args_no_prefill_on_partial_only_match(self):
        """AC 40: partial-only match (no exact match) → no initial_option.

        Under the spec, preselection happens only on case-insensitive *exact*
        name match; a substring match that doesn't hit any equipment exactly
        must NOT preselect (Copilot review on PR #42).
        """
        # 'saw' partially matches 'SawStop' but does not exactly match any
        # equipment name -- preselection must be skipped.
        ack = MagicMock()
        client = MagicMock()
        client.users_info.return_value = {'user': {'profile': {'email': self.staff_user.email}}}
        body = {'trigger_id': 'T', 'user_id': 'U', 'channel_id': 'C', 'text': 'saw'}

        self.handlers['command:/esb-repair'](ack=ack, body=body, client=client)
        modal = client.views_open.call_args.kwargs['view']
        eq_block = next(b for b in modal['blocks'] if b['block_id'] == 'equipment_block')
        assert 'initial_option' not in eq_block['element']

    def test_with_args_exact_match_wins_over_partial_siblings(self):
        """AC 40: when an exact match exists alongside other partial matches, the exact match preselects."""
        _create_equipment(name='SawStop Mini', area=self.area)

        ack = MagicMock()
        client = MagicMock()
        client.users_info.return_value = {'user': {'profile': {'email': self.staff_user.email}}}
        body = {'trigger_id': 'T', 'user_id': 'U', 'channel_id': 'C', 'text': 'SawStop'}

        self.handlers['command:/esb-repair'](ack=ack, body=body, client=client)
        modal = client.views_open.call_args.kwargs['view']
        eq_block = next(b for b in modal['blocks'] if b['block_id'] == 'equipment_block')
        assert eq_block['element']['initial_option']['value'] == str(self.equipment.id)

    def test_rejects_unauthorized_user(self):
        """AC 15: non-tech/staff user → ephemeral error, no modal."""
        member = _create_user('member', username='memberX')

        ack = MagicMock()
        client = MagicMock()
        client.users_info.return_value = {'user': {'profile': {'email': member.email}}}
        body = {'trigger_id': 'T', 'user_id': 'U', 'channel_id': 'C', 'text': ''}

        self.handlers['command:/esb-repair'](ack=ack, body=body, client=client)
        client.views_open.assert_not_called()
        text = client.chat_postEphemeral.call_args.kwargs['text']
        assert 'Technician or Staff' in text


class TestRepairDispatcherSubmission:
    """Tests for repair_dispatcher_submission view handler."""

    @pytest.fixture(autouse=True)
    def setup(self, app, db):
        self.app = app
        self.db = db
        self.area = _create_area(name='Woodshop', slack_channel='#woodshop')
        self.equipment = _create_equipment(name='SawStop', area=self.area)
        self.staff_user = _create_user('staff', username='admin1')
        self.handlers = _register_and_capture(app)

    def _build_view(self, repair_id):
        return {
            'state': {
                'values': {
                    'repair_select_block': {
                        'repair_select': {'selected_option': {'value': str(repair_id)}},
                    },
                },
            },
        }

    def _body(self, email=None):
        return {'user': {'id': 'U1', 'username': 'admin1'}, 'trigger_id': 'T'}

    def test_pushes_action_modal(self):
        """AC 16: submitting with selected repair pushes the action modal via response_action='push'."""
        record = _create_repair_record(
            equipment=self.equipment, status='New', severity='Down', description='broken',
        )

        ack = MagicMock()
        client = MagicMock()
        client.users_info.return_value = {'user': {'profile': {'email': self.staff_user.email}}}
        view = self._build_view(record.id)

        self.handlers['view:repair_dispatcher_submission'](
            ack=ack, body=self._body(), client=client, view=view,
        )

        ack.assert_called_once()
        kwargs = ack.call_args.kwargs
        assert kwargs.get('response_action') == 'push'
        assert kwargs['view']['callback_id'] == 'repair_action_submission'
        assert kwargs['view']['private_metadata'] == str(record.id)

    def test_record_not_found_returns_error(self):
        ack = MagicMock()
        client = MagicMock()
        client.users_info.return_value = {'user': {'profile': {'email': self.staff_user.email}}}
        view = self._build_view(99999)

        self.handlers['view:repair_dispatcher_submission'](
            ack=ack, body=self._body(), client=client, view=view,
        )

        ack.assert_called_once()
        kwargs = ack.call_args.kwargs
        assert kwargs.get('response_action') == 'errors'
        assert 'repair_select_block' in kwargs['errors']

    def test_closed_record_returns_error(self):
        """F10: record closed between dispatcher open and submit → error, no push."""
        record = _create_repair_record(
            equipment=self.equipment, status='Resolved', severity='Down', description='x',
        )
        ack = MagicMock()
        client = MagicMock()
        client.users_info.return_value = {'user': {'profile': {'email': self.staff_user.email}}}
        view = self._build_view(record.id)

        self.handlers['view:repair_dispatcher_submission'](
            ack=ack, body=self._body(), client=client, view=view,
        )

        kwargs = ack.call_args.kwargs
        assert kwargs.get('response_action') == 'errors'
        # No push happened.
        assert 'view' not in kwargs

    def test_unauthorized_user_returns_error(self):
        """AC 24b / F14: member-role caller is rejected at submission time."""
        member = _create_user('member', username='memberX')
        record = _create_repair_record(
            equipment=self.equipment, status='New', severity='Down', description='x',
        )
        ack = MagicMock()
        client = MagicMock()
        client.users_info.return_value = {'user': {'profile': {'email': member.email}}}
        view = self._build_view(record.id)

        self.handlers['view:repair_dispatcher_submission'](
            ack=ack, body=self._body(), client=client, view=view,
        )

        kwargs = ack.call_args.kwargs
        assert kwargs.get('response_action') == 'errors'
        assert 'repair_select_block' in kwargs['errors']

    def test_no_selected_option_returns_error(self):
        ack = MagicMock()
        client = MagicMock()
        client.users_info.return_value = {'user': {'profile': {'email': self.staff_user.email}}}
        view = {
            'state': {
                'values': {
                    'repair_select_block': {'repair_select': {'selected_option': None}},
                },
            },
        }

        self.handlers['view:repair_dispatcher_submission'](
            ack=ack, body=self._body(), client=client, view=view,
        )

        kwargs = ack.call_args.kwargs
        assert kwargs.get('response_action') == 'errors'


class TestRepairActionSubmission:
    """Tests for repair_action_submission view handler."""

    @pytest.fixture(autouse=True)
    def setup(self, app, db):
        self.app = app
        self.db = db
        self.area = _create_area(name='Woodshop', slack_channel='#woodshop')
        self.equipment = _create_equipment(name='SawStop', area=self.area)
        self.staff_user = _create_user('staff', username='admin1')
        self.tech_user = _create_user('technician', username='techie')
        self.handlers = _register_and_capture(app)

    def _build_view(
        self, repair_id, action=None, eta=None, status=None, note=None,
        duplicate_id=None, include_duplicate_block=None,
    ):
        action_block = {'action': {'selected_option': {'value': action}}} if action else {'action': {'selected_option': None}}
        eta_block = {'eta': {'selected_date': eta}}
        status_block = {'status': {'selected_option': {'value': status}}} if status else {'status': {'selected_option': None}}
        note_block = {'note': {'value': note}}
        values = {
            'action_block': action_block,
            'eta_block': eta_block,
            'status_block': status_block,
            'note_block': note_block,
        }
        # Include duplicate_block when explicitly opted in, or when a duplicate_id is provided.
        if include_duplicate_block or duplicate_id is not None:
            if duplicate_id is not None:
                values['duplicate_block'] = {
                    'duplicated_repair_id': {
                        'selected_option': {'value': str(duplicate_id)},
                    },
                }
            else:
                values['duplicate_block'] = {
                    'duplicated_repair_id': {'selected_option': None},
                }
        return {
            'private_metadata': str(repair_id),
            'state': {
                'values': values,
            },
        }

    def _body(self, email):
        return {'user': {'id': 'U1', 'username': 'caller'}, 'trigger_id': 'T'}

    def _client(self, email):
        client = MagicMock()
        client.users_info.return_value = {'user': {'profile': {'email': email}}}
        return client

    def test_claim_assigns_to_caller_and_sets_status_to_assigned_when_new(self):
        """AC 17: claim on 'New' record sets assignee + status='Assigned'."""
        record = _create_repair_record(
            equipment=self.equipment, status='New', severity='Down', description='x',
        )
        ack = MagicMock()
        client = self._client(self.tech_user.email)
        view = self._build_view(record.id, action='claim')

        self.handlers['view:repair_action_submission'](
            ack=ack, body=self._body(self.tech_user.email), client=client, view=view,
        )

        ack.assert_called_once_with(response_action='clear')
        from esb.models.repair_record import RepairRecord
        self.db.session.expire_all()
        rec = self.db.session.get(RepairRecord, record.id)
        assert rec.assignee_id == self.tech_user.id
        assert rec.status == 'Assigned'

    def test_claim_leaves_status_when_already_assigned(self):
        """AC 18 / F11: claim on 'Assigned' updates assignee but not status."""
        other = _create_user('technician', username='other')
        record = _create_repair_record(
            equipment=self.equipment, status='Assigned', severity='Down',
            description='x', assignee_id=other.id,
        )
        ack = MagicMock()
        client = self._client(self.tech_user.email)
        view = self._build_view(record.id, action='claim')

        self.handlers['view:repair_action_submission'](
            ack=ack, body=self._body(self.tech_user.email), client=client, view=view,
        )

        ack.assert_called_once_with(response_action='clear')
        from esb.models.repair_record import RepairRecord
        self.db.session.expire_all()
        rec = self.db.session.get(RepairRecord, record.id)
        assert rec.assignee_id == self.tech_user.id
        assert rec.status == 'Assigned'

    def test_claim_leaves_status_when_in_progress(self):
        """AC 18 / F11: claim on 'In Progress' updates assignee but not status."""
        record = _create_repair_record(
            equipment=self.equipment, status='In Progress', severity='Down', description='x',
        )
        ack = MagicMock()
        client = self._client(self.tech_user.email)
        view = self._build_view(record.id, action='claim')

        self.handlers['view:repair_action_submission'](
            ack=ack, body=self._body(self.tech_user.email), client=client, view=view,
        )

        ack.assert_called_once_with(response_action='clear')
        from esb.models.repair_record import RepairRecord
        self.db.session.expire_all()
        rec = self.db.session.get(RepairRecord, record.id)
        assert rec.assignee_id == self.tech_user.id
        assert rec.status == 'In Progress'

    def test_set_eta_updates_eta_when_value_differs(self):
        """AC 19: set_eta with new date updates eta + adds eta_update timeline entry."""
        record = _create_repair_record(
            equipment=self.equipment, status='New', severity='Down', description='x',
        )
        ack = MagicMock()
        client = self._client(self.tech_user.email)
        view = self._build_view(record.id, action='set_eta', eta='2026-08-01')

        self.handlers['view:repair_action_submission'](
            ack=ack, body=self._body(self.tech_user.email), client=client, view=view,
        )

        ack.assert_called_once_with(response_action='clear')
        from datetime import date
        from esb.models.repair_record import RepairRecord
        from esb.models.repair_timeline_entry import RepairTimelineEntry
        self.db.session.expire_all()
        rec = self.db.session.get(RepairRecord, record.id)
        assert rec.eta == date(2026, 8, 1)
        entries = self.db.session.execute(
            self.db.select(RepairTimelineEntry)
            .filter_by(repair_record_id=record.id, entry_type='eta_update')
        ).scalars().all()
        assert len(entries) == 1

    def test_set_eta_no_op_when_value_matches(self):
        """AC 19a / F12: set_eta with matching date → no new timeline entry, ephemeral still posted."""
        from datetime import date
        record = _create_repair_record(
            equipment=self.equipment, status='New', severity='Down',
            description='x', eta=date(2026, 8, 1),
        )
        ack = MagicMock()
        client = self._client(self.tech_user.email)
        view = self._build_view(record.id, action='set_eta', eta='2026-08-01')

        self.handlers['view:repair_action_submission'](
            ack=ack, body=self._body(self.tech_user.email), client=client, view=view,
        )

        ack.assert_called_once_with(response_action='clear')
        from esb.models.repair_timeline_entry import RepairTimelineEntry
        entries = self.db.session.execute(
            self.db.select(RepairTimelineEntry)
            .filter_by(repair_record_id=record.id, entry_type='eta_update')
        ).scalars().all()
        assert len(entries) == 0
        client.chat_postEphemeral.assert_called_once()
        text = client.chat_postEphemeral.call_args.kwargs['text']
        assert ':calendar:' in text
        assert f'Repair #{record.id}' in text

    def test_set_eta_without_date_returns_error(self):
        """AC 20."""
        record = _create_repair_record(
            equipment=self.equipment, status='New', severity='Down', description='x',
        )
        ack = MagicMock()
        client = self._client(self.tech_user.email)
        view = self._build_view(record.id, action='set_eta', eta=None)

        self.handlers['view:repair_action_submission'](
            ack=ack, body=self._body(self.tech_user.email), client=client, view=view,
        )

        kwargs = ack.call_args.kwargs
        assert kwargs.get('response_action') == 'errors'
        assert 'eta_block' in kwargs['errors']

    def test_set_status_updates_status_when_value_differs(self):
        """AC 21: set_status updates status + creates 'status_change' timeline entry."""
        record = _create_repair_record(
            equipment=self.equipment, status='New', severity='Down', description='x',
        )
        ack = MagicMock()
        client = self._client(self.tech_user.email)
        view = self._build_view(record.id, action='set_status', status='In Progress')

        self.handlers['view:repair_action_submission'](
            ack=ack, body=self._body(self.tech_user.email), client=client, view=view,
        )

        ack.assert_called_once_with(response_action='clear')
        from esb.models.repair_record import RepairRecord
        from esb.models.repair_timeline_entry import RepairTimelineEntry
        self.db.session.expire_all()
        rec = self.db.session.get(RepairRecord, record.id)
        assert rec.status == 'In Progress'
        entries = self.db.session.execute(
            self.db.select(RepairTimelineEntry)
            .filter_by(repair_record_id=record.id, entry_type='status_change')
        ).scalars().all()
        assert len(entries) == 1

    def test_set_status_no_op_when_value_matches(self):
        """AC 21a / F12: set_status to current status → no new timeline entry, ephemeral still posted."""
        record = _create_repair_record(
            equipment=self.equipment, status='In Progress', severity='Down', description='x',
        )
        ack = MagicMock()
        client = self._client(self.tech_user.email)
        view = self._build_view(record.id, action='set_status', status='In Progress')

        self.handlers['view:repair_action_submission'](
            ack=ack, body=self._body(self.tech_user.email), client=client, view=view,
        )

        ack.assert_called_once_with(response_action='clear')
        from esb.models.repair_timeline_entry import RepairTimelineEntry
        entries = self.db.session.execute(
            self.db.select(RepairTimelineEntry)
            .filter_by(repair_record_id=record.id, entry_type='status_change')
        ).scalars().all()
        assert len(entries) == 0
        text = client.chat_postEphemeral.call_args.kwargs['text']
        assert ':arrows_counterclockwise:' in text
        assert 'In Progress' in text

    def test_set_status_without_selection_returns_error(self):
        """AC 22."""
        record = _create_repair_record(
            equipment=self.equipment, status='New', severity='Down', description='x',
        )
        ack = MagicMock()
        client = self._client(self.tech_user.email)
        view = self._build_view(record.id, action='set_status', status=None)

        self.handlers['view:repair_action_submission'](
            ack=ack, body=self._body(self.tech_user.email), client=client, view=view,
        )

        kwargs = ack.call_args.kwargs
        assert kwargs.get('response_action') == 'errors'
        assert 'status_block' in kwargs['errors']

    def test_resolve_with_note_sets_resolved_and_adds_note(self):
        """AC 23."""
        record = _create_repair_record(
            equipment=self.equipment, status='In Progress', severity='Down', description='x',
        )
        ack = MagicMock()
        client = self._client(self.tech_user.email)
        view = self._build_view(record.id, action='resolve_with_note', note='Fixed it')

        self.handlers['view:repair_action_submission'](
            ack=ack, body=self._body(self.tech_user.email), client=client, view=view,
        )

        ack.assert_called_once_with(response_action='clear')
        from esb.models.repair_record import RepairRecord
        from esb.models.repair_timeline_entry import RepairTimelineEntry
        self.db.session.expire_all()
        rec = self.db.session.get(RepairRecord, record.id)
        assert rec.status == 'Resolved'
        notes = self.db.session.execute(
            self.db.select(RepairTimelineEntry)
            .filter_by(repair_record_id=record.id, entry_type='note')
        ).scalars().all()
        assert len(notes) == 1
        assert notes[0].content == 'Fixed it'

    def test_resolve_with_note_queues_only_resolved_notification(self):
        """AC 23a: exactly one outbound (event_type='resolved'), not two."""
        from esb.models.pending_notification import PendingNotification

        record = _create_repair_record(
            equipment=self.equipment, status='In Progress', severity='Down', description='x',
        )
        ack = MagicMock()
        client = self._client(self.tech_user.email)
        view = self._build_view(record.id, action='resolve_with_note', note='done')

        self.handlers['view:repair_action_submission'](
            ack=ack, body=self._body(self.tech_user.email), client=client, view=view,
        )

        ack.assert_called_once_with(response_action='clear')
        notifications = self.db.session.execute(
            self.db.select(PendingNotification).filter_by(notification_type='slack_message')
        ).scalars().all()
        event_types = [n.payload['event_type'] for n in notifications]
        assert event_types == ['resolved']

    def test_resolve_without_note_returns_error(self):
        """AC 24: blank note → error."""
        record = _create_repair_record(
            equipment=self.equipment, status='New', severity='Down', description='x',
        )
        ack = MagicMock()
        client = self._client(self.tech_user.email)
        view = self._build_view(record.id, action='resolve_with_note', note='   ')

        self.handlers['view:repair_action_submission'](
            ack=ack, body=self._body(self.tech_user.email), client=client, view=view,
        )

        kwargs = ack.call_args.kwargs
        assert kwargs.get('response_action') == 'errors'
        assert 'note_block' in kwargs['errors']

    def test_closed_record_returns_error(self):
        """AC 24a: closed record between dispatcher select and action submit → error, no DB write."""
        record = _create_repair_record(
            equipment=self.equipment, status='Resolved', severity='Down', description='x',
        )
        ack = MagicMock()
        client = self._client(self.tech_user.email)
        view = self._build_view(record.id, action='claim')

        self.handlers['view:repair_action_submission'](
            ack=ack, body=self._body(self.tech_user.email), client=client, view=view,
        )

        kwargs = ack.call_args.kwargs
        assert kwargs.get('response_action') == 'errors'
        assert 'action_block' in kwargs['errors']

    def test_unauthorized_user_returns_error(self):
        """AC 24c / F30: member-role caller rejected, no DB write."""
        member = _create_user('member', username='memberX')
        record = _create_repair_record(
            equipment=self.equipment, status='New', severity='Down', description='x',
        )
        ack = MagicMock()
        client = self._client(member.email)
        view = self._build_view(record.id, action='claim')

        self.handlers['view:repair_action_submission'](
            ack=ack, body=self._body(member.email), client=client, view=view,
        )

        kwargs = ack.call_args.kwargs
        assert kwargs.get('response_action') == 'errors'

        from esb.models.repair_record import RepairRecord
        self.db.session.expire_all()
        rec = self.db.session.get(RepairRecord, record.id)
        assert rec.assignee_id is None
        client.chat_postEphemeral.assert_not_called()

    def test_posts_ephemeral_confirmation_with_legend_emoji(self):
        """AC 25 / F18 / F35: confirmation emojis match the legend per action."""
        # claim → :arrows_counterclockwise:
        rec1 = _create_repair_record(equipment=self.equipment, status='New', severity='Down', description='x')
        client1 = self._client(self.tech_user.email)
        self.handlers['view:repair_action_submission'](
            ack=MagicMock(), body=self._body(self.tech_user.email), client=client1,
            view=self._build_view(rec1.id, action='claim'),
        )
        assert ':arrows_counterclockwise:' in client1.chat_postEphemeral.call_args.kwargs['text']

        # set_eta → :calendar:
        rec2 = _create_repair_record(equipment=self.equipment, status='New', severity='Down', description='x')
        client2 = self._client(self.tech_user.email)
        self.handlers['view:repair_action_submission'](
            ack=MagicMock(), body=self._body(self.tech_user.email), client=client2,
            view=self._build_view(rec2.id, action='set_eta', eta='2026-09-01'),
        )
        assert ':calendar:' in client2.chat_postEphemeral.call_args.kwargs['text']

        # set_status to non-closed → :arrows_counterclockwise:
        rec3 = _create_repair_record(equipment=self.equipment, status='New', severity='Down', description='x')
        client3 = self._client(self.tech_user.email)
        self.handlers['view:repair_action_submission'](
            ack=MagicMock(), body=self._body(self.tech_user.email), client=client3,
            view=self._build_view(rec3.id, action='set_status', status='In Progress'),
        )
        assert ':arrows_counterclockwise:' in client3.chat_postEphemeral.call_args.kwargs['text']

        # set_status to a Closed-* → :white_check_mark: (F35)
        rec4 = _create_repair_record(equipment=self.equipment, status='New', severity='Down', description='x')
        client4 = self._client(self.tech_user.email)
        self.handlers['view:repair_action_submission'](
            ack=MagicMock(), body=self._body(self.tech_user.email), client=client4,
            view=self._build_view(rec4.id, action='set_status', status='Closed - No Issue Found'),
        )
        text4 = client4.chat_postEphemeral.call_args.kwargs['text']
        assert ':white_check_mark:' in text4
        assert 'closed: Closed - No Issue Found' in text4

        # resolve_with_note → :white_check_mark:
        rec5 = _create_repair_record(equipment=self.equipment, status='In Progress', severity='Down', description='x')
        client5 = self._client(self.tech_user.email)
        self.handlers['view:repair_action_submission'](
            ack=MagicMock(), body=self._body(self.tech_user.email), client=client5,
            view=self._build_view(rec5.id, action='resolve_with_note', note='done'),
        )
        assert ':white_check_mark:' in client5.chat_postEphemeral.call_args.kwargs['text']

    def test_set_status_closed_duplicate_with_target_succeeds(self):
        """AC-22: set_status to Closed - Duplicate with a valid target updates record + acks."""
        target = _create_repair_record(
            equipment=self.equipment, status='In Progress', severity='Down', description='target',
        )
        record = _create_repair_record(
            equipment=self.equipment, status='In Progress', severity='Down', description='dup',
        )
        ack = MagicMock()
        client = self._client(self.tech_user.email)
        view = self._build_view(
            record.id, action='set_status', status='Closed - Duplicate',
            duplicate_id=target.id,
        )
        self.handlers['view:repair_action_submission'](
            ack=ack, body=self._body(self.tech_user.email), client=client, view=view,
        )
        ack.assert_called_once_with(response_action='clear')

        from esb.models.repair_record import RepairRecord
        self.db.session.expire_all()
        rec = self.db.session.get(RepairRecord, record.id)
        assert rec.status == 'Closed - Duplicate'
        assert rec.duplicated_repair_id == target.id
        client.chat_postEphemeral.assert_called_once()
        text = client.chat_postEphemeral.call_args.kwargs['text']
        assert f'Repair #{record.id}' in text
        assert 'Closed - Duplicate' in text

    def test_set_status_closed_duplicate_without_target_returns_inline_error(self):
        """AC-23: missing duplicate selection → ack errors and no update."""
        target = _create_repair_record(
            equipment=self.equipment, status='In Progress', severity='Down', description='target',
        )
        record = _create_repair_record(
            equipment=self.equipment, status='In Progress', severity='Down', description='dup',
        )
        ack = MagicMock()
        client = self._client(self.tech_user.email)
        # include_duplicate_block True but no duplicate_id => selected_option None
        view = self._build_view(
            record.id, action='set_status', status='Closed - Duplicate',
            include_duplicate_block=True,
        )
        self.handlers['view:repair_action_submission'](
            ack=ack, body=self._body(self.tech_user.email), client=client, view=view,
        )
        ack.assert_called_once()
        kwargs = ack.call_args.kwargs
        assert kwargs.get('response_action') == 'errors'
        assert 'duplicate_block' in kwargs.get('errors', {})

        from esb.models.repair_record import RepairRecord
        self.db.session.expire_all()
        rec = self.db.session.get(RepairRecord, record.id)
        assert rec.status == 'In Progress'  # unchanged
        # target untouched too
        assert self.db.session.get(RepairRecord, target.id).status == 'In Progress'

    def test_set_status_closed_duplicate_stale_target_surfaces_validation_error(self):
        """AC-24: target deleted between modal build and submit → ValidationError surfaces on action_block."""
        target = _create_repair_record(
            equipment=self.equipment, status='In Progress', severity='Down', description='target',
        )
        record = _create_repair_record(
            equipment=self.equipment, status='In Progress', severity='Down', description='dup',
        )
        target_id = target.id

        # Simulate target deletion between modal-build and submit.
        self.db.session.delete(target)
        self.db.session.commit()

        ack = MagicMock()
        client = self._client(self.tech_user.email)
        view = self._build_view(
            record.id, action='set_status', status='Closed - Duplicate',
            duplicate_id=target_id,
        )
        self.handlers['view:repair_action_submission'](
            ack=ack, body=self._body(self.tech_user.email), client=client, view=view,
        )
        ack.assert_called_once()
        kwargs = ack.call_args.kwargs
        assert kwargs.get('response_action') == 'errors'
        assert 'action_block' in kwargs.get('errors', {})
        assert f'Duplicated repair {target_id} not found' in kwargs['errors']['action_block']

        from esb.models.repair_record import RepairRecord
        self.db.session.expire_all()
        rec = self.db.session.get(RepairRecord, record.id)
        assert rec.status == 'In Progress'  # unchanged
        assert rec.duplicated_repair_id is None
        # No ephemeral message was posted
        client.chat_postEphemeral.assert_not_called()

class TestEsbReportRegression:
    """AC 30 / F13: /esb-report stays distinct from /esb-repair after the dispatcher refactor."""

    @pytest.fixture(autouse=True)
    def setup(self, app, db):
        self.app = app
        self.db = db
        self.area = _create_area(name='Woodshop', slack_channel='#woodshop')
        self.equipment = _create_equipment(name='SawStop', area=self.area)
        self.handlers = _register_and_capture(app)

    def test_report_command_unchanged_after_dispatcher(self):
        """/esb-report still opens the problem_report_submission modal -- not the dispatcher."""
        ack = MagicMock()
        client = MagicMock()
        body = {'trigger_id': 'T', 'user_id': 'U', 'channel_id': 'C'}

        self.handlers['command:/esb-report'](ack=ack, body=body, client=client)

        client.views_open.assert_called_once()
        modal = client.views_open.call_args.kwargs['view']
        assert modal['callback_id'] == 'problem_report_submission'


class TestHandlersWithFlaskAppContext:
    """5.14: Test all handlers work within Flask app context."""

    @pytest.fixture(autouse=True)
    def setup(self, app, db):
        self.app = app
        self.db = db
        self.area = _create_area(name='Woodshop', slack_channel='#woodshop')
        self.equipment = _create_equipment(name='SawStop', area=self.area)
        self.staff_user = _create_user('staff', username='admin1')
        self.handlers = _register_and_capture(app)

    def test_report_handler_in_app_context(self):
        """Command handler works within Flask app context."""
        ack = MagicMock()
        client = MagicMock()
        body = {'trigger_id': 'T123', 'user_id': 'U123', 'channel_id': 'C123'}

        # Should not raise any context errors
        self.handlers['command:/esb-report'](ack=ack, body=body, client=client)
        ack.assert_called_once()

    def test_view_handler_in_app_context(self):
        """View submission handler works within Flask app context."""
        ack = MagicMock()
        client = MagicMock()
        view = {
            'state': {
                'values': {
                    'equipment_block': {'equipment_select': {'selected_option': {'value': str(self.equipment.id)}}},
                    'name_block': {'reporter_name': {'value': 'Test User'}},
                    'description_block': {'description': {'value': 'Test problem'}},
                    'severity_block': {'severity': {'selected_option': {'value': 'Not Sure'}}},
                    'safety_risk_block': {'safety_risk': {'selected_options': []}},
                    'consumable_block': {'consumable': {'selected_options': []}},
                },
            },
        }
        body = {'user': {'id': 'U123', 'username': 'testuser'}}

        # Should not raise any context errors
        self.handlers['view:problem_report_submission'](ack=ack, body=body, client=client, view=view)
        ack.assert_called_once_with()


class TestHandlersOutsideAppContext:
    """Regression tests for issue #15: handlers must work outside Flask app context."""

    def test_command_handler_works_outside_app_context(self):
        """Handler pushes its own app context when none exists (reproduces #15)."""
        from esb import create_app
        app = create_app('testing')
        # Setup: create test data inside a temporary context
        with app.app_context():
            from esb.extensions import db
            db.create_all()
            area = _create_area(name='Woodshop', slack_channel='#woodshop')
            _create_equipment(name='SawStop', area=area)
        # Now OUTSIDE any app context — simulates Socket Mode thread
        handlers = _register_and_capture(app)
        ack = MagicMock()
        client = MagicMock()
        body = {'trigger_id': 'T1', 'user_id': 'U1', 'channel_id': 'C1', 'text': ''}
        # This would raise RuntimeError before the fix
        handlers['command:/esb-status'](ack=ack, body=body, client=client, respond=MagicMock())
        ack.assert_called_once()
        view = client.views_open.call_args.kwargs['view']
        # Check for specific data to make failures diagnostic
        section_texts = [
            b['text']['text']
            for b in view['blocks']
            if isinstance(b.get('text'), dict) and 'text' in b['text']
        ]
        assert any('Woodshop' in t for t in section_texts)
        # Teardown
        with app.app_context():
            db.drop_all()

    def test_view_handler_works_outside_app_context(self):
        """View submission handler pushes its own app context (reproduces #15)."""
        from esb import create_app
        app = create_app('testing')
        with app.app_context():
            from esb.extensions import db
            db.create_all()
            area = _create_area(name='Woodshop', slack_channel='#woodshop')
            equipment = _create_equipment(name='SawStop', area=area)
            equipment_id = equipment.id
        # Outside any app context
        handlers = _register_and_capture(app)
        ack = MagicMock()
        client = MagicMock()
        view = {
            'state': {
                'values': {
                    'equipment_block': {'equipment_select': {'selected_option': {'value': str(equipment_id)}}},
                    'name_block': {'reporter_name': {'value': 'Test User'}},
                    'description_block': {'description': {'value': 'Machine is broken'}},
                    'severity_block': {'severity': {'selected_option': {'value': 'Down'}}},
                    'safety_risk_block': {'safety_risk': {'selected_options': []}},
                    'consumable_block': {'consumable': {'selected_options': []}},
                },
            },
        }
        body = {'user': {'id': 'U123', 'username': 'testuser'}}
        handlers['view:problem_report_submission'](ack=ack, body=body, client=client, view=view)
        ack.assert_called_once_with()
        # Verify repair record created by querying inside a fresh context
        with app.app_context():
            from esb.models.repair_record import RepairRecord
            records = RepairRecord.query.all()
            assert len(records) == 1
            assert records[0].description == 'Machine is broken'
            assert records[0].reporter_name == 'Test User'
            # Teardown
            from esb.extensions import db
            db.drop_all()

    def test_ensure_app_context_pushes_when_needed(self):
        from esb import create_app
        from esb.slack.handlers import _ensure_app_context
        from flask import has_app_context
        app = create_app('testing')
        assert not has_app_context()
        with _ensure_app_context(app):
            assert has_app_context()
        assert not has_app_context()

    def test_ensure_app_context_noop_when_context_exists(self):
        from contextlib import nullcontext
        from esb import create_app
        from esb.slack.handlers import _ensure_app_context
        app = create_app('testing')
        with app.app_context():
            ctx_mgr = _ensure_app_context(app)
            assert isinstance(ctx_mgr, nullcontext)
