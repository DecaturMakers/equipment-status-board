"""Slack command and view submission handlers."""

import logging
from contextlib import nullcontext

from flask import has_app_context

logger = logging.getLogger(__name__)


def _ensure_app_context(app):
    """Return app context manager if not already in one, else a no-op context.

    Slack Bolt dispatches handlers in Socket Mode threads without Flask app
    context. This helper ensures DB operations work in both production (no
    existing context) and tests (context provided by fixture).

    IMPORTANT: All handlers registered in register_handlers() that access
    DB/services must wrap their body in: with _ensure_app_context(app):

    Note: _resolve_esb_user() and forms.py functions do NOT call this
    themselves — they rely on being called from within an already-wrapped
    handler. If you add a new caller of these functions, wrap it.
    """
    if has_app_context():
        return nullcontext()
    return app.app_context()


def _resolve_esb_user(client, slack_user_id):
    """Map a Slack user ID to an ESB User account.

    Strategy:
    1. Call Slack API to get user's email from their profile
    2. Look up ESB User by matching email

    Args:
        client: Slack WebClient instance (provided by Bolt).
        slack_user_id: Slack user ID (e.g., 'U12345678').

    Returns:
        User instance or None if no matching ESB account.

    Note: Must be called from within a Flask app context (provided by the
    calling handler's _ensure_app_context wrapper).
    """
    from esb.extensions import db
    from esb.models.user import User

    try:
        result = client.users_info(user=slack_user_id)
        email = result['user']['profile'].get('email')
        if not email:
            return None
        return db.session.execute(
            db.select(User).filter_by(email=email, is_active=True)
        ).scalars().first()
    except Exception:
        logger.warning('Failed to resolve ESB user for Slack user %s', slack_user_id, exc_info=True)
        return None


# IMPORTANT: All handlers that access DB/services must wrap their body in
# with _ensure_app_context(app): — see _ensure_app_context docstring.
def register_handlers(bolt_app, app):
    """Register all Slack command and view submission handlers."""

    @bolt_app.command('/esb-report')
    def handle_esb_report(ack, body, client):
        ack()
        with _ensure_app_context(app):
            from esb.slack.forms import build_equipment_options, build_problem_report_modal

            options = build_equipment_options()
            if not options:
                client.chat_postEphemeral(
                    channel=body['channel_id'],
                    user=body['user_id'],
                    text=':x: No equipment available for reporting.',
                )
                return

            client.views_open(
                trigger_id=body['trigger_id'],
                view=build_problem_report_modal(options),
            )

    @bolt_app.view('problem_report_submission')
    def handle_problem_report_submission(ack, body, client, view):
        with _ensure_app_context(app):
            values = view['state']['values']

            equipment_id = int(values['equipment_block']['equipment_select']['selected_option']['value'])
            reporter_name = values['name_block']['reporter_name']['value']
            description = values['description_block']['description']['value']

            severity_data = values['severity_block']['severity'].get('selected_option')
            severity = severity_data['value'] if severity_data else 'Not Sure'

            safety_options = values['safety_risk_block']['safety_risk'].get('selected_options', [])
            has_safety_risk = any(o['value'] == 'safety_risk' for o in safety_options)

            consumable_options = values['consumable_block']['consumable'].get('selected_options', [])
            is_consumable = any(o['value'] == 'consumable' for o in consumable_options)

            from esb.utils.exceptions import ValidationError

            try:
                from esb.services import repair_service

                record = repair_service.create_repair_record(
                    equipment_id=equipment_id,
                    description=description,
                    created_by=body['user']['username'],
                    severity=severity,
                    reporter_name=reporter_name,
                    has_safety_risk=has_safety_risk,
                    is_consumable=is_consumable,
                )
            except ValidationError as e:
                ack(response_action='errors', errors={
                    'description_block': str(e),
                })
                return
            except Exception:
                logger.exception('Unexpected error in problem report submission')
                ack(response_action='errors', errors={
                    'description_block': 'An unexpected error occurred. Please try again.',
                })
                return

            ack()

            from esb.extensions import db
            from esb.models.equipment import Equipment
            equipment = db.session.get(Equipment, equipment_id)
            equipment_name = equipment.name if equipment else f'ID {equipment_id}'

            client.chat_postEphemeral(
                channel=body['user']['id'],
                user=body['user']['id'],
                text=f':white_check_mark: Problem report submitted for *{equipment_name}* (Repair #{record.id})',
            )

    @bolt_app.command('/esb-repair')
    def handle_esb_repair(ack, body, client):
        ack()
        with _ensure_app_context(app):
            esb_user = _resolve_esb_user(client, body['user_id'])
            if esb_user is None or esb_user.role not in ('technician', 'staff'):
                client.chat_postEphemeral(
                    channel=body['channel_id'],
                    user=body['user_id'],
                    text=':x: You must have a Technician or Staff account linked to use this command.',
                )
                return

            text_arg = body.get('text', '').strip()

            if not text_arg:
                from esb.services import repair_service
                from esb.slack.forms import build_repair_dispatcher_modal

                open_records = repair_service.get_repair_queue()
                if not open_records:
                    client.chat_postEphemeral(
                        channel=body['channel_id'],
                        user=body['user_id'],
                        text=':wrench: No open repairs.',
                    )
                    return
                client.views_open(
                    trigger_id=body['trigger_id'],
                    view=build_repair_dispatcher_modal(open_records),
                )
                return

            from esb.services import equipment_service
            from esb.slack.forms import build_equipment_options, build_repair_create_modal, build_user_options

            equipment_options = build_equipment_options()
            if not equipment_options:
                client.chat_postEphemeral(
                    channel=body['channel_id'],
                    user=body['user_id'],
                    text=':x: No equipment available.',
                )
                return

            # Preselect equipment only on a case-insensitive exact name match.
            # search_equipment_by_name() uses an ilike '%term%' partial match,
            # so "saw" would otherwise preselect "SawStop" -- post-filter to
            # the exact-name case so the prefill matches the spec/docs.
            preselected_id = None
            matches = equipment_service.search_equipment_by_name(text_arg)
            exact_matches = [m for m in matches if m.name.lower() == text_arg.lower()]
            if len(exact_matches) == 1:
                preselected_id = exact_matches[0].id

            user_options = build_user_options()
            client.views_open(
                trigger_id=body['trigger_id'],
                view=build_repair_create_modal(
                    equipment_options, user_options,
                    preselected_equipment_id=preselected_id,
                ),
            )

    @bolt_app.view('repair_create_submission')
    def handle_repair_create_submission(ack, body, client, view):
        with _ensure_app_context(app):
            values = view['state']['values']

            equipment_id = int(values['equipment_block']['equipment_select']['selected_option']['value'])
            description = values['description_block']['description']['value']

            severity_data = values['severity_block']['severity'].get('selected_option')
            severity = severity_data['value'] if severity_data else None

            assignee_block = values.get('assignee_block')
            assignee_data = assignee_block['assignee'].get('selected_option') if assignee_block else None
            assignee_id = int(assignee_data['value']) if assignee_data else None

            status_data = values['status_block']['status'].get('selected_option')
            status = status_data['value'] if status_data else 'New'

            # Resolve the Slack user to get author_id
            esb_user = _resolve_esb_user(client, body['user']['id'])

            from esb.utils.exceptions import ValidationError

            try:
                from esb.services import repair_service

                record = repair_service.create_repair_record(
                    equipment_id=equipment_id,
                    description=description,
                    created_by=esb_user.username if esb_user else body['user']['username'],
                    severity=severity,
                    assignee_id=assignee_id,
                    author_id=esb_user.id if esb_user else None,
                )

                # Note: Setting non-"New" status requires a second service call, which
                # may generate a duplicate notification. This is a known limitation of
                # the service layer not accepting status on creation.
                if status != 'New':
                    repair_service.update_repair_record(
                        repair_record_id=record.id,
                        updated_by=esb_user.username if esb_user else body['user']['username'],
                        author_id=esb_user.id if esb_user else None,
                        status=status,
                    )
            except ValidationError as e:
                ack(response_action='errors', errors={
                    'description_block': str(e),
                })
                return
            except Exception:
                logger.exception('Unexpected error in repair creation submission')
                ack(response_action='errors', errors={
                    'description_block': 'An unexpected error occurred. Please try again.',
                })
                return

            ack()

            from esb.extensions import db
            from esb.models.equipment import Equipment
            equipment = db.session.get(Equipment, equipment_id)
            equipment_name = equipment.name if equipment else f'ID {equipment_id}'

            client.chat_postEphemeral(
                channel=body['user']['id'],
                user=body['user']['id'],
                text=f':white_check_mark: Repair record #{record.id} created for *{equipment_name}*',
            )

    @bolt_app.command('/esb-status')
    def handle_esb_status(ack, body, client):
        ack()
        search_term = body.get('text', '').strip()

        with _ensure_app_context(app):
            try:
                if not search_term:
                    from esb.services import status_service
                    dashboard = status_service.get_area_status_dashboard()
                    from esb.slack.forms import format_status_summary
                    text = format_status_summary(dashboard)
                else:
                    from esb.services import equipment_service, status_service

                    area = equipment_service.get_area_by_name(search_term)
                    if area is not None:
                        from esb.slack.forms import format_area_status_detail
                        area_data = status_service.get_single_area_status_dashboard(area.id)
                        text = format_area_status_detail(area_data)
                    else:
                        matches = equipment_service.search_equipment_by_name(search_term)
                        if len(matches) == 0:
                            text = (
                                f':mag: Equipment not found: "{search_term}"\n'
                                'Check the spelling or use the full equipment name. '
                                'Try `/esb-status` with no arguments to see all equipment.'
                            )
                        elif len(matches) == 1:
                            detail = status_service.get_equipment_status_detail(matches[0].id)
                            from esb.slack.forms import format_equipment_status_detail
                            text = format_equipment_status_detail(matches[0], detail)
                        else:
                            from esb.slack.forms import format_equipment_list
                            text = format_equipment_list(matches, search_term)
            except Exception:
                logger.warning('Error processing /esb-status command', exc_info=True)
                text = ':x: An error occurred while checking equipment status. Please try again.'

            client.chat_postEphemeral(
                channel=body['channel_id'],
                user=body['user_id'],
                text=text,
            )

    # Dispatch path verified in Task 0: push_via_ack (slack-bolt 1.27.0
    # accepts ack(response_action='push', view=...) for view submissions).
    @bolt_app.view('repair_dispatcher_submission')
    def handle_repair_dispatcher_submission(ack, body, client, view):
        with _ensure_app_context(app):
            from esb.services import repair_service
            from esb.slack.forms import build_repair_action_modal
            from esb.utils.exceptions import ValidationError

            # Defense-in-depth auth re-check (F14): the dispatcher modal can
            # have been opened before a role downgrade.
            esb_user = _resolve_esb_user(client, body['user']['id'])
            if esb_user is None or esb_user.role not in ('technician', 'staff'):
                ack(response_action='errors', errors={
                    'repair_select_block': 'You must have a Technician or Staff account linked.',
                })
                return

            selected = (
                view['state']['values']
                .get('repair_select_block', {})
                .get('repair_select', {})
                .get('selected_option')
            )
            if not selected:
                ack(response_action='errors', errors={
                    'repair_select_block': 'Please select a repair.',
                })
                return

            try:
                selected_id = int(selected['value'])
            except (KeyError, TypeError, ValueError):
                ack(response_action='errors', errors={
                    'repair_select_block': 'Invalid selection. Please re-run /esb-repair.',
                })
                return

            try:
                record = repair_service.get_repair_record(selected_id)
            except ValidationError:
                ack(response_action='errors', errors={
                    'repair_select_block': 'Repair record no longer exists.',
                })
                return

            # Closed-record race guard (F10): record may have been closed
            # between modal-open and modal-submit.
            if record.status in repair_service.CLOSED_STATUSES:
                ack(response_action='errors', errors={
                    'repair_select_block': (
                        'This repair was closed by someone else. '
                        'Refresh by re-running /esb-repair.'
                    ),
                })
                return

            ack(response_action='push', view=build_repair_action_modal(record))

    @bolt_app.view('repair_action_submission')
    def handle_repair_action_submission(ack, body, client, view):
        with _ensure_app_context(app):
            from datetime import datetime

            from esb.services import repair_service
            from esb.utils.exceptions import ValidationError

            # private_metadata is set by us when pushing the action modal
            # (str(record.id)). Catch corruption defensively -- a malformed
            # value here would otherwise bubble up as an unhandled exception
            # and the user would see a generic Slack failure.
            try:
                repair_record_id = int(view['private_metadata'])
            except (KeyError, TypeError, ValueError):
                ack(response_action='errors', errors={
                    'action_block': 'Internal error: repair id missing. Please re-run /esb-repair.',
                })
                return

            esb_user = _resolve_esb_user(client, body['user']['id'])
            if esb_user is None or esb_user.role not in ('technician', 'staff'):
                ack(response_action='errors', errors={
                    'action_block': 'You must have a Technician or Staff account linked.',
                })
                return

            values = view['state']['values']
            action_opt = values.get('action_block', {}).get('action', {}).get('selected_option')
            if not action_opt:
                ack(response_action='errors', errors={
                    'action_block': 'Please choose an action.',
                })
                return
            action = action_opt['value']

            try:
                record = repair_service.get_repair_record(repair_record_id)
            except ValidationError:
                ack(response_action='errors', errors={
                    'action_block': 'Repair record no longer exists.',
                })
                return

            if record.status in repair_service.CLOSED_STATUSES:
                ack(response_action='errors', errors={
                    'action_block': 'This repair has already been closed.',
                })
                return

            # Collect inputs for non-claim actions. The 'claim' branch is
            # dispatched separately at submission time -- the New→Assigned
            # promotion is a domain rule that lives in
            # repair_service.claim_repair_record() so other call paths
            # (REST, web UI, CLI) can reuse it.
            changes: dict = {}
            # Defensive: bind resolve_note in the outer scope so the dispatch
            # block below never hits an UnboundLocalError if branches are
            # rearranged. Only the 'resolve_with_note' branch reassigns it,
            # and only after pre-validating the input is non-empty -- so
            # type is str (not str | None), and the empty-string default is
            # unreachable. The service-layer guard still catches an empty
            # string defensively if a branch rearrangement ever lets it
            # through.
            resolve_note: str = ''
            if action == 'claim':
                pass  # handled below
            elif action == 'set_eta':
                eta_str = values.get('eta_block', {}).get('eta', {}).get('selected_date')
                if not eta_str:
                    ack(response_action='errors', errors={
                        'eta_block': 'ETA is required when "Set ETA" is chosen.',
                    })
                    return
                try:
                    changes['eta'] = datetime.strptime(eta_str, '%Y-%m-%d').date()
                except ValueError:
                    ack(response_action='errors', errors={
                        'eta_block': 'Invalid date format.',
                    })
                    return
            elif action == 'set_status':
                status_opt = values.get('status_block', {}).get('status', {}).get('selected_option')
                if not status_opt:
                    ack(response_action='errors', errors={
                        'status_block': 'Status is required when "Set Status" is chosen.',
                    })
                    return
                changes['status'] = status_opt['value']
                if changes['status'] == 'Closed - Duplicate':
                    dup_opt = (
                        values.get('duplicate_block', {})
                        .get('duplicated_repair_id', {})
                        .get('selected_option')
                    )
                    if not dup_opt:
                        ack(response_action='errors', errors={
                            'duplicate_block': 'Selecting which repair this duplicates is required.',
                        })
                        return
                    try:
                        changes['duplicated_repair_id'] = int(dup_opt['value'])
                    except (KeyError, TypeError, ValueError):
                        ack(response_action='errors', errors={
                            'duplicate_block': 'Invalid duplicate selection.',
                        })
                        return
            elif action == 'resolve_with_note':
                note_val = values.get('note_block', {}).get('note', {}).get('value')
                if not note_val or not note_val.strip():
                    ack(response_action='errors', errors={
                        'note_block': 'Note is required when resolving.',
                    })
                    return
                # The new resolve_repair_record service call (below) takes
                # the note as a kwarg, so we don't add it to `changes`.
                resolve_note = note_val.strip()
            else:
                ack(response_action='errors', errors={
                    'action_block': f'Unknown action: {action}',
                })
                return

            try:
                if action == 'claim':
                    repair_service.claim_repair_record(
                        repair_record_id=repair_record_id,
                        claimed_by_user_id=esb_user.id,
                        claimed_by_username=esb_user.username,
                    )
                elif action == 'resolve_with_note':
                    repair_service.resolve_repair_record(
                        repair_record_id=repair_record_id,
                        resolved_by_user_id=esb_user.id,
                        resolved_by_username=esb_user.username,
                        note=resolve_note,
                    )
                else:
                    repair_service.update_repair_record(
                        repair_record_id=repair_record_id,
                        updated_by=esb_user.username,
                        author_id=esb_user.id,
                        **changes,
                    )
            except ValidationError as e:
                ack(response_action='errors', errors={'action_block': str(e)})
                return
            except Exception:
                logger.exception('Unexpected error in repair action submission')
                ack(response_action='errors', errors={
                    'action_block': 'An unexpected error occurred. Please try again.',
                })
                return

            # response_action='clear' closes the ENTIRE modal stack (the pushed
            # action modal AND the underlying dispatcher), so the user is not
            # returned to the "Open Repairs" dialog after a successful Apply
            # (Issue #53). The ephemeral confirmation below still posts.
            ack(response_action='clear')

            # Declarative wording (F28): the message describes post-state, so it
            # is accurate even when the value matched current state and no DB
            # change occurred (no-op guard in update_repair_record).
            if action == 'claim':
                msg = f':arrows_counterclockwise: Repair #{repair_record_id} claimed by {esb_user.username}'
            elif action == 'set_eta':
                eta_date = changes['eta'].strftime('%b %d, %Y')
                msg = f':calendar: Repair #{repair_record_id}: ETA is {eta_date}'
            elif action == 'set_status':
                new_status = changes['status']
                if new_status in repair_service.CLOSED_STATUSES:
                    # F35: closure uses the resolved/success emoji.
                    msg = f':white_check_mark: Repair #{repair_record_id} closed: {new_status}'
                else:
                    msg = f':arrows_counterclockwise: Repair #{repair_record_id}: status is {new_status}'
            else:  # resolve_with_note
                msg = f':white_check_mark: Repair #{repair_record_id} resolved'

            client.chat_postEphemeral(
                channel=body['user']['id'],
                user=body['user']['id'],
                text=msg,
            )
