"""Block Kit builders for Slack reservation flows."""

from datetime import UTC, datetime, timedelta

from esb.utils.timezones import MAKERSPACE_TIMEZONE


def _format_time(value):
    text = value.astimezone(MAKERSPACE_TIMEZONE).strftime('%I:%M %p')
    return text.lstrip('0')


def _format_datetime(value):
    local_value = value.astimezone(MAKERSPACE_TIMEZONE)
    return f'{local_value.strftime("%A, %B")} {local_value.day}, {_format_time(value)}'


def _format_duration(minutes):
    if minutes % (24 * 60) == 0:
        days = minutes // (24 * 60)
        unit = 'day' if days == 1 else 'days'
        return f'{days} {unit}'
    if minutes % 60 == 0:
        hours = minutes // 60
        unit = 'hour' if hours == 1 else 'hours'
        return f'{hours} {unit}'
    return f'{minutes} min'


def _ceil_to_slot(value, slot_minutes):
    value = value.astimezone(UTC).replace(second=0, microsecond=0)
    minutes_since_midnight = value.hour * 60 + value.minute
    remainder = minutes_since_midnight % slot_minutes
    if remainder:
        value += timedelta(minutes=slot_minutes - remainder)
    return value


def _availability_status(item, now):
    now_utc = now.astimezone(UTC)
    current_reservations = []
    for reservation in item['reservations']:
        starts_at = datetime.fromisoformat(reservation['starts_at'])
        ends_at = datetime.fromisoformat(reservation['ends_at'])
        if starts_at <= now_utc < ends_at:
            current_reservations.append(ends_at)

    if current_reservations:
        return f'Reserved until {_format_time(min(current_reservations))}'
    return 'Available now'


def _date_label(value, today):
    if value == today:
        return 'Today'
    if value == today + timedelta(days=1):
        return 'Tomorrow'
    return value.strftime('%A')


def _booked_ranges_by_day(item, now, days=3):
    local_tz = MAKERSPACE_TIMEZONE
    today = now.astimezone(MAKERSPACE_TIMEZONE).date()
    ranges_by_day = {today + timedelta(days=offset): [] for offset in range(days)}

    for reservation in item['reservations']:
        reservation_start = datetime.fromisoformat(reservation['starts_at']).astimezone(local_tz)
        reservation_end = datetime.fromisoformat(reservation['ends_at']).astimezone(local_tz)
        day = reservation_start.date()
        if day in ranges_by_day:
            ranges_by_day[day].append((reservation_start, reservation_end))

    for ranges in ranges_by_day.values():
        ranges.sort()
    return ranges_by_day


def _format_booked_range(start, end):
    return f'Unavailable: {_format_time(start)}-{_format_time(end)}'


def _modal_title(text):
    return text[:24]


def _button(text, action_id, value, style=None, url=None):
    button = {
        'type': 'button',
        'text': {'type': 'plain_text', 'text': text},
        'action_id': action_id,
        'value': value,
    }
    if style:
        button['style'] = style
    if url:
        button['url'] = url
    return button


def build_reservation_landing_modal(availability, availability_url=None, now=None):
    """Build the Flow 1 reservation landing modal with current tool availability."""
    availability_url = availability_url.strip() if availability_url else None
    now = now or datetime.now(UTC)
    blocks = [
        {
            'type': 'section',
            'block_id': 'reservation_intro_block',
            'text': {
                'type': 'mrkdwn',
                'text': 'Choose a tool to view availability or start a reservation.',
            },
        },
        {'type': 'divider'},
    ]

    for item in availability['equipment']:
        equipment_id = str(item['id'])
        blocks.append(
            {
                'type': 'section',
                'block_id': f'reservation_tool_{equipment_id}_status_block',
                'text': {
                    'type': 'mrkdwn',
                    'text': f'*{item["name"]}*\nStatus: {_availability_status(item, now)}',
                },
            }
        )

        elements = [
            _button(
                'Reserve',
                'reservation_start_reserve',
                equipment_id,
                style='primary',
            )
        ]
        if availability_url:
            elements.append(
                _button(
                    'Availability',
                    'reservation_view_availability',
                    equipment_id,
                    url=availability_url,
                )
            )
        blocks.append(
            {
                'type': 'actions',
                'block_id': f'reservation_tool_{equipment_id}_actions_block',
                'elements': elements,
            }
        )
        blocks.append({'type': 'divider'})

    if not availability['equipment']:
        blocks.append(
            {
                'type': 'section',
                'block_id': 'reservation_empty_block',
                'text': {
                    'type': 'mrkdwn',
                    'text': 'No tools are available for reservations right now.',
                },
            }
        )
        blocks.append({'type': 'divider'})

    blocks.append(
        {
            'type': 'actions',
            'block_id': 'reservation_member_actions_block',
            'elements': [
                _button(
                    'My reservations',
                    'reservation_view_mine',
                    'stub-my-reservations',
                ),
            ],
        }
    )

    return {
        'type': 'modal',
        'callback_id': 'reservation_landing',
        'title': {'type': 'plain_text', 'text': 'Makerspace Tools'},
        'close': {'type': 'plain_text', 'text': 'Close'},
        'blocks': blocks,
    }


def build_reservation_availability_modal(item, now=None):
    """Build the Flow 2 one-tool reservation modal."""
    now = now or datetime.now(UTC)
    today = now.astimezone(MAKERSPACE_TIMEZONE).date()
    slot_minutes = item['slot_granularity_minutes']
    duration_minutes = item['min_duration_minutes']
    initial_start = _ceil_to_slot(
        now + timedelta(minutes=item['min_advance_notice_minutes']),
        slot_minutes,
    )
    initial_end = initial_start + timedelta(minutes=duration_minutes)
    initial_start_date_time = int(initial_start.timestamp())
    initial_end_date_time = int(initial_end.timestamp())
    booked_ranges_by_day = _booked_ranges_by_day(item, now)

    blocks = [
        {'type': 'divider'},
        {
            'type': 'header',
            'block_id': 'reservation_existing_reservations_header_block',
            'text': {
                'type': 'plain_text',
                'text': 'Existing Reservations',
            },
        },
    ]

    has_booked_ranges = any(booked_ranges_by_day.values())
    if not has_booked_ranges:
        blocks.append(
            {
                'type': 'section',
                'block_id': 'reservation_booked_empty_block',
                'text': {
                    'type': 'mrkdwn',
                    'text': 'No existing reservations',
                },
            }
        )
    else:
        for offset, (day, booked_ranges) in enumerate(booked_ranges_by_day.items()):
            range_text = '\n'.join(
                _format_booked_range(start, end) for start, end in booked_ranges
            ) or 'No existing reservations'
            blocks.append(
                {
                    'type': 'section',
                    'block_id': f'reservation_booked_day_{offset}_block',
                    'text': {
                        'type': 'mrkdwn',
                        'text': f'*{_date_label(day, today)}*\n{range_text}',
                    },
                }
            )

    equipment_id = str(item['id'])
    blocks.extend([
        {'type': 'divider'},
        {
            'type': 'header',
            'block_id': 'reservation_details_header_block',
            'text': {
                'type': 'plain_text',
                'text': 'Reservation Request',
            },
        },
        {
            'type': 'context',
            'block_id': 'reservation_policy_context_block',
            'elements': [
                {
                    'type': 'mrkdwn',
                    'text': (
                        '*Limits:* '
                        f'{_format_duration(item["min_duration_minutes"])}-'
                        f'{_format_duration(item["max_duration_minutes"])} reservations; '
                        f'{_format_duration(item["min_advance_notice_minutes"])}-'
                        f'{_format_duration(item["max_advance_notice_minutes"])} advance notice.'
                    ),
                },
            ],
        },
        {
            'type': 'input',
            'block_id': 'reservation_notes_block',
            'element': {
                'type': 'plain_text_input',
                'action_id': 'reservation_notes',
                'multiline': True,
                'placeholder': {'type': 'plain_text', 'text': 'Reservation note'},
            },
            'label': {'type': 'plain_text', 'text': 'Note'},
        },
        {
            'type': 'input',
            'block_id': 'reservation_start_at_block',
            'element': {
                'type': 'datetimepicker',
                'action_id': 'reservation_start_at',
                'initial_date_time': initial_start_date_time,
            },
            'label': {'type': 'plain_text', 'text': 'Requested Start'},
        },
        {
            'type': 'input',
            'block_id': 'reservation_end_at_block',
            'element': {
                'type': 'datetimepicker',
                'action_id': 'reservation_end_at',
                'initial_date_time': initial_end_date_time,
            },
            'label': {'type': 'plain_text', 'text': 'Requested End'},
        },
    ])

    return {
        'type': 'modal',
        'callback_id': 'reservation_availability',
        'private_metadata': equipment_id,
        'title': {'type': 'plain_text', 'text': _modal_title(f'Reserve {item["name"]}')},
        'submit': {'type': 'plain_text', 'text': 'Reserve'},
        'close': {'type': 'plain_text', 'text': 'Back'},
        'blocks': blocks,
    }


def build_reservation_confirmation_modal(
    reservation_id,
    equipment_name,
    starts_at,
    ends_at,
    notes=None,
):
    """Build the Flow 3 successful reservation confirmation modal."""
    text = (
        '*Reservation confirmed*\n\n'
        f'Tool: {equipment_name}\n'
        f'Time: {_format_datetime(starts_at)} to {_format_time(ends_at)}'
    )
    if notes:
        text += f'\nNote: {notes}'

    return {
        'type': 'modal',
        'callback_id': 'reservation_confirmation',
        'title': {'type': 'plain_text', 'text': 'Confirmed'},
        'close': {'type': 'plain_text', 'text': 'Close'},
        'blocks': [
            {
                'type': 'section',
                'block_id': 'reservation_confirmation_block',
                'text': {'type': 'mrkdwn', 'text': text},
            },
            {
                'type': 'actions',
                'block_id': 'reservation_confirmation_actions_block',
                'elements': [
                    _button(
                        'Cancel reservation',
                        'reservation_cancel_start',
                        str(reservation_id),
                        style='danger',
                    ),
                    _button(
                        'View my reservations',
                        'reservation_view_mine',
                        'stub-my-reservations',
                    ),
                ],
            },
        ],
    }


def build_reservation_processing_modal():
    """Build a lightweight modal shown while Slack/DB work completes."""
    return {
        'type': 'modal',
        'callback_id': 'reservation_processing',
        'title': {'type': 'plain_text', 'text': 'Reserving'},
        'close': {'type': 'plain_text', 'text': 'Close'},
        'blocks': [
            {
                'type': 'section',
                'block_id': 'reservation_processing_block',
                'text': {'type': 'mrkdwn', 'text': 'Processing your reservation...'},
            },
        ],
    }


def _reservation_equipment_name(reservation):
    return reservation.equipment.name if reservation.equipment else f'ID {reservation.equipment_id}'


def _reservation_time_text(reservation):
    starts_at = reservation.starts_at.replace(tzinfo=UTC)
    ends_at = reservation.ends_at.replace(tzinfo=UTC)
    return f'{_format_datetime(starts_at)} to {_format_time(ends_at)}'


def build_cancel_reservation_modal(reservation):
    """Build the Flow 5 cancellation confirmation modal."""
    equipment_name = _reservation_equipment_name(reservation)
    return {
        'type': 'modal',
        'callback_id': 'reservation_cancel_confirm',
        'private_metadata': str(reservation.id),
        'title': {'type': 'plain_text', 'text': 'Cancel reservation?'},
        'close': {'type': 'plain_text', 'text': 'Close'},
        'blocks': [
            {
                'type': 'section',
                'block_id': 'reservation_cancel_summary_block',
                'text': {
                    'type': 'mrkdwn',
                    'text': (
                        f'*{equipment_name}*\n'
                        f'{_reservation_time_text(reservation)}\n\n'
                        'This will make the time available to other members.'
                    ),
                },
            },
            {
                'type': 'actions',
                'block_id': 'reservation_cancel_actions_block',
                'elements': [
                    _button(
                        'Keep reservation',
                        'reservation_cancel_keep',
                        str(reservation.id),
                    ),
                    _button(
                        'Cancel it',
                        'reservation_cancel_confirm',
                        str(reservation.id),
                        style='danger',
                    ),
                ],
            },
        ],
    }


def build_reservation_canceled_modal(reservation, availability_url=None):
    """Build the Flow 5 cancellation success modal."""
    availability_url = availability_url.strip() if availability_url else None
    equipment_name = _reservation_equipment_name(reservation)
    elements = [
        _button(
            'Reserve another tool',
            'reservation_reserve_another',
            'reserve-another-tool',
            style='primary',
        ),
    ]
    if availability_url:
        elements.append(
            _button(
                'View availability',
                'reservation_view_availability',
                str(reservation.equipment_id),
                url=availability_url,
            )
        )

    return {
        'type': 'modal',
        'callback_id': 'reservation_canceled',
        'title': {'type': 'plain_text', 'text': 'Canceled'},
        'close': {'type': 'plain_text', 'text': 'Close'},
        'blocks': [
            {
                'type': 'section',
                'block_id': 'reservation_canceled_block',
                'text': {
                    'type': 'mrkdwn',
                    'text': (
                        '*Reservation canceled*\n\n'
                        f'{equipment_name} is no longer reserved for\n'
                        f'{_reservation_time_text(reservation)}.'
                    ),
                },
            },
            {
                'type': 'actions',
                'block_id': 'reservation_canceled_actions_block',
                'elements': elements,
            },
        ],
    }


def build_reservation_error_modal(message):
    """Build a modal-safe reservation error view."""
    return {
        'type': 'modal',
        'callback_id': 'reservation_error',
        'title': {'type': 'plain_text', 'text': 'Reservation error'},
        'close': {'type': 'plain_text', 'text': 'Close'},
        'blocks': [
            {
                'type': 'section',
                'block_id': 'reservation_error_block',
                'text': {
                    'type': 'mrkdwn',
                    'text': f'*Unable to continue*\n\n{message}',
                },
            },
            {
                'type': 'actions',
                'block_id': 'reservation_error_actions_block',
                'elements': [
                    _button(
                        'Reserve another tool',
                        'reservation_reserve_another',
                        'reserve-another-tool',
                        style='primary',
                    ),
                ],
            },
        ],
    }


def build_reservation_unavailable_modal(equipment_id, equipment_name, error_message):
    """Build the Flow 3 unavailable-time error modal."""
    return {
        'type': 'modal',
        'callback_id': 'reservation_unavailable',
        'private_metadata': str(equipment_id),
        'title': {'type': 'plain_text', 'text': 'Time unavailable'},
        'close': {'type': 'plain_text', 'text': 'Close'},
        'blocks': [
            {
                'type': 'section',
                'block_id': 'reservation_unavailable_block',
                'text': {
                    'type': 'mrkdwn',
                    'text': (
                        '*That time is no longer available*\n\n'
                        f'{equipment_name}: {error_message}\n\n'
                        'Choose another start and end time to try again.'
                    ),
                },
            },
            {
                'type': 'actions',
                'block_id': 'reservation_unavailable_actions_block',
                'elements': [
                    _button(
                        'Choose another time',
                        'reservation_choose_another_time',
                        str(equipment_id),
                        style='primary',
                    ),
                ],
            },
        ],
    }


def build_my_reservations_modal(reservations):
    """Build the Flow 4 modal listing a user's upcoming reservations."""
    blocks = []

    if reservations:
        for reservation in reservations:
            equipment_name = reservation.equipment.name if reservation.equipment else f'ID {reservation.equipment_id}'
            blocks.append(
                {
                    'type': 'section',
                    'block_id': f'reservation_{reservation.id}_summary_block',
                    'text': {
                        'type': 'mrkdwn',
                        'text': (
                            f'*{equipment_name}*\n'
                            f'{_format_datetime(reservation.starts_at.replace(tzinfo=UTC))} '
                            f'to {_format_time(reservation.ends_at.replace(tzinfo=UTC))}'
                        ),
                    },
                }
            )
            blocks.append(
                {
                    'type': 'actions',
                    'block_id': f'reservation_{reservation.id}_actions_block',
                    'elements': [
                        _button(
                            'Cancel',
                            'reservation_cancel_start',
                            str(reservation.id),
                            style='danger',
                        ),
                    ],
                }
            )
            blocks.append({'type': 'divider'})
    else:
        blocks.append(
            {
                'type': 'section',
                'block_id': 'reservation_mine_empty_block',
                'text': {'type': 'mrkdwn', 'text': 'You do not have any upcoming reservations.'},
            }
        )

    blocks.append(
        {
            'type': 'actions',
            'block_id': 'reservation_mine_actions_block',
            'elements': [
                _button(
                    'Reserve another tool',
                    'reservation_reserve_another',
                    'reserve-another-tool',
                    style='primary',
                ),
            ],
        }
    )

    return {
        'type': 'modal',
        'callback_id': 'reservation_mine',
        'title': {'type': 'plain_text', 'text': 'My Reservations'},
        'close': {'type': 'plain_text', 'text': 'Close'},
        'blocks': blocks,
    }


def build_reservation_stub_modal():
    """Backward-compatible alias for the current stub reservation entry point."""
    return build_reservation_landing_modal({'equipment': []})
