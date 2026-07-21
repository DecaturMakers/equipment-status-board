"""Slack handlers for reservation flows."""

import logging

logger = logging.getLogger(__name__)


def _update_error_modal(client, body, message):
    from esb.slack.reservation_forms import build_reservation_error_modal

    client.views_update(
        view_id=body["view"]["id"],
        view=build_reservation_error_modal(message),
    )


def register_reservation_handlers(bolt_app, app, *, ensure_app_context, resolve_esb_user):
    """Register only the reservation Slack commands, actions, and submissions."""

    @bolt_app.command('/esb-reserve')
    def handle_esb_reserve(ack, body, client):
        ack()
        with ensure_app_context(app):
            from datetime import UTC, datetime

            from esb.services import reservation_read_service
            from esb.slack.reservation_forms import build_reservation_landing_modal

            now = datetime.now(UTC)
            availability = reservation_read_service.get_public_availability(now=now)
            client.views_open(
                trigger_id=body['trigger_id'],
                view=build_reservation_landing_modal(
                    availability,
                    availability_url=app.config.get('STATIC_PAGE_PUBLIC_URL', ''),
                    now=now,
                ),
            )

    @bolt_app.action('reservation_start_reserve')
    def handle_reservation_start_reserve(ack, body, client):
        ack()
        with ensure_app_context(app):
            from datetime import UTC, datetime

            from esb.services import reservation_read_service
            from esb.slack.reservation_forms import build_reservation_availability_modal

            equipment_id = int(body['actions'][0]['value'])
            now = datetime.now(UTC)
            availability = reservation_read_service.get_public_availability(now=now)
            selected = next(
                (item for item in availability['equipment'] if item['id'] == equipment_id),
                None,
            )
            if selected is None:
                _update_error_modal(
                    client,
                    body,
                    'That tool is not available for reservations.',
                )
                return

            client.views_update(
                view_id=body['view']['id'],
                view=build_reservation_availability_modal(
                    selected,
                    now=now,
                ),
            )

    @bolt_app.view('reservation_availability')
    def handle_reservation_availability_submission(ack, body, client, view):
        with ensure_app_context(app):
            from datetime import UTC, datetime

            from esb.services import equipment_service, reservation_service
            from esb.slack.reservation_forms import (
                build_reservation_confirmation_modal,
                build_reservation_error_modal,
                build_reservation_processing_modal,
                build_reservation_unavailable_modal,
            )
            from esb.utils.exceptions import ValidationError

            equipment_id = int(view['private_metadata'])
            values = view['state']['values']
            start_timestamp = values['reservation_start_at_block']['reservation_start_at']['selected_date_time']
            end_timestamp = values['reservation_end_at_block']['reservation_end_at']['selected_date_time']
            notes = values['reservation_notes_block']['reservation_notes'].get('value')

            starts_at = datetime.fromtimestamp(start_timestamp, UTC)
            ends_at = datetime.fromtimestamp(end_timestamp, UTC)
            duration_minutes = int((ends_at - starts_at).total_seconds() // 60)
            if duration_minutes <= 0:
                ack(response_action='errors', errors={
                    'reservation_end_at_block': 'End must be after start.',
                })
                return

            ack(response_action='update', view=build_reservation_processing_modal())
            view_id = body.get('view', view).get('id')
            esb_user = resolve_esb_user(client, body['user']['id'])
            if esb_user is None:
                client.views_update(
                    view_id=view_id,
                    view=build_reservation_error_modal(
                        'Your Slack account is not linked to an ESB user.'
                    ),
                )
                return

            equipment_name = equipment_service.get_equipment_display_name(equipment_id)

            try:
                reservation = reservation_service.create_reservation(
                    equipment_id=equipment_id,
                    owner_user_id=esb_user.id,
                    starts_at_utc=starts_at,
                    duration_minutes=duration_minutes,
                    notes=notes,
                    created_via='slack',
                    actor_user_id=esb_user.id,
                )
            except ValidationError as e:
                client.views_update(
                    view_id=view_id,
                    view=build_reservation_unavailable_modal(
                        equipment_id,
                        equipment_name,
                        str(e),
                    ),
                )
                return
            except Exception:
                logger.exception('Unexpected error in reservation submission')
                client.views_update(
                    view_id=view_id,
                    view=build_reservation_unavailable_modal(
                        equipment_id,
                        equipment_name,
                        'An unexpected error occurred. Please try again.',
                    ),
                )
                return

            client.views_update(
                view_id=view_id,
                view=build_reservation_confirmation_modal(
                    reservation.id,
                    equipment_name,
                    reservation.starts_at.replace(tzinfo=UTC),
                    reservation.ends_at.replace(tzinfo=UTC),
                    reservation.notes,
                ),
            )

    @bolt_app.action('reservation_view_availability')
    def handle_reservation_view_availability(ack):
        ack()

    @bolt_app.action('reservation_choose_another_time')
    def handle_reservation_choose_another_time(ack, body, client):
        ack()
        with ensure_app_context(app):
            from datetime import UTC, datetime

            from esb.services import reservation_read_service
            from esb.slack.reservation_forms import build_reservation_availability_modal

            equipment_id = int(body['actions'][0]['value'])
            now = datetime.now(UTC)
            availability = reservation_read_service.get_public_availability(now=now)
            selected = next(
                (item for item in availability['equipment'] if item['id'] == equipment_id),
                None,
            )
            if selected is None:
                _update_error_modal(
                    client,
                    body,
                    'That tool is not available for reservations.',
                )
                return

            client.views_update(
                view_id=body['view']['id'],
                view=build_reservation_availability_modal(
                    selected,
                    now=now,
                ),
            )

    @bolt_app.action('reservation_view_mine')
    def handle_reservation_view_mine(ack, body, client):
        ack()
        with ensure_app_context(app):
            from esb.services import reservation_read_service
            from esb.slack.reservation_forms import build_my_reservations_modal

            esb_user = resolve_esb_user(client, body['user']['id'])
            if esb_user is None:
                _update_error_modal(
                    client,
                    body,
                    'Your Slack account is not linked to an ESB user.',
                )
                return

            reservations = reservation_read_service.list_user_upcoming_reservations(esb_user.id)
            client.views_update(
                view_id=body['view']['id'],
                view=build_my_reservations_modal(reservations),
            )

    @bolt_app.action('reservation_reserve_another')
    def handle_reservation_reserve_another(ack, body, client):
        ack()
        with ensure_app_context(app):
            from datetime import UTC, datetime

            from esb.services import reservation_read_service
            from esb.slack.reservation_forms import build_reservation_landing_modal

            now = datetime.now(UTC)
            availability = reservation_read_service.get_public_availability(now=now)
            client.views_update(
                view_id=body['view']['id'],
                view=build_reservation_landing_modal(
                    availability,
                    availability_url=app.config.get('STATIC_PAGE_PUBLIC_URL', ''),
                    now=now,
                ),
            )

    @bolt_app.action('reservation_cancel_start')
    def handle_reservation_cancel_start(ack, body, client):
        ack()
        with ensure_app_context(app):
            from esb.services import reservation_read_service
            from esb.slack.reservation_forms import build_cancel_reservation_modal

            esb_user = resolve_esb_user(client, body['user']['id'])
            if esb_user is None:
                _update_error_modal(
                    client,
                    body,
                    'Your Slack account is not linked to an ESB user.',
                )
                return

            reservation_id = int(body['actions'][0]['value'])
            reservation = reservation_read_service.get_user_reservation(reservation_id, esb_user.id)
            if reservation is None or reservation.status != 'active':
                _update_error_modal(
                    client,
                    body,
                    'That reservation is no longer available to cancel.',
                )
                return

            client.views_update(
                view_id=body['view']['id'],
                view=build_cancel_reservation_modal(reservation),
            )

    @bolt_app.action('reservation_cancel_keep')
    def handle_reservation_cancel_keep(ack, body, client):
        ack()
        with ensure_app_context(app):
            from esb.services import reservation_read_service
            from esb.slack.reservation_forms import build_my_reservations_modal

            esb_user = resolve_esb_user(client, body['user']['id'])
            if esb_user is None:
                _update_error_modal(
                    client,
                    body,
                    'Your Slack account is not linked to an ESB user.',
                )
                return

            reservations = reservation_read_service.list_user_upcoming_reservations(esb_user.id)
            client.views_update(
                view_id=body['view']['id'],
                view=build_my_reservations_modal(reservations),
            )

    @bolt_app.action('reservation_cancel_confirm')
    def handle_reservation_cancel_confirm(ack, body, client):
        ack()
        with ensure_app_context(app):
            from esb.services import reservation_read_service, reservation_service
            from esb.slack.reservation_forms import build_reservation_canceled_modal
            from esb.utils.exceptions import ValidationError

            esb_user = resolve_esb_user(client, body['user']['id'])
            if esb_user is None:
                _update_error_modal(
                    client,
                    body,
                    'Your Slack account is not linked to an ESB user.',
                )
                return

            reservation_id = int(body['actions'][0]['value'])
            reservation = reservation_read_service.get_user_reservation(reservation_id, esb_user.id)
            if reservation is None:
                _update_error_modal(
                    client,
                    body,
                    'That reservation is no longer available to cancel.',
                )
                return

            try:
                canceled = reservation_service.cancel_reservation(
                    reservation.id,
                    esb_user.id,
                )
            except ValidationError as e:
                _update_error_modal(client, body, str(e))
                return

            client.views_update(
                view_id=body['view']['id'],
                view=build_reservation_canceled_modal(
                    canceled,
                    availability_url=app.config.get('STATIC_PAGE_PUBLIC_URL', ''),
                ),
            )
