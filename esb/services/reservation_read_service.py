"""Public and administrative reservation read models."""

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import TypedDict

from sqlalchemy.orm import joinedload

from esb.extensions import db
from esb.models.area import Area
from esb.models.equipment import Equipment
from esb.models.equipment_reservation_settings import EquipmentReservationSettings
from esb.models.reservation import (
    RESERVATION_CREATED_VIA,
    RESERVATION_STATUSES,
    RESERVATION_STATUS_ACTIVE,
    RESERVATION_STATUS_CANCELED,
    Reservation,
)
from esb.models.user import User
from esb.utils.exceptions import ValidationError
from esb.utils.timezones import (
    local_date_range_to_utc,
    to_utc_naive,
    utc_naive_to_local,
    utc_now_naive,
)

ACTIVE_STATUS = RESERVATION_STATUS_ACTIVE
CANCELED_STATUS = RESERVATION_STATUS_CANCELED
ADMIN_RESERVATION_DEFAULT_HISTORY_DAYS = 14
ADMIN_RESERVATION_MAX_HISTORY_DAYS = 90
ADMIN_RESERVATION_PAGE_SIZE = 25


def _utc_now() -> datetime:
    """Compatibility seam for deterministic read-model tests."""
    return utc_now_naive()


class AdminReservationRow(TypedDict):
    id: int
    equipment_id: int
    equipment: str
    area: str
    equipment_archived: bool
    reservations_disabled: bool
    user: str
    reservation_type: str
    starts_at: str
    ends_at: str
    starts_at_label: str
    ends_at_label: str
    status: str
    created_via: str
    created_by: str
    canceled_by: str
    replaces_reservation_id: int | None
    replaces_label: str
    replaced_by_reservation_id: int | None
    replaced_by_label: str
    override_codes: list[str]
    note: str
    calendar_label: str


class AdminPagination(TypedDict):
    page: int
    pages: int
    total: int
    has_prev: bool
    has_next: bool


class AdminCalendarData(TypedDict):
    startDate: str
    startsOn: str
    endsOn: str
    columns: list[dict]
    events: list[dict]
    details: dict[str, AdminReservationRow]
    reservations: list[AdminReservationRow]
    pagination: AdminPagination


@dataclass(frozen=True)
class AdminReservationFilters:
    """Validated filters for the admin reservation calendar and history list."""

    starts_on: date
    ends_on: date
    calendar_date: date
    area_id: int | None = None
    equipment_id: int | None = None
    user_id: int | None = None
    status: str | None = None
    created_via: str | None = None

    def query_params(self) -> dict[str, str | int]:
        """Return non-empty query parameters needed to reproduce this view."""
        values: dict[str, str | int] = {
            "starts_on": self.starts_on.isoformat(),
            "ends_on": self.ends_on.isoformat(),
            "calendar_date": self.calendar_date.isoformat(),
        }
        for name in ("area_id", "equipment_id", "user_id", "status", "created_via"):
            value = getattr(self, name)
            if value is not None:
                values[name] = value
        return values


def list_reservable_equipment() -> list[Equipment]:
    """Return non-archived equipment with enabled reservation settings."""
    return list(
        db.session.execute(
            db.select(Equipment)
            .join(EquipmentReservationSettings)
            .options(joinedload(Equipment.reservation_settings))
            .filter(
                Equipment.is_archived.is_(False),
                EquipmentReservationSettings.reservations_enabled.is_(True),
            )
            .order_by(Equipment.name)
        )
        .scalars()
        .all()
    )


def get_admin_reservation_creation_options() -> dict[str, list]:
    """Return equipment and active members eligible for admin creation."""
    return {
        "equipment": list_reservable_equipment(),
        "users": list(
            db.session.execute(db.select(User).filter(User.is_active.is_(True)).order_by(User.username)).scalars().all()
        ),
    }


def get_user_reservation(reservation_id: int, user_id: int) -> Reservation | None:
    """Return a reservation only when it belongs to the given user."""
    return db.session.execute(
        db.select(Reservation).filter_by(id=reservation_id, user_id=user_id)
    ).scalar_one_or_none()


def list_user_upcoming_reservations(user_id: int) -> list[Reservation]:
    """Return a user's active reservations that have not ended yet."""
    return list(
        db.session.execute(
            db.select(Reservation)
            .filter(
                Reservation.user_id == user_id,
                Reservation.status == ACTIVE_STATUS,
                Reservation.ends_at > _utc_now(),
            )
            .order_by(Reservation.starts_at)
        )
        .scalars()
        .all()
    )


def get_admin_reservation(reservation_id: int) -> Reservation:
    """Return a reservation and its edit/display relationships for admin actions."""
    reservation = db.session.execute(
        db.select(Reservation)
        .options(
            joinedload(Reservation.equipment),
            joinedload(Reservation.user),
        )
        .filter(Reservation.id == reservation_id)
    ).scalar_one_or_none()
    if reservation is None:
        raise ValidationError(f"Reservation with id {reservation_id} not found")
    return reservation


def get_public_availability(now=None) -> dict:
    """Build a privacy-safe reservation availability read model."""
    now_utc = to_utc_naive(now) if now is not None else _utc_now()
    equipment_items = []

    for equipment in list_reservable_equipment():
        settings = equipment.reservation_settings
        window_end = now_utc + timedelta(minutes=settings.max_advance_notice_minutes)
        reservations = _active_reservations_for_window(
            equipment.id,
            now_utc,
            window_end,
        )
        equipment_items.append(
            {
                "id": equipment.id,
                "name": equipment.name,
                "reservation_slug": settings.reservation_slug,
                "reservations_enabled": settings.reservations_enabled,
                "min_advance_notice_minutes": settings.min_advance_notice_minutes,
                "max_advance_notice_minutes": settings.max_advance_notice_minutes,
                "min_duration_minutes": settings.min_duration_minutes,
                "max_duration_minutes": settings.max_duration_minutes,
                "slot_granularity_minutes": settings.slot_granularity_minutes,
                "reservations": [
                    {
                        "label": "Reserved",
                        "starts_at": reservation.starts_at.replace(tzinfo=UTC).isoformat(),
                        "ends_at": reservation.ends_at.replace(tzinfo=UTC).isoformat(),
                    }
                    for reservation in reservations
                ],
            }
        )

    return {
        "equipment": equipment_items,
    }


def get_public_calendar_data(now=None) -> dict:
    """Build privacy-safe public reservation calendar data."""
    now_utc = to_utc_naive(now) if now is not None else _utc_now()
    local_now = utc_naive_to_local(now_utc)

    columns = []
    events = []
    for equipment in list_reservable_equipment():
        settings = equipment.reservation_settings
        window_end = now_utc + timedelta(minutes=settings.max_advance_notice_minutes)
        reservations = _active_reservations_for_window(
            equipment.id,
            now_utc,
            window_end,
        )
        resource_id = str(equipment.id)
        columns.append(
            {
                "id": resource_id,
                "name": equipment.name,
            }
        )
        for reservation in reservations:
            starts_at = utc_naive_to_local(reservation.starts_at).replace(tzinfo=None)
            ends_at = utc_naive_to_local(reservation.ends_at).replace(tzinfo=None)
            events.append(
                {
                    "id": str(reservation.id),
                    "resource": resource_id,
                    "start": starts_at.isoformat(timespec="seconds"),
                    "end": ends_at.isoformat(timespec="seconds"),
                    "text": "Reserved",
                    "backColor": "#2f6f73",
                    "barColor": "#164e52",
                    "fontColor": "#ffffff",
                }
            )

    return {
        "startDate": local_now.date().isoformat(),
        "columns": columns,
        "events": events,
    }


def parse_admin_reservation_filters(
    args,
    *,
    now: datetime | None = None,
) -> tuple[AdminReservationFilters, tuple[str, ...]]:
    """Parse request arguments into bounded, typed admin reservation filters."""
    now_utc = to_utc_naive(now) if now is not None else _utc_now()
    today = utc_naive_to_local(now_utc).date()
    default_start = today - timedelta(days=ADMIN_RESERVATION_DEFAULT_HISTORY_DAYS)
    default_end = today + timedelta(days=ADMIN_RESERVATION_DEFAULT_HISTORY_DAYS)
    warnings = []

    starts_on = _parse_admin_filter_date(args.get("starts_on"), default_start, "start", warnings)
    ends_on = _parse_admin_filter_date(args.get("ends_on"), default_end, "end", warnings)
    if ends_on < starts_on:
        warnings.append("Reservation end date must be on or after the start date; using the default range.")
        starts_on, ends_on = default_start, default_end
    elif (ends_on - starts_on).days > ADMIN_RESERVATION_MAX_HISTORY_DAYS:
        warnings.append(
            f"Reservation date range is limited to {ADMIN_RESERVATION_MAX_HISTORY_DAYS} days; using the default range."
        )
        starts_on, ends_on = default_start, default_end

    calendar_date = _parse_admin_filter_date(args.get("calendar_date"), today, "calendar", warnings)
    status = _parse_admin_choice(args.get("status"), RESERVATION_STATUSES, "status", warnings)
    created_via = _parse_admin_choice(args.get("created_via"), RESERVATION_CREATED_VIA, "source", warnings)

    filters = AdminReservationFilters(
        starts_on=starts_on,
        ends_on=ends_on,
        calendar_date=calendar_date,
        area_id=_parse_admin_filter_id(args.get("area_id"), "area", warnings),
        equipment_id=_parse_admin_filter_id(args.get("equipment_id"), "equipment", warnings),
        user_id=_parse_admin_filter_id(args.get("user_id"), "user", warnings),
        status=status,
        created_via=created_via,
    )
    return _validate_admin_filter_ids(filters, warnings), tuple(warnings)


def get_admin_reservation_filter_options() -> dict[str, list]:
    """Return all historical filter choices, including archived objects."""
    return {
        "areas": list(db.session.execute(db.select(Area).order_by(Area.sort_order, Area.name)).scalars().all()),
        "equipment": list(
            db.session.execute(
                db.select(Equipment).options(joinedload(Equipment.reservation_settings)).order_by(Equipment.name)
            )
            .scalars()
            .all()
        ),
        "users": list(db.session.execute(db.select(User).order_by(User.username)).scalars().all()),
    }


def get_admin_calendar_data(
    *,
    filters: AdminReservationFilters,
    page: int = 1,
    per_page: int = ADMIN_RESERVATION_PAGE_SIZE,
) -> AdminCalendarData:
    """Build private calendar data and a paginated administrative history list."""
    equipment_items = _admin_filtered_equipment(filters)
    equipment_ids = [equipment.id for equipment in equipment_items]
    if not equipment_ids:
        return {
            "startDate": filters.calendar_date.isoformat(),
            "startsOn": filters.starts_on.isoformat(),
            "endsOn": filters.ends_on.isoformat(),
            "columns": [],
            "events": [],
            "details": {},
            "reservations": [],
            "pagination": {"page": 1, "pages": 0, "total": 0, "has_prev": False, "has_next": False},
        }

    list_query = _admin_reservation_query(
        filters,
        equipment_ids,
        filters.starts_on,
        filters.ends_on,
    )
    total = db.session.scalar(db.select(db.func.count()).select_from(list_query.order_by(None).subquery()))
    pages = max(1, (total + per_page - 1) // per_page) if total else 0
    page = min(max(page, 1), pages) if pages else 1
    list_reservations = list(
        db.session.execute(
            list_query.order_by(Reservation.starts_at.desc(), Reservation.id.desc())
            .offset((page - 1) * per_page)
            .limit(per_page)
        )
        .scalars()
        .all()
    )

    calendar_reservations = list(
        db.session.execute(
            _admin_reservation_query(
                filters,
                equipment_ids,
                filters.calendar_date,
                filters.calendar_date,
            ).order_by(Reservation.starts_at, Reservation.id)
        )
        .scalars()
        .all()
    )
    calendar_rows = [_serialize_admin_reservation(reservation) for reservation in calendar_reservations]
    list_rows = [_serialize_admin_reservation(reservation) for reservation in list_reservations]
    displayed_ids = {row["id"] for row in calendar_rows + list_rows}
    if displayed_ids:
        replacement_links = dict(
            db.session.execute(
                db.select(Reservation.replaces_reservation_id, Reservation.id).filter(
                    Reservation.replaces_reservation_id.in_(displayed_ids)
                )
            ).all()
        )
        for row in calendar_rows + list_rows:
            replacement_id = replacement_links.get(row["id"])
            if replacement_id is not None:
                row["replaced_by_reservation_id"] = replacement_id
                row["replaced_by_label"] = f"Reservation #{replacement_id}"
    details = {str(row["id"]): row for row in calendar_rows + list_rows}

    return {
        "startDate": filters.calendar_date.isoformat(),
        "startsOn": filters.starts_on.isoformat(),
        "endsOn": filters.ends_on.isoformat(),
        "columns": [_serialize_admin_equipment(equipment) for equipment in equipment_items],
        "events": [_serialize_admin_calendar_event(row) for row in calendar_rows],
        "details": details,
        "reservations": list_rows,
        "pagination": {
            "page": page,
            "pages": pages,
            "total": total,
            "has_prev": page > 1,
            "has_next": page < pages,
        },
    }


def _parse_admin_filter_date(value, default: date, label: str, warnings: list[str]) -> date:
    if not value:
        return default
    try:
        return date.fromisoformat(value)
    except ValueError:
        warnings.append(f"Ignoring invalid reservation {label} date filter.")
        return default


def _parse_admin_filter_id(value, label: str, warnings: list[str]) -> int | None:
    if not value:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        warnings.append(f"Ignoring invalid reservation {label} filter.")
        return None
    if parsed <= 0:
        warnings.append(f"Ignoring invalid reservation {label} filter.")
        return None
    return parsed


def _parse_admin_choice(value, choices, label: str, warnings: list[str]) -> str | None:
    if not value:
        return None
    if value not in choices:
        warnings.append(f"Ignoring invalid reservation {label} filter.")
        return None
    return value


def _validate_admin_filter_ids(
    filters: AdminReservationFilters,
    warnings: list[str],
) -> AdminReservationFilters:
    values = {
        "area_id": filters.area_id,
        "equipment_id": filters.equipment_id,
        "user_id": filters.user_id,
    }
    models = {"area_id": Area, "equipment_id": Equipment, "user_id": User}
    for name, value in values.items():
        if value is not None and db.session.get(models[name], value) is None:
            warnings.append(f"Ignoring unknown reservation {name[:-3]} filter.")
            values[name] = None
    return AdminReservationFilters(
        starts_on=filters.starts_on,
        ends_on=filters.ends_on,
        calendar_date=filters.calendar_date,
        status=filters.status,
        created_via=filters.created_via,
        **values,
    )


def _admin_filtered_equipment(filters: AdminReservationFilters) -> list[Equipment]:
    query = db.select(Equipment).options(
        joinedload(Equipment.area),
        joinedload(Equipment.reservation_settings),
    )
    if filters.area_id is not None:
        query = query.filter(Equipment.area_id == filters.area_id)
    if filters.equipment_id is not None:
        query = query.filter(Equipment.id == filters.equipment_id)
    return list(db.session.execute(query.order_by(Equipment.name)).scalars().all())


def _admin_reservation_query(
    filters: AdminReservationFilters,
    equipment_ids: list[int],
    starts_on: date,
    ends_on: date,
):
    starts_at, ends_at = local_date_range_to_utc(starts_on, ends_on)
    query = (
        db.select(Reservation)
        .options(
            joinedload(Reservation.equipment).joinedload(Equipment.area),
            joinedload(Reservation.equipment).joinedload(Equipment.reservation_settings),
            joinedload(Reservation.user),
            joinedload(Reservation.created_by_user),
            joinedload(Reservation.canceled_by_user),
            joinedload(Reservation.replaces_reservation),
        )
        .filter(
            Reservation.equipment_id.in_(equipment_ids),
            Reservation.starts_at < ends_at,
            Reservation.ends_at > starts_at,
        )
    )
    if filters.user_id is not None:
        query = query.filter(Reservation.user_id == filters.user_id)
    if filters.status is not None:
        query = query.filter(Reservation.status == filters.status)
    if filters.created_via is not None:
        query = query.filter(Reservation.created_via == filters.created_via)
    return query


def _serialize_admin_equipment(equipment: Equipment) -> dict:
    settings = equipment.reservation_settings
    disabled = settings is None or not settings.reservations_enabled
    badges = []
    if equipment.is_archived:
        badges.append("Archived")
    if disabled:
        badges.append("Reservations disabled")
    return {
        "id": str(equipment.id),
        "name": equipment.name,
        "badges": badges,
    }


def _serialize_admin_calendar_event(row: AdminReservationRow) -> dict:
    return {
        "id": str(row["id"]),
        "resource": str(row["equipment_id"]),
        "start": row["starts_at"],
        "end": row["ends_at"],
        "text": row["calendar_label"],
        "backColor": "#4f5d75" if row["status"] == CANCELED_STATUS else "#2f6f73",
        "barColor": "#2d3142" if row["status"] == CANCELED_STATUS else "#164e52",
        "fontColor": "#ffffff",
    }


def _serialize_admin_reservation(reservation: Reservation) -> AdminReservationRow:
    starts_local = utc_naive_to_local(reservation.starts_at)
    ends_local = utc_naive_to_local(reservation.ends_at)
    equipment = reservation.equipment
    settings = equipment.reservation_settings if equipment else None
    owner = reservation.user.display_name if reservation.user else "Admin Hold"
    equipment_name = equipment.name if equipment else f"Equipment {reservation.equipment_id}"
    note = reservation.notes or ""
    calendar_label = f"{equipment_name}: {owner}"
    if note:
        calendar_label = f"{calendar_label} - {note}"
    return {
        "id": reservation.id,
        "equipment_id": reservation.equipment_id,
        "equipment": equipment_name,
        "area": equipment.area.name if equipment and equipment.area else "",
        "equipment_archived": bool(equipment and equipment.is_archived),
        "reservations_disabled": settings is None or not settings.reservations_enabled,
        "user": owner,
        "reservation_type": reservation.reservation_type,
        "starts_at": starts_local.replace(tzinfo=None).isoformat(timespec="seconds"),
        "ends_at": ends_local.replace(tzinfo=None).isoformat(timespec="seconds"),
        "starts_at_label": _format_local_datetime_label(starts_local),
        "ends_at_label": _format_local_datetime_label(ends_local),
        "status": reservation.status,
        "created_via": reservation.created_via,
        "created_by": reservation.created_by_user.display_name if reservation.created_by_user else "",
        "canceled_by": reservation.canceled_by_user.display_name if reservation.canceled_by_user else "",
        "replaces_reservation_id": reservation.replaces_reservation_id,
        "replaces_label": (
            f"Reservation #{reservation.replaces_reservation_id}" if reservation.replaces_reservation_id else ""
        ),
        "replaced_by_reservation_id": None,
        "replaced_by_label": "",
        "override_codes": reservation.overridden_policy_codes or [],
        "note": note,
        "calendar_label": calendar_label,
    }


def _format_local_datetime_label(value: datetime) -> str:
    return f"{value.strftime('%Y-%m-%d')} {value.strftime('%I:%M %p').lstrip('0')}"


def _active_reservations_for_window(
    equipment_id: int,
    starts_at: datetime,
    ends_at: datetime,
) -> list[Reservation]:
    return list(
        db.session.execute(
            db.select(Reservation)
            .filter(
                Reservation.equipment_id == equipment_id,
                Reservation.status == ACTIVE_STATUS,
                Reservation.starts_at < ends_at,
                Reservation.ends_at > starts_at,
            )
            .order_by(Reservation.starts_at)
        )
        .scalars()
        .all()
    )
