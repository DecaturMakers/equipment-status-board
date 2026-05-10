"""Equipment status derivation service.

Single source of truth for computing equipment operational status
from open repair records.
"""

from esb.extensions import db
from esb.models.area import Area
from esb.models.equipment import Equipment
from esb.models.repair_record import RepairRecord
from esb.services.repair_service import CLOSED_STATUSES
from esb.utils.exceptions import AreaArchived, AreaNotFound, EquipmentNotFound

# Severity to status mapping: priority order (lower = higher priority)
_SEVERITY_STATUS = {
    'Down': ('red', 'Down', 0),
    'Degraded': ('yellow', 'Degraded', 1),
    'Not Sure': ('yellow', 'Degraded', 2),
}


def _get_open_records(equipment_id: int) -> list:
    """Query open (non-closed) repair records for an equipment item.

    Records are ordered by ``(created_at, id)`` ascending so callers (and
    the ``_derive_status_from_records()`` tie-break rule) see a fully
    deterministic order: the oldest open record wins on ties, with ``id``
    breaking the rare ``created_at``-collision case (e.g. two records
    inserted in the same second on a DB with second-precision timestamps).
    """
    return (
        db.session.execute(
            db.select(RepairRecord)
            .filter(
                RepairRecord.equipment_id == equipment_id,
                RepairRecord.status.notin_(CLOSED_STATUSES),
            )
            .order_by(RepairRecord.created_at, RepairRecord.id)
        )
        .scalars()
        .all()
    )


def _find_highest_severity_record(records: list):
    """Find the record with the highest severity priority.

    Returns the highest-severity record, or None if no severity matches
    or records is empty.
    """
    if not records:
        return None

    best_record = None
    best_priority = 999
    for record in records:
        sev = record.severity
        if sev in _SEVERITY_STATUS:
            priority = _SEVERITY_STATUS[sev][2]
            if priority < best_priority:
                best_priority = priority
                best_record = record

    return best_record


def _derive_status_from_records(records: list) -> dict:
    """Derive equipment status from a list of open repair records.

    Single source of truth for status derivation logic (AC #2).

    Args:
        records: List of open RepairRecord instances for one equipment item.
            Callers must pass records ordered by ``created_at`` ascending so
            the tie-break rule below is deterministic; ``_get_open_records()``
            and the dashboard prefetch queries already do this.

    Returns:
        dict with keys: color, label, issue_description, severity, eta.
        ``eta`` is the highest-severity open record's ETA (or ``None`` if
        empty or unset). When multiple records share the highest severity,
        the oldest record (earliest ``created_at``) wins.
    """
    if not records:
        return {
            'color': 'green',
            'label': 'Operational',
            'issue_description': None,
            'severity': None,
            'eta': None,
        }

    best_record = _find_highest_severity_record(records)

    if best_record is None:
        return {
            'color': 'yellow',
            'label': 'Degraded',
            'issue_description': records[0].description,
            'severity': None,
            'eta': records[0].eta,
        }

    color, label, _ = _SEVERITY_STATUS[best_record.severity]
    return {
        'color': color,
        'label': label,
        'issue_description': best_record.description,
        'severity': best_record.severity,
        'eta': best_record.eta,
    }


def compute_equipment_status(equipment_id: int) -> dict:
    """Compute equipment status from open repair records.

    Returns dict with keys:
        - color: 'green' | 'yellow' | 'red'
        - label: 'Operational' | 'Degraded' | 'Down'
        - issue_description: str | None (brief description from highest severity record)
        - severity: str | None (raw severity value from highest severity record)
        - eta: date | None (from highest severity record; oldest wins on ties)

    Raises:
        EquipmentNotFound: if equipment_id doesn't exist
    """
    equipment = db.session.get(Equipment, equipment_id)
    if equipment is None:
        raise EquipmentNotFound(f'Equipment with id {equipment_id} not found')

    return _derive_status_from_records(_get_open_records(equipment_id))


def get_equipment_status_detail(equipment_id: int) -> dict:
    """Get equipment status with repair detail for Slack status bot.

    Returns dict with keys:
        - color: 'green' | 'yellow' | 'red'
        - label: 'Operational' | 'Degraded' | 'Down'
        - issue_description: str | None
        - severity: str | None
        - eta: date | None (from highest-severity open repair record)
        - assignee_name: str | None (from highest-severity open repair record)

    Raises:
        EquipmentNotFound: if equipment_id doesn't exist.
    """
    equipment = db.session.get(Equipment, equipment_id)
    if equipment is None:
        raise EquipmentNotFound(f'Equipment with id {equipment_id} not found')

    open_records = _get_open_records(equipment_id)
    status = _derive_status_from_records(open_records)

    assignee_name = None
    if open_records:
        best_record = _find_highest_severity_record(open_records)
        if best_record is None:
            best_record = open_records[0]
        if best_record.assignee:
            assignee_name = best_record.assignee.username

    return {
        **status,
        'assignee_name': assignee_name,
    }


def get_area_status_dashboard() -> list[dict]:
    """Get all non-archived areas with their non-archived equipment and computed statuses.

    Returns list of dicts:
        [
            {
                'area': Area instance,
                'equipment': [
                    {
                        'equipment': Equipment instance,
                        'status': {color, label, issue_description, severity, eta}
                    },
                    ...
                ]
            },
            ...
        ]
    """
    areas = (
        db.session.execute(
            db.select(Area)
            .filter(Area.is_archived.is_(False))
            .order_by(Area.name)
        )
        .scalars()
        .all()
    )

    # Prefetch all non-archived equipment in one query (avoids N+1 per area)
    all_equipment = (
        db.session.execute(
            db.select(Equipment)
            .filter(Equipment.is_archived.is_(False))
            .order_by(Equipment.name)
        )
        .scalars()
        .all()
    )

    # Group equipment by area_id
    equipment_by_area: dict[int, list[Equipment]] = {}
    for equip in all_equipment:
        equipment_by_area.setdefault(equip.area_id, []).append(equip)

    # Prefetch all open repair records for non-archived equipment in one query
    open_records = (
        db.session.execute(
            db.select(RepairRecord)
            .join(RepairRecord.equipment)
            .filter(
                Equipment.is_archived.is_(False),
                RepairRecord.status.notin_(CLOSED_STATUSES),
            )
            .order_by(RepairRecord.created_at, RepairRecord.id)
        )
        .scalars()
        .all()
    )

    # Group open records by equipment_id
    records_by_equipment: dict[int, list[RepairRecord]] = {}
    for record in open_records:
        records_by_equipment.setdefault(record.equipment_id, []).append(record)

    result = []
    for area in areas:
        equip_statuses = []
        for equip in equipment_by_area.get(area.id, []):
            equip_records = records_by_equipment.get(equip.id, [])
            status = _derive_status_from_records(equip_records)
            equip_statuses.append({
                'equipment': equip,
                'status': status,
            })

        result.append({
            'area': area,
            'equipment': equip_statuses,
        })

    return result


def get_single_area_status_dashboard(area_id: int) -> dict:
    """Get a single non-archived area's equipment with computed statuses.

    Returns the same shape as one entry from get_area_status_dashboard():
        {
            'area': Area instance,
            'equipment': [
                {'equipment': Equipment, 'status': {color, label, issue_description, severity, eta}},
                ...
            ],
        }

    Raises:
        AreaNotFound: if the area does not exist.
        AreaArchived: if the area exists but is archived.
                      (Subclass of AreaNotFound -- catch the parent if the
                       caller treats both cases identically, e.g. a 404 view.)
    """
    area = db.session.get(Area, area_id)
    if area is None:
        raise AreaNotFound(f'Area with id {area_id} not found')
    if area.is_archived:
        raise AreaArchived(f'Area with id {area_id} is archived')

    equipment_list = (
        db.session.execute(
            db.select(Equipment)
            .filter(Equipment.area_id == area_id, Equipment.is_archived.is_(False))
            .order_by(Equipment.name)
        )
        .scalars()
        .all()
    )

    equip_ids = [e.id for e in equipment_list]
    records_by_equipment: dict[int, list[RepairRecord]] = {}
    if equip_ids:
        # Skip the IN-clause query when there's no equipment, purely as
        # a roundtrip-saving optimization. (SQLAlchemy 1.4+ handles
        # empty IN clauses gracefully -- this is not a correctness guard.)
        open_records = (
            db.session.execute(
                db.select(RepairRecord)
                .filter(
                    RepairRecord.equipment_id.in_(equip_ids),
                    RepairRecord.status.notin_(CLOSED_STATUSES),
                )
                .order_by(RepairRecord.created_at, RepairRecord.id)
            )
            .scalars()
            .all()
        )
        for record in open_records:
            records_by_equipment.setdefault(record.equipment_id, []).append(record)

    equip_statuses = []
    for equip in equipment_list:
        equip_records = records_by_equipment.get(equip.id, [])
        equip_statuses.append({
            'equipment': equip,
            'status': _derive_status_from_records(equip_records),
        })

    return {'area': area, 'equipment': equip_statuses}
