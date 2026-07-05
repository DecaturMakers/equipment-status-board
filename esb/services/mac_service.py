"""MAC (Machine Access Control) integration service.

Outbound HTTP client for the MAC 0.15.0 API plus the writers/readers for the
local status cache (``MachineStatus``) and activity log (``MachineActivityEvent``).

The whole integration is gated on the ``MAC_URL`` config value: when it is empty,
``mac_enabled()`` is False and every public function short-circuits to a sensible
empty result -- no outbound calls, no badges, webhook no-ops.

MAC API facts (verified against tag 0.15.0):
- ``GET {MAC_URL}/api/machines`` -> ``{"machines": [status_dict, ...]}`` (no auth).
- Controls (no request body): ``POST/DELETE /api/machine/oops/<name>`` and
  ``POST/DELETE /api/machine/locked_out/<name>``. "Clear" = DELETE both.
- A control call may return HTTP 503 ``{"error": ..., "action_applied": true}``
  on a state-save timeout; that is treated as success-with-warning, not failure.
"""

import logging
from datetime import UTC, datetime

import requests
from requests import RequestException
from sqlalchemy.exc import IntegrityError

from esb.extensions import db
from esb.models.equipment import Equipment
from esb.models.machine_activity_event import MachineActivityEvent
from esb.models.machine_status import MAC_MACHINE_STATUSES, MachineStatus
from esb.utils.logging import log_mutation

logger = logging.getLogger(__name__)

# Per-call outbound HTTP timeout (seconds). Mirrors the explicit-timeout pattern
# the Slack client uses so a hung MAC cannot wedge a request/worker indefinitely.
_TIMEOUT = 10

# Surfaces that can display MAC status badges.
MAC_SURFACES = ('public', 'kiosk', 'admin')

# Default per-surface visibility matrix (issue #2): public shows only the
# actionable states; kiosk and admin show everything. Used as the get_config
# default so an unconfigured deployment still renders sensibly, and as the single
# source of truth for the admin toggle defaults (Task 18, admin.app_config).
DEFAULT_VISIBLE_STATUSES = {
    'public': {'oops', 'locked_out'},
    'kiosk': set(MAC_MACHINE_STATUSES),
    'admin': set(MAC_MACHINE_STATUSES),
}


def mac_enabled() -> bool:
    """Return True when the MAC integration is configured (non-blank MAC_URL).

    Strips whitespace so a blank-but-non-empty value doesn't count as enabled
    (which would make _base_url() produce an empty base and malformed requests).
    """
    from flask import current_app

    return bool(current_app.config.get('MAC_URL', '').strip())


def _base_url() -> str:
    """Return the trimmed MAC base URL (no trailing slash)."""
    from flask import current_app

    return current_app.config.get('MAC_URL', '').strip().rstrip('/')


# --- Outbound HTTP client ------------------------------------------------------


def fetch_all_status() -> list[dict]:
    """Fetch every machine's status from MAC.

    Returns the list under the ``machines`` key. Returns ``[]`` when disabled.
    Raises on transport error / non-2xx (the caller -- the worker poll -- logs
    and swallows; page renders never call this).
    """
    if not mac_enabled():
        return []
    resp = requests.get(f'{_base_url()}/api/machines', timeout=_TIMEOUT)
    resp.raise_for_status()
    return resp.json()['machines']


def _control_request(method: str, kind: str, name: str) -> bool:
    """Issue a single control request to MAC and interpret the response.

    Args:
        method: 'post' (set) or 'delete' (clear).
        kind: 'oops' or 'locked_out'.
        name: MAC machine name.

    Returns:
        True if MAC returned HTTP 503 with ``action_applied: true`` (the action
        was applied but the state-save timed out -- success-with-warning); False
        on a normal 2xx success.

    Raises:
        RuntimeError: on any other non-2xx response or a transport error.
    """
    url = f'{_base_url()}/api/machine/{kind}/{name}'
    try:
        resp = requests.request(method, url, timeout=_TIMEOUT)
    except RequestException as exc:
        raise RuntimeError(f'MAC {method.upper()} {url} failed: {exc}') from exc

    if resp.status_code == 503:
        # State-save timeout: the action was applied per MAC's contract.
        try:
            body = resp.json()
        except ValueError:
            body = {}
        if body.get('action_applied'):
            logger.warning(
                'MAC %s %s returned 503 action_applied=true (success-with-warning)',
                method.upper(), url,
            )
            return True
        raise RuntimeError(f'MAC {method.upper()} {url} failed: 503 without action_applied')

    if not (200 <= resp.status_code < 300):
        raise RuntimeError(f'MAC {method.upper()} {url} failed: HTTP {resp.status_code}')
    return False


def set_oops(name: str) -> bool:
    """Flag a machine as oops'ed in MAC. Returns the 503-warning flag."""
    return _control_request('post', 'oops', name)


def clear_oops(name: str) -> bool:
    """Clear a machine's oops in MAC. Returns the 503-warning flag."""
    return _control_request('delete', 'oops', name)


def set_lockout(name: str) -> bool:
    """Lock out a machine in MAC (maintenance). Returns the 503-warning flag."""
    return _control_request('post', 'locked_out', name)


def clear_lockout(name: str) -> bool:
    """Clear a machine's lockout in MAC. Returns the 503-warning flag."""
    return _control_request('delete', 'locked_out', name)


def clear(name: str) -> bool:
    """Clear BOTH oops and lockout for a machine. Returns True if either warned."""
    warned_oops = clear_oops(name)
    warned_lockout = clear_lockout(name)
    return warned_oops or warned_lockout


# --- Epoch conversion ----------------------------------------------------------


def _epoch_to_dt(value):
    """Convert a MAC epoch-seconds float to a UTC datetime, or None.

    Uses ``datetime.fromtimestamp(value, tz=UTC)`` (NOT utcfromtimestamp) so the
    instant is correct. Note the stored ``db.DateTime`` column is naive on read
    (SQLite and MariaDB both drop tzinfo) -- do not assert awareness after a
    round-trip; treat the column as naive-UTC when comparing (F7).
    """
    if value is None:
        return None
    return datetime.fromtimestamp(value, tz=UTC)


# --- Status cache --------------------------------------------------------------


def _apply_status_fields(row: MachineStatus, status_dict: dict) -> None:
    """Copy fields from a MAC status_dict onto a MachineStatus row."""
    user = status_dict.get('current_user') or {}
    row.display_name = status_dict.get('display_name')
    row.status = status_dict.get('status', 'unknown')
    row.relay = bool(status_dict.get('relay'))
    row.oops = bool(status_dict.get('oops'))
    row.locked_out = bool(status_dict.get('locked_out'))
    row.current_user_account_id = user.get('account_id')
    row.current_user_full_name = user.get('full_name')
    row.last_checkin = _epoch_to_dt(status_dict.get('last_checkin'))
    row.last_update = _epoch_to_dt(status_dict.get('last_update'))


def upsert_machine_status(status_dict: dict) -> MachineStatus:
    """Insert or update the cached status for a single machine (race-safe).

    The webhook (web process) and the poll (worker process) both write the same
    UNIQUE ``machine_name`` row, so this mirrors ``config_service.set_config``'s
    IntegrityError-retry: SELECT -> UPDATE-or-INSERT -> on IntegrityError roll
    back, re-SELECT, UPDATE (F1).
    """
    machine_name = status_dict['name']
    row = db.session.execute(
        db.select(MachineStatus).filter_by(machine_name=machine_name)
    ).scalar_one_or_none()

    if row is not None:
        _apply_status_fields(row, status_dict)
        db.session.commit()
        return row

    row = MachineStatus(machine_name=machine_name)
    _apply_status_fields(row, status_dict)
    db.session.add(row)
    try:
        db.session.commit()
    except IntegrityError:
        # Lost the insert race against the other process -- re-select and update.
        db.session.rollback()
        row = db.session.execute(
            db.select(MachineStatus).filter_by(machine_name=machine_name)
        ).scalar_one()
        _apply_status_fields(row, status_dict)
        db.session.commit()
    return row


def reconcile_orphans(seen_names: set[str]) -> int:
    """Delete cached MachineStatus rows whose machine_name is not in seen_names.

    Called from the poll ONLY after a successful, non-empty fetch (F10), so a
    machine removed/renamed in MAC does not leak a stale cache row. Returns the
    number of rows deleted.

    Defensive: an empty ``seen_names`` returns 0 without deleting anything. A bare
    ``.notin_(set())`` would otherwise delete the ENTIRE cache (and generates
    dialect-dependent SQL), which would be a dangerous footgun for any future
    caller that doesn't pre-guard on a non-empty fetch.
    """
    if not seen_names:
        return 0
    stale = db.session.execute(
        db.select(MachineStatus).filter(MachineStatus.machine_name.notin_(seen_names))
    ).scalars().all()
    for row in stale:
        db.session.delete(row)
    if stale:
        db.session.commit()
        log_mutation('machine_status.reconciled', 'system', {
            'deleted': [r.machine_name for r in stale],
        })
    return len(stale)


# --- Activity log --------------------------------------------------------------


def record_activity_event(payload: dict) -> MachineActivityEvent | None:
    """Append a webhook event to the activity log, deduped on the event triple.

    Returns ``None`` when this is a duplicate delivery -- a row already exists
    with the same ``(machine_name, event_type, event_timestamp)``, or a
    concurrent insert won the race against the UNIQUE dedup index (F4) -- so no
    second activity row is written. Otherwise inserts and returns the new row.

    A ``None`` return means only "this activity was already recorded"; it does
    NOT instruct the caller to skip auto-repair. Auto-repair idempotency is
    handled independently by ``maybe_create_oops_repair``'s open-repair guard,
    so the webhook attempts it on every ``oops`` regardless of this return value
    (see webhooks.mac_status). Pruning is NOT done here (it runs in the poll, F10).
    """
    machine_name = payload['name']
    event_type = payload.get('event')
    event_ts = _epoch_to_dt(payload.get('timestamp'))
    user = payload.get('user') or {}

    existing = db.session.execute(
        db.select(MachineActivityEvent).filter_by(
            machine_name=machine_name,
            event_type=event_type,
            event_timestamp=event_ts,
        )
    ).scalar_one_or_none()
    if existing is not None:
        return None

    event = MachineActivityEvent(
        machine_name=machine_name,
        event_type=event_type,
        status=payload.get('status'),
        user_account_id=user.get('account_id'),
        user_full_name=user.get('full_name'),
        event_timestamp=event_ts,
        raw_payload=payload,
    )
    db.session.add(event)
    try:
        db.session.commit()
    except IntegrityError:
        # Lost a concurrent insert race for the same event triple against the
        # UNIQUE dedup index -- treat as a duplicate delivery (F3).
        db.session.rollback()
        return None
    return event


def prune_activity_events(machine_name: str, keep: int = 500) -> int:
    """Delete all but the newest ``keep`` activity events for one machine.

    Called once per machine per worker-poll cycle (NOT per webhook insert -- F10),
    so the ordered scan+DELETE cost is bounded and does not race concurrent
    inserts. Returns the number of rows deleted.
    """
    keep_ids = db.session.execute(
        db.select(MachineActivityEvent.id)
        .filter_by(machine_name=machine_name)
        .order_by(MachineActivityEvent.event_timestamp.desc(), MachineActivityEvent.id.desc())
        .limit(keep)
    ).scalars().all()

    if len(keep_ids) < keep:
        return 0  # Fewer than `keep` rows exist -- nothing to prune.

    stale = db.session.execute(
        db.select(MachineActivityEvent)
        .filter_by(machine_name=machine_name)
        .filter(MachineActivityEvent.id.notin_(keep_ids))
    ).scalars().all()
    for row in stale:
        db.session.delete(row)
    if stale:
        db.session.commit()
        log_mutation('machine_activity.pruned', 'system', {
            'machine_name': machine_name,
            'deleted': len(stale),
            'kept': keep,
        })
    return len(stale)


# --- Display / lookup helpers --------------------------------------------------


def visible_statuses(surface: str) -> set[str]:
    """Return the set of MAC statuses configured to display on ``surface``.

    Reads the five ``mac_show_{surface}_{status}`` config booleans. Returns an
    empty set when the integration is disabled (so nothing renders, AC1).
    """
    if not mac_enabled():
        return set()
    from esb.services import config_service

    visible = set()
    for status in MAC_MACHINE_STATUSES:
        key = f'mac_show_{surface}_{status}'
        default = 'true' if status in DEFAULT_VISIBLE_STATUSES.get(surface, set()) else 'false'
        if config_service.get_config(key, default) == 'true':
            visible.add(status)
    return visible


def get_status_for_equipment(equipment) -> MachineStatus | None:
    """Return the cached MachineStatus for an equipment's linked machine, or None.

    Matches case-insensitively (``lower(machine_name) == lower(name)``): the
    stored MAC name and the admin-typed ``mac_machine_name`` may differ in case,
    and this keeps the detail/public-equipment pages consistent with the batched
    ``get_statuses_for_names`` path on both MariaDB and SQLite.
    """
    if not mac_enabled():
        return None
    name = getattr(equipment, 'mac_machine_name', None)
    if not name:
        return None
    return db.session.execute(
        db.select(MachineStatus).filter(db.func.lower(MachineStatus.machine_name) == name.lower())
    ).scalars().first()


def get_statuses_for_names(names) -> dict[str, MachineStatus]:
    """Batch-load MachineStatus rows for many machine names (avoids N+1).

    Returns a **case-insensitively keyed** ``{lower(machine_name): MachineStatus}``
    map; look up with ``get_statuses_for_names(...).get(name.lower())``. Empty when
    disabled or no names given.

    Case matters here: ``MachineStatus.machine_name`` is stored verbatim from MAC
    (e.g. ``"planer"``) while ``Equipment.mac_machine_name`` is whatever an admin
    typed (e.g. ``"Planer"``). MariaDB's default collation matches them
    case-insensitively in SQL, but a case-sensitive Python dict would then miss on
    the re-key. So both the query (``lower(...) IN (lower...)``) and the returned
    keys are lowercased, keeping this batched path consistent with the direct-DB
    ``get_status_for_equipment`` lookup on both MariaDB and SQLite.
    """
    names = [n for n in names if n]
    if not names or not mac_enabled():
        return {}
    lowered = [n.lower() for n in names]
    rows = db.session.execute(
        db.select(MachineStatus).filter(db.func.lower(MachineStatus.machine_name).in_(lowered))
    ).scalars().all()
    return {row.machine_name.lower(): row for row in rows}


def maybe_create_oops_repair(payload: dict):
    """Auto-create a 'Down' repair when a machine is oops'ed via webhook (Task 15).

    Resolves the equipment by the payload's machine name. Returns ``None`` (no-op)
    when: no equipment is linked (AC18 -- status/activity are still recorded), or
    an open repair already exists for that equipment (AC17 -- no duplicate).

    The webhook attempts this on EVERY ``oops`` delivery (including duplicates);
    idempotency is provided by the open-repair guard above, not by the activity
    dedup. So a retried ``oops`` while a repair is still open is a no-op, but an
    ``oops`` redelivered after the prior repair was resolved does open a fresh
    one (there is no longer an open repair to guard against).

    The reporter name is read defensively as ``(payload.get('user') or {}).get(
    'full_name')`` (F13) so a missing/None user yields ``None``, not a KeyError.
    MAC provides no email, so ``reporter_email`` is left blank.
    """
    from esb.models.repair_record import RepairRecord
    from esb.services import repair_service

    eq = get_equipment_by_machine_name(payload.get('name'))
    if eq is None:
        return None

    open_repair = db.session.execute(
        db.select(RepairRecord)
        .filter(RepairRecord.equipment_id == eq.id)
        .filter(RepairRecord.status.notin_(repair_service.CLOSED_STATUSES))
    ).scalars().first()
    if open_repair is not None:
        return None

    reporter_name = (payload.get('user') or {}).get('full_name')
    return repair_service.create_repair_record(
        equipment_id=eq.id,
        description="Machine reported 'Oops' via MAC.",
        created_by='mac-webhook',
        severity='Down',
        reporter_name=reporter_name,
        reporter_email=None,
    )


def get_recent_activity(machine_name: str, limit: int = 100) -> list[MachineActivityEvent]:
    """Return a machine's recent activity events, newest first (Task 17).

    Returns an empty list when the machine name is falsy.
    """
    if not machine_name:
        return []
    return db.session.execute(
        db.select(MachineActivityEvent)
        .filter_by(machine_name=machine_name)
        .order_by(MachineActivityEvent.event_timestamp.desc(), MachineActivityEvent.id.desc())
        .limit(limit)
    ).scalars().all()


def get_equipment_by_machine_name(name: str):
    """Return the (single) non-archived-preferred Equipment linked to a machine name.

    Uses ``.order_by(Equipment.id)`` and returns the first match. If more than
    one equipment shares the name (form validation in Task 13 should prevent it),
    log a warning and act on the deterministically-first row (F6).
    """
    if not name:
        return None
    # Only non-archived equipment (matches the uniqueness rule and the docstring):
    # an archived row may legitimately share the name, but it can't take repairs.
    # Case-insensitive so a webhook for 'planer' resolves an admin-typed 'Planer'.
    matches = db.session.execute(
        db.select(Equipment)
        .filter(
            db.func.lower(Equipment.mac_machine_name) == name.lower(),
            Equipment.is_archived.is_(False),
        )
        .order_by(Equipment.id)
    ).scalars().all()
    if not matches:
        return None
    if len(matches) > 1:
        logger.warning(
            'Multiple equipment (%s) linked to MAC machine %r; using id=%s',
            [e.id for e in matches], name, matches[0].id,
        )
    return matches[0]
