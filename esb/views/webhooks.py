"""Inbound webhook receiver for MAC status events.

MAC's ``STATUS_WEBHOOK_URL`` POSTs a status_dict + ``event`` + ``timestamp`` +
``user`` on each machine state change. This endpoint caches the status, appends
an activity event, and (on a non-duplicate ``oops``) auto-creates a repair.

Network-trusted by default. An OPTIONAL ``MAC_WEBHOOK_TOKEN`` enables a
``/webhooks/mac/<token>`` guard (403 on mismatch). The route is CSRF-exempt
(registered via ``csrf.exempt(webhooks_bp)`` in the app factory).
"""

import hmac
import logging
import math

from flask import Blueprint, current_app, request

from esb.services import mac_service

logger = logging.getLogger(__name__)

webhooks_bp = Blueprint('webhooks', __name__, url_prefix='/webhooks')


@webhooks_bp.route('/mac', methods=['POST'])
@webhooks_bp.route('/mac/<token>', methods=['POST'])
def mac_status(token=None):
    """Receive a MAC status webhook. Always returns 204 on success.

    Response codes:
        403 -- MAC_WEBHOOK_TOKEN is set and the URL token does not match.
        204 -- integration disabled, duplicate delivery, or success.
        400 -- body is missing required fields (unprocessable input).
        500 -- an internal/transient error occurred (so MAC retries).
    """
    # Token guard: only enforced when a token is configured. Constant-time
    # Check enabled FIRST: when the integration is disabled the endpoint is a
    # documented 204 no-op regardless of any token, so a leftover
    # MAC_WEBHOOK_TOKEN can't turn a disabled deployment's webhook into a 403
    # (which MAC would retry). Nothing is written when disabled, so there is no
    # security reason to authenticate here.
    if not mac_service.mac_enabled():
        return ('', 204)

    # Token guard (only when enabled). Strip so a whitespace-only configured
    # token behaves like "unset" (network-trusted). Constant-time comparison
    # avoids leaking the secret via timing.
    configured_token = current_app.config.get('MAC_WEBHOOK_TOKEN', '').strip()
    if configured_token and not hmac.compare_digest(token or '', configured_token):
        return ('', 403)

    payload = request.get_json(silent=True)
    # Validate required fields AND their types BEFORE any DB write, so bad input
    # is a clean 400 and never leaves a half-written status row (F5). Crucially,
    # timestamp must be numeric: a non-numeric value would make
    # datetime.fromtimestamp() raise, which would otherwise surface as a 500 and
    # make MAC retry unprocessable input indefinitely. (bool is a subclass of
    # int, so it's excluded explicitly.) name/event back String columns and every
    # lookup, so they must be non-empty strings.
    if not isinstance(payload, dict):
        return ('', 400)
    name = payload.get('name')
    event = payload.get('event')
    timestamp = payload.get('timestamp')
    if (
        not isinstance(name, str) or not name
        or not isinstance(event, str) or not event
        or isinstance(timestamp, bool) or not isinstance(timestamp, (int, float))
        or not math.isfinite(timestamp)
    ):
        # math.isfinite rejects NaN / Infinity (which Python's JSON parser
        # accepts by default) -- datetime.fromtimestamp() would raise on those.
        return ('', 400)

    try:
        mac_service.upsert_machine_status(payload)
        mac_service.record_activity_event(payload)
        # Auto-repair is driven by its OWN open-repair guard, not the activity
        # dedup, so it is attempted on every oops event -- including a duplicate
        # delivery whose first attempt failed after the activity row committed
        # (F1). The guard prevents a duplicate repair when one is already open.
        if payload.get('event') == 'oops':
            mac_service.maybe_create_oops_repair(payload)
    except Exception:
        # Server-side / transient failure -> 500 so MAC retries. Genuinely bad
        # input was already rejected with 400 above (F4).
        logger.warning('MAC webhook processing failed', exc_info=True)
        return ('', 500)

    return ('', 204)
