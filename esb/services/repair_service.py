"""Repair record lifecycle management."""

from datetime import UTC, datetime

from sqlalchemy import case, func
from sqlalchemy.orm import joinedload

from esb.extensions import db
from esb.models.audit_log import AuditLog
from esb.models.document import Document
from esb.models.equipment import Equipment
from esb.models.repair_record import REPAIR_SEVERITIES, REPAIR_STATUSES, RepairRecord
from esb.models.repair_timeline_entry import RepairTimelineEntry
from esb.models.user import User
from esb.utils.exceptions import ValidationError
from esb.utils.logging import log_mutation


# Ordered tuple for deterministic timeline entry creation order.
# specialist_description is intentionally saved regardless of status -- the AC
# requires it available when status is "Needs Specialist", not restricted to it.
_REPAIR_UPDATABLE_FIELDS = (
    'status', 'severity', 'assignee_id', 'eta', 'specialist_description',
    'duplicated_repair_id',
)


def _serialize(value):
    """Serialize a value for audit log JSON."""
    return str(value) if value is not None else None


def _assignee_payload_fields(user):
    """Build the assignee-related payload fields for a Slack notification.

    Args:
        user: A User instance, or None for unassignment.

    Returns:
        Dict with assignee_username/assignee_email/assignee_has_slack. For a
        None user (unassignment), all fields are None/False. ``assignee_has_slack``
        records whether the user has a ``slack_handle`` set (the "wants Slack"
        flag); the actual Slack-ID resolution happens at delivery time.
    """
    if user is None:
        return {
            'assignee_username': None,
            'assignee_email': None,
            'assignee_has_slack': False,
        }
    return {
        'assignee_username': user.username,
        'assignee_email': user.email,
        'assignee_has_slack': bool(user.slack_handle),
    }


def _queue_slack_notification(equipment, event_type, extra_payload=None):
    """Queue a slack_message notification for a repair event.

    Args:
        equipment: Equipment model instance (must have area relationship loaded).
        event_type: One of 'new_report', 'resolved', 'severity_changed', 'eta_updated'.
        extra_payload: Additional payload fields to merge.
    """
    from esb.services import notification_service

    payload = {
        'event_type': event_type,
        'equipment_id': equipment.id,
        'equipment_name': equipment.name,
        'area_name': equipment.area.name if equipment.area else 'Unknown',
    }
    if extra_payload:
        payload.update(extra_payload)

    target = equipment.area.slack_channel if equipment.area and equipment.area.slack_channel else '#general'

    notification_service.queue_notification(
        notification_type='slack_message',
        target=target,
        payload=payload,
    )


def create_repair_record(
    equipment_id: int,
    description: str,
    created_by: str,
    severity: str | None = None,
    reporter_name: str | None = None,
    reporter_email: str | None = None,
    assignee_id: int | None = None,
    has_safety_risk: bool = False,
    is_consumable: bool = False,
    author_id: int | None = None,
) -> RepairRecord:
    """Create a new repair record with initial timeline entry.

    Args:
        equipment_id: ID of the equipment this repair is for.
        description: Description of the problem.
        created_by: Username of the person creating the record.
        severity: Optional severity level (Down, Degraded, Not Sure).
        reporter_name: Name of the person reporting (for member reports).
        reporter_email: Email of the reporter (for member reports).
        assignee_id: Optional user ID to assign the repair to.
        has_safety_risk: Whether this is a safety risk.
        is_consumable: Whether this involves consumables.
        author_id: User ID of the creator (None for anonymous reports).

    Returns:
        The created RepairRecord.

    Raises:
        ValidationError: if equipment not found, archived, or invalid input.
    """
    if not description or not description.strip():
        raise ValidationError('Description is required')

    equipment = db.session.get(Equipment, equipment_id)
    if equipment is None:
        raise ValidationError(f'Equipment with id {equipment_id} not found')
    if equipment.is_archived:
        raise ValidationError(f'Equipment {equipment.name!r} is archived and cannot have new repair records')

    if severity is not None and severity not in REPAIR_SEVERITIES:
        raise ValidationError(f'Invalid severity: {severity!r}')

    # Snapshot assignee scalars BEFORE the commit below. The new_report
    # notification block runs after db.session.commit(), and with
    # expire_on_commit=True reading .username/.email/.slack_handle off the ORM
    # User there would each trigger a refresh SELECT (mirrors update_repair_record).
    assignee_fields = None
    if assignee_id is not None:
        assignee = db.session.get(User, assignee_id)
        if assignee is None:
            raise ValidationError(f'User with id {assignee_id} not found')
        assignee_fields = _assignee_payload_fields(assignee)

    record = RepairRecord(
        equipment_id=equipment_id,
        description=description.strip(),
        status='New',
        severity=severity,
        reporter_name=reporter_name,
        reporter_email=reporter_email,
        assignee_id=assignee_id,
        has_safety_risk=has_safety_risk,
        is_consumable=is_consumable,
    )
    db.session.add(record)
    db.session.flush()

    # Create timeline creation entry
    timeline_entry = RepairTimelineEntry(
        repair_record_id=record.id,
        entry_type='creation',
        author_id=author_id,
        author_name=reporter_name or created_by,
        content=description.strip(),
    )
    db.session.add(timeline_entry)

    # Create audit log entry
    audit_entry = AuditLog(
        entity_type='repair_record',
        entity_id=record.id,
        action='created',
        user_id=author_id,
        changes={
            'equipment_id': equipment_id,
            'status': 'New',
            'severity': severity,
            'description': description.strip(),
        },
    )
    db.session.add(audit_entry)

    db.session.commit()

    log_mutation('repair_record.created', created_by, {
        'id': record.id,
        'equipment_id': record.equipment_id,
        'status': record.status,
        'severity': record.severity,
        'description': record.description,
        'reporter_name': record.reporter_name,
    })

    # Queue static page regeneration (new repair affects equipment status)
    from esb.services import notification_service
    notification_service.queue_notification(
        notification_type='static_page_push',
        target='status_change',
        payload={'trigger': 'repair_record_created', 'equipment_id': equipment_id},
    )

    # Queue Slack notification if new_report trigger is enabled
    from esb.services import config_service
    if config_service.get_config('notify_new_report', 'true') == 'true':
        new_report_payload = {
            'severity': severity,
            'description': description.strip(),
            'reporter_name': reporter_name,
            'has_safety_risk': has_safety_risk,
        }
        # When the repair is created already assigned, carry the assignee
        # identity so the new_report message gains an "Assigned to:" line.
        # Creation has no previous assignee, so old_assignee_username is None.
        # Uses the scalars snapshotted before commit (see assignee_fields above).
        if assignee_fields is not None:
            new_report_payload['old_assignee_username'] = None
            new_report_payload.update(assignee_fields)
        _queue_slack_notification(equipment, 'new_report', new_report_payload)

    return record


def get_repair_record(repair_record_id: int) -> RepairRecord:
    """Get a repair record by ID.

    Raises:
        ValidationError: if not found.
    """
    record = db.session.get(RepairRecord, repair_record_id)
    if record is None:
        raise ValidationError(f'Repair record with id {repair_record_id} not found')
    return record


def list_repair_records(
    equipment_id: int | None = None,
    status: str | None = None,
    eager_load_assignee: bool = False,
) -> list[RepairRecord]:
    """List repair records, optionally filtered.

    Args:
        equipment_id: Filter by equipment ID.
        status: Filter by status.
        eager_load_assignee: If True, join-load the assignee relationship to
            avoid N+1 queries when the caller will access ``record.assignee``
            for every row (e.g. the equipment-detail history table).

    Returns:
        List of RepairRecord instances ordered by created_at desc.
    """
    query = db.select(RepairRecord).order_by(RepairRecord.created_at.desc())
    if eager_load_assignee:
        query = query.options(joinedload(RepairRecord.assignee))
    if equipment_id is not None:
        query = query.filter_by(equipment_id=equipment_id)
    if status is not None:
        query = query.filter_by(status=status)
    scalars = db.session.execute(query).scalars()
    if eager_load_assignee:
        scalars = scalars.unique()
    return list(scalars.all())


def list_duplicate_candidates(repair_record_id: int) -> list[RepairRecord]:
    """Return same-equipment repair records (excluding self), newest first.

    Raises:
        ValidationError: if ``repair_record_id`` does not exist.
    """
    record = get_repair_record(repair_record_id)
    query = (
        db.select(RepairRecord)
        .filter(RepairRecord.equipment_id == record.equipment_id)
        .filter(RepairRecord.id != record.id)
        .order_by(RepairRecord.created_at.desc())
    )
    return list(db.session.execute(query).scalars().all())


CLOSED_STATUSES = ('Resolved', 'Closed - No Issue Found', 'Closed - Duplicate')

KANBAN_COLUMNS = [s for s in REPAIR_STATUSES if s not in CLOSED_STATUSES]


def claim_repair_record(
    repair_record_id: int,
    claimed_by_user_id: int,
    claimed_by_username: str,
) -> RepairRecord:
    """Claim a repair record for the given user.

    Sets ``assignee_id`` to ``claimed_by_user_id`` always. As a status
    transition rule (issue #34), if the record's current status is
    ``'New'``, the claim also promotes status to ``'Assigned'``; on any
    later open status (``'Assigned'``, ``'In Progress'``, ``'Parts Needed'``,
    ``'Parts Ordered'``, ``'Parts Received'``, ``'Needs Specialist'``),
    the status is left untouched -- claim is purely an assignee swap.

    Closed records cannot be claimed; this function raises
    ``ValidationError`` if the record's current status is in
    ``CLOSED_STATUSES``. (The dispatcher view handler also pre-checks
    this for a friendlier error path; the service-level enforcement is
    here so other callers can't bypass it.)

    Args:
        repair_record_id: ID of the RepairRecord to claim.
        claimed_by_user_id: ESB user id of the claiming user.
        claimed_by_username: Username of the claiming user (for timeline
            entry attribution).

    Returns:
        The updated RepairRecord.

    Raises:
        ValidationError: if the record doesn't exist, the claiming user
            doesn't exist, or the record is in a closed status.
    """
    user = db.session.get(User, claimed_by_user_id)
    if user is None:
        raise ValidationError(f'User with id {claimed_by_user_id} not found')
    record = get_repair_record(repair_record_id)
    if record.status in CLOSED_STATUSES:
        raise ValidationError(
            f'Cannot claim repair record {repair_record_id}: '
            f'status {record.status!r} is closed',
        )
    changes: dict = {'assignee_id': claimed_by_user_id}
    if record.status == 'New':
        changes['status'] = 'Assigned'
    return update_repair_record(
        repair_record_id=repair_record_id,
        updated_by=claimed_by_username,
        author_id=claimed_by_user_id,
        **changes,
    )


def resolve_repair_record(
    repair_record_id: int,
    resolved_by_user_id: int,
    resolved_by_username: str,
    note: str,
) -> RepairRecord:
    """Resolve a repair record with a required note.

    Validates inputs in order: note non-empty, user exists, record
    exists and is open. Then sets status='Resolved' and appends the
    note as a timeline entry in the same transaction via
    update_repair_record. The 'resolved' Slack notification fires
    automatically via the existing trigger in update_repair_record.

    UI-level rule that 'New' records should be claimed before resolve
    is NOT enforced here -- the service contract is permissive so
    both Slack's dispatcher and the web UI can layer their own
    conventions. Resolves from 'New' are allowed.

    Args:
        repair_record_id: ID of the RepairRecord to resolve.
        resolved_by_user_id: ESB user id of the resolving user. Must
            reference an existing User.
        resolved_by_username: Username (for timeline-entry attribution).
        note: Resolution note. Required; whitespace-only is rejected.

    Returns:
        The updated RepairRecord.

    Raises:
        ValidationError: if note is empty/whitespace-only, the user
            does not exist, the record does not exist, or the record
            is already closed.
    """
    # Reject empty / whitespace-only / zero-width-only / control-only notes.
    # Python's str.strip() is Unicode-aware for whitespace (covers NBSP,
    # U+2000-U+200A, U+2028/2029, etc. — anything where ch.isspace() is
    # True). But it does NOT strip Unicode-category Cc (control) or Cf
    # (format) characters, which include zero-width space U+200B, ZWNJ
    # U+200C, ZWJ U+200D, BOM U+FEFF, ASCII NUL/control bytes, etc.
    # A note like '​​​' or '\x00\x01' would pass a bare
    # str.strip() check but be visually empty. So we walk the codepoints
    # explicitly looking for at least one "visible" character (anything
    # that is neither whitespace nor Cc/Cf).
    import unicodedata
    has_content = False
    if note:
        for ch in note:
            if ch.isspace():
                continue
            if unicodedata.category(ch) in ('Cc', 'Cf'):
                continue
            has_content = True
            break
    if not has_content:
        raise ValidationError('Resolution note is required')
    user = db.session.get(User, resolved_by_user_id)
    if user is None:
        raise ValidationError(f'User with id {resolved_by_user_id} not found')
    record = get_repair_record(repair_record_id)
    if record.status in CLOSED_STATUSES:
        raise ValidationError(
            f'Cannot resolve repair record {repair_record_id}: '
            f'status {record.status!r} is already closed',
        )
    return update_repair_record(
        repair_record_id=repair_record_id,
        updated_by=resolved_by_username,
        author_id=resolved_by_user_id,
        status='Resolved',
        note=note.strip(),
    )


def get_kanban_data() -> dict[str, list[RepairRecord]]:
    """Get open repair records grouped by status for the Kanban board.

    Returns a dict of {status: [records]} where each record is annotated
    with a ``time_in_column`` attribute (float seconds). Records within
    each column are ordered oldest-time-in-column first.
    """
    now = datetime.now(UTC).replace(tzinfo=None)

    # Correlated scalar subquery: most recent status_change timestamp
    # where new_value matches the record's current status.
    latest_status_change = (
        db.select(func.max(RepairTimelineEntry.created_at))
        .filter(
            RepairTimelineEntry.repair_record_id == RepairRecord.id,
            RepairTimelineEntry.entry_type == 'status_change',
            RepairTimelineEntry.new_value == RepairRecord.status,
        )
        .correlate(RepairRecord)
        .scalar_subquery()
        .label('last_change')
    )

    records = (
        db.session.execute(
            db.select(
                RepairRecord,
                latest_status_change,
            )
            .join(RepairRecord.equipment)
            .join(Equipment.area)
            .options(
                joinedload(RepairRecord.equipment).joinedload(Equipment.area),
                joinedload(RepairRecord.assignee),
            )
            .filter(RepairRecord.status.notin_(CLOSED_STATUSES))
        )
        .unique()
        .all()
    )

    result: dict[str, list[RepairRecord]] = {col: [] for col in KANBAN_COLUMNS}

    for record, last_change in records:
        ref_time = last_change if last_change is not None else record.created_at
        record.time_in_column = (now - ref_time).total_seconds()
        if record.status in result:
            result[record.status].append(record)

    for col in result:
        result[col].sort(key=lambda r: r.time_in_column, reverse=True)

    return result


_SEVERITY_PRIORITY = case(
    (RepairRecord.severity == 'Down', 0),
    (RepairRecord.severity == 'Degraded', 1),
    (RepairRecord.severity == 'Not Sure', 2),
    else_=3,
)


def get_repair_queue(
    area_id: int | None = None,
    status: str | None = None,
    assignee_id: int | None = None,
    unassigned: bool = False,
) -> list[RepairRecord]:
    """Get open repair records for the technician queue.

    Returns records whose status is not in CLOSED_STATUSES, with eager-loaded
    equipment and area relationships. Default sort: severity priority (Down
    first) then age (oldest first via created_at ASC).

    Args:
        area_id: Optional filter by equipment's area ID.
        status: Optional filter by repair record status.
        assignee_id: Optional filter to records assigned to this user ID.
        unassigned: When True, filter to records where assignee_id IS NULL.
            Mutually exclusive with assignee_id; raises ValidationError if
            both are non-default.

    Returns:
        List of RepairRecord instances.

    Raises:
        ValidationError: if both `assignee_id` and `unassigned=True` are
            passed simultaneously (mutually exclusive filters).
    """
    if assignee_id is not None and unassigned:
        raise ValidationError(
            'Cannot filter by both assignee_id and unassigned simultaneously',
        )
    query = (
        db.select(RepairRecord)
        .join(RepairRecord.equipment)
        .join(Equipment.area)
        .options(
            joinedload(RepairRecord.equipment).joinedload(Equipment.area),
            joinedload(RepairRecord.assignee),
        )
        .filter(RepairRecord.status.notin_(CLOSED_STATUSES))
        .order_by(_SEVERITY_PRIORITY, RepairRecord.created_at.asc())
    )
    if area_id is not None:
        query = query.filter(Equipment.area_id == area_id)
    if status is not None:
        query = query.filter(RepairRecord.status == status)
    if assignee_id is not None:
        query = query.filter(RepairRecord.assignee_id == assignee_id)
    elif unassigned:
        query = query.filter(RepairRecord.assignee_id.is_(None))
    return list(
        db.session.execute(query).scalars().unique().all()
    )


def update_repair_record(
    repair_record_id: int,
    updated_by: str,
    author_id: int | None = None,
    **changes,
) -> RepairRecord:
    """Update a repair record and create timeline entries for each change.

    Accepts keyword arguments for any updatable field. Only fields that
    actually differ from the current value will generate timeline entries.

    Updatable fields:
        status (str): New status value. Must be in REPAIR_STATUSES.
        severity (str | None): New severity value. Must be in REPAIR_SEVERITIES or None.
        assignee_id (int | None): New assignee user ID, or None to unassign.
        eta (date | None): New ETA date, or None to clear.
        specialist_description (str | None): Free-text description for specialist needs.
        duplicated_repair_id (int | None): Repair this record duplicates. Must be a
            different record on the same equipment. Required iff status is
            ``'Closed - Duplicate'``. Transitioning status away from
            ``'Closed - Duplicate'`` clears this field (silently when the kwarg
            is omitted by the caller; the web edit flow forces None explicitly).
            Cannot be set non-None when status is anything other than
            ``'Closed - Duplicate'``. See module-level docs for full rules.
        note (str | None): Optional note text to add to timeline.

    Returns:
        The updated RepairRecord.

    Raises:
        ValidationError: if repair record not found, or invalid field values.
    """
    record = db.session.get(RepairRecord, repair_record_id)
    if record is None:
        raise ValidationError(f'Repair record with id {repair_record_id} not found')

    # Validate incoming values
    if 'status' in changes and changes['status'] not in REPAIR_STATUSES:
        raise ValidationError(f'Invalid status: {changes["status"]!r}')
    if 'severity' in changes and changes['severity'] is not None and changes['severity'] not in REPAIR_SEVERITIES:
        raise ValidationError(f'Invalid severity: {changes["severity"]!r}')
    if 'assignee_id' in changes and changes['assignee_id'] is not None:
        assignee = db.session.get(User, changes['assignee_id'])
        if assignee is None:
            raise ValidationError(f'User with id {changes["assignee_id"]} not found')

    # duplicated_repair_id validation -- keyed on real *status transitions*,
    # not idempotent form re-submissions. See tech-spec Technical Decisions §3.
    effective_dup_id = changes.get('duplicated_repair_id', record.duplicated_repair_id)
    effective_status = changes.get('status', record.status)
    transitioning_to_closed_dup = (
        'status' in changes
        and changes['status'] == 'Closed - Duplicate'
        and record.status != 'Closed - Duplicate'
    )
    setting_dup_explicit = (
        'duplicated_repair_id' in changes
        and changes['duplicated_repair_id'] is not None
        and changes['duplicated_repair_id'] != record.duplicated_repair_id
    )
    transitioning_away_from_closed_dup = (
        'status' in changes
        and changes['status'] != 'Closed - Duplicate'
        and record.status == 'Closed - Duplicate'
    )

    if transitioning_to_closed_dup and effective_dup_id is None:
        raise ValidationError(
            "'Closed - Duplicate' status requires a duplicated_repair_id",
        )
    # Forbid clearing an existing dup_id to NULL while status stays Closed - Duplicate.
    # The legacy carve-out (record.duplicated_repair_id is None) is preserved so
    # legacy rows with NULL dup_id can still be edited for unrelated fields.
    if (
        effective_status == 'Closed - Duplicate'
        and 'duplicated_repair_id' in changes
        and changes['duplicated_repair_id'] is None
        and record.duplicated_repair_id is not None
    ):
        raise ValidationError(
            "'Closed - Duplicate' status requires a duplicated_repair_id",
        )
    if setting_dup_explicit and effective_status != 'Closed - Duplicate':
        raise ValidationError(
            "duplicated_repair_id may only be set when status is 'Closed - Duplicate'",
        )
    if transitioning_to_closed_dup or setting_dup_explicit:
        target_id = effective_dup_id
        if target_id == repair_record_id:
            raise ValidationError('A repair cannot be a duplicate of itself')
        target = db.session.get(RepairRecord, target_id)
        if target is None:
            raise ValidationError(f'Duplicated repair {target_id} not found')
        if target.equipment_id != record.equipment_id:
            raise ValidationError(
                'Duplicated repair must be on the same equipment',
            )

    # Silent clear for callers that pass status but omit duplicated_repair_id
    # when transitioning away from Closed - Duplicate. The web edit flow does
    # NOT rely on this path -- it explicitly forces duplicated_repair_id=None
    # at the view layer so the per-field loop handles the clear deterministically.
    # This branch protects future callers (CLI, REST) that send a partial update.
    if (
        transitioning_away_from_closed_dup
        and record.duplicated_repair_id is not None
        and 'duplicated_repair_id' not in changes
    ):
        changes['duplicated_repair_id'] = None

    # Extract note separately (not a model field)
    note = changes.pop('note', None)

    # Validate no unknown keys were passed
    unknown_keys = set(changes.keys()) - set(_REPAIR_UPDATABLE_FIELDS)
    if unknown_keys:
        raise ValidationError(f'Unknown fields: {", ".join(sorted(unknown_keys))}')

    # Detect changes and create timeline entries
    audit_changes = {}
    # Capture assignee identity as plain scalars (NOT ORM objects) inside the
    # assignee_id branch below. The Slack-notification block runs AFTER
    # db.session.commit(); with Flask-SQLAlchemy's default expire_on_commit=True,
    # reading .username/.email/.slack_handle off an ORM User there would each
    # trigger a refresh SELECT. Pre-initialized here so they are always bound.
    old_assignee_username = None
    new_assignee_fields = _assignee_payload_fields(None)
    for field_name in _REPAIR_UPDATABLE_FIELDS:
        if field_name not in changes:
            continue
        new_value = changes[field_name]
        old_value = getattr(record, field_name)
        if old_value == new_value:
            continue

        # Record the change
        audit_changes[field_name] = [_serialize(old_value), _serialize(new_value)]
        setattr(record, field_name, new_value)

        # Create appropriate timeline entry
        if field_name == 'status':
            db.session.add(RepairTimelineEntry(
                repair_record_id=record.id,
                entry_type='status_change',
                author_id=author_id,
                author_name=updated_by,
                old_value=str(old_value),
                new_value=str(new_value),
            ))
        elif field_name == 'assignee_id':
            old_user = db.session.get(User, old_value) if old_value else None
            new_user = db.session.get(User, new_value) if new_value else None
            # Snapshot scalars for the post-commit notification block (see note
            # at audit_changes init). Do NOT re-derive old assignee from
            # audit_changes['assignee_id'] -- those values are _serialize()'d strings.
            old_assignee_username = old_user.username if old_user else None
            new_assignee_fields = _assignee_payload_fields(new_user)
            db.session.add(RepairTimelineEntry(
                repair_record_id=record.id,
                entry_type='assignee_change',
                author_id=author_id,
                author_name=updated_by,
                old_value=old_user.username if old_user else None,
                new_value=new_user.username if new_user else None,
            ))
        elif field_name == 'eta':
            db.session.add(RepairTimelineEntry(
                repair_record_id=record.id,
                entry_type='eta_update',
                author_id=author_id,
                author_name=updated_by,
                old_value=str(old_value) if old_value else None,
                new_value=str(new_value) if new_value else None,
            ))
        elif field_name == 'duplicated_repair_id':
            db.session.add(RepairTimelineEntry(
                repair_record_id=record.id,
                entry_type='duplicated_repair_id_change',
                author_id=author_id,
                author_name=updated_by,
                old_value=str(old_value) if old_value is not None else None,
                new_value=str(new_value) if new_value is not None else None,
            ))

    # Create note timeline entry if note provided
    if note and note.strip():
        db.session.add(RepairTimelineEntry(
            repair_record_id=record.id,
            entry_type='note',
            author_id=author_id,
            author_name=updated_by,
            content=note.strip(),
        ))
        audit_changes['note'] = [None, note.strip()]

    # Create audit log entry
    if audit_changes:
        db.session.add(AuditLog(
            entity_type='repair_record',
            entity_id=record.id,
            action='updated',
            user_id=author_id,
            changes=audit_changes,
        ))

    db.session.commit()

    if audit_changes:
        log_mutation('repair_record.updated', updated_by, {
            'id': record.id,
            'changes': audit_changes,
        })

    # Queue static page regeneration if status-affecting fields changed
    if any(k in audit_changes for k in ('status', 'severity', 'eta')):
        from esb.services import notification_service
        notification_service.queue_notification(
            notification_type='static_page_push',
            target='status_change',
            payload={
                'trigger': 'repair_record_updated',
                'equipment_id': record.equipment_id,
                'changes': list(audit_changes.keys()),
            },
        )

    # Queue Slack notifications based on trigger configuration
    if audit_changes:
        from esb.services import config_service

        # Assignee delta (None unless the assignee actually changed in this
        # update). The scalars were snapshotted in the audit loop above.
        if 'assignee_id' in audit_changes:
            assignee_delta = {'old_assignee_username': old_assignee_username, **new_assignee_fields}
        else:
            assignee_delta = None

        # Status/assignee notification chain (single if/elif keyed on status).
        # The severity/eta branches below are INDEPENDENT and still fire on top.
        if 'status' in audit_changes and audit_changes['status'][1] in CLOSED_STATUSES:
            # Closed transition: resolved only -- assignee info never added,
            # assignee_changed never queued (even if assignee also changed).
            if config_service.get_config('notify_resolved', 'true') == 'true':
                _queue_slack_notification(record.equipment, 'resolved', {
                    'old_status': audit_changes['status'][0],
                    'new_status': audit_changes['status'][1],
                })
        elif 'status' in audit_changes:
            # Open transition. Enrich status_changed with the assignee delta when
            # one is present; fall through to assignee_changed if status_changed
            # is suppressed so assignment visibility is governed by its own toggle.
            if config_service.get_config('notify_status_changed', 'true') == 'true':
                status_payload = {
                    'old_status': audit_changes['status'][0],
                    'new_status': audit_changes['status'][1],
                }
                if assignee_delta is not None:
                    status_payload.update(assignee_delta)
                _queue_slack_notification(record.equipment, 'status_changed', status_payload)
            elif assignee_delta is not None and (
                config_service.get_config('notify_assignee_changed', 'true') == 'true'
            ):
                _queue_slack_notification(record.equipment, 'assignee_changed', assignee_delta)
        elif assignee_delta is not None:
            # Assignee changed with NO status change in the update. Guarded as the
            # elif tail of the status-keyed chain so it can never double-fire
            # alongside resolved or an enriched status_changed.
            if config_service.get_config('notify_assignee_changed', 'true') == 'true':
                _queue_slack_notification(record.equipment, 'assignee_changed', assignee_delta)

        # Severity changed trigger
        if 'severity' in audit_changes:
            if config_service.get_config('notify_severity_changed', 'true') == 'true':
                _queue_slack_notification(record.equipment, 'severity_changed', {
                    'old_severity': audit_changes['severity'][0],
                    'new_severity': audit_changes['severity'][1],
                })

        # ETA updated trigger
        if 'eta' in audit_changes:
            if config_service.get_config('notify_eta_updated', 'true') == 'true':
                _queue_slack_notification(record.equipment, 'eta_updated', {
                    'eta': str(audit_changes['eta'][1]) if audit_changes['eta'][1] else None,
                    'old_eta': str(audit_changes['eta'][0]) if audit_changes['eta'][0] else None,
                })

    return record


def add_repair_note(
    repair_record_id: int,
    note: str,
    author_name: str,
    author_id: int | None = None,
) -> RepairTimelineEntry:
    """Add a note to a repair record's timeline.

    Args:
        repair_record_id: ID of the repair record.
        note: Text content of the note.
        author_name: Username of the person adding the note.
        author_id: User ID of the author (None for system notes).

    Returns:
        The created RepairTimelineEntry.

    Raises:
        ValidationError: if repair record not found or note is empty.
    """
    if not note or not note.strip():
        raise ValidationError('Note text is required')

    record = db.session.get(RepairRecord, repair_record_id)
    if record is None:
        raise ValidationError(f'Repair record with id {repair_record_id} not found')

    entry = RepairTimelineEntry(
        repair_record_id=record.id,
        entry_type='note',
        author_id=author_id,
        author_name=author_name,
        content=note.strip(),
    )
    db.session.add(entry)

    db.session.add(AuditLog(
        entity_type='repair_record',
        entity_id=record.id,
        action='note_added',
        user_id=author_id,
        changes={'note': note.strip()},
    ))

    db.session.commit()

    log_mutation('repair_record.note_added', author_name, {
        'id': record.id,
        'note': note.strip(),
    })

    return entry


def add_repair_photo(
    repair_record_id: int,
    file,
    author_name: str,
    author_id: int | None = None,
) -> tuple[Document, RepairTimelineEntry]:
    """Upload a photo to a repair record and add a timeline entry.

    Args:
        repair_record_id: ID of the repair record.
        file: Werkzeug FileStorage object from the form.
        author_name: Username of the person uploading.
        author_id: User ID of the uploader.

    Returns:
        Tuple of (Document, RepairTimelineEntry).

    Raises:
        ValidationError: if repair record not found or file invalid.
    """
    from esb.services import upload_service

    record = db.session.get(RepairRecord, repair_record_id)
    if record is None:
        raise ValidationError(f'Repair record with id {repair_record_id} not found')

    doc = upload_service.save_upload(
        file=file,
        parent_type='repair_photo',
        parent_id=record.id,
        uploaded_by=author_name,
    )

    entry = RepairTimelineEntry(
        repair_record_id=record.id,
        entry_type='photo',
        author_id=author_id,
        author_name=author_name,
        content=str(doc.id),
    )
    db.session.add(entry)

    db.session.add(AuditLog(
        entity_type='repair_record',
        entity_id=record.id,
        action='photo_added',
        user_id=author_id,
        changes={
            'document_id': doc.id,
            'filename': doc.original_filename,
        },
    ))

    db.session.commit()

    log_mutation('repair_record.photo_added', author_name, {
        'id': record.id,
        'document_id': doc.id,
        'filename': doc.original_filename,
    })

    return doc, entry
