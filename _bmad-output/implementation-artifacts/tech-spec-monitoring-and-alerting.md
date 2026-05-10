---
title: 'Monitoring and Alerting Guide + System-Health Metrics'
slug: 'monitoring-and-alerting'
created: '2026-05-10'
status: 'ready-for-dev'
stepsCompleted: [1, 2, 3, 4]
revision: 2
revision_notes: 'Adversarial-review pass applied — 17 findings addressed'
tech_stack:
  - 'Python 3.14'
  - 'Flask'
  - 'Flask-SQLAlchemy + SQLAlchemy 2.x style'
  - 'MariaDB (production) / SQLite (tests)'
  - 'prometheus_client'
  - 'slack-bolt + slack_sdk (Socket Mode)'
  - 'pytest'
  - 'MkDocs (Material) — docs site'
files_to_modify:
  - 'docs/administrators.md'
  - 'docker-compose.yml'
  - 'esb/services/metrics_service.py'
  - 'esb/services/notification_service.py'
  - 'esb/slack/__init__.py'
  - 'tests/test_services/test_metrics_service.py'
  - 'tests/test_services/test_notification_service.py'
  - 'tests/test_views/test_metrics_view.py'
code_patterns:
  - 'Custom prometheus_client collector class in metrics_service.py with fresh CollectorRegistry per request'
  - "Omit gauges entirely when 'not applicable' rather than emitting a sentinel value (alert with absent())"
  - 'Service-layer pattern: views and the worker delegate to esb/services/* functions; no direct model access from views'
  - 'AppConfig key-value table for runtime-configurable / cross-process state'
  - 'Worker writes heartbeat file at three points (startup, after DB poll, after each notification)'
  - 'SQLAlchemy session: explicit rollback() on caught exceptions before continuing the loop, narrow except clauses (SQLAlchemyError, OSError) — broad except Exception is reserved for the outermost worker-loop guard'
  - "Slack module-globals (_bolt_app, _socket_handler) reset in test setUp/tearDown; new tests touching them must follow the same pattern (see tests/test_slack/test_init.py:51-52,74-75,151-152)"
test_patterns:
  - "Service-layer tests in tests/test_services/test_metrics_service.py — use 'app' fixture; assert against rendered exposition text via regex (_extract_metric helper)"
  - "Route-level tests in tests/test_views/test_metrics_view.py — use 'client' fixture; GET /metrics, assert 200 and substring match on metric name lines"
  - 'Worker-loop tests in tests/test_services/test_notification_service.py — use SQLite in-memory DB; for full-iteration tests, stub get_pending_notifications() and run one cycle with _shutdown set true after the iteration'
  - 'Pin module attribute monkeypatch via the import idiom: `import esb.slack as _slack` in metrics_service, then `monkeypatch.setattr("esb.slack.is_socket_mode_connected", ...)` resolves correctly at call time'
issue: 12
related_issues: [32]
---

# Tech-Spec: Monitoring and Alerting Guide + System-Health Metrics

**Created:** 2026-05-10
**Issue:** [#12 — Monitoring and alerting](https://github.com/jantman/equipment-status-board/issues/12)
**Related:** #32 (initial Prometheus endpoint and worker-resilience hardening)
**Revision:** 2 (adversarial-review pass applied)

## Overview

### Problem Statement

The Administrator Guide (`docs/administrators.md`) lacks a dedicated "Monitoring and Alerting" section. Issue #32 added two notification-queue gauges to a `/metrics` endpoint, but operators deploying ESB with Prometheus + Loki + Grafana have no documented guidance on what signals indicate ESB itself is unhealthy. The existing `/metrics` endpoint exposes only queue gauges — nothing about worker liveness as a scrapable metric (the heartbeat is a file inside the worker container, unreadable from the app process), nothing distinguishing "Socket Mode intentionally off" from "Socket Mode tried and failed at boot," and nothing about per-instance app availability beyond the existing Docker healthcheck and autoheal sidecar.

In addition, application-side stdout is currently subject to Python's default block buffering (only the worker container has `PYTHONUNBUFFERED=1`), so app log lines reach Loki/Promtail with a multi-second lag — invalidating any low-latency log-based alerting recommended by this section unless that asymmetry is fixed.

### Solution

Three-part change:

1. **Documentation:** Add a new top-level `## Monitoring and Alerting` section to `docs/administrators.md` (peer of the existing "New Relic Monitoring (Optional)" section). Promote the existing "Prometheus Metrics" subsection (currently under "Ongoing Maintenance") into this new section, preserving the original `#prometheus-metrics` HTML anchor at the forward-pointer location for backward link compatibility. Cover Prometheus, Loki (substring-style guidance with verified substrings — no full LogQL), Grafana (high-level dashboard guidance — no JSON), container-level liveness (`up{}` and cAdvisor — brief), a "What to alert on" checklist (system-health only), an explicit operator caveat about clock skew / NTP and Prometheus's `time()` function, and an explicit caveat that the Socket Mode metrics assume the current single-gunicorn-worker deployment. Note that Prom/Loki/Grafana and New Relic are complementary.

2. **Code:** Expand `/metrics` with **three** new system-health-only gauges (revised up from two after adversarial review):
   - `esb_worker_last_iteration_timestamp_seconds` (gauge, DB-backed via `AppConfig` key `worker_last_iteration_at`) — Unix epoch seconds of the worker's most recent successful poll cycle. The metric reads the row's `value` field (parsed from ISO-8601). The row's `updated_at` is informational only and may differ slightly. Omitted when the row does not exist; operators alert with `absent()` paired with a `for:` clause long enough to ride out cold-deploy time-to-first-poll (recommend `for: 5m` minimum).
   - `esb_socket_mode_enabled` (gauge, in-process, always emitted) — `1` if the deployment *intends* to run Socket Mode (i.e. tokens configured and `SLACK_SOCKET_MODE_CONNECT=true` and not `TESTING`), `0` otherwise. Lets operators distinguish "deployment without Slack" from "Slack tried and failed."
   - `esb_socket_mode_connected` (gauge, in-process, always emitted) — `1` if the Bolt SocketModeHandler initialized successfully at app startup (`_socket_handler is not None`), `0` otherwise. Reflects *startup state only* — Slack Bolt does not expose connection-state hooks. The actionable failure mode is `enabled == 1 AND connected == 0`.

   No counters, no business metrics, no auth on `/metrics`.

3. **Operational fix:** Add `PYTHONUNBUFFERED=1` to the `app` service in `docker-compose.yml` so app stdout reaches Docker's log driver (and Loki/Promtail) without Python's block buffer interposing. Without this, any log-based alerting recommended in the new doc section is misleading by multiple seconds.

### Scope

**In Scope:**

- New `## Monitoring and Alerting` section in `docs/administrators.md`
- Reorganization of the existing "Prometheus Metrics" subsection into that new section, with an HTML `<a id="prometheus-metrics"></a>` anchor preserved at the forward-pointer location
- Three new gauges on `/metrics`: `esb_worker_last_iteration_timestamp_seconds`, `esb_socket_mode_enabled`, `esb_socket_mode_connected`
- A change to `esb/services/notification_service.py` so the worker writes its last-iteration timestamp to `AppConfig` (key `worker_last_iteration_at`) once per successful poll cycle, with explicit `db.session.rollback()` on `SQLAlchemyError` (including `IntegrityError` from concurrent inserts)
- New public functions `is_socket_mode_enabled()` and `is_socket_mode_connected()` in `esb/slack/__init__.py`
- Loki guidance with verified error-string substrings against the actual codebase (no placeholder text)
- An `absent()`-based example alert YAML for `esb_worker_last_iteration_timestamp_seconds` with explanation of the cold-deploy `for:` clause
- Clock-skew / NTP note (worker clock vs. Prometheus `time()`)
- Multi-gunicorn-worker caveat for the Socket Mode metrics (current Dockerfile pins `--workers 1`)
- Brief note on container-level liveness via `up{}` / cAdvisor
- Note that New Relic and Prom/Loki/Grafana are complementary
- `PYTHONUNBUFFERED=1` added to `app` service in `docker-compose.yml`
- Service-layer + route-level + worker-loop tests for all new behavior, including the IntegrityError race-recovery path and the full-iteration loop-survival assertion
- Cross-link from "Ongoing Maintenance" to the new Monitoring section

**Out of Scope:**

- Full LogQL queries, Loki label selectors, parser configurations, or Grafana dashboard JSON
- Business metrics (repair counts, equipment counts, user activity, login rates, page-view counters)
- Slack delivery success/failure counters (intentionally dropped — Loki on log strings covers it at lower complexity)
- Static page push freshness/failure metric (already represented in queue-staleness gauge)
- DB connectivity gauge (already represented by `up{}` and queue gauge errors)
- Changes to existing New Relic integration
- Installing or configuring Prometheus / Loki / Grafana themselves
- Authentication for `/metrics` (stays unauthenticated; trusted-network deployment)
- Alertmanager / alert routing configuration
- Any new Docker / docker-compose services
- Live (mid-life) Socket Mode WebSocket connection-state detection — Slack Bolt does not expose hooks for this
- Multi-process Socket Mode coordination (out of scope; single-worker is the documented deployment)

## Context for Development

### Codebase Patterns

- **Metrics collector pattern:** Custom collector class implementing `collect()` and yielding `GaugeMetricFamily`; registered into a fresh `CollectorRegistry` per scrape inside `render_metrics()` (`esb/services/metrics_service.py:84-92`). Avoids cross-request state and keeps the snapshot consistent.
- **Single-query snapshot:** Aggregates that need to be consistent come from one combined `SELECT` (e.g., `_query_pending_stats()` at `esb/services/metrics_service.py:27-52`). New gauges may add a separate query for unrelated state (e.g. `AppConfig`).
- **Omit when N/A:** When a gauge has no meaningful value, do not emit it. Operators alert with `absent()`.
- **Worker entry point:** `flask worker run` CLI is registered in `esb/__init__.py:149-157` and invokes `notification_service.run_worker_loop()` at `esb/services/notification_service.py:322`. Worker is a CLI process — it has **no HTTP listener**, so worker-side metrics must reach the app via the database.
- **Heartbeat write sites:** `_write_heartbeat()` at `esb/services/notification_service.py:29-37` is called at three points: startup (line 355), after each DB poll (line 369), and after each notification processed (line 397). The new `worker_last_iteration_at` write should reuse the **after-each-DB-poll** site (line 369) — represents forward progress per cycle.
- **`_write_heartbeat` catches `OSError` specifically (not `Exception`).** Adversarial-review correction: do not paraphrase this as "swallow-and-log of `Exception`." The new `_record_iteration_timestamp` will catch `SQLAlchemyError` specifically (the relevant DB-error superclass) and explicitly rollback the session before returning.
- **AppConfig key-value pattern:** `esb/models/app_config.py` is a single-row-per-key table (`key` unique, `value` text, `updated_at` with both `default=` and `onupdate=`). The metric reads the **`value` field** (ISO-8601 string written by the worker via `datetime.now(UTC).isoformat()`). The DB column `updated_at` is set by SQLAlchemy's lifecycle hook and is informational only — these two timestamps may differ by sub-second on insert and are not guaranteed to agree.
- **Slack Bolt initialization** (verified file lines):
  - Bolt `App` constructed at `esb/slack/__init__.py:42`
  - Five distinct early-return paths leave `_socket_handler` as `None`: missing `SLACK_BOT_TOKEN` (line 27-29), missing `SLACK_APP_TOKEN` (line 31-33), `TESTING=True` (line 51-53), `SLACK_SOCKET_MODE_CONNECT != 'true'` (line 56-58), or `connect()` raised (line 67-70). Only the last is alertable.
  - Successful `connect()` at line 65, log substring `Slack Socket Mode connected` at line 66.
  - Failure-at-connect log substring `Failed to connect Slack Socket Mode — app will run without Slack` at line 68.
- **Slack Bolt has no public connection-state callbacks** — confirmed during investigation. The `esb_socket_mode_connected` gauge intentionally reflects only the *startup* state.
- **Slack module-globals are reset by existing tests:** `tests/test_slack/test_init.py` does `slack_mod._bolt_app = None; slack_mod._socket_handler = None` in setUp (lines 51-52), tearDown (lines 74-75), and across other test classes (lines 151-152). New tests touching these globals must follow the same setup/teardown pattern.
- **Logging — corrected.** `PYTHONUNBUFFERED=1` is currently set **only on the `worker` service** in `docker-compose.yml` (line 51). The `app` service is not configured for unbuffered stdout, so app log lines pass through Python's block buffer before Docker's log driver captures them. This spec adds the variable to the `app` service so log-based alerting on app-side log lines is not silently delayed.
- **Mutation logger** at `esb/utils/logging.py` emits structured JSON on a separate logger name (`esb.mutations`). Permanent-fail events are logged here as `log_mutation('notification.permanently_failed', ...)` (`notification_service.py:141-147`) — there is **no free-text log line** for that event. Loki guidance for this event must reference the JSON `event` field, not a plain substring.

### Files to Reference

| File | Purpose |
| ---- | ------- |
| `docs/administrators.md` | The doc being edited; gains the new top-level "Monitoring and Alerting" section |
| `docker-compose.yml` | Add `PYTHONUNBUFFERED=1` to the `app` service environment |
| `esb/services/metrics_service.py` | Existing collector; add a new collector class for the three new gauges |
| `esb/__init__.py` | `/metrics` and `/health` routes; CLI registration for `flask worker run` |
| `esb/services/notification_service.py` | Worker run loop; add `_record_iteration_timestamp()` helper and call site |
| `esb/models/app_config.py` | `AppConfig` model — backing store for `worker_last_iteration_at` |
| `esb/slack/__init__.py` | Slack Bolt + Socket Mode initialization; gains two public accessors |
| `esb/utils/logging.py` | Mutation logger reference for JSON-stream Loki guidance |
| `tests/conftest.py` | Test fixtures (`app`, `client`, `db`) reused by new metric tests |
| `tests/test_services/test_metrics_service.py` | Service-layer tests; existing `_extract_metric` regex pattern |
| `tests/test_views/test_metrics_view.py` | Route-level tests; existing GET `/metrics` substring-assert pattern |
| `tests/test_services/test_notification_service.py` | Worker-loop tests |
| `tests/test_slack/test_init.py` | Reference for module-global reset pattern (lines 51-52, 74-75, 151-152) |

### Technical Decisions

- **No new authentication on `/metrics`** — stays unauthenticated, trusted-network deployment.
- **System-health metrics only** — no business / activity metrics.
- **`AppConfig` reused, no new table** — single key/value row sufficient. The `value` field (ISO-8601 string) is **authoritative** for the metric; `updated_at` (set by SQLAlchemy lifecycle) is informational and not read by the metric.
- **Worker writes timestamp at the after-poll heartbeat site only** — one write per `poll_interval` (default 30s).
- **Three-gauge Socket Mode design (revised from one).** Splitting into `esb_socket_mode_enabled` and `esb_socket_mode_connected` lets operators write `enabled == 1 AND connected == 0` to alert on the only actionable failure case (Slack tried-and-failed). A single gauge of `_socket_handler is not None` could not distinguish that from "no Slack tokens set" or "Socket Mode opt-out."
- **Loki guidance — verified substrings only.** Every "log substring" entry in the doc table is taken verbatim (or as a unique unambiguous prefix) from the actual `logger.error/warning/info` call sites cited in this spec by file:line. No placeholder "TBD at implementation time" entries.
- **Permanent-fail signal uses the JSON mutation logger, not free-text grep.** The doc names this signal explicitly and tells operators to parse the JSON `event` field rather than substring-grep — a different primitive than the rest of the table.
- **Narrow `except` clause + explicit rollback for the worker timestamp write.** The helper catches `SQLAlchemyError` (covers `IntegrityError`, `OperationalError`, etc.), then calls `db.session.rollback()` before returning. This prevents `PendingRollbackError` from poisoning the next iteration's commit. A broad `except Exception` is **not** used here — it would silently absorb programming errors.
- **IntegrityError tolerance.** Two writers racing on the unique `key` constraint will produce `IntegrityError` for the loser. The helper logs at warning, rolls back, and continues; the next iteration will see the row populated and update it normally. Documented in tech decisions because the spec explicitly handles it (rather than ignoring the race).
- **Pinned import idiom for monkeypatch surface.** `metrics_service` does `import esb.slack as _slack` (lazy, inside `collect()`) and calls `_slack.is_socket_mode_enabled()` / `_slack.is_socket_mode_connected()` — module-attribute lookup at call time. Tests then `monkeypatch.setattr('esb.slack.is_socket_mode_connected', lambda: True)` and the patch is observed. This is the only correct combination; the spec pins it explicitly because the wrong combination silently passes tests against stale state.
- **Single gunicorn worker is a deployment assumption** for the Socket Mode metrics. The current `Dockerfile` pins `--workers 1`. If an operator scales workers, every process opens its own SocketModeHandler (a separate problem, out of scope) and scrape-to-scrape gauge values become non-deterministic. Documented as a caveat in the admin guide.
- **Clock-skew caveat.** The `ESBWorkerStalled` example rule uses `time() - <gauge>`, mixing Prometheus's clock and the worker container's clock. A note in the doc recommends NTP and a threshold ≥ `4 × poll_interval` to absorb expected drift.
- **Anchor preservation.** When `### Prometheus Metrics` moves out of "Ongoing Maintenance", the forward-pointer line at the old location includes a literal `<a id="prometheus-metrics"></a>` so external links to `#prometheus-metrics` still resolve to the right page.
- **`PYTHONUNBUFFERED=1` added to the app service.** Without it, app-side log lines reach Loki via Python's block buffer with multi-second latency, invalidating any low-latency log-alerting promises in the new doc section. Single-line config change in `docker-compose.yml`.
- **Performance trade-off: one extra DB query per scrape.** The new `_WorkerStatusCollector` adds one `AppConfig` SELECT per scrape on top of `_query_pending_stats`. At default `scrape_interval=15s` and `--workers 1`, this adds ~4 extra queries/min — negligible. Operators with aggressive scrape intervals (≤ 5s) and multiple Prometheis can in-process-cache the value with a short freshness budget; this spec does not implement caching since the default cost is small.
- **Metric naming.** Continue the `esb_` prefix convention from #32. All three new metrics are gauges.
- **`/metrics` exposition stability.** The two existing metrics keep their names, types, and emission semantics. No backward-incompatible changes for downstream alert rules.

## Implementation Plan

### Tasks

Tasks are ordered by dependency: backing-store writes first, then read-side metric emission, then tests, then documentation, then operational fix.

- [ ] **Task 1: Worker writes `worker_last_iteration_at` to `AppConfig` once per poll cycle**
  - File: `esb/services/notification_service.py`
  - Action: Add a private helper `_record_iteration_timestamp() -> None`. Body:
    1. Construct the new value: `now_iso = datetime.now(UTC).isoformat()`.
    2. Look up the existing row: `row = db.session.execute(select(AppConfig).where(AppConfig.key == 'worker_last_iteration_at')).scalar_one_or_none()`.
    3. If the row exists, set `row.value = now_iso`. If it does not exist, `db.session.add(AppConfig(key='worker_last_iteration_at', value=now_iso))`.
    4. `db.session.commit()`.
    5. Wrap steps 2-4 in `try / except SQLAlchemyError:`. On exception: call `db.session.rollback()`, then `logger.warning('Failed to update worker last-iteration timestamp', exc_info=True)`, then return. **Do not catch `Exception`** — narrow except is intentional, mirrors the pattern of `_write_heartbeat` (which catches `OSError` only, not `Exception`).
    6. Add the imports: `from sqlalchemy.exc import SQLAlchemyError`, `from sqlalchemy import select` (if not already imported), and `from esb.models.app_config import AppConfig`.
  - Action (continued): In `run_worker_loop()` at line 322, call `_record_iteration_timestamp()` immediately after the existing post-poll `_write_heartbeat()` call (line 369). Do **not** call it at the startup site (line 355) or per-notification site (line 397).
  - Notes: `IntegrityError` from a race on the unique `key` constraint is a subclass of `SQLAlchemyError` and is handled by the same rollback. The next iteration will find the row and update it.

- [ ] **Task 2: Expose two Slack accessors from `esb.slack`**
  - File: `esb/slack/__init__.py`
  - Action: Add a new module-level boolean `_socket_mode_intended: bool = False` near the other module-globals (lines 9-11).
  - Action: Add two public functions:
    1. `def is_socket_mode_enabled() -> bool:` — returns `_socket_mode_intended`. Docstring: "True iff the deployment is configured to run Socket Mode (tokens set, not TESTING, opt-in flag true). Reflects intent, not state."
    2. `def is_socket_mode_connected() -> bool:` — returns `_socket_handler is not None`. Docstring: "Reflects *startup* state only. Slack Bolt does not expose mid-life connection-state callbacks; this gauge does not detect WebSocket disconnects after init."
  - Action: Update `init_slack(app)` to compute `_socket_mode_intended` once, near the top of the function (after `token`/`app_token` are read). Set it `True` iff all of:
    - `bool(token)` (i.e. `SLACK_BOT_TOKEN` non-empty), AND
    - `bool(app_token)` (`SLACK_APP_TOKEN` non-empty), AND
    - `not app.config.get('TESTING')`, AND
    - `app.config.get('SLACK_SOCKET_MODE_CONNECT', '').lower() == 'true'`.
    Use `global _socket_mode_intended` and assign before the existing early-return checks; the value is a snapshot of intent regardless of which (if any) early return fires.
  - Notes: Keep `_socket_handler` and `_socket_mode_intended` private (underscore prefix). The two accessor functions are the only new public symbols.

- [ ] **Task 3: Add `_WorkerStatusCollector` and the `esb_worker_last_iteration_timestamp_seconds` gauge**
  - File: `esb/services/metrics_service.py`
  - Action: Add a new collector class `_WorkerStatusCollector` next to `_PendingNotificationsCollector`. In its `collect()`:
    1. Query `AppConfig` for the row with `key == 'worker_last_iteration_at'` (one statement; `scalar_one_or_none()`).
    2. If row exists, parse `row.value` with `datetime.fromisoformat()`. If naive, treat as UTC (mirror lines 46-50). On parse failure (`ValueError`): call `logger.warning('Failed to parse worker last-iteration timestamp value=%r', row.value, exc_info=True)` and continue (omit the metric).
    3. Yield `GaugeMetricFamily('esb_worker_last_iteration_timestamp_seconds', "Unix timestamp (seconds) of the worker's last successful poll. Omitted if the worker has never run.", value=<epoch_seconds>)`.
    4. If the row does not exist, do not yield this metric.
  - Action: Register `_WorkerStatusCollector()` in `render_metrics()` alongside `_PendingNotificationsCollector()`.
  - Action: Add `import logging` and `logger = logging.getLogger(__name__)` if not already present, and `from esb.models.app_config import AppConfig`.
  - Notes: This collector also yields the two Socket Mode gauges (Task 4). The metric reads `row.value`, never `row.updated_at`.

- [ ] **Task 4: Add `esb_socket_mode_enabled` and `esb_socket_mode_connected` gauges (in the same collector)**
  - File: `esb/services/metrics_service.py`
  - Action: Inside `_WorkerStatusCollector.collect()` (after the worker-timestamp logic), do `import esb.slack as _slack` (lazy, inside `collect()` to avoid circular imports). Yield two gauges:
    1. `GaugeMetricFamily('esb_socket_mode_enabled', '1 if the deployment intends to run Slack Socket Mode (tokens configured and SLACK_SOCKET_MODE_CONNECT=true and not TESTING), 0 otherwise.', value=1.0 if _slack.is_socket_mode_enabled() else 0.0)`
    2. `GaugeMetricFamily('esb_socket_mode_connected', '1 if Slack Socket Mode initialized successfully at app startup, 0 otherwise. Reflects startup state only — does not detect mid-life WebSocket disconnects.', value=1.0 if _slack.is_socket_mode_connected() else 0.0)`
  - Action (continued): **Always emit** both. Neither has an "omit-when-N/A" semantics — `0` is meaningful.
  - Notes: Pinned import idiom — `import esb.slack as _slack` then `_slack.is_socket_mode_connected()`. **Do not** use `from esb.slack import is_socket_mode_connected` — that would bind the symbol into `metrics_service`'s namespace at import time and `monkeypatch.setattr('esb.slack.is_socket_mode_connected', ...)` would no longer be observed by the collector. The spec's tests rely on this idiom.

- [ ] **Task 5: Worker-loop tests — happy + IntegrityError + full-iteration survival**
  - File: `tests/test_services/test_notification_service.py`
  - Action: Add three tests.
    1. `test_record_iteration_timestamp_writes_appconfig_row`: invoke `_record_iteration_timestamp()` directly; query `AppConfig` for `key='worker_last_iteration_at'`; assert the row exists and `datetime.fromisoformat(row.value)` is within ±5 s of `datetime.now(UTC)`.
    2. `test_record_iteration_timestamp_recovers_from_integrity_error`: insert an `AppConfig` row with `key='worker_last_iteration_at'` and an old timestamp; monkeypatch `db.session.commit` to raise `IntegrityError('mock', None, Exception('mock'))` on the next call; invoke `_record_iteration_timestamp()`; assert no exception escapes, `caplog` contains `'Failed to update worker last-iteration timestamp'`. Then un-patch `commit` and perform an unrelated commit on the same session (e.g. inserting an unrelated `AppConfig` row); assert that commit succeeds — verifying the rollback left the session in a clean state (no `PendingRollbackError`).
    3. `test_worker_loop_survives_one_full_iteration_with_record_failure`: monkeypatch `_record_iteration_timestamp` (the module-level function) to raise `RuntimeError('boom')` once; stub `get_pending_notifications` to return `[]`; arrange for `_shutdown` to flip `True` after one iteration (e.g. via a side-effect on the stubbed function or by setting it directly); invoke `run_worker_loop(...)`; assert it returns without raising. (Closes the AC-coverage gap from adversarial review F11 — exercises the loop, not just the helper.)
  - Notes: Use existing `app`, `db`, `monkeypatch`, `caplog` fixtures. SQLite in-memory DB. For test 3, since `_record_iteration_timestamp` already swallows `SQLAlchemyError` internally, the test patches the helper itself to raise — which exercises whether the *loop* is also robust to a buggy helper. Both layers should be defensive.

- [ ] **Task 6: Service-layer metrics tests — three gauges, two-state Socket Mode coverage**
  - File: `tests/test_services/test_metrics_service.py`
  - Action: Add a `pytest.fixture(autouse=True)` (function-scoped) at module level (or in a new test class) that, before each test, resets the relevant Slack module-globals: `import esb.slack as slack_mod; slack_mod._bolt_app = None; slack_mod._socket_handler = None; slack_mod._socket_mode_intended = False`. Mirrors `tests/test_slack/test_init.py:51-52`.
  - Action: Add five tests using the existing `_extract_metric` regex helper and `app` fixture:
    1. `test_worker_last_iteration_timestamp_emitted_when_present`: insert AppConfig row with known ISO-8601 timestamp; call `render_metrics()`; extract metric; assert float value equals expected epoch seconds (within 1 µs).
    2. `test_worker_last_iteration_timestamp_omitted_when_absent`: no row; call `render_metrics()`; assert substring `'esb_worker_last_iteration_timestamp_seconds'` is NOT in body.
    3. `test_socket_mode_enabled_emits_one_when_intent_true`: monkeypatch `'esb.slack.is_socket_mode_enabled'` → `lambda: True`; assert body contains `esb_socket_mode_enabled 1.0`.
    4. `test_socket_mode_enabled_emits_zero_when_intent_false`: monkeypatch `'esb.slack.is_socket_mode_enabled'` → `lambda: False`; assert body contains `esb_socket_mode_enabled 0.0`.
    5. `test_socket_mode_connected_reflects_state`: parametrize over `[(True, '1.0'), (False, '0.0')]` with `monkeypatch.setattr('esb.slack.is_socket_mode_connected', lambda v=v: v)`; assert body contains the corresponding `esb_socket_mode_connected <expected>` line.
  - Notes: Tests 3 and 4 are split (per F17) — one assertion per test. Test 5 uses `pytest.mark.parametrize`. A small `_make_app_config(key, value)` helper (mirroring the existing `_make_pending` pattern at lines 17-27) is fine.

- [ ] **Task 7: Route-level metrics tests — three gauges with module-global reset**
  - File: `tests/test_views/test_metrics_view.py`
  - Action: Add the same autouse fixture as Task 6 to reset Slack module-globals before each test.
  - Action: Add four tests using the existing `client` fixture:
    1. `test_metrics_endpoint_includes_worker_timestamp_when_present`: insert AppConfig row; GET `/metrics`; assert `200`; body contains `'esb_worker_last_iteration_timestamp_seconds'`.
    2. `test_metrics_endpoint_omits_worker_timestamp_when_absent`: no row; GET `/metrics`; assert `200`; body does NOT contain `'esb_worker_last_iteration_timestamp_seconds'`.
    3. `test_metrics_endpoint_socket_mode_both_one_when_connected`: monkeypatch both Slack accessors to return `True`; GET `/metrics`; assert body contains `'esb_socket_mode_enabled 1.0'` AND `'esb_socket_mode_connected 1.0'`.
    4. `test_metrics_endpoint_socket_mode_both_zero_when_disabled`: monkeypatch both accessors to return `False`; GET `/metrics`; assert body contains `'esb_socket_mode_enabled 0.0'` AND `'esb_socket_mode_connected 0.0'`.
  - Notes: All monkeypatches use the dotted-string form `'esb.slack.is_socket_mode_enabled'` etc. — the import idiom in Task 4 makes this the correct surface.

- [ ] **Task 8: Reorganize the existing "Prometheus Metrics" subsection out of "Ongoing Maintenance" with anchor preservation**
  - File: `docs/administrators.md`
  - Action: Delete the `### Prometheus Metrics` subsection currently at lines 346-377 (heading, body, scrape config example, and `ESBNotificationQueueStuck` alert rule). In its place insert exactly:
    ```markdown
    <a id="prometheus-metrics"></a>

    For metrics, log-based alerting, and recommended dashboards, see [Monitoring and Alerting](#monitoring-and-alerting) below.
    ```
  - Notes: The literal HTML `<a id="prometheus-metrics"></a>` preserves the old anchor so external links (issue tracker, prior commit messages, blog posts) still scroll to a sensible position. MkDocs Material renders raw HTML inline. The deleted content is reused (with additions) by Task 9 — preserve the existing scrape config and `ESBNotificationQueueStuck` alert rule verbatim there.

- [ ] **Task 9: Add new top-level "Monitoring and Alerting" section**
  - File: `docs/administrators.md`
  - Action: Insert a new top-level `## Monitoring and Alerting` section immediately after `## New Relic Monitoring (Optional)` and before `## Ongoing Maintenance`. Subsections in order:
    1. **`### Overview`** — One paragraph: ESB exposes Prometheus metrics for system-health signals on `/metrics` (unauthenticated; trusted-network deployment); logs to stdout/stderr (consume with Loki/Promtail; both `app` and `worker` containers run unbuffered Python — see `PYTHONUNBUFFERED=1` in `docker-compose.yml`); metrics are designed for direct Grafana panel use. Complementary to the optional New Relic integration, which observes APM and browser layers. This guide gives recommended *signals*, not a turnkey configuration.
    2. **`### Prometheus Metrics`** — Reuse the existing scrape config example verbatim. Five-row metrics table:

       | Metric | Type | Description | Emission |
       |--------|------|-------------|----------|
       | `esb_pending_notifications_count` | gauge | Number of rows in `pending_notifications` with `status='pending'` | Always |
       | `esb_oldest_pending_notification_timestamp_seconds` | gauge | Unix epoch seconds of the oldest pending row's `created_at` | Omitted when queue empty (alert with `absent()`) |
       | `esb_worker_last_iteration_timestamp_seconds` | gauge | Unix epoch seconds of the worker's last successful poll cycle (read from `AppConfig.value`; `updated_at` is informational only) | Omitted when worker has never run (alert with `absent()`, **`for: 5m` minimum** to ride out cold-deploy time-to-first-poll) |
       | `esb_socket_mode_enabled` | gauge | `1` if deployment intends to run Socket Mode (tokens set, `SLACK_SOCKET_MODE_CONNECT=true`, not `TESTING`); `0` otherwise | Always |
       | `esb_socket_mode_connected` | gauge | `1` if `SocketModeHandler.connect()` succeeded at app startup; `0` otherwise. Reflects *startup state only* — does not detect mid-life WebSocket disconnects. | Always |

       Include the existing `ESBNotificationQueueStuck` rule verbatim, plus three new example rules:
       ```yaml
       - alert: ESBWorkerStalled
         expr: time() - esb_worker_last_iteration_timestamp_seconds > 120
         for: 1m
         annotations:
           summary: "ESB notification worker has not iterated in 2+ minutes"
       ```
       ```yaml
       - alert: ESBWorkerNeverRan
         expr: absent(esb_worker_last_iteration_timestamp_seconds)
         for: 5m
         annotations:
           summary: "ESB worker has not produced a heartbeat row since deploy (or DB reset)"
       ```
       ```yaml
       - alert: ESBSocketModeFailedAtBoot
         expr: esb_socket_mode_enabled == 1 and esb_socket_mode_connected == 0
         for: 2m
         annotations:
           summary: "ESB intended to run Slack Socket Mode but the handler failed at boot"
       ```
       Add a `!!! note` admonition:
       > **Clock skew.** The `ESBWorkerStalled` rule mixes Prometheus's `time()` (Prometheus server clock) with a worker-written timestamp (worker container clock). Run NTP on every node, and pick the threshold to be at least ~4× `poll_interval` (so 120s for the default 30s) to absorb expected drift. The `for: 5m` on `ESBWorkerNeverRan` is similarly there to ride out cold-deploy time-to-first-poll, not to detect a fast failure.

       Add a second `!!! note`:
       > **Single-worker assumption.** These metrics assume the current single-gunicorn-worker deployment (`--workers 1` in the Dockerfile). Scaling app-side gunicorn workers makes the Socket Mode metrics non-deterministic across scrapes (each worker process runs its own `init_slack`).
    3. **`### Container and Process Liveness`** — 2-3 sentences. `up{job="esb"} == 0` for ≥ 1 m indicates the app process is not responding to scrapes. cAdvisor / `container_last_seen`-style metrics catch container restart loops. Don't tutorialize.
    4. **`### Log-Based Alerting (Loki)`** — Intro paragraph: ESB writes logs to stdout/stderr; both `app` and `worker` containers run with `PYTHONUNBUFFERED=1`, so default Loki/Promtail Docker discovery captures lines without buffering latency. Then a *verified* "What to detect / Log substring" table — every entry is a real string from the cited source line:

       | What to detect | Source | Log substring |
       |----------------|--------|---------------|
       | Worker poll-cycle failure | `notification_service.py:402-405` | `Error in worker polling loop` |
       | Slack delivery exception (per notification) | `notification_service.py:390-393` | `delivery failed` (full line: `Notification %d delivery failed: %s`) |
       | Worker heartbeat write failure | `notification_service.py:35-37` | `Failed to update worker heartbeat at` |
       | Worker last-iteration write failure | (introduced by this PR) | `Failed to update worker last-iteration timestamp` |
       | Slack Socket Mode failed at boot | `esb/slack/__init__.py:67-69` | `Failed to connect Slack Socket Mode` |
       | Generic ERROR-level traffic | any | `ERROR` (level) and/or `Traceback` |

       Then a separate paragraph: **Permanent-fail signal lives in the structured JSON mutation log.** When a notification is permanently failed after `MAX_RETRIES`, `notification_service.py:141-147` writes a JSON record to logger `esb.mutations` with field `event=notification.permanently_failed`. Operators alerting on this event should match the JSON `event` field via Promtail JSON-stage parsing rather than substring grep — this is the only entry in this section that is structured rather than free-text.

       End with: "Operators write their own LogQL queries and alert rules; this guide intentionally lists signals, not queries."
    5. **`### What to Alert On`** — Bulleted punch list (≤ 7 items):
       - **App down** — `up{job="esb"} == 0` for ≥ 1 m
       - **Worker stalled** — the `ESBWorkerStalled` rule above
       - **Worker never ran since deploy / DB reset** — the `ESBWorkerNeverRan` rule above
       - **Notification queue stuck** — the existing `ESBNotificationQueueStuck` rule
       - **Slack Socket Mode failed at boot** — the `ESBSocketModeFailedAtBoot` rule above
       - **Elevated rate of Slack delivery failures** — Loki on `delivery failed` exceeding a per-minute threshold
       - **Container flapping** — cAdvisor restart-count rate (or equivalent)
    6. **`### Grafana Dashboards`** — 2-3 sentences. Metrics are designed for direct panel use (gauge stats for the count and the boolean gauges; time-series rendering `time() - <timestamp_gauge>`). ESB does not ship dashboard JSON.
    7. **`### Relationship to New Relic`** — 2-3 sentences. Different observation layers (server-side metrics + structured logs vs. APM + browser monitoring); complementary; can run together.
  - Notes: Match existing heading levels, table formatting, fenced code blocks, and `!!!` admonition syntax. Cross-link from this section back to `## New Relic Monitoring (Optional)` once.

- [ ] **Task 10: Add `PYTHONUNBUFFERED=1` to the `app` service in `docker-compose.yml`**
  - File: `docker-compose.yml`
  - Action: Locate the `app` service definition's `environment:` block. Add a new entry: `- PYTHONUNBUFFERED=1`. (The `worker` service already has it at line 51.)
  - Notes: Without this, app-side log lines pass through Python's block buffer and reach Docker's log driver (and therefore Loki/Promtail) with multi-second delay, invalidating the low-latency log alerting recommended in Task 9. Single-line change.

### Acceptance Criteria

- [ ] **AC 1 — Worker liveness gauge, happy path:** Given an `AppConfig` row with key `worker_last_iteration_at` and a valid ISO-8601 `value`, when an operator GETs `/metrics`, then the response body contains a value line of the form `esb_worker_last_iteration_timestamp_seconds <float>` where `<float>` equals the Unix epoch seconds of the parsed timestamp.

- [ ] **AC 2 — Worker liveness gauge, never-run:** Given no `AppConfig` row with key `worker_last_iteration_at` exists, when an operator GETs `/metrics`, then the substring `esb_worker_last_iteration_timestamp_seconds` does not appear in the response body.

- [ ] **AC 3 — Worker writes timestamp once per poll cycle:** Given `_record_iteration_timestamp()` is invoked, when it returns, then exactly one `AppConfig` row with key `worker_last_iteration_at` exists; its `value` parses as ISO-8601 and equals `datetime.now(UTC)` within ±5 s.

- [ ] **AC 4 — Worker timestamp write is non-fatal AND the worker loop survives one full iteration after a write failure:** Given `_record_iteration_timestamp` is patched to raise (or its underlying commit raises `SQLAlchemyError`), when one full poll iteration is exercised via `run_worker_loop()` with `_shutdown` arranged to set `True` after one cycle, then a warning is logged with substring `Failed to update worker last-iteration timestamp` (when failure originates inside the helper) or analogous, `db.session.rollback()` is invoked so the next commit on the same session succeeds, and `run_worker_loop()` returns cleanly without propagating an exception.

- [ ] **AC 5 — Worker timestamp write recovers from `IntegrityError`:** Given a simulated unique-constraint race where `db.session.commit` raises `IntegrityError` once, when `_record_iteration_timestamp()` catches it, then it calls `db.session.rollback()`, logs a warning with substring `Failed to update worker last-iteration timestamp`, and a subsequent unrelated commit on the same session succeeds (no `PendingRollbackError`).

- [ ] **AC 6 — `esb_socket_mode_enabled` reflects intent:** Given `SLACK_BOT_TOKEN` non-empty AND `SLACK_APP_TOKEN` non-empty AND `TESTING=False` AND `SLACK_SOCKET_MODE_CONNECT='true'`, when an operator GETs `/metrics`, then the response contains `esb_socket_mode_enabled 1.0`. Given any of those four conditions is false, the response contains `esb_socket_mode_enabled 0.0`.

- [ ] **AC 7 — `esb_socket_mode_connected` reflects state:** Given `_socket_handler is not None` (the Bolt SocketModeHandler initialized successfully at app startup), when an operator GETs `/metrics`, then the response contains `esb_socket_mode_connected 1.0`. Otherwise, the response contains `esb_socket_mode_connected 0.0`.

- [ ] **AC 8 — Both Socket Mode gauges always emitted:** Given any state of the system, when an operator GETs `/metrics`, then both `esb_socket_mode_enabled` and `esb_socket_mode_connected` are present in the response (no omit-when-N/A semantics).

- [ ] **AC 9 — Existing metrics unchanged:** `esb_pending_notifications_count` and `esb_oldest_pending_notification_timestamp_seconds` retain their names, types, labels, and emission semantics from #32. No backward-incompatible changes for downstream alert rules.

- [ ] **AC 10 — `/metrics` endpoint stability:** GET `/metrics` returns HTTP `200`, `Content-Type` includes `text/plain` and `version=`, body parses as valid Prometheus exposition format, no authentication required.

- [ ] **AC 11 — `PYTHONUNBUFFERED=1` set on the app service:** Given the updated `docker-compose.yml`, when `docker compose config` is run (or the file is inspected), then `PYTHONUNBUFFERED=1` is present in the `app` service's environment. The `worker` service continues to have it set.

- [ ] **AC 12 — Documentation, new section exists:** A top-level `## Monitoring and Alerting` section exists in `docs/administrators.md` immediately after `## New Relic Monitoring (Optional)`, containing exactly seven subsections in order: Overview; Prometheus Metrics; Container and Process Liveness; Log-Based Alerting (Loki); What to Alert On; Grafana Dashboards; Relationship to New Relic.

- [ ] **AC 13 — Documentation, old subsection migrated with anchor preservation:** Under `## Ongoing Maintenance`, the previous `### Prometheus Metrics` subsection is gone; a forward-pointer line including a literal `<a id="prometheus-metrics"></a>` HTML anchor and a Markdown link to the new section replaces it. External links to `docs/administrators/#prometheus-metrics` continue to land on a meaningful location.

- [ ] **AC 14 — Documentation, metric and alert tables updated:** The new `### Prometheus Metrics` subsection's metric table includes one row each for the five metrics. The example alert rules include the existing `ESBNotificationQueueStuck` (verbatim), the new `ESBWorkerStalled` (`time() - esb_worker_last_iteration_timestamp_seconds > 120`, `for: 1m`), the new `ESBWorkerNeverRan` (`absent(...)`, `for: 5m`), and the new `ESBSocketModeFailedAtBoot` (`enabled == 1 AND connected == 0`, `for: 2m`).

- [ ] **AC 15 — Documentation, Loki substrings are verified:** The "What to detect / Log substring" table contains only substrings that appear verbatim (or as unambiguous prefixes) in the source files at the cited line ranges. Specifically: `Error in worker polling loop` (notification_service.py:402-405), `delivery failed` (notification_service.py:390-393), `Failed to update worker heartbeat at` (notification_service.py:35-37), `Failed to update worker last-iteration timestamp` (introduced in this PR), `Failed to connect Slack Socket Mode` (esb/slack/__init__.py:67-69). The permanent-fail signal is documented separately as a JSON mutation-log event (`event=notification.permanently_failed`), not as a substring-grep entry.

- [ ] **AC 16 — Documentation, clock-skew and multi-worker caveats present:** The new "Prometheus Metrics" subsection includes one `!!! note` admonition recommending NTP and a threshold ≥ 4× `poll_interval` for the `ESBWorkerStalled` rule, and a second `!!! note` warning that the Socket Mode metrics assume single-gunicorn-worker deployment (`--workers 1`).

- [ ] **AC 17 — Lint and tests pass:** `make lint` exits `0`. `make test` exits `0`. The new tests are present and pass: 3 in `test_notification_service.py`, 5 in `test_metrics_service.py`, 4 in `test_metrics_view.py` = **12 new tests**.

## Additional Context

### Dependencies

- `prometheus_client` — already a runtime dependency (introduced in #32). No new packages.
- `AppConfig` model — already exists at `esb/models/app_config.py`. No schema migration required.
- `sqlalchemy.exc.SQLAlchemyError` — standard SQLAlchemy import, already pulled in transitively.
- No new Python packages, no new Docker services, no new external integrations.

### Testing Strategy

- **Unit / service tests**: 8 new tests across `tests/test_services/test_metrics_service.py` (5) and `tests/test_services/test_notification_service.py` (3). Reuse the existing SQLite in-memory DB, the `_extract_metric` regex helper, and `app`, `db`, `monkeypatch`, `caplog` fixtures. No new conftest fixtures required.
- **Route / integration tests**: 4 new tests in `tests/test_views/test_metrics_view.py`. Use the `client` fixture; mirror the existing GET `/metrics` substring-assert style.
- **Module-global hygiene**: tests in `test_metrics_service.py` and `test_metrics_view.py` reset `esb.slack._bolt_app`, `_socket_handler`, and `_socket_mode_intended` before each test (mirrors `tests/test_slack/test_init.py:51-52` precedent). Without this, test order can leak Socket Mode state.
- **High-risk-mode coverage**: Task 5 includes a dedicated `test_worker_loop_survives_one_full_iteration_with_record_failure` which actually invokes `run_worker_loop()` (not just the helper) — closes the AC-coverage gap identified in adversarial review.
- **Race-condition coverage**: Task 5 includes `test_record_iteration_timestamp_recovers_from_integrity_error` which simulates an `IntegrityError` and verifies the rollback semantics (the next commit on the same session succeeds).
- **Manual verification**: After implementation:
  - `docker compose up -d --build`
  - `curl http://localhost:5000/metrics` — confirm the gauge lines: `esb_pending_notifications_count`, `esb_socket_mode_enabled`, `esb_socket_mode_connected`. Wait ~30 s for one worker poll cycle; re-curl; confirm `esb_worker_last_iteration_timestamp_seconds` is recent.
  - `docker compose stop worker`; wait 2 m; verify the `ESBWorkerStalled` rule (if loaded into Prometheus) would fire.
  - `docker compose exec app sh -c 'logger() { echo $(date +%s.%N) marker; }'` — confirm app log lines reach `docker logs <app>` without multi-second buffering delay.

### Notes

- **Known limitation: `esb_socket_mode_connected` is startup-only.** Slack Bolt's `SocketModeHandler` exposes no public connection-state hooks; a live "is the WebSocket currently connected" gauge would require monkey-patching `slack-bolt` internals. The two-gauge design (`enabled` + `connected`) lets operators alert on `enabled == 1 AND connected == 0` to catch the actionable failure (Slack tried-and-failed) without false alarms on intentional opt-out.
- **Known limitation: single-gunicorn-worker assumption.** With `--workers 1` (current Dockerfile), `_socket_handler` is per-process and stable. Scaling workers introduces non-determinism (each process runs its own `init_slack`) and is a separate hardening task out of this scope.
- **Known limitation: clock-skew sensitivity.** `time() - <gauge>` rules mix Prometheus and worker clocks. NTP and a threshold ≥ 4× `poll_interval` are recommended in the doc.
- **`PYTHONUNBUFFERED=1` on app is a small but load-bearing operational fix.** Without it, the entire low-latency log-alerting story in Task 9 is silently broken.
- **High-risk item — non-fatal worker write semantics.** A bug here (broad `except`, missing rollback, or unhandled `IntegrityError`) could re-introduce the silent-stall failure class that #32 set out to fix. AC 4 and AC 5 explicitly cover the negative paths.
- **Loki guidance ships verified substrings only.** No "TBD at implementation time" placeholders survive into the doc — every substring in the table is taken from a source line cited in this spec.
- **Permanent-fail signal is JSON, not free-text.** Doc explicitly distinguishes the JSON mutation-log signal from the substring-grep table; operators wire it via Promtail JSON parsing, not `|=` line filters.
- **Performance: ~one extra DB query per scrape.** Negligible at default scrape intervals; documented as a trade-off without consolidation.
- **Anchor preservation** for `#prometheus-metrics` keeps existing external links functional after the doc reorganization.
- **Future considerations (out of scope):**
  - Counter-based slack-delivery metrics (DB-backed) — dropped; Loki on `delivery failed` covers the alerting goal.
  - Live Socket Mode WebSocket-state gauge — requires upstream Slack Bolt change.
  - Multi-process Socket Mode coordination — separate hardening task.
  - `/metrics` authentication option for less-trusted deployments — not in scope.
  - In-process caching of `worker_last_iteration_at` for aggressive scrape intervals — not currently warranted.
