"""Tests for Slack command and view submission handlers (esb/slack/handlers.py)."""

from unittest.mock import MagicMock

import pytest

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

    bolt_app = MagicMock()
    bolt_app.command = capture_command
    bolt_app.view = capture_view
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


class TestEsbUpdateCommand:
    """Tests for /esb-update command handler."""

    @pytest.fixture(autouse=True)
    def setup(self, app, db):
        self.app = app
        self.db = db
        self.area = _create_area(name='Woodshop', slack_channel='#woodshop')
        self.equipment = _create_equipment(name='SawStop', area=self.area)
        self.staff_user = _create_user('staff', username='admin1')
        self.record = _create_repair_record(
            equipment=self.equipment, status='In Progress', description='Blade issue',
        )
        self.handlers = _register_and_capture(app)

    def test_parses_repair_id_and_opens_modal(self):
        """5.7: /esb-update 42 parses repair ID and opens pre-populated modal."""
        ack = MagicMock()
        client = MagicMock()
        client.users_info.return_value = {
            'user': {'profile': {'email': self.staff_user.email}},
        }
        body = {
            'trigger_id': 'T123',
            'user_id': 'U123',
            'channel_id': 'C123',
            'text': str(self.record.id),
        }

        self.handlers['command:/esb-update'](ack=ack, body=body, client=client)

        ack.assert_called_once()
        client.views_open.assert_called_once()
        modal = client.views_open.call_args.kwargs['view']
        assert modal['callback_id'] == 'repair_update_submission'
        assert modal['private_metadata'] == str(self.record.id)

    def test_modal_status_options_include_closed_duplicate_when_record_is_already(self):
        """If the record's current status is already Closed - Duplicate, the
        option must remain so Slack does not reject the modal (initial_option
        must exist in options).
        """
        # Need a second repair to satisfy the service-layer validation for the
        # existing Closed - Duplicate record. Then create one with that status.
        target = _create_repair_record(
            equipment=self.equipment, status='In Progress', description='target',
        )
        from esb.models.repair_record import RepairRecord
        dup_record = RepairRecord(
            equipment_id=self.equipment.id,
            description='already closed as dup',
            status='Closed - Duplicate',
            duplicated_repair_id=target.id,
        )
        self.db.session.add(dup_record)
        self.db.session.commit()

        ack = MagicMock()
        client = MagicMock()
        client.users_info.return_value = {
            'user': {'profile': {'email': self.staff_user.email}},
        }
        body = {
            'trigger_id': 'T123', 'user_id': 'U123', 'channel_id': 'C123',
            'text': str(dup_record.id),
        }

        self.handlers['command:/esb-update'](ack=ack, body=body, client=client)

        modal = client.views_open.call_args.kwargs['view']
        status_block = next(b for b in modal['blocks'] if b.get('block_id') == 'status_block')
        values = [o['value'] for o in status_block['element']['options']]
        assert 'Closed - Duplicate' in values
        # initial_option set to the record's current status -- must also be in options.
        assert status_block['element']['initial_option']['value'] == 'Closed - Duplicate'

    def test_modal_status_options_exclude_closed_duplicate(self):
        """Closed - Duplicate filtered from /esb-update modal: the update flow
        does not collect a dup target, so setting that status here would always
        trip the service-layer validation."""
        ack = MagicMock()
        client = MagicMock()
        client.users_info.return_value = {
            'user': {'profile': {'email': self.staff_user.email}},
        }
        body = {
            'trigger_id': 'T123',
            'user_id': 'U123',
            'channel_id': 'C123',
            'text': str(self.record.id),
        }

        self.handlers['command:/esb-update'](ack=ack, body=body, client=client)

        modal = client.views_open.call_args.kwargs['view']
        status_block = next(b for b in modal['blocks'] if b.get('block_id') == 'status_block')
        values = [o['value'] for o in status_block['element']['options']]
        assert 'Closed - Duplicate' not in values

    def test_without_id_returns_error(self):
        """5.8: /esb-update without ID returns error message."""
        ack = MagicMock()
        client = MagicMock()
        client.users_info.return_value = {
            'user': {'profile': {'email': self.staff_user.email}},
        }
        body = {'trigger_id': 'T123', 'user_id': 'U123', 'channel_id': 'C123', 'text': ''}

        self.handlers['command:/esb-update'](ack=ack, body=body, client=client)

        client.chat_postEphemeral.assert_called_once()
        assert 'Usage' in client.chat_postEphemeral.call_args.kwargs['text']

    def test_nonexistent_id_returns_error(self):
        """5.9: /esb-update 999 with non-existent ID returns error."""
        ack = MagicMock()
        client = MagicMock()
        client.users_info.return_value = {
            'user': {'profile': {'email': self.staff_user.email}},
        }
        body = {'trigger_id': 'T123', 'user_id': 'U123', 'channel_id': 'C123', 'text': '99999'}

        self.handlers['command:/esb-update'](ack=ack, body=body, client=client)

        client.chat_postEphemeral.assert_called_once()
        assert 'not found' in client.chat_postEphemeral.call_args.kwargs['text']
        client.views_open.assert_not_called()

    def test_invalid_id_format_returns_error(self):
        """M2: /esb-update with non-numeric ID returns error."""
        ack = MagicMock()
        client = MagicMock()
        client.users_info.return_value = {
            'user': {'profile': {'email': self.staff_user.email}},
        }
        body = {'trigger_id': 'T123', 'user_id': 'U123', 'channel_id': 'C123', 'text': 'abc'}

        self.handlers['command:/esb-update'](ack=ack, body=body, client=client)

        client.chat_postEphemeral.assert_called_once()
        assert 'Invalid repair ID' in client.chat_postEphemeral.call_args.kwargs['text']
        client.views_open.assert_not_called()

    def test_rejects_unauthorized_user(self):
        """Unauthorized user rejected from /esb-update."""
        ack = MagicMock()
        client = MagicMock()
        client.users_info.return_value = {
            'user': {'profile': {'email': 'nobody@test.com'}},
        }
        body = {'trigger_id': 'T123', 'user_id': 'U999', 'channel_id': 'C123', 'text': '1'}

        self.handlers['command:/esb-update'](ack=ack, body=body, client=client)

        client.chat_postEphemeral.assert_called_once()
        assert 'Technician or Staff' in client.chat_postEphemeral.call_args.kwargs['text']
        client.views_open.assert_not_called()


class TestRepairUpdateSubmission:
    """Tests for repair_update_submission view handler."""

    @pytest.fixture(autouse=True)
    def setup(self, app, db):
        self.app = app
        self.db = db
        self.area = _create_area(name='Woodshop', slack_channel='#woodshop')
        self.equipment = _create_equipment(name='SawStop', area=self.area)
        self.staff_user = _create_user('staff', username='admin1')
        self.record = _create_repair_record(
            equipment=self.equipment, status='New', description='Blade issue',
        )
        self.handlers = _register_and_capture(app)

    def _build_view(self, repair_record_id=None, status='In Progress',
                    severity=None, assignee_id=None, eta=None,
                    specialist_description=None, note=None):
        repair_record_id = repair_record_id or self.record.id
        severity_opt = {'selected_option': {'value': severity}} if severity else {'selected_option': None}
        assignee_opt = {'selected_option': {'value': str(assignee_id)}} if assignee_id else {'selected_option': None}
        return {
            'private_metadata': str(repair_record_id),
            'state': {
                'values': {
                    'status_block': {'status': {'selected_option': {'value': status}}},
                    'severity_block': {'severity': severity_opt},
                    'assignee_block': {'assignee': assignee_opt},
                    'eta_block': {'eta': {'selected_date': eta}},
                    'specialist_block': {'specialist_description': {'value': specialist_description}},
                    'note_block': {'note': {'value': note}},
                },
            },
        }

    def test_updates_repair_record(self):
        """5.10: Repair update submission calls update_repair_record() with correct changes."""
        ack = MagicMock()
        client = MagicMock()
        client.users_info.return_value = {
            'user': {'profile': {'email': self.staff_user.email}},
        }
        view = self._build_view(status='In Progress', severity='Down')
        body = {'user': {'id': 'U123', 'username': 'slackuser'}}

        self.handlers['view:repair_update_submission'](ack=ack, body=body, client=client, view=view)

        ack.assert_called_once_with()

        from esb.extensions import db as _db
        from esb.models.repair_record import RepairRecord
        record = _db.session.get(RepairRecord, self.record.id)
        assert record.status == 'In Progress'
        assert record.severity == 'Down'

    def test_posts_ephemeral_confirmation(self):
        """Update submission posts ephemeral confirmation."""
        ack = MagicMock()
        client = MagicMock()
        client.users_info.return_value = {
            'user': {'profile': {'email': self.staff_user.email}},
        }
        view = self._build_view(status='In Progress')
        body = {'user': {'id': 'U123', 'username': 'slackuser'}}

        self.handlers['view:repair_update_submission'](ack=ack, body=body, client=client, view=view)

        client.chat_postEphemeral.assert_called_once()
        msg = client.chat_postEphemeral.call_args.kwargs['text']
        assert f'Repair record #{self.record.id} updated' in msg

    def test_update_with_note(self):
        """Update with a note adds timeline entry."""
        ack = MagicMock()
        client = MagicMock()
        client.users_info.return_value = {
            'user': {'profile': {'email': self.staff_user.email}},
        }
        view = self._build_view(note='Fixed the blade')
        body = {'user': {'id': 'U123', 'username': 'slackuser'}}

        self.handlers['view:repair_update_submission'](ack=ack, body=body, client=client, view=view)

        ack.assert_called_once_with()

        from esb.models.repair_timeline_entry import RepairTimelineEntry
        notes = RepairTimelineEntry.query.filter_by(
            repair_record_id=self.record.id, entry_type='note',
        ).all()
        assert len(notes) == 1
        assert notes[0].content == 'Fixed the blade'


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


class TestEsbStatusCommand:
    """Tests for /esb-status command handler."""

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

    def test_no_args_shows_summary(self):
        """/esb-status with no args shows area summary."""
        ack = MagicMock()
        client = MagicMock()
        body = {
            'trigger_id': 'T123',
            'user_id': 'U123',
            'channel_id': 'C123',
            'text': '',
        }

        self.handlers['command:/esb-status'](ack=ack, body=body, client=client)

        ack.assert_called_once()
        client.chat_postEphemeral.assert_called_once()
        response_text = client.chat_postEphemeral.call_args.kwargs['text']
        assert 'Equipment Status Summary' in response_text

    def test_exact_match_shows_detail(self):
        """Single match shows equipment detail."""
        ack = MagicMock()
        client = MagicMock()
        body = {
            'trigger_id': 'T123',
            'user_id': 'U123',
            'channel_id': 'C123',
            'text': 'SawStop',
        }

        self.handlers['command:/esb-status'](ack=ack, body=body, client=client)

        ack.assert_called_once()
        client.chat_postEphemeral.assert_called_once()
        response_text = client.chat_postEphemeral.call_args.kwargs['text']
        assert 'SawStop' in response_text
        assert 'Operational' in response_text

    def test_no_match_shows_error(self):
        """Posts 'Equipment not found' for no matches."""
        ack = MagicMock()
        client = MagicMock()
        body = {
            'trigger_id': 'T123',
            'user_id': 'U123',
            'channel_id': 'C123',
            'text': 'NonexistentThing',
        }

        self.handlers['command:/esb-status'](ack=ack, body=body, client=client)

        ack.assert_called_once()
        client.chat_postEphemeral.assert_called_once()
        response_text = client.chat_postEphemeral.call_args.kwargs['text']
        assert 'Equipment not found' in response_text

    def test_multiple_matches_shows_list(self):
        """Posts disambiguation list for multiple matches."""
        _create_equipment(name='Band Saw', area=self.area)

        ack = MagicMock()
        client = MagicMock()
        body = {
            'trigger_id': 'T123',
            'user_id': 'U123',
            'channel_id': 'C123',
            'text': 'Saw',
        }

        self.handlers['command:/esb-status'](ack=ack, body=body, client=client)

        ack.assert_called_once()
        client.chat_postEphemeral.assert_called_once()
        response_text = client.chat_postEphemeral.call_args.kwargs['text']
        assert 'Multiple equipment items match' in response_text
        assert 'Band Saw' in response_text
        assert 'SawStop' in response_text

    def test_partial_match_single(self):
        """Partial name with one match shows detail."""
        ack = MagicMock()
        client = MagicMock()
        body = {
            'trigger_id': 'T123',
            'user_id': 'U123',
            'channel_id': 'C123',
            'text': 'Stop',
        }

        self.handlers['command:/esb-status'](ack=ack, body=body, client=client)

        ack.assert_called_once()
        client.chat_postEphemeral.assert_called_once()
        response_text = client.chat_postEphemeral.call_args.kwargs['text']
        assert 'SawStop' in response_text

    def test_ack_called_before_response(self):
        """ack() is called before chat_postEphemeral."""
        call_order = []
        ack = MagicMock(side_effect=lambda: call_order.append('ack'))
        client = MagicMock()
        client.chat_postEphemeral = MagicMock(
            side_effect=lambda **kwargs: call_order.append('chat_postEphemeral'),
        )
        body = {
            'trigger_id': 'T123',
            'user_id': 'U123',
            'channel_id': 'C123',
            'text': '',
        }

        self.handlers['command:/esb-status'](ack=ack, body=body, client=client)

        assert call_order[0] == 'ack'
        assert 'chat_postEphemeral' in call_order

    def test_service_error_returns_ephemeral_error(self):
        """Service exception returns friendly error message."""
        from unittest.mock import patch

        ack = MagicMock()
        client = MagicMock()
        body = {
            'trigger_id': 'T123',
            'user_id': 'U123',
            'channel_id': 'C123',
            'text': 'SawStop',
        }

        with patch(
            'esb.services.equipment_service.search_equipment_by_name',
            side_effect=Exception('DB error'),
        ):
            self.handlers['command:/esb-status'](ack=ack, body=body, client=client)

        ack.assert_called_once()
        client.chat_postEphemeral.assert_called_once()
        response_text = client.chat_postEphemeral.call_args.kwargs['text']
        assert 'error occurred' in response_text.lower()

    def test_empty_dashboard(self):
        """No equipment returns appropriate message."""
        from esb.models.equipment import Equipment
        Equipment.query.delete()
        self.db.session.commit()

        ack = MagicMock()
        client = MagicMock()
        body = {
            'trigger_id': 'T123',
            'user_id': 'U123',
            'channel_id': 'C123',
            'text': '',
        }

        self.handlers['command:/esb-status'](ack=ack, body=body, client=client)

        ack.assert_called_once()
        client.chat_postEphemeral.assert_called_once()
        response_text = client.chat_postEphemeral.call_args.kwargs['text']
        assert 'No equipment' in response_text

    def test_area_name_match_shows_area_detail(self):
        """AC 9: exact case-insensitive area name shows the area-detail view."""
        ack = MagicMock()
        client = MagicMock()
        body = {'trigger_id': 'T', 'user_id': 'U', 'channel_id': 'C', 'text': 'woodshop'}

        self.handlers['command:/esb-status'](ack=ack, body=body, client=client)

        response_text = client.chat_postEphemeral.call_args.kwargs['text']
        # Area-detail formatter starts with :bar_chart: *<area>*
        assert ':bar_chart:' in response_text
        assert '*Woodshop*' in response_text

    def test_area_name_takes_precedence_over_equipment(self):
        """AC 10: when an area and equipment share a substring, area wins by exact-name match."""
        # The setup creates area 'Woodshop' and equipment 'SawStop'. Create an
        # equipment whose name CONTAINS 'Woodshop' to force the precedence test.
        _create_equipment(name='Woodshop Helper', area=self.area)

        ack = MagicMock()
        client = MagicMock()
        body = {'trigger_id': 'T', 'user_id': 'U', 'channel_id': 'C', 'text': 'Woodshop'}

        self.handlers['command:/esb-status'](ack=ack, body=body, client=client)

        response_text = client.chat_postEphemeral.call_args.kwargs['text']
        # Area-detail header is rendered (not the multi-match list).
        assert ':bar_chart:' in response_text
        assert 'Multiple equipment items match' not in response_text

    def test_no_area_match_falls_back_to_equipment_search(self):
        """AC 11: a non-matching area name falls through to equipment search."""
        ack = MagicMock()
        client = MagicMock()
        body = {'trigger_id': 'T', 'user_id': 'U', 'channel_id': 'C', 'text': 'SawStop'}

        self.handlers['command:/esb-status'](ack=ack, body=body, client=client)

        response_text = client.chat_postEphemeral.call_args.kwargs['text']
        # Existing single-equipment detail formatter is used.
        assert 'SawStop' in response_text
        assert 'Operational' in response_text


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
        handlers['command:/esb-status'](ack=ack, body=body, client=client)
        ack.assert_called_once()
        response_text = client.chat_postEphemeral.call_args.kwargs['text']
        # Check for specific data to make failures diagnostic
        assert 'Woodshop' in response_text
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
