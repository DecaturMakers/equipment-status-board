"""Equipment service layer for area management and equipment CRUD.

All area/equipment business logic lives here. Views call these functions;
they never query models directly.
"""

import csv
import io
from datetime import date
from decimal import Decimal

from sqlalchemy.orm import joinedload

from esb.extensions import db
from esb.models.area import Area
from esb.models.equipment import Equipment
from esb.models.equipment_note import EquipmentNote
from esb.models.external_link import ExternalLink
from esb.utils.exceptions import ValidationError
from esb.utils.logging import log_mutation


def list_areas() -> list[Area]:
    """Return all active (non-archived) areas ordered by ``(sort_order, name)``."""
    return list(
        db.session.execute(
            db.select(Area).filter_by(is_archived=False).order_by(Area.sort_order, Area.name)
        ).scalars().all()
    )


def get_area(area_id: int) -> Area:
    """Get a single area by ID.

    Raises:
        ValidationError: if area not found.
    """
    area = db.session.get(Area, area_id)
    if area is None:
        raise ValidationError(f'Area with id {area_id} not found')
    return area


def get_area_by_name(name: str | None) -> Area | None:
    """Look up a non-archived area by exact (case-insensitive) name.

    The input is stripped of leading/trailing whitespace before comparison
    because callers (e.g., Slack slash command bodies) provide unsanitized
    text -- unlike the validated Flask-WTF inputs used by create_area /
    update_area, which the form layer trims for us.

    Args:
        name: Candidate area name. Whitespace-only or empty input returns None.

    Returns:
        The Area instance if a non-archived area matches the trimmed name
        case-insensitively, otherwise None. Does not raise on miss.
    """
    if name is None:
        return None
    stripped = name.strip()
    if not stripped:
        return None
    return db.session.execute(
        db.select(Area).filter(
            db.func.lower(Area.name) == stripped.lower(),
            Area.is_archived.is_(False),
        )
    ).scalar_one_or_none()


def create_area(name: str, slack_channel: str, created_by: str, sort_order: int = 0) -> Area:
    """Create a new area.

    Raises:
        ValidationError: if name already exists (case-insensitive).
    """
    existing = db.session.execute(
        db.select(Area).filter(db.func.lower(Area.name) == name.lower())
    ).scalar_one_or_none()
    if existing is not None:
        if existing.is_archived:
            raise ValidationError(f'An archived area with name {name!r} already exists')
        raise ValidationError(f'An area with name {name!r} already exists')

    area = Area(name=name, slack_channel=slack_channel, sort_order=sort_order)
    db.session.add(area)
    db.session.commit()

    log_mutation('area.created', created_by, {
        'id': area.id,
        'name': area.name,
        'slack_channel': area.slack_channel,
        'sort_order': area.sort_order,
    })

    return area


def update_area(
    area_id: int,
    name: str,
    slack_channel: str,
    updated_by: str,
    *,
    sort_order: int | None = None,
) -> Area:
    """Update an area.

    Raises:
        ValidationError: if area not found or name conflicts with another area.
    """
    area = db.session.get(Area, area_id)
    if area is None:
        raise ValidationError(f'Area with id {area_id} not found')

    existing = db.session.execute(
        db.select(Area).filter(
            db.func.lower(Area.name) == name.lower(),
            Area.id != area_id,
        )
    ).scalar_one_or_none()
    if existing is not None:
        if existing.is_archived:
            raise ValidationError(f'An archived area with name {name!r} already exists')
        raise ValidationError(f'An area with name {name!r} already exists')

    changes = {}
    if area.name != name:
        changes['name'] = [area.name, name]
        area.name = name
    if area.slack_channel != slack_channel:
        changes['slack_channel'] = [area.slack_channel, slack_channel]
        area.slack_channel = slack_channel
    if sort_order is not None:
        if area.sort_order != sort_order:
            changes['sort_order'] = [area.sort_order, sort_order]
            area.sort_order = sort_order

    db.session.commit()

    if changes:
        log_mutation('area.updated', updated_by, {
            'id': area.id,
            'name': area.name,
            'slack_channel': area.slack_channel,
            'changes': changes,
        })

    return area


def archive_area(area_id: int, archived_by: str) -> Area:
    """Soft-delete an area.

    Raises:
        ValidationError: if area not found or already archived.
    """
    area = db.session.get(Area, area_id)
    if area is None:
        raise ValidationError(f'Area with id {area_id} not found')

    if area.is_archived:
        raise ValidationError(f'Area {area.name!r} is already archived')

    area.is_archived = True
    db.session.commit()

    log_mutation('area.archived', archived_by, {
        'id': area.id,
        'name': area.name,
    })

    return area


def archive_equipment(equipment_id: int, archived_by: str) -> Equipment:
    """Soft-delete an equipment record.

    Raises:
        ValidationError: if equipment not found or already archived.
    """
    equipment = db.session.get(Equipment, equipment_id)
    if equipment is None:
        raise ValidationError(f'Equipment with id {equipment_id} not found')

    if equipment.is_archived:
        raise ValidationError(f'Equipment {equipment.name!r} is already archived')

    equipment.is_archived = True
    db.session.commit()

    log_mutation('equipment.archived', archived_by, {
        'id': equipment.id,
        'name': equipment.name,
    })

    return equipment


# --- Equipment CRUD ---


def list_equipment(area_id: int | None = None) -> list[Equipment]:
    """Return all active (non-archived) equipment, optionally filtered by area.

    Args:
        area_id: If provided, filter to equipment in this area only.
    """
    query = db.select(Equipment).filter_by(is_archived=False).order_by(Equipment.name)
    if area_id is not None:
        query = query.filter_by(area_id=area_id)
    return list(db.session.execute(query).scalars().all())


def get_equipment(equipment_id: int) -> Equipment:
    """Get a single equipment record by ID.

    Raises:
        ValidationError: if equipment not found.
    """
    equipment = db.session.get(Equipment, equipment_id)
    if equipment is None:
        raise ValidationError(f'Equipment with id {equipment_id} not found')
    return equipment


def get_equipment_display_name(equipment_id: int) -> str:
    """Return an equipment name for user-facing messages, with an ID fallback."""
    equipment = db.session.get(Equipment, equipment_id)
    return equipment.name if equipment else f'ID {equipment_id}'


def create_equipment(
    name: str,
    manufacturer: str,
    model: str,
    area_id: int,
    created_by: str,
    serial_number: str | None = None,
    acquisition_date: date | None = None,
    acquisition_source: str | None = None,
    acquisition_cost: Decimal | None = None,
    warranty_expiration: date | None = None,
    description: str | None = None,
) -> Equipment:
    """Create a new equipment record.

    Raises:
        ValidationError: if area_id is invalid or required fields are missing.
    """
    if not name or not name.strip():
        raise ValidationError('Name is required')
    if not manufacturer or not manufacturer.strip():
        raise ValidationError('Manufacturer is required')
    if not model or not model.strip():
        raise ValidationError('Model is required')

    area = db.session.get(Area, area_id)
    if area is None:
        raise ValidationError(f'Area with id {area_id} not found')
    if area.is_archived:
        raise ValidationError(f'Area {area.name!r} is archived and cannot be used')

    equipment = Equipment(
        name=name.strip(),
        manufacturer=manufacturer.strip(),
        model=model.strip(),
        area_id=area_id,
        serial_number=serial_number,
        acquisition_date=acquisition_date,
        acquisition_source=acquisition_source,
        acquisition_cost=acquisition_cost,
        warranty_expiration=warranty_expiration,
        description=description,
    )
    db.session.add(equipment)
    db.session.commit()

    data = {
        'id': equipment.id,
        'name': equipment.name,
        'manufacturer': equipment.manufacturer,
        'model': equipment.model,
        'area_id': equipment.area_id,
    }
    if serial_number:
        data['serial_number'] = serial_number
    if acquisition_date:
        data['acquisition_date'] = str(acquisition_date)
    if acquisition_source:
        data['acquisition_source'] = acquisition_source
    if acquisition_cost is not None:
        data['acquisition_cost'] = str(acquisition_cost)
    if warranty_expiration:
        data['warranty_expiration'] = str(warranty_expiration)
    if description:
        data['description'] = description

    log_mutation('equipment.created', created_by, data)

    return equipment


_UPDATABLE_FIELDS = {
    'name', 'manufacturer', 'model', 'area_id', 'serial_number',
    'acquisition_date', 'acquisition_source', 'acquisition_cost',
    'warranty_expiration', 'description',
}


def update_equipment(
    equipment_id: int,
    updated_by: str,
    **fields,
) -> Equipment:
    """Update an equipment record.

    Raises:
        ValidationError: if equipment not found or validation fails.
    """
    equipment = db.session.get(Equipment, equipment_id)
    if equipment is None:
        raise ValidationError(f'Equipment with id {equipment_id} not found')

    # Validate required fields if being changed
    for required_field in ('name', 'manufacturer', 'model'):
        if required_field in fields:
            value = fields[required_field]
            if not value or not str(value).strip():
                raise ValidationError(f'{required_field.capitalize()} is required')

    # Validate area_id if being changed
    if 'area_id' in fields:
        new_area_id = fields['area_id']
        if new_area_id != equipment.area_id:
            area = db.session.get(Area, new_area_id)
            if area is None:
                raise ValidationError(f'Area with id {new_area_id} not found')
            if area.is_archived:
                raise ValidationError(f'Area {area.name!r} is archived and cannot be used')

    changes = {}
    for field_name in _UPDATABLE_FIELDS:
        if field_name not in fields:
            continue
        new_value = fields[field_name]
        old_value = getattr(equipment, field_name)
        if old_value != new_value:
            changes[field_name] = [old_value, new_value]
            setattr(equipment, field_name, new_value)

    db.session.commit()

    if changes:
        # Serialize non-JSON-safe types (date, Decimal) for mutation log
        serialized_changes = {}
        for field_name, (old_val, new_val) in changes.items():
            serialized_changes[field_name] = [
                str(old_val) if isinstance(old_val, (date, Decimal)) else old_val,
                str(new_val) if isinstance(new_val, (date, Decimal)) else new_val,
            ]
        log_mutation('equipment.updated', updated_by, {
            'id': equipment.id,
            'name': equipment.name,
            'changes': serialized_changes,
        })

    return equipment


# --- External Links ---


def add_equipment_link(
    equipment_id: int, title: str, url: str, created_by: str,
) -> ExternalLink:
    """Add an external link to an equipment record.

    Raises:
        ValidationError: if equipment not found or fields invalid.
    """
    equipment = db.session.get(Equipment, equipment_id)
    if equipment is None:
        raise ValidationError(f'Equipment with id {equipment_id} not found')

    if not title or not title.strip():
        raise ValidationError('Title is required')
    if not url or not url.strip():
        raise ValidationError('URL is required')

    link = ExternalLink(
        equipment_id=equipment_id,
        title=title.strip(),
        url=url.strip(),
        created_by=created_by,
    )
    db.session.add(link)
    db.session.commit()

    log_mutation('equipment_link.created', created_by, {
        'id': link.id,
        'equipment_id': link.equipment_id,
        'title': link.title,
        'url': link.url,
    })

    return link


def delete_equipment_link(
    link_id: int, deleted_by: str, *, equipment_id: int | None = None,
) -> None:
    """Delete an external link.

    Args:
        link_id: ID of the ExternalLink to delete.
        deleted_by: Username performing the deletion.
        equipment_id: If provided, verify link belongs to this equipment.

    Raises:
        ValidationError: if link not found or ownership mismatch.
    """
    link = db.session.get(ExternalLink, link_id)
    if link is None:
        raise ValidationError(f'Link with id {link_id} not found')
    if equipment_id is not None and link.equipment_id != equipment_id:
        raise ValidationError(f'Link with id {link_id} not found')

    log_data = {
        'id': link.id,
        'equipment_id': link.equipment_id,
        'title': link.title,
    }

    db.session.delete(link)
    db.session.commit()

    log_mutation('equipment_link.deleted', deleted_by, log_data)


def search_equipment_by_name(search_term: str) -> list[Equipment]:
    """Search for non-archived equipment by name (case-insensitive partial match).

    Args:
        search_term: Search string to match against equipment names.

    Returns:
        List of matching Equipment instances, ordered by name.
    """
    # Escape SQL LIKE wildcards so user input is matched literally
    escaped = search_term.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
    return list(
        db.session.execute(
            db.select(Equipment)
            .filter(
                Equipment.is_archived.is_(False),
                Equipment.name.ilike(f'%{escaped}%', escape='\\'),
            )
            .order_by(Equipment.name)
        ).scalars().all()
    )


def get_equipment_links(equipment_id: int) -> list[ExternalLink]:
    """Get all external links for an equipment item, ordered by created_at desc."""
    return list(
        db.session.execute(
            db.select(ExternalLink)
            .filter_by(equipment_id=equipment_id)
            .order_by(ExternalLink.created_at.desc())
        ).scalars().all()
    )


# --- Equipment Notes ---

# Max stored note length. The service (authoritative) rejects content whose
# stripped length exceeds this; EquipmentNoteForm reuses this constant for a
# friendly pre-check that measures the same stripped length. Keep in sync here.
NOTE_MAX_LENGTH = 5000


def add_equipment_note(
    equipment_id: int, content: str, author_id: int | None, author_name: str | None,
) -> EquipmentNote:
    """Add an append-only free-form note to an equipment record.

    Raises:
        ValidationError: if equipment not found, content is empty/whitespace,
            or content exceeds ``NOTE_MAX_LENGTH`` characters (after stripping).
    """
    equipment = db.session.get(Equipment, equipment_id)
    if equipment is None:
        raise ValidationError(f'Equipment with id {equipment_id} not found')

    if not content or not content.strip():
        raise ValidationError('Note content is required')

    stripped = content.strip()
    if len(stripped) > NOTE_MAX_LENGTH:
        raise ValidationError(f'Note is too long (max {NOTE_MAX_LENGTH} characters)')

    note = EquipmentNote(
        equipment_id=equipment_id,
        content=stripped,
        author_id=author_id,
        author_name=author_name,
    )
    db.session.add(note)
    db.session.commit()

    log_mutation('equipment_note.created', author_name or 'unknown', {
        'id': note.id,
        'equipment_id': note.equipment_id,
    })

    return note


def get_equipment_notes(equipment_id: int) -> list[EquipmentNote]:
    """Get all notes for an equipment item, newest-first with a stable id tiebreaker."""
    return list(
        db.session.execute(
            db.select(EquipmentNote)
            .filter_by(equipment_id=equipment_id)
            .order_by(EquipmentNote.created_at.desc(), EquipmentNote.id.desc())
        ).scalars().all()
    )


CSV_EXPORT_COLUMNS = [
    'id',
    'name',
    'manufacturer',
    'model',
    'serial_number',
    'area',
    'acquisition_date',
    'acquisition_source',
    'acquisition_cost',
    'warranty_expiration',
    'description',
    'is_archived',
    'created_at',
    'updated_at',
]

_CSV_INJECTION_TRIGGERS = ('=', '+', '-', '@')


def _sanitize_csv_cell(value):
    """Prefix formula-leading characters with a single quote to defuse Excel/LibreOffice injection.

    Spreadsheet apps ignore leading whitespace (including tabs and CRs) when
    deciding whether a cell is a formula, so detect the formula triggers after
    any leading whitespace while preserving the original string contents.
    """
    if isinstance(value, str) and value.lstrip().startswith(_CSV_INJECTION_TRIGGERS):
        return "'" + value
    return value


def export_equipment_csv(
    username: str,
    area_id: int | None = None,
    include_archived: bool = False,
) -> str:
    """Return CSV text of equipment inventory and emit an audit log entry.

    Args:
        username: User performing the export (recorded in the audit log).
        area_id: If provided, limit export to equipment in this area.
        include_archived: If True, include archived equipment in export.
    """
    query = (
        db.select(Equipment)
        .options(joinedload(Equipment.area))
        .order_by(Equipment.name)
    )
    if not include_archived:
        query = query.filter_by(is_archived=False)
    if area_id is not None:
        query = query.filter_by(area_id=area_id)
    equipment = list(db.session.execute(query).scalars().all())

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(CSV_EXPORT_COLUMNS)
    for eq in equipment:
        writer.writerow([
            eq.id,
            _sanitize_csv_cell(eq.name),
            _sanitize_csv_cell(eq.manufacturer),
            _sanitize_csv_cell(eq.model),
            _sanitize_csv_cell(eq.serial_number or ''),
            _sanitize_csv_cell(eq.area.name) if eq.area else '',
            eq.acquisition_date.isoformat() if eq.acquisition_date else '',
            _sanitize_csv_cell(eq.acquisition_source or ''),
            str(eq.acquisition_cost) if eq.acquisition_cost is not None else '',
            eq.warranty_expiration.isoformat() if eq.warranty_expiration else '',
            _sanitize_csv_cell(eq.description or ''),
            'true' if eq.is_archived else 'false',
            eq.created_at.isoformat() if eq.created_at else '',
            eq.updated_at.isoformat() if eq.updated_at else '',
        ])

    log_mutation('equipment.exported_csv', username, {
        'area_id': area_id,
        'include_archived': include_archived,
        'row_count': len(equipment),
    })

    return buf.getvalue()
