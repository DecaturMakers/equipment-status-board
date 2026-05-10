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
_REPAIR_UPDATABLE_FIELDS = ('status', 'severity', 'assignee_id', 'eta', 'specialist_description')


def _serialize(value):
    """Serialize a value for audit log JSON."""
    return str(value) if value is not None else None


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

    if assignee_id is not None:
        assignee = db.session.get(User, assignee_id)
        if assignee is None:
            raise ValidationError(f'User with id {assignee_id} not found')

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
        _queue_slack_notification(equipment, 'new_report', {
            'severity': severity,
            'description': description.strip(),
            'reporter_name': reporter_name,
            'has_safety_risk': has_safety_risk,
        })

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


CLOSED_STATUSES = ['Resolved', 'Closed - No Issue Found', 'Closed - Duplicate']

KANBAN_COLUMNS = [s for s in REPAIR_STATUSES if s not in CLOSED_STATUSES]


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
) -> list[RepairRecord]:
    """Get open repair records for the technician queue.

    Returns records whose status is not in CLOSED_STATUSES, with eager-loaded
    equipment and area relationships. Default sort: severity priority (Down
    first) then age (oldest first via created_at ASC).

    Args:
        area_id: Optional filter by equipment's area ID.
        status: Optional filter by repair record status.

    Returns:
        List of RepairRecord instances.
    """
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

    # Extract note separately (not a model field)
    note = changes.pop('note', None)

    # Validate no unknown keys were passed
    unknown_keys = set(changes.keys()) - set(_REPAIR_UPDATABLE_FIELDS)
    if unknown_keys:
        raise ValidationError(f'Unknown fields: {", ".join(sorted(unknown_keys))}')

    # Detect changes and create timeline entries
    audit_changes = {}
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

        # Resolved trigger: status changed to a resolved/closed status
        if 'status' in audit_changes and audit_changes['status'][1] in CLOSED_STATUSES:
            if config_service.get_config('notify_resolved', 'true') == 'true':
                _queue_slack_notification(record.equipment, 'resolved', {
                    'old_status': audit_changes['status'][0],
                    'new_status': audit_changes['status'][1],
                })

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
