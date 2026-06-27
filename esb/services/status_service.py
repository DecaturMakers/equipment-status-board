"""Equipment status derivation service.

Single source of truth for computing equipment operational status
from open repair records.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import joinedload

from esb.extensions import db
from esb.models.area import Area
from esb.models.equipment import Equipment
from esb.models.equipment_reservation_settings import EquipmentReservationSettings
from esb.models.repair_record import RepairRecord
from esb.models.reservation import Reservation
from esb.services.repair_service import CLOSED_STATUSES
from esb.utils.exceptions import AreaArchived, AreaNotFound, EquipmentNotFound

# Severity to status mapping: priority order (lower = higher priority)
_SEVERITY_STATUS = {
    'Down': ('red', 'Down', 0),
    'Degraded': ('yellow', 'Degraded', 1),
    'Not Sure': ('yellow', 'Degraded', 2),
}

_NOT_SURE_PRIORITY = _SEVERITY_STATUS['Not Sure'][2]


def _open_records_sort_key(rec):
    """Sort key for open repair records.

    Returns ``(severity priority, created_at)``. Unknown severities and
    ``None`` fold to the ``Not Sure`` priority — same fallback the
    equipment-level status derivation uses — so a per-record list and
    its equipment-level dot cannot disagree about which records sort
    above which.
    """
    sev_entry = _SEVERITY_STATUS.get(rec.severity)
    priority = sev_entry[2] if sev_entry else _NOT_SURE_PRIORITY
    return (priority, rec.created_at)


def _get_open_records(equipment_id: int) -> list:
    """Query open (non-closed) repair records for an equipment item.

    Records are ordered by ``(created_at, id)`` ascending so callers (and
    the ``_derive_status_from_records()`` tie-break rule) see a fully
    deterministic order: the oldest open record wins on ties, with ``id``
    breaking the rare ``created_at``-collision case (e.g. two records
    inserted in the same second on a DB with second-precision timestamps).

    Eager-loads the assignee relationship so callers reading
    ``best_record.assignee.username`` (e.g., dashboards via
    ``_derive_status_from_records``) don't trigger an N+1 of lazy-loads.
    """
    return (
        db.session.execute(
            db.select(RepairRecord)
            .options(joinedload(RepairRecord.assignee))
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
        dict with keys: color, label, issue_description, severity, eta,
        assignee_name. ``eta`` is the highest-severity open record's ETA
        (or ``None`` if empty or unset). ``assignee_name`` is the same
        record's ``assignee.username`` (or ``None`` if unassigned).
        When multiple records share the highest severity, the oldest
        record (earliest ``created_at``) wins.
    """
    if not records:
        return {
            'color': 'green',
            'label': 'Operational',
            'issue_description': None,
            'severity': None,
            'eta': None,
            'assignee_name': None,
        }

    best_record = _find_highest_severity_record(records)
    if best_record is None:
        # No record has a recognized severity; fall through to the oldest record
        # for description/eta/assignee, but report Degraded.
        anchor = records[0]
        return {
            'color': 'yellow',
            'label': 'Degraded',
            'issue_description': anchor.description,
            'severity': None,
            'eta': anchor.eta,
            'assignee_name': anchor.assignee.username if anchor.assignee else None,
        }

    color, label, _ = _SEVERITY_STATUS[best_record.severity]
    return {
        'color': color,
        'label': label,
        'issue_description': best_record.description,
        'severity': best_record.severity,
        'eta': best_record.eta,
        'assignee_name': best_record.assignee.username if best_record.assignee else None,
    }


def compute_equipment_status(equipment_id: int) -> dict:
    """Compute equipment status from open repair records.

    Returns dict with keys:
        - color: 'green' | 'yellow' | 'red'
        - label: 'Operational' | 'Degraded' | 'Down'
        - issue_description: str | None (brief description from highest severity record)
        - severity: str | None (raw severity value from highest severity record)
        - eta: date | None (from highest severity record; oldest wins on ties)
        - assignee_name: str | None (from highest-severity open record's assignee)

    Raises:
        EquipmentNotFound: if equipment_id doesn't exist
    """
    equipment = db.session.get(Equipment, equipment_id)
    if equipment is None:
        raise EquipmentNotFound(f'Equipment with id {equipment_id} not found')

    return _derive_status_from_records(_get_open_records(equipment_id))


def _get_dashboard_reservation_summaries(
    equipment_ids: list[int],
    now: datetime | None = None,
) -> dict[int, dict]:
    """Build compact public-dashboard reservation labels by equipment id."""
    if not equipment_ids:
        return {}

    now = now or datetime.now(UTC).replace(tzinfo=None, second=0, microsecond=0)

    def format_time(value):
        text = value.replace(tzinfo=UTC).astimezone().strftime('%I:%M %p')
        return text.lstrip('0')

    def format_next_time(value):
        local_value = value.replace(tzinfo=UTC).astimezone()
        local_date = local_value.date()
        today = now.replace(tzinfo=UTC).astimezone().date()
        if local_date == today:
            return f'today at {format_time(value)}'
        if local_date == today + timedelta(days=1):
            return f'tomorrow at {format_time(value)}'
        return f'{local_value.strftime("%b")} {local_value.day} at {format_time(value)}'

    settings = (
        db.session.execute(
            db.select(EquipmentReservationSettings)
            .filter(EquipmentReservationSettings.equipment_id.in_(equipment_ids))
        )
        .scalars()
        .all()
    )
    enabled_equipment_ids = {
        item.equipment_id for item in settings if item.reservations_enabled
    }
    if not enabled_equipment_ids:
        return {}

    reservations = (
        db.session.execute(
            db.select(Reservation)
            .filter(
                Reservation.equipment_id.in_(enabled_equipment_ids),
                Reservation.status == 'active',
                Reservation.ends_at > now,
            )
            .order_by(Reservation.starts_at, Reservation.id)
        )
        .scalars()
        .all()
    )
    reservations_by_equipment: dict[int, list[Reservation]] = {}
    for reservation in reservations:
        reservations_by_equipment.setdefault(reservation.equipment_id, []).append(reservation)

    summaries: dict[int, dict] = {}
    for equipment_id in enabled_equipment_ids:
        equipment_reservations = reservations_by_equipment.get(equipment_id, [])
        current_reservations = [
            reservation for reservation in equipment_reservations
            if reservation.starts_at <= now < reservation.ends_at
        ]
        if current_reservations:
            ends_at = min(reservation.ends_at for reservation in current_reservations)
            summaries[equipment_id] = {
                'label': f'Reserved until {format_time(ends_at)}',
                'state': 'reserved',
            }
            continue

        next_reservation = next(
            (
                reservation for reservation in equipment_reservations
                if reservation.starts_at > now
            ),
            None,
        )
        label = 'Available now'
        if next_reservation is not None:
            next_time = format_next_time(next_reservation.starts_at)
            label += f' · Next reservation {next_time}'
        summaries[equipment_id] = {
            'label': label,
            'state': 'available',
        }

    return summaries


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

    return _derive_status_from_records(_get_open_records(equipment_id))


def get_area_status_dashboard() -> list[dict]:
    """Get all non-archived areas with their non-archived equipment and computed statuses.

    Returns list of dicts:
        [
            {
                'area': Area instance,
                'equipment': [
                    {
                        'equipment': Equipment instance,
                        'status': {color, label, issue_description, severity, eta, assignee_name},
                        'open_records': [RepairRecord, ...],
                    },
                    ...
                ]
            },
            ...
        ]

    ``open_records`` is the list of non-closed ``RepairRecord`` instances for
    each equipment item, sorted by ``(severity priority ASC, created_at ASC)``.
    Unknown severities and ``None`` fold to the ``Not Sure`` priority (matching
    the equipment-level status fallback). Ties on those fields preserve the
    prefetch query's ``(created_at, id) ASC`` order (Python's ``sorted()`` is
    stable).
    """
    areas = (
        db.session.execute(
            db.select(Area)
            .filter(Area.is_archived.is_(False))
            .order_by(Area.sort_order, Area.name)
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

    reservation_summaries = _get_dashboard_reservation_summaries(
        [equip.id for equip in all_equipment]
    )

    # Prefetch all open repair records for non-archived equipment in one query.
    # Eager-load assignee so dashboard rendering does not lazy-fire one
    # query per non-green item when it reads ``best_record.assignee.username``.
    open_records = (
        db.session.execute(
            db.select(RepairRecord)
            .options(joinedload(RepairRecord.assignee))
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

    # Group open records by equipment_id. Lists stay in the prefetch's
    # (created_at, id) ASC order so `_derive_status_from_records` sees the
    # input it documents (oldest-first). `open_records` for the static page
    # needs a different order, so we sort a copy below.
    records_by_equipment: dict[int, list[RepairRecord]] = {}
    for record in open_records:
        records_by_equipment.setdefault(record.equipment_id, []).append(record)

    result = []
    for area in areas:
        equip_statuses = []
        for equip in equipment_by_area.get(area.id, []):
            equip_records = records_by_equipment.get(equip.id, [])
            status = _derive_status_from_records(equip_records)
            # Sorted copy: severity-priority order for at-a-glance display
            # on the static page. The derivation above used the original
            # (created_at, id) ASC order per its documented contract.
            open_records_sorted = sorted(equip_records, key=_open_records_sort_key)
            equip_statuses.append({
                'equipment': equip,
                'status': status,
                'open_records': open_records_sorted,
                'reservation': reservation_summaries.get(equip.id),
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
                {'equipment': Equipment, 'status': {color, label, issue_description, severity, eta, assignee_name}},
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
                .options(joinedload(RepairRecord.assignee))
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
