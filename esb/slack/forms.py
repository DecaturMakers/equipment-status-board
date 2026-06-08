"""Block Kit modal builder and message formatting functions for Slack commands."""


_STATUS_EMOJI = {
    'green': ':white_check_mark:',
    'yellow': ':warning:',
    'red': ':x:',
}

_NON_GREEN_DESC_TRUNCATE = 80


def _truncate(text: str, limit: int) -> str:
    """Truncate text to limit, appending an ellipsis when shortened."""
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + '\u2026'


def format_status_summary(dashboard_data):
    """Format area status dashboard data as Slack mrkdwn text.

    Each non-archived area that has at least one piece of equipment
    renders one count line; areas with no equipment at all are skipped
    to avoid cluttering the summary with empty "0 / 0 / 0" rows. Areas
    with non-green equipment also list those items as bullets (severity
    emoji + name + truncated description + optional ETA). The message
    ends with a hint pointing users at ``/esb-status <area name>`` for
    one-area detail.

    Args:
        dashboard_data: List of dicts from status_service.get_area_status_dashboard().

    Returns:
        Formatted mrkdwn string for ephemeral Slack message.
    """
    if not dashboard_data or all(not area_data['equipment'] for area_data in dashboard_data):
        return 'No equipment has been registered yet.'

    lines = [':bar_chart: *Equipment Status Summary*\n']

    for area_data in dashboard_data:
        area = area_data['area']
        equipment_list = area_data['equipment']
        if not equipment_list:
            continue

        counts = {'green': 0, 'yellow': 0, 'red': 0}
        for equip_data in equipment_list:
            color = equip_data['status']['color']
            counts[color] = counts.get(color, 0) + 1

        lines.append(
            f"*{area.name}* — "
            f"{counts['green']} :white_check_mark: operational, "
            f"{counts['yellow']} :warning: degraded, "
            f"{counts['red']} :x: down"
        )

        for equip_data in equipment_list:
            status = equip_data['status']
            color = status['color']
            if color == 'green':
                continue
            equip = equip_data['equipment']
            emoji = _STATUS_EMOJI.get(color, ':grey_question:')
            parts = [f'\u2022 {emoji} *{equip.name}*']
            desc = status.get('issue_description')
            if desc:
                parts.append(f'\u2014 {_truncate(desc, _NON_GREEN_DESC_TRUNCATE)}')
            eta = status.get('eta')
            if eta:
                parts.append(f'(ETA: {eta.strftime("%b %d, %Y")})')
            lines.append(' '.join(parts))

    lines.append('')
    lines.append('_Tip: try `/esb-status <area name>` for full details on one area._')

    return '\n'.join(lines)


def format_area_status_detail(area_data):
    """Format a single area's full status detail (all equipment, with detail for non-green).

    Args:
        area_data: One element of the list returned by
            ``status_service.get_area_status_dashboard()`` (or the dict
            returned by ``get_single_area_status_dashboard``). Shape:
            ``{'area': Area, 'equipment': [{'equipment': Equipment, 'status': {...}}, ...]}``

    Returns:
        Slack mrkdwn string with a ``:bar_chart: *<area>*`` header followed
        by one line per equipment item; non-green items get an indented
        blockquote with issue description, ETA, and assignee.
    """
    area = area_data['area']
    equipment_list = area_data['equipment']
    lines = [f':bar_chart: *{area.name}*']

    if not equipment_list:
        lines.append('_No equipment in this area._')
        return '\n'.join(lines)

    for equip_data in equipment_list:
        equip = equip_data['equipment']
        status = equip_data['status']
        color = status['color']
        emoji = _STATUS_EMOJI.get(color, ':grey_question:')
        lines.append(f'{emoji} *{equip.name}* \u2014 {status["label"]}')
        if color == 'green':
            continue
        if status.get('issue_description'):
            lines.append(f'> {status["issue_description"]}')
        if status.get('eta'):
            lines.append(f'> ETA: {status["eta"].strftime("%b %d, %Y")}')
        if status.get('assignee_name'):
            lines.append(f'> Assigned to: {status["assignee_name"]}')

    return '\n'.join(lines)


def format_equipment_status_detail(equipment, status_detail):
    """Format single equipment status detail as Slack mrkdwn text.

    Args:
        equipment: Equipment model instance.
        status_detail: Dict from status_service.get_equipment_status_detail().

    Returns:
        Formatted mrkdwn string.
    """
    emoji = _STATUS_EMOJI.get(status_detail['color'], ':grey_question:')
    area_name = equipment.area.name if equipment.area else 'No Area'
    text = f"{emoji} *{equipment.name}* ({area_name}) — {status_detail['label']}"

    if status_detail['color'] != 'green':
        if status_detail.get('issue_description'):
            text += f"\n> {status_detail['issue_description']}"
        if status_detail.get('eta'):
            text += f"\n> ETA: {status_detail['eta'].strftime('%b %d, %Y')}"
        if status_detail.get('assignee_name'):
            text += f"\n> Assigned to: {status_detail['assignee_name']}"

    return text


def format_equipment_list(matches, search_term):
    """Format a list of matching equipment for disambiguation.

    Args:
        matches: List of Equipment model instances.
        search_term: Original search string from the user.

    Returns:
        Formatted mrkdwn string.
    """
    lines = [f'Multiple equipment items match "{search_term}":']
    for equip in matches:
        area_name = equip.area.name if equip.area else 'No Area'
        lines.append(f'\u2022 {equip.name} ({area_name})')
    lines.append('\nPlease be more specific. Try `/esb-status [full name]`')
    return '\n'.join(lines)


def build_equipment_options():
    """Build Slack static_select options for non-archived equipment.

    Returns:
        List of option dicts: [{"text": {"type": "plain_text", "text": "Name (Area)"}, "value": "id"}, ...]
    """
    from esb.extensions import db
    from esb.models.equipment import Equipment

    equipment_list = db.session.execute(
        db.select(Equipment)
        .filter(Equipment.is_archived.is_(False))
        .order_by(Equipment.name)
    ).scalars().all()

    options = []
    for e in equipment_list:
        area_name = e.area.name if e.area else 'No Area'
        options.append({
            'text': {'type': 'plain_text', 'text': f'{e.name} ({area_name})'[:75]},
            'value': str(e.id),
        })
    return options


def build_user_options():
    """Build Slack static_select options for active Technician/Staff users.

    Returns:
        List of option dicts.
    """
    from esb.extensions import db
    from esb.models.user import User

    users = db.session.execute(
        db.select(User)
        .filter(User.is_active.is_(True), User.role.in_(['technician', 'staff']))
        .order_by(User.username)
    ).scalars().all()

    return [
        {
            'text': {'type': 'plain_text', 'text': f'{u.username} ({u.role})'[:75]},
            'value': str(u.id),
        }
        for u in users
    ]


def build_problem_report_modal(equipment_options):
    """Build Block Kit modal for member problem reports.

    Args:
        equipment_options: List of equipment option dicts from build_equipment_options().

    Returns:
        Block Kit modal view dict.
    """
    from esb.models.repair_record import REPAIR_SEVERITIES

    return {
        'type': 'modal',
        'callback_id': 'problem_report_submission',
        'title': {'type': 'plain_text', 'text': 'Report a Problem'},
        'submit': {'type': 'plain_text', 'text': 'Submit Report'},
        'close': {'type': 'plain_text', 'text': 'Cancel'},
        'blocks': [
            {
                'type': 'input',
                'block_id': 'equipment_block',
                'element': {
                    'type': 'static_select',
                    'action_id': 'equipment_select',
                    'placeholder': {'type': 'plain_text', 'text': 'Select equipment'},
                    'options': equipment_options,
                },
                'label': {'type': 'plain_text', 'text': 'Equipment'},
            },
            {
                'type': 'input',
                'block_id': 'name_block',
                'element': {
                    'type': 'plain_text_input',
                    'action_id': 'reporter_name',
                    'placeholder': {'type': 'plain_text', 'text': 'Your name'},
                },
                'label': {'type': 'plain_text', 'text': 'Your Name'},
            },
            {
                'type': 'input',
                'block_id': 'description_block',
                'element': {
                    'type': 'plain_text_input',
                    'action_id': 'description',
                    'multiline': True,
                    'placeholder': {'type': 'plain_text', 'text': 'Describe the problem'},
                },
                'label': {'type': 'plain_text', 'text': 'Description'},
            },
            {
                'type': 'input',
                'block_id': 'severity_block',
                'optional': True,
                'element': {
                    'type': 'static_select',
                    'action_id': 'severity',
                    'initial_option': {
                        'text': {'type': 'plain_text', 'text': 'Not Sure'},
                        'value': 'Not Sure',
                    },
                    'options': [
                        {'text': {'type': 'plain_text', 'text': s}, 'value': s}
                        for s in REPAIR_SEVERITIES
                    ],
                },
                'label': {'type': 'plain_text', 'text': 'Severity'},
            },
            {
                'type': 'input',
                'block_id': 'safety_risk_block',
                'optional': True,
                'element': {
                    'type': 'checkboxes',
                    'action_id': 'safety_risk',
                    'options': [
                        {
                            'text': {'type': 'plain_text', 'text': 'This is a safety risk'},
                            'value': 'safety_risk',
                        },
                    ],
                },
                'label': {'type': 'plain_text', 'text': 'Safety Risk'},
            },
            {
                'type': 'input',
                'block_id': 'consumable_block',
                'optional': True,
                'element': {
                    'type': 'checkboxes',
                    'action_id': 'consumable',
                    'options': [
                        {
                            'text': {'type': 'plain_text', 'text': 'This is a consumable item'},
                            'value': 'consumable',
                        },
                    ],
                },
                'label': {'type': 'plain_text', 'text': 'Consumable'},
            },
        ],
    }


def build_repair_create_modal(equipment_options, user_options, preselected_equipment_id=None):
    """Build Block Kit modal for technician/staff repair record creation.

    Args:
        equipment_options: List of equipment option dicts from build_equipment_options().
        user_options: List of user option dicts from build_user_options().
        preselected_equipment_id: Optional equipment id (int). When provided
            and matching one of ``equipment_options``, that option is set as
            ``initial_option`` so the user sees their slash-command argument
            already applied. Pass None for no preselection.

    Returns:
        Block Kit modal view dict.
    """
    from esb.models.repair_record import REPAIR_SEVERITIES, REPAIR_STATUSES

    equipment_element = {
        'type': 'static_select',
        'action_id': 'equipment_select',
        'placeholder': {'type': 'plain_text', 'text': 'Select equipment'},
        'options': equipment_options,
    }
    if preselected_equipment_id is not None:
        target_value = str(preselected_equipment_id)
        for opt in equipment_options:
            if opt.get('value') == target_value:
                equipment_element['initial_option'] = opt
                break

    blocks = [
        {
            'type': 'input',
            'block_id': 'equipment_block',
            'element': equipment_element,
            'label': {'type': 'plain_text', 'text': 'Equipment'},
        },
        {
            'type': 'input',
            'block_id': 'description_block',
            'element': {
                'type': 'plain_text_input',
                'action_id': 'description',
                'multiline': True,
                'placeholder': {'type': 'plain_text', 'text': 'Describe the issue'},
            },
            'label': {'type': 'plain_text', 'text': 'Description'},
        },
        {
            'type': 'input',
            'block_id': 'severity_block',
            'optional': True,
            'element': {
                'type': 'static_select',
                'action_id': 'severity',
                'placeholder': {'type': 'plain_text', 'text': 'Select severity'},
                'options': [
                    {'text': {'type': 'plain_text', 'text': s}, 'value': s}
                    for s in REPAIR_SEVERITIES
                ],
            },
            'label': {'type': 'plain_text', 'text': 'Severity'},
        },
    ]

    if user_options:
        blocks.append({
            'type': 'input',
            'block_id': 'assignee_block',
            'optional': True,
            'element': {
                'type': 'static_select',
                'action_id': 'assignee',
                'placeholder': {'type': 'plain_text', 'text': 'Select assignee'},
                'options': user_options,
            },
            'label': {'type': 'plain_text', 'text': 'Assignee'},
        })

    blocks.append({
        'type': 'input',
        'block_id': 'status_block',
        'optional': True,
        'element': {
            'type': 'static_select',
            'action_id': 'status',
            'initial_option': {
                'text': {'type': 'plain_text', 'text': 'New'},
                'value': 'New',
            },
            'options': [
                {'text': {'type': 'plain_text', 'text': s}, 'value': s}
                for s in REPAIR_STATUSES if s != 'Closed - Duplicate'
            ],
        },
        'label': {'type': 'plain_text', 'text': 'Status'},
    })

    return {
        'type': 'modal',
        'callback_id': 'repair_create_submission',
        'title': {'type': 'plain_text', 'text': 'Create Repair Record'},
        'submit': {'type': 'plain_text', 'text': 'Create Record'},
        'close': {'type': 'plain_text', 'text': 'Cancel'},
        'blocks': blocks,
    }


def build_repair_dispatcher_modal(open_records):
    """Build the dispatcher modal listing open repair records grouped by area.

    Caller must precheck that ``open_records`` is non-empty (the empty case
    is handled by the ``/esb-repair`` handler with an ephemeral message,
    not by this builder).

    Sorting:
        - Within each area's option_group, options preserve the caller's
          input order (caller is expected to provide records ordered by
          ``(severity_priority, created_at_asc)`` -- typical
          ``get_repair_queue()`` output).
        - Across area groups, areas are presented by ``(sort_order, name)``
          ascending, matching the ordering used everywhere else in the app.

    Args:
        open_records: Non-empty list of RepairRecord instances with
            ``equipment.area`` and ``assignee`` eager-loaded.

    Returns:
        Block Kit modal view dict.
    """
    buckets: dict[str, list] = {}
    area_sort_keys: dict[str, tuple[int, str]] = {}
    for record in open_records:
        area = record.equipment.area
        area_name = area.name if area else 'No Area'
        sort_order = area.sort_order if area else 0
        area_sort_keys[area_name] = (sort_order, area_name)
        buckets.setdefault(area_name, []).append(record)

    option_groups = []
    for area_name in sorted(buckets, key=lambda n: area_sort_keys[n]):
        options = []
        for record in buckets[area_name]:
            label = f'#{record.id} {record.equipment.name} \u2014 {record.status}'
            severity = record.severity or '\u2014'
            assignee = record.assignee.username if record.assignee else 'Unassigned'
            description = f'{severity} | {assignee}'
            options.append({
                'text': {'type': 'plain_text', 'text': label[:75]},
                'description': {'type': 'plain_text', 'text': description[:75]},
                'value': str(record.id),
            })
        option_groups.append({
            'label': {'type': 'plain_text', 'text': area_name[:75]},
            'options': options,
        })

    return {
        'type': 'modal',
        'callback_id': 'repair_dispatcher_submission',
        'title': {'type': 'plain_text', 'text': 'Open Repairs'},
        'submit': {'type': 'plain_text', 'text': 'Continue'},
        'close': {'type': 'plain_text', 'text': 'Cancel'},
        'private_metadata': '',
        'blocks': [
            {
                'type': 'input',
                'block_id': 'repair_select_block',
                'element': {
                    'type': 'static_select',
                    'action_id': 'repair_select',
                    'placeholder': {'type': 'plain_text', 'text': 'Select a repair'},
                    'option_groups': option_groups,
                },
                'label': {'type': 'plain_text', 'text': 'Repair'},
            },
        ],
    }


def build_repair_action_modal(repair_record):
    """Build the dispatcher's action modal (Step B of the two-step flow).

    The action modal is a single form: one ``radio_buttons`` ``Action`` block
    plus optional ETA / status / note inputs. Slack does not support truly
    conditional input visibility in a static modal -- the server resolves
    which inputs apply based on the ``Action`` value at submission time.

    Args:
        repair_record: The selected RepairRecord (with equipment + area).

    Returns:
        Block Kit modal view dict; ``private_metadata`` carries the id.
    """
    from esb.services import repair_service  # local: avoid module-level cycle

    candidates = repair_service.list_duplicate_candidates(repair_record.id)

    equipment = repair_record.equipment
    area_name = equipment.area.name if equipment and equipment.area else 'No Area'
    equipment_name = equipment.name if equipment else 'Unknown'
    severity_label = repair_record.severity or '\u2014'

    status_options = [
        ('In Progress', 'In Progress'),
        ('Closed - Duplicate', 'Closed - Duplicate'),
        ('Closed - No Issue Found', 'Closed - No Issue Found'),
    ]
    if not candidates:
        status_options = [opt for opt in status_options if opt[0] != 'Closed - Duplicate']

    blocks = [
        {
            'type': 'context',
            'elements': [
                {
                    'type': 'mrkdwn',
                    'text': (
                        f'*{equipment_name}* ({area_name}) '
                        f'\u2014 {repair_record.status} / {severity_label}'
                    ),
                },
            ],
        },
        {
            'type': 'input',
            'block_id': 'action_block',
            'element': {
                'type': 'radio_buttons',
                'action_id': 'action',
                'options': [
                    {'text': {'type': 'plain_text', 'text': 'Claim (assign to me)'}, 'value': 'claim'},
                    {'text': {'type': 'plain_text', 'text': 'Set ETA'}, 'value': 'set_eta'},
                    {'text': {'type': 'plain_text', 'text': 'Set Status'}, 'value': 'set_status'},
                    {'text': {'type': 'plain_text', 'text': 'Resolve with Note'}, 'value': 'resolve_with_note'},
                ],
            },
            'label': {'type': 'plain_text', 'text': 'Action'},
        },
    ]

    eta_element = {
        'type': 'datepicker',
        'action_id': 'eta',
        'placeholder': {'type': 'plain_text', 'text': 'Select a date'},
    }
    if repair_record.eta:
        eta_element['initial_date'] = repair_record.eta.strftime('%Y-%m-%d')
    blocks.append({
        'type': 'input',
        'block_id': 'eta_block',
        'optional': True,
        'element': eta_element,
        'label': {'type': 'plain_text', 'text': "ETA (used when 'Set ETA' chosen)"},
    })

    blocks.append({
        'type': 'input',
        'block_id': 'status_block',
        'optional': True,
        'element': {
            'type': 'static_select',
            'action_id': 'status',
            'placeholder': {'type': 'plain_text', 'text': 'Select a status'},
            'options': [
                {'text': {'type': 'plain_text', 'text': label}, 'value': value}
                for value, label in status_options
            ],
        },
        'label': {'type': 'plain_text', 'text': "New Status (used when 'Set Status' chosen)"},
    })

    blocks.append({
        'type': 'input',
        'block_id': 'note_block',
        'optional': True,
        'element': {
            'type': 'plain_text_input',
            'action_id': 'note',
            'multiline': True,
            'placeholder': {'type': 'plain_text', 'text': 'Add a note (required when resolving)'},
        },
        'label': {'type': 'plain_text', 'text': 'Note (required when resolving)'},
    })

    if candidates:
        def _label(r):
            prefix = f'#{r.id} [{r.status}] '
            return prefix + _truncate(r.description, 75 - len(prefix))

        dup_options = [
            {
                'text': {'type': 'plain_text', 'text': _label(r)},
                'value': str(r.id),
            }
            for r in candidates
        ]
        blocks.append({
            'type': 'input',
            'block_id': 'duplicate_block',
            'optional': True,
            'element': {
                'type': 'static_select',
                'action_id': 'duplicated_repair_id',
                'placeholder': {'type': 'plain_text', 'text': 'Select duplicated repair'},
                'options': dup_options,
            },
            'label': {
                'type': 'plain_text',
                'text': "Duplicate of (used when 'Set Status → Closed - Duplicate' chosen)",
            },
        })

    return {
        'type': 'modal',
        'callback_id': 'repair_action_submission',
        'title': {'type': 'plain_text', 'text': f'Repair #{repair_record.id}'[:24]},
        'submit': {'type': 'plain_text', 'text': 'Apply'},
        'close': {'type': 'plain_text', 'text': 'Cancel'},
        'private_metadata': str(repair_record.id),
        'blocks': blocks,
    }
