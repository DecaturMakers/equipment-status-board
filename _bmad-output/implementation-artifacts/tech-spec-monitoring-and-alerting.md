---
title: 'Monitoring and Alerting Guide + System-Health Metrics'
slug: 'monitoring-and-alerting'
created: '2026-05-10'
status: 'ready-for-dev'
stepsCompleted: [1, 2, 3, 4]
revision: 4
revision_notes: 'Third adversarial-review pass applied — 18 findings addressed (revision 3 introduced regressions: contradictory test 5.3 design, broad db.session.execute monkeypatch breaking the existing collector, vacuous rollback verification, CWD-relative test paths, undeclared PyYAML dependency, (False, True) Socket Mode race window, undocumented import-failure invisibility, and several alert/log-cardinality concerns).'
tech_stack:
  - 'Python 3.14'
  - 'Flask'
  - 'Flask-SQLAlchemy + SQLAlchemy 2.x style'
  - 'MariaDB (production) / SQLite (tests)'
  - 'prometheus_client'
  - 'slack-bolt + slack_sdk (Socket Mode)'
  - 'pytest'
  - 'PyYAML (added explicitly to dev deps in this PR)'
  - 'MkDocs Material — docs site (markdown_extensions: attr_list, md_in_html, admonition, pymdownx.details, pymdownx.superfences, tables, toc with permalink)'
files_to_modify:
  - 'docs/administrators.md'
  - 'docker-compose.yml'
  - 'requirements-dev.txt'
  - 'esb/services/metrics_service.py'
  - 'esb/services/notification_service.py'
  - 'esb/slack/__init__.py'
  - 'tests/test_services/test_metrics_service.py'
  - 'tests/test_services/test_notification_service.py'
  - 'tests/test_views/test_metrics_view.py'
  - 'tests/test_compose.py (new file)'
code_patterns:
  - 'Custom prometheus_client collector class in metrics_service.py with fresh CollectorRegistry per request'
  - "Omit gauges entirely when 'not applicable' rather than emitting a sentinel value (alert with absent())"
  - 'Service-layer pattern: views and the worker delegate to esb/services/* functions; no direct model access from views'
  - 'AppConfig key-value table for runtime-configurable / cross-process state'
  - 'Worker writes heartbeat file at three points (startup, after DB poll, after each notification)'
  - 'SQLAlchemy session: explicit rollback() on caught SQLAlchemyError before continuing the loop, narrow except clauses (SQLAlchemyError, OSError) — broad except Exception is reserved for the outermost worker-loop guard'
  - "Slack module-globals (_bolt_app, _socket_handler) reset in test setUp/tearDown; new tests touching them must follow the same pattern (see tests/test_slack/test_init.py:51-52,74-75,151-152)"
  - "Worker-loop tests break the loop by stubbing get_pending_notifications to raise KeyboardInterrupt — _shutdown is function-local and not externally settable. time.sleep MUST be patched too (notification_service.time) or the test sleeps the real backoff"
  - "Lazy + dotted import idiom for monkeypatch surface: inside _WorkerStatusCollector.collect(), use `import esb.slack as _slack` then `_slack.is_socket_mode_connected()`. Tests then patch via `monkeypatch.setattr('esb.slack.is_socket_mode_connected', ...)`"
test_patterns:
  - "Service-layer tests in tests/test_services/test_metrics_service.py — use 'app' fixture; assert against rendered exposition text via regex (_extract_metric helper)"
  - "Route-level tests in tests/test_views/test_metrics_view.py — use 'client' fixture; GET /metrics, assert 200 and substring match on metric name lines"
  - 'Worker-loop tests in tests/test_services/test_notification_service.py — use SQLite in-memory DB; for full-iteration tests, stub get_pending_notifications to raise KeyboardInterrupt after the desired number of iterations, AND patch notification_service.time so backoff sleeps do not actually run'
  - 'DB-error degradation tests use db.drop_all(tables=[AppConfig.__table__]) followed by db.create_all(tables=[AppConfig.__table__]) for restoration — surgical, real DB error from a real session, does not affect other tables (so the existing pending_notifications collector is untouched)'
  - 'Resolve repo-root paths in tests via Path(__file__).resolve().parent.parent — never CWD-relative'
issue: 12
related_issues: [32]
---

# Tech-Spec: Monitoring and Alerting Guide + System-Health Metrics

**Created:** 2026-05-10
**Issue:** [#12 — Monitoring and alerting](https://github.com/jantman/equipment-status-board/issues/12)
**Related:** #32 (initial Prometheus endpoint and worker-resilience hardening)
**Revision:** 4 (third adversarial-review pass applied)

## Overview

### Problem Statement

The Administrator Guide (`docs/administrators.md`) lacks a dedicated "Monitoring and Alerting" section. Issue #32 added two notification-queue gauges to `/metrics`, but operators deploying ESB with Prometheus + Loki + Grafana have no documented guidance on what signals indicate ESB itself is unhealthy. The existing `/metrics` endpoint exposes only queue gauges — nothing about worker liveness as a scrapable metric (the heartbeat is a file inside the worker container, unreadable from the app process), nothing distinguishing "Socket Mode intentionally off" from "Socket Mode tried and failed at boot," and nothing about per-instance app availability beyond the existing Docker healthcheck and autoheal sidecar.

In addition, application-side stdout is currently subject to Python's default block buffering (only the worker container has `PYTHONUNBUFFERED=1`), so app log lines reach Loki/Promtail with multi-second lag — invalidating any low-latency log-based alerting unless the asymmetry is fixed.

### Solution

Three-part change:

1. **Documentation:** Add a new top-level `## Monitoring and Alerting` section to `docs/administrators.md` (peer of "New Relic Monitoring (Optional)"). Promote the existing "Prometheus Metrics" subsection into it, preserving the original `#prometheus-metrics` HTML anchor at the forward-pointer location (`mkdocs.yml` enables `attr_list` and `md_in_html`, so raw inline HTML passes through). Cover Prometheus, Loki (verified substrings only), Grafana (high-level), container-level liveness (`up{}`, cAdvisor — brief), a "What to alert on" checklist, an explicit clock-skew/NTP caveat, the single-gunicorn-worker assumption, and an information-disclosure note.

2. **Code:** Expand `/metrics` with **three** new system-health-only gauges:
   - `esb_worker_last_iteration_timestamp_seconds` (gauge, DB-backed via `AppConfig` key `worker_last_iteration_at`) — Unix epoch seconds of the worker's most recent successful poll cycle. Read from `AppConfig.value` (parsed from ISO-8601). Omitted when the row does not exist or when the underlying `AppConfig` SELECT raises `SQLAlchemyError` (covers `OperationalError` / `ProgrammingError` from a missing or unreachable table — pre-migration deployments stay 200 instead of 500).
   - `esb_socket_mode_enabled` (gauge, in-process, always emitted) — `1` if `init_slack` reached the Socket Mode setup block; `0` if any of the five early-return paths fired or the Socket Mode setup block raised. Set by `init_slack` itself at the start of the setup block (before handler instantiation), so the gauge cannot drift from `init_slack`'s actual code path and there is no `(False, True)` race window.
   - `esb_socket_mode_connected` (gauge, in-process, always emitted) — `1` if a Bolt SocketModeHandler is currently bound; `0` if never bound or released. Transitions `1 → 0` at process shutdown via `_shutdown_socket()`.
   - **Actionable failure mode:** `esb_socket_mode_enabled == 1 AND esb_socket_mode_connected == 0` — covers connect-call failures, handler-instantiation failures, AND import-time failures (all of which now share the same setup `try` block, per Task 2).

3. **Operational fix:** Add `PYTHONUNBUFFERED=1` to the `app` service in `docker-compose.yml`. Add `PyYAML` explicitly to `requirements-dev.txt` (currently only available transitively via `mkdocs`). Add `tests/test_compose.py` with two automated YAML-load assertions: one for `PYTHONUNBUFFERED=1` on both `app` and `worker`, and one for `attr_list`/`md_in_html` in `mkdocs.yml`. Both assertions resolve their paths via `Path(__file__).resolve().parent.parent` so they work from any CWD.

### Scope

**In Scope:**

- New `## Monitoring and Alerting` section in `docs/administrators.md`
- Reorganization of the existing "Prometheus Metrics" subsection with HTML anchor preservation
- Three new gauges on `/metrics` with `try/except SQLAlchemyError` graceful-degradation in the new collector
- Worker writes its last-iteration timestamp to `AppConfig` via `_record_iteration_timestamp()`; the call site in `run_worker_loop` is wrapped in its **own** `try/except Exception` so a programming bug in the helper does not abort notification processing for the iteration (closes adversarial F5)
- New public `is_socket_mode_enabled()` and `is_socket_mode_connected()` accessors in `esb/slack/__init__.py`
- `_socket_mode_intended` set inside `init_slack` **at the start of the Socket Mode setup block** (before handler instantiation) — eliminates the `(False, True)` race window AND covers the import-time failure path through the same `try/except` (closes F7 and F12)
- Verified Loki substrings using unique markers (`Notification ` with capital N for the per-notification log) that don't collide with the JSON mutation-log stream (closes F11)
- `ESBSocketModeFailedAtBoot` rule with `for: 5m` and `unless on(instance) up{} == 0` to absorb shutdowns and gunicorn worker reloads (closes F9)
- `_WorkerStatusCollector` logs SQLAlchemyError without `exc_info=True` (one-line warning per scrape) to avoid log-flooding on pre-migration deployments; the *first* occurrence per process is logged with `exc_info=True` for diagnostics (closes F10)
- `tests/test_compose.py` resolves paths via `Path(__file__).resolve().parent.parent` (closes F6); explicit `PyYAML` dev dependency (closes F8)
- DB-error degradation tests use `db.drop_all(tables=[AppConfig.__table__])` for surgical, realistic table-missing simulation — does not affect `pending_notifications`, so the existing `_PendingNotificationsCollector` is unperturbed (closes F2, F3, F18)
- Worker-loop test patches `notification_service.time` so backoff sleeps don't actually run (closes F14); test design uses a side-effect counter on `get_pending_notifications` rather than a buggy two-call helper flag (closes F1)
- Three explicit `(enabled, connected)` combination tests in Task 7 covering the reachable matrix (closes F13)
- Cross-link from "Ongoing Maintenance" to the new Monitoring section
- Frontmatter `code_patterns` and the body Tasks describe the **same** import idiom (closes F16)

**Out of Scope:**

- Full LogQL queries, Loki label selectors, parser configurations, or Grafana dashboard JSON
- Business metrics (repair counts, equipment counts, user activity, login rates, page-view counters)
- Slack delivery success/failure counters (Loki on log strings covers it)
- Static page push freshness/failure metric (covered by queue-staleness gauge)
- DB connectivity gauge (covered by `up{}` and queue gauge errors)
- Changes to existing New Relic integration
- Installing or configuring Prometheus / Loki / Grafana themselves
- Authentication for `/metrics` (stays unauthenticated; trusted-network deployment) — incremental information disclosure called out in Notes
- Alertmanager / alert routing configuration
- Wrapping the existing `_PendingNotificationsCollector` in graceful-degradation try/except — separate hardening, not motivated by this spec; the new tests use real table-drop on `AppConfig` so they don't trigger the existing collector's failure path
- Live Socket Mode WebSocket-state hooks — Slack Bolt does not expose them
- Multi-process Socket Mode coordination
- IntegrityError-race hardening for the AppConfig write (single-writer makes it impossible)

## Context for Development

### Codebase Patterns

- **Metrics collector pattern:** Custom collector class implementing `collect()` and yielding `GaugeMetricFamily`; registered into a fresh `CollectorRegistry` per scrape inside `render_metrics()` (`esb/services/metrics_service.py:84-92`).
- **Single-query snapshot:** Aggregates that need to be consistent come from one combined `SELECT` (e.g., `_query_pending_stats()` at lines 27-52). New gauges may add a separate query for unrelated state.
- **Omit when N/A or query fails:** When a gauge has no meaningful value, do not emit it. Operators alert with `absent()`. Same pattern applies on a transient query failure: omit + log a brief warning, do not raise out of `collect()`.
- **Worker entry point:** `flask worker run` CLI registered in `esb/__init__.py:149-157` invokes `notification_service.run_worker_loop()` at line 322.
- **Worker shutdown semantics:** `_shutdown` is **function-local** to `run_worker_loop()` (line 364), assigned `nonlocal` from a SIGTERM-handler closure inside the same function. Not externally settable. Tests terminate the loop by raising `KeyboardInterrupt` (or any other `BaseException`) from a stubbed in-loop call — `KeyboardInterrupt` propagates past the inner `except Exception:` guard at line 399.
- **Worker poll loop body** (verified, current main, lines 364-409):
  ```text
  while not _shutdown:
      try:                               # outer try, line 365
          notifications = get_pending_notifications()    # line 366
          _write_heartbeat(heartbeat_path)               # line 369 (post-poll heartbeat)
          consecutive_poll_failures = 0
          if notifications: logger.info(...)
          for notification in notifications:             # line 374
              if _shutdown: break
              try:                       # inner try, line 377
                  process_notification(notification)
                  mark_delivered(notification.id)
              except NotImplementedError: ...
              except Exception: ...
              _write_heartbeat(heartbeat_path)           # line 397 (per-notification)
      except Exception:                  # outer except, line 399
          consecutive_poll_failures += 1
          backoff = min(poll_interval * (2 ** consecutive_poll_failures), 300)
          logger.error('Error in worker polling loop ...', exc_info=True)
          if not _shutdown:
              time.sleep(backoff)        # ← real sleep; tests must patch this
              continue
  ```
- **`_write_heartbeat` catches `OSError` specifically** (`notification_service.py:29-37`). The new `_record_iteration_timestamp` catches `SQLAlchemyError` specifically and rolls back the session.
- **AppConfig key-value pattern:** `esb/models/app_config.py` is a single-row-per-key table (`key` unique, `value` text, `updated_at` with `default=` and `onupdate=`). The metric reads `value` (authoritative ISO-8601 string); `updated_at` is informational only.
- **ISO-8601 round-trip:** Worker writes `datetime.now(UTC).isoformat()` (always offset-bearing); `datetime.fromisoformat()` returns aware. No naive-handling branch needed.
- **DB-error class portability:** SQLite raises `OperationalError` for "no such table"; MariaDB raises `ProgrammingError`. Both subclass `SQLAlchemyError`. The collector and helper catch `SQLAlchemyError` (the superclass) so they work in both environments. Test code drops the `AppConfig` table to drive the SQLite case.
- **Slack Bolt initialization** (verified, current main `esb/slack/__init__.py`):
  - Bolt `App` constructed at line 42.
  - **Five early-return paths** leave `_socket_handler = None`: missing `SLACK_BOT_TOKEN` (lines 27-29), missing `SLACK_APP_TOKEN` (lines 31-33), `TESTING=True` (lines 51-53), `SLACK_SOCKET_MODE_CONNECT.lower() != 'true'` (lines 56-58), or `connect()` raised (lines 67-70).
  - **Sixth, currently uncovered path:** `from slack_bolt.adapter.socket_mode import SocketModeHandler` (line 60) raising `ImportError` — propagates out of `init_slack` today (Task 2 closes this hole).
  - Failure-at-connect log substring `Failed to connect Slack Socket Mode` at line 68.
  - `_shutdown_socket()` (lines 92-105) sets `_socket_handler = None` on graceful shutdown — `is_socket_mode_connected()` transitions 1→0 here.
- **Slack module-globals reset by existing tests:** `tests/test_slack/test_init.py` resets `slack_mod._bolt_app`, `_socket_handler` in setUp/tearDown (lines 51-52, 74-75, 151-152). New metrics tests in this PR use an autouse fixture that does the same. `_socket_mode_intended` is reset by every `init_slack(app)` call (Task 2 places the reset at the top of the function), so it is not in the autouse fixture's reset list — but new tests that don't call `init_slack` should reset it manually.
- **Mutation logger** at `esb/utils/logging.py:36-42` emits **structured JSON** via `json.dumps(...)`. Permanent-fail events are `log_mutation('notification.permanently_failed', ...)` (`notification_service.py:141-147`). The rendered line is a single-line JSON document.
- **Free-text vs JSON log line discrimination:** The free-text per-notification error log starts with `Notification ` (capital N + space, from format string `'Notification %d delivery failed: %s'`); the JSON mutation log starts with `{` and uses lowercase `notification.failed` as a structured field. Loki substring `Notification ` (with the leading capital N + space) uniquely identifies the free-text line.

### Files to Reference

| File | Purpose |
| ---- | ------- |
| `docs/administrators.md` | The doc being edited |
| `docker-compose.yml` | Add `PYTHONUNBUFFERED=1` to the `app` service environment |
| `mkdocs.yml` | Read-only reference; verifies `attr_list` + `md_in_html` are enabled |
| `requirements-dev.txt` | Add explicit `PyYAML` pin |
| `esb/services/metrics_service.py` | Existing collector; add `_WorkerStatusCollector` with try/except |
| `esb/__init__.py` | `/metrics` and `/health` routes |
| `esb/services/notification_service.py` | Worker run loop; add `_record_iteration_timestamp()` and a defensive call site |
| `esb/models/app_config.py` | `AppConfig` model |
| `esb/slack/__init__.py` | Slack Bolt initialization; gains two accessors and a unified Socket Mode setup `try` block |
| `esb/utils/logging.py` | Mutation logger reference (`logging.py:36-42` — `json.dumps`-based JSON output) |
| `tests/conftest.py` | Test fixtures (`app`, `client`, `db`) |
| `tests/test_services/test_metrics_service.py` | Service-layer tests |
| `tests/test_views/test_metrics_view.py` | Route-level tests |
| `tests/test_services/test_notification_service.py` | Worker-loop tests (existing tests show the `notification_service.time` patch pattern) |
| `tests/test_slack/test_init.py` | Reference for module-global reset pattern |
| `tests/test_compose.py` (new) | YAML-load assertions for `docker-compose.yml` and `mkdocs.yml` |

### Technical Decisions

- **No new authentication on `/metrics`** — stays unauthenticated, trusted-network deployment.
- **System-health metrics only** — no business / activity metrics.
- **`AppConfig` reused, no new table.** `value` (ISO-8601 string) is authoritative.
- **`_socket_mode_intended` set at the start of the unified Socket Mode setup `try` block, before handler instantiation.** No `(False, True)` race window. Import errors, instantiation errors, and connect errors all leave state at `(True, False)` — the actionable alert state.
- **`ESBWorkerStalled` and `ESBWorkerNeverRan` cover different failure modes** and complement each other. `ESBWorkerStalled` (`time() - X > 120`, `for: 1m`) detects "worker has been alive but stopped iterating recently". `ESBWorkerNeverRan` (`absent(X)`, `for: 5m`) detects "metric is missing entirely" — including cold-deploy time-to-first-poll AND transient AppConfig query failures. The doc explicitly says "load both rules; they are complementary."
- **`ESBSocketModeFailedAtBoot` uses `for: 5m unless on(instance) up{} == 0`.** The `for: 5m` absorbs gunicorn worker reloads (`--max-requests` recycling) where `_shutdown_socket()` briefly leaves state at `(1, 0)`. The `unless` clause silences the alert during full app outages where `up == 0` would already be the dominant alert.
- **`_WorkerStatusCollector` logs DB errors with rate limiting.** First failure per process is logged with `exc_info=True`; subsequent failures within the same process lifetime are logged at WARNING with a single-line message and no traceback. Implemented via a module-level boolean `_app_config_query_failed_once` (set on first failure). Prevents log flooding on pre-migration scrapes (every 15-30s).
- **Helper call site is wrapped in its own `try/except Exception`** so a programming bug in `_record_iteration_timestamp` (which already catches `SQLAlchemyError` internally — so the only escape is a non-DB exception, i.e., a code bug) does NOT abort notification processing for the iteration. Inner `except` logs at ERROR level (it's a bug); outer worker-loop `try` continues to process notifications.
- **Loki substring for per-notification delivery failure: `Notification ` (with the capital N and trailing space).** Uniquely matches the format-string-prefixed app log line; does NOT match the JSON mutation log (which starts with `{` and uses lowercase `notification`).
- **`tests/test_compose.py` paths resolve via `Path(__file__).resolve().parent.parent`.** CWD-independent.
- **`PyYAML` declared explicitly in `requirements-dev.txt`.** No reliance on transitive accidents.
- **DB-error degradation tests use `db.drop_all(tables=[AppConfig.__table__])`.** Real table-missing in SQLite raises real `OperationalError`. Surgical: only `app_config` is dropped, so the `pending_notifications` collector is unaffected.
- **Pinned import idiom for monkeypatch surface:** `import esb.slack as _slack` is **lazy, inside `_WorkerStatusCollector.collect()`** — not at module top of `metrics_service.py`. Frontmatter and body agree on this.
- **Single gunicorn worker is a deployment assumption.** Documented in admin guide.
- **Performance: ~one extra DB query per scrape.** Negligible at default intervals.
- **`/metrics` exposition stability:** existing two metrics keep their names, types, and emission semantics.

## Implementation Plan

### Tasks

- [ ] **Task 1: Worker writes `worker_last_iteration_at` to `AppConfig` once per poll cycle, with a defensive call-site wrapper**
  - File: `esb/services/notification_service.py`
  - Action (helper definition): Add a private helper `_record_iteration_timestamp() -> None`:
    ```python
    def _record_iteration_timestamp() -> None:
        """Upsert the worker's last-iteration timestamp into AppConfig.

        Catches SQLAlchemyError (covers OperationalError from transient DB drops
        and ProgrammingError from a missing app_config table on pre-migration
        deployments — both subclasses of SQLAlchemyError). On error: rollback
        the session and log a warning. Do not propagate.
        """
        now_iso = datetime.now(UTC).isoformat()
        try:
            row = db.session.execute(
                select(AppConfig).where(AppConfig.key == 'worker_last_iteration_at')
            ).scalar_one_or_none()
            if row is None:
                db.session.add(AppConfig(key='worker_last_iteration_at', value=now_iso))
            else:
                row.value = now_iso
            db.session.commit()
        except SQLAlchemyError:
            db.session.rollback()
            logger.warning('Failed to update worker last-iteration timestamp', exc_info=True)
    ```
  - Imports to add (top of file): `from sqlalchemy.exc import SQLAlchemyError`, `from sqlalchemy import select` (if not already imported), `from esb.models.app_config import AppConfig`.
  - Action (call site): In the loop body of `run_worker_loop()` (function defined at line 322), insert the helper call immediately after the existing post-poll `_write_heartbeat(heartbeat_path)` at line 369. **Wrap the call in its own inner `try/except Exception`** — *not* sharing the outer `try` block:
    ```python
    _write_heartbeat(heartbeat_path)         # existing line 369
    consecutive_poll_failures = 0           # existing line 370
    # NEW: defensive wrapper. The helper already catches SQLAlchemyError; the
    # only thing it can raise is a programming bug. Don't let that abort the
    # iteration's notification processing — log loudly and continue.
    try:
        _record_iteration_timestamp()
    except Exception:
        logger.error(
            'BUG: _record_iteration_timestamp raised unexpectedly — iteration metric will be stale',
            exc_info=True,
        )
    ```
  - Notes: This two-block design closes adversarial-review F5 (a buggy helper would otherwise skip notification processing for the iteration). Do not call the helper at the startup-heartbeat site (line 355) or the per-notification site (line 397).

- [ ] **Task 2: Unified Socket Mode setup `try` block; expose two accessors**
  - File: `esb/slack/__init__.py`
  - Action: Add module-level `_socket_mode_intended: bool = False` near existing globals at lines 9-11.
  - Action: At the **top** of `init_slack(app)` (immediately after the docstring), add: `global _socket_mode_intended; _socket_mode_intended = False`. This resets the flag on every fixture-driven re-init.
  - Action: **Restructure the Socket Mode setup block** (currently lines 60-70). Replace those lines with a single unified `try/except` that covers import, instantiation, connect, and the intent flag:
    ```python
    try:
        global _socket_mode_intended
        _socket_mode_intended = True   # set FIRST — before handler binding — so there
                                       # is no (False, True) observation window.
        from slack_bolt.adapter.socket_mode import SocketModeHandler
        _socket_handler = SocketModeHandler(app=_bolt_app, app_token=app_token)
        _socket_handler.connect()
        logger.info('Slack Socket Mode connected')
    except Exception:
        logger.warning(
            'Failed to set up Slack Socket Mode — app will run without Slack',
            exc_info=True,
        )
        _socket_handler = None
        return
    ```
    Now the actionable failure mode `enabled==1 AND connected==0` covers all five things that can go wrong during setup: import error, handler-instantiation error, connect error, and any other unexpected exception in this block. Closes F7 and F12.
  - Action: Add two public functions:
    ```python
    def is_socket_mode_enabled() -> bool:
        """True iff the most recent init_slack() call entered the Socket Mode setup
        block (tokens set, not TESTING, opt-in flag true). False on any of the four
        early-return paths or if the setup block was never reached."""
        return _socket_mode_intended

    def is_socket_mode_connected() -> bool:
        """True iff a Bolt SocketModeHandler is currently bound. Transitions
        True→False at process shutdown via _shutdown_socket(). Slack Bolt does
        not expose mid-life WebSocket connection-state callbacks."""
        return _socket_handler is not None
    ```
  - Notes: The Loki substring `Failed to set up Slack Socket Mode` (note the change from "Failed to connect Slack Socket Mode" — broader scope) covers all setup failure paths. Update the doc Loki table accordingly.

- [ ] **Task 3: `_WorkerStatusCollector` with worker-timestamp gauge and rate-limited DB-error logging**
  - File: `esb/services/metrics_service.py`
  - Action: Add a module-level boolean: `_app_config_query_failed_once: bool = False`.
  - Action: Add a new collector class `_WorkerStatusCollector` next to `_PendingNotificationsCollector`. In `collect()`:
    ```python
    global _app_config_query_failed_once
    row = None
    try:
        row = db.session.execute(
            select(AppConfig).where(AppConfig.key == 'worker_last_iteration_at')
        ).scalar_one_or_none()
    except SQLAlchemyError as e:
        # Rate-limit: full traceback only on the first failure per process;
        # subsequent failures get a one-line warning so /metrics scrapes
        # (every 15-30s) on a pre-migration deployment do not flood logs.
        if not _app_config_query_failed_once:
            logger.warning(
                'Failed to query worker_last_iteration_at from AppConfig; omitting metric',
                exc_info=True,
            )
            _app_config_query_failed_once = True
        else:
            logger.warning(
                'Failed to query worker_last_iteration_at from AppConfig: %s: %s',
                type(e).__name__, e,
            )
    if row is not None:
        try:
            ts = datetime.fromisoformat(row.value)
            yield GaugeMetricFamily(
                'esb_worker_last_iteration_timestamp_seconds',
                "Unix timestamp (seconds) of the worker's last successful poll. "
                "Omitted if the worker has never run or the AppConfig query failed.",
                value=ts.timestamp(),
            )
        except ValueError:
            logger.warning(
                'Failed to parse worker last-iteration timestamp value=%r',
                row.value, exc_info=True,
            )
    ```
  - Action: After the worker-timestamp logic in the same `collect()`, emit the two Socket Mode gauges (Task 4).
  - Action: Register `_WorkerStatusCollector()` in `render_metrics()` alongside `_PendingNotificationsCollector()`.
  - Imports to add: `import logging`, `logger = logging.getLogger(__name__)` (if not present), `from sqlalchemy.exc import SQLAlchemyError`, `from sqlalchemy import select`, `from esb.models.app_config import AppConfig`.
  - Notes: `_app_config_query_failed_once` is a deliberate per-process latch (closes F10). Tests that need to trigger the "first failure" path again can reset it via `monkeypatch.setattr('esb.services.metrics_service._app_config_query_failed_once', False)`.

- [ ] **Task 4: `esb_socket_mode_enabled` and `esb_socket_mode_connected` gauges**
  - File: `esb/services/metrics_service.py`
  - Action: Inside `_WorkerStatusCollector.collect()` (after the worker-timestamp logic), use the lazy + dotted import idiom:
    ```python
    # Lazy + dotted import inside collect(). Two reasons (NOT circular-import
    # avoidance — there is no circular-import risk):
    #   1. Defers Flask app-context dependencies that some test fixtures lazily
    #      install during early test setup.
    #   2. Preserves the monkeypatch surface: tests do
    #      monkeypatch.setattr('esb.slack.is_socket_mode_connected', ...)
    #      which only takes effect via attribute lookup at call time. A top-of-
    #      module `from esb.slack import is_socket_mode_connected` would bind
    #      the symbol locally and silently miss the patch.
    # If you "clean this up" by moving the import to module top, you will
    # break the test design. Don't.
    import esb.slack as _slack
    yield GaugeMetricFamily(
        'esb_socket_mode_enabled',
        '1 if init_slack entered the Socket Mode setup block (tokens set, not '
        'TESTING, opt-in flag true). 0 on any of the four early-return paths or '
        'if the setup block was never reached.',
        value=1.0 if _slack.is_socket_mode_enabled() else 0.0,
    )
    yield GaugeMetricFamily(
        'esb_socket_mode_connected',
        '1 if a Bolt SocketModeHandler is currently bound; 0 if never bound or '
        'released. Transitions 1->0 at process shutdown.',
        value=1.0 if _slack.is_socket_mode_connected() else 0.0,
    )
    ```
  - Notes: The inline comment about *why* the import is lazy + dotted is mandatory — closes F12 of pass 2 and F16 of pass 3.

- [ ] **Task 5: Worker-loop tests — three tests with sleep-mocking and real DB-error simulation**
  - File: `tests/test_services/test_notification_service.py`
  - Action: Add three tests using existing `app`, `db`, `monkeypatch`, `caplog`, `tmp_path` fixtures.
    1. **`test_record_iteration_timestamp_writes_appconfig_row`**:
       - Invoke `notification_service._record_iteration_timestamp()` once.
       - Query `AppConfig` for `key='worker_last_iteration_at'`; assert row exists; assert `abs((datetime.fromisoformat(row.value) - datetime.now(UTC)).total_seconds()) <= 5.0`.
    2. **`test_record_iteration_timestamp_recovers_from_real_db_error`** (closes F2/F3/F4):
       - `db.drop_all(bind_key=None, tables=[AppConfig.__table__])` — drops only the `app_config` table; `pending_notifications` is unaffected.
       - Invoke `_record_iteration_timestamp()`; assert no exception escapes; `caplog` contains `'Failed to update worker last-iteration timestamp'`.
       - **Verify the rollback was actually necessary:** without restoring the table, attempt `db.session.execute(select(PendingNotification)).all()` (the `pending_notifications` table still exists and is unrelated). It must succeed — proving the session is usable. If `db.session.rollback()` were absent from the helper, this query would raise `PendingRollbackError`.
       - `db.create_all(tables=[AppConfig.__table__])` — restore the table so subsequent tests aren't affected (also use a fixture cleanup for safety).
    3. **`test_worker_loop_survives_buggy_helper_continues_iterating`** (closes F1, F5, F14):
       - `monkeypatch.setattr('esb.services.notification_service.time', MagicMock())` — mocks `time.sleep` so backoff doesn't actually sleep.
       - Patch `_record_iteration_timestamp` to raise `RuntimeError('boom')` on every call (simulating a permanent programming bug).
       - Patch `get_pending_notifications` with a side-effect counter that returns `[]` for the first two calls and raises `KeyboardInterrupt` on the third call (forcing the loop to terminate after two complete iterations).
       - Use `tmp_path / 'hb'` for the heartbeat path; `poll_interval=0.01`.
       - `with pytest.raises(KeyboardInterrupt): notification_service.run_worker_loop(heartbeat_path=str(tmp_path / 'hb'), poll_interval=0.01)`.
       - Assert `get_pending_notifications.call_count == 3` (proves the loop ran two complete iterations past the first helper failure).
       - Assert `caplog` records contain `'BUG: _record_iteration_timestamp raised unexpectedly'` (proves the inner-try caught the buggy helper).
       - Notes: This design avoids the contradictory "second-call flag on the helper" approach. Loop-continuation is verified by counting `get_pending_notifications` calls — which must run before the helper. The `time` mock prevents real sleeps.

- [ ] **Task 6: Service-layer metrics tests — eight tests including DB-error degradation and the latch-reset case**
  - File: `tests/test_services/test_metrics_service.py`
  - Action: Add an `autouse=True` function-scoped fixture that, before each test:
    - Resets `esb.slack._bolt_app = None; esb.slack._socket_handler = None`. (`_socket_mode_intended` is reset by `init_slack(app)` itself; not in this fixture's reset list.)
    - Resets `esb.services.metrics_service._app_config_query_failed_once = False` (so each test sees a fresh "first failure" latch).
  - Action: Add a small `_make_app_config(key, value)` helper analogous to `_make_pending` (lines 17-27).
  - Action: Add eight tests using the existing `_extract_metric` regex helper and `app` fixture:
    1. `test_worker_last_iteration_timestamp_emitted_when_present`: insert AppConfig row with known ISO-8601 timestamp; call `render_metrics()`; assert metric value equals expected epoch seconds (within 1 µs).
    2. `test_worker_last_iteration_timestamp_omitted_when_absent`: no row; call `render_metrics()`; assert substring `'esb_worker_last_iteration_timestamp_seconds'` is NOT in body.
    3. `test_worker_last_iteration_timestamp_omitted_on_real_db_error` (closes F2/F3): `db.drop_all(tables=[AppConfig.__table__])`; call `render_metrics()`; assert it returns successfully (no raise); assert `'esb_worker_last_iteration_timestamp_seconds'` is NOT in body; assert `'esb_socket_mode_enabled'` IS in body; assert `'esb_socket_mode_connected'` IS in body; assert `caplog` contains `'Failed to query worker_last_iteration_at from AppConfig'`. Restore via `db.create_all(tables=[AppConfig.__table__])`.
    4. `test_appconfig_query_error_logs_full_traceback_only_on_first_failure` (closes F10): drop the table; call `render_metrics()` once; assert one record in `caplog` has `exc_info` set. Then call `render_metrics()` again (table still dropped); assert the second-call log record's message contains the exception class+text but does NOT have `exc_info` set.
    5. `test_socket_mode_enabled_emits_one_when_intent_true`: `monkeypatch.setattr('esb.slack.is_socket_mode_enabled', lambda: True)`; assert body contains `esb_socket_mode_enabled 1.0`.
    6. `test_socket_mode_enabled_emits_zero_when_intent_false`: same as 5 with `False`; assert `esb_socket_mode_enabled 0.0`.
    7. `test_socket_mode_connected_emits_one_when_handler_bound`: `monkeypatch.setattr('esb.slack.is_socket_mode_connected', lambda: True)`; assert body contains `esb_socket_mode_connected 1.0`.
    8. `test_socket_mode_connected_emits_zero_when_handler_unbound`: same with `False`; assert `esb_socket_mode_connected 0.0`.

- [ ] **Task 7: Route-level metrics tests — six tests with all reachable Socket Mode combinations**
  - File: `tests/test_views/test_metrics_view.py`
  - Action: Add the same autouse fixture as Task 6 (reset `_bolt_app`, `_socket_handler`, `_app_config_query_failed_once`).
  - Action: Add six tests using the existing `client` fixture:
    1. `test_metrics_endpoint_includes_worker_timestamp_when_present`: insert AppConfig row; GET `/metrics`; assert `200`; body contains `'esb_worker_last_iteration_timestamp_seconds'`.
    2. `test_metrics_endpoint_omits_worker_timestamp_when_absent`: no row; GET `/metrics`; assert `200`; body does NOT contain `'esb_worker_last_iteration_timestamp_seconds'`.
    3. `test_metrics_endpoint_returns_200_when_appconfig_table_missing`: `db.drop_all(tables=[AppConfig.__table__])`; GET `/metrics`; assert `200` (NOT 500); body does NOT contain `'esb_worker_last_iteration_timestamp_seconds'`; body DOES contain both Socket Mode gauges; body DOES contain `'esb_pending_notifications_count'` (the existing collector is unaffected because it queries `pending_notifications`, not `app_config`). Restore via `db.create_all(tables=[AppConfig.__table__])`.
    4. `test_metrics_endpoint_socket_mode_state_enabled_connected` (closes F13): patch both accessors → `True`; GET `/metrics`; assert body contains `'esb_socket_mode_enabled 1.0'` AND `'esb_socket_mode_connected 1.0'`.
    5. `test_metrics_endpoint_socket_mode_state_enabled_not_connected`: patch `is_socket_mode_enabled` → `True`, `is_socket_mode_connected` → `False`; GET `/metrics`; assert body contains `'esb_socket_mode_enabled 1.0'` AND `'esb_socket_mode_connected 0.0'`. (This is the actionable failure state.)
    6. `test_metrics_endpoint_socket_mode_state_neither`: patch both → `False`; GET `/metrics`; assert body contains `'esb_socket_mode_enabled 0.0'` AND `'esb_socket_mode_connected 0.0'`.
  - Notes: The fourth reachable combination `(False, True)` is unreachable in the new unified-setup design (Task 2 sets `_socket_mode_intended = True` before binding `_socket_handler`); not tested. Documented in AC8.

- [ ] **Task 8: Reorganize the existing "Prometheus Metrics" subsection out of "Ongoing Maintenance" with anchor preservation**
  - File: `docs/administrators.md`
  - Action: Delete the `### Prometheus Metrics` subsection currently at lines 346-377. In its place insert exactly:
    ```markdown
    <a id="prometheus-metrics"></a>

    For metrics, log-based alerting, and recommended dashboards, see [Monitoring and Alerting](#monitoring-and-alerting) below.
    ```
  - Notes: Verified safe under `mkdocs.yml`'s `attr_list` + `md_in_html` extensions. Task 12 enforces this config invariant via test.

- [ ] **Task 9: Add new top-level "Monitoring and Alerting" section**
  - File: `docs/administrators.md`
  - Action: Insert a new top-level `## Monitoring and Alerting` section immediately after `## New Relic Monitoring (Optional)` and before `## Ongoing Maintenance`. Subsections in order:
    1. **`### Overview`** — One paragraph: ESB exposes Prometheus metrics on `/metrics` (unauthenticated; trusted-network deployment); both `app` and `worker` containers run with `PYTHONUNBUFFERED=1` so logs reach Loki/Promtail without buffering latency; metrics are designed for direct Grafana panel use. Complementary to the optional New Relic integration. This guide gives recommended *signals*, not a turnkey configuration.
    2. **`### Prometheus Metrics`** — Reuse the existing scrape config example verbatim. Five-row metrics table:

       | Metric | Type | Description | Emission |
       |--------|------|-------------|----------|
       | `esb_pending_notifications_count` | gauge | Number of rows in `pending_notifications` with `status='pending'` | Always |
       | `esb_oldest_pending_notification_timestamp_seconds` | gauge | Unix epoch seconds of the oldest pending row's `created_at` | Omitted when queue empty (alert with `absent()`) |
       | `esb_worker_last_iteration_timestamp_seconds` | gauge | Unix epoch seconds of the worker's last successful poll cycle (read from `AppConfig.value`) | Omitted when worker has never run, or when the `AppConfig` query fails (alert with `absent()`, **`for: 5m` minimum**) |
       | `esb_socket_mode_enabled` | gauge | `1` if `init_slack` entered the Socket Mode setup block (tokens set, not `TESTING`, opt-in flag true); `0` otherwise | Always |
       | `esb_socket_mode_connected` | gauge | `1` if a Bolt SocketModeHandler is currently bound; `0` otherwise. Transitions 1→0 at process shutdown. | Always |

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
           summary: "ESB worker has not produced a heartbeat row since deploy (or DB reset / transient query failure)"
       ```
       ```yaml
       - alert: ESBSocketModeFailedAtBoot
         expr: (esb_socket_mode_enabled == 1 and esb_socket_mode_connected == 0) unless on(instance) up == 0
         for: 5m
         annotations:
           summary: "ESB intended to run Slack Socket Mode but the handler failed at boot"
       ```
       Add a note explicitly: **`ESBWorkerStalled` and `ESBWorkerNeverRan` are complementary and should both be loaded.** `ESBWorkerStalled` detects "worker was alive recently but stopped iterating" — fires on a normal stall but doesn't fire when the metric is missing entirely. `ESBWorkerNeverRan` detects the metric-missing case — fires on cold-deploy time-to-first-poll AND on transient `AppConfig` query failures. Together they cover the full failure space.

       Add a `!!! note` admonition:
       > **Clock skew.** `time() - <gauge>` rules mix Prometheus's clock with the worker container's clock. Run NTP on every node and pick the threshold ≥ 4× `poll_interval` (so 120s for the default 30s).

       Add a second `!!! note`:
       > **Single-worker assumption.** These metrics assume the current single-gunicorn-worker deployment (`--workers 1`). Scaling app-side gunicorn workers makes the Socket Mode metrics non-deterministic across scrapes.

       Add a third `!!! note`:
       > **Information disclosure.** The Socket Mode gauges let any unauthenticated reader of `/metrics` distinguish "Slack not configured" from "Slack configured but failed at boot" from "Slack working." Acceptable on a trusted network; something to be aware of if `/metrics` is ever exposed more broadly.

       Add a fourth `!!! note`:
       > **`ESBSocketModeFailedAtBoot` shutdown safety.** The rule includes `unless on(instance) up == 0` to suppress the alert during a full app outage (where `up == 0` is already the dominant signal) and uses `for: 5m` to absorb gunicorn worker reloads (`--max-requests` recycling) where `_shutdown_socket()` briefly leaves state at `(1, 0)`.

       Add a fifth `!!! note`:
       > **`/metrics` endpoint resilience.** The endpoint returns HTTP 200 even when the `app_config` table is missing (e.g., on a fresh deployment that hasn't yet run `flask db upgrade`). The worker-timestamp metric is simply omitted; alert via `ESBWorkerNeverRan`. The first per-process query failure logs a full stack trace; subsequent failures log a one-line warning to avoid log flooding.
    3. **`### Container and Process Liveness`** — 2-3 sentences. `up{job="esb"} == 0` for ≥ 1 m indicates the app is not responding to scrapes. cAdvisor / `container_last_seen` catches container restart loops.
    4. **`### Log-Based Alerting (Loki)`** — Intro: ESB writes logs to stdout/stderr; both containers run with `PYTHONUNBUFFERED=1`. Then the verified substring table:

       | What to detect | Source | Log substring |
       |----------------|--------|---------------|
       | Worker poll-cycle failure (any exception in the loop body) | `notification_service.py:402-405` | `Error in worker polling loop` |
       | Slack delivery exception (per notification, app-log line) | `notification_service.py:390-393` | `Notification ` (with the leading capital N + space — uniquely matches the format-string log line, NOT the JSON mutation log which starts with `{` and uses lowercase `notification`) |
       | Worker heartbeat write failure | `notification_service.py:35-37` | `Failed to update worker heartbeat at` |
       | Worker last-iteration write failure | (introduced by this PR) | `Failed to update worker last-iteration timestamp` |
       | Buggy iteration-timestamp helper | (introduced by this PR) | `BUG: _record_iteration_timestamp raised unexpectedly` |
       | Slack Socket Mode setup failure (import / instantiation / connect) | `esb/slack/__init__.py` (after Task 2) | `Failed to set up Slack Socket Mode` |
       | `/metrics` AppConfig query failure (first per process) | `esb/services/metrics_service.py` (after Task 3) | `Failed to query worker_last_iteration_at from AppConfig` |
       | Generic ERROR-level traffic | any | `ERROR` (level) and/or `Traceback` |

       **Permanent-fail signal lives in the structured JSON mutation log.** When a notification is permanently failed after `MAX_RETRIES`, `esb/utils/logging.py:36-42` writes a single-line JSON record to logger `esb.mutations` containing `event: notification.permanently_failed`. Two equivalent alerting options:
       - **Substring match** on `notification.permanently_failed` — simplest; works regardless of JSON-whitespace variation.
       - **Promtail JSON-stage parsing** — extract `event` as a structured Loki label. Use a Promtail `match` stage to apply the JSON parser only to lines starting with `{`, since the regular Python logger and the mutation logger share the same stdout stream.

       End with: "Operators write their own LogQL queries and alert rules; this guide intentionally lists signals, not queries."
    5. **`### What to Alert On`** — Bulleted punch list (≤ 7 items):
       - **App down** — `up{job="esb"} == 0` for ≥ 1 m
       - **Worker stalled** — the `ESBWorkerStalled` rule
       - **Worker never ran since deploy / DB reset** — the `ESBWorkerNeverRan` rule
       - **Notification queue stuck** — the existing `ESBNotificationQueueStuck` rule
       - **Slack Socket Mode failed at boot** — the `ESBSocketModeFailedAtBoot` rule (covers import, instantiation, and connect failures; suppressed during full app outage)
       - **Elevated rate of Slack delivery failures** — Loki on `Notification ` substring exceeding a per-minute threshold
       - **Container flapping** — cAdvisor restart-count rate
    6. **`### Grafana Dashboards`** — 2-3 sentences. Metrics are designed for direct panel use. ESB does not ship dashboard JSON.
    7. **`### Relationship to New Relic`** — 2-3 sentences. Different observation layers; complementary; can run together.
  - Notes: Match existing heading levels, table formatting, fenced code blocks, and `!!!` admonition syntax.

- [ ] **Task 10: Add `PYTHONUNBUFFERED=1` to the `app` service in `docker-compose.yml`**
  - File: `docker-compose.yml`
  - Action: In the `app` service's `environment:` block, add `- PYTHONUNBUFFERED=1`.

- [ ] **Task 11: Declare `PyYAML` explicitly in `requirements-dev.txt`**
  - File: `requirements-dev.txt`
  - Action: Add a line `PyYAML>=6.0` (or match the version pin style used by the rest of the file).
  - Notes: PyYAML is currently only available transitively via `mkdocs`; making it an explicit dev dep prevents `tests/test_compose.py` from breaking when transitive resolution changes (closes F8).

- [ ] **Task 12: New `tests/test_compose.py` with two CWD-independent YAML-load assertions**
  - File: `tests/test_compose.py` (new)
  - Action:
    ```python
    """Config-invariant tests: assertions about non-Python project files
    (docker-compose.yml, mkdocs.yml) that the monitoring/alerting design
    depends on. Paths are resolved relative to this file so the tests pass
    regardless of pytest's CWD."""
    from pathlib import Path

    import yaml

    REPO_ROOT = Path(__file__).resolve().parent.parent


    def test_compose_pythonunbuffered_set_on_app_and_worker():
        compose = yaml.safe_load((REPO_ROOT / 'docker-compose.yml').read_text())
        for service_name in ('app', 'worker'):
            env = compose['services'][service_name].get('environment', [])
            if isinstance(env, list):
                assert 'PYTHONUNBUFFERED=1' in env, (
                    f"{service_name} missing PYTHONUNBUFFERED=1; log lines will buffer"
                )
            else:
                assert env.get('PYTHONUNBUFFERED') in ('1', 1), (
                    f"{service_name} missing PYTHONUNBUFFERED=1; log lines will buffer"
                )


    def test_mkdocs_enables_html_passthrough_for_anchor_preservation():
        cfg = yaml.safe_load((REPO_ROOT / 'mkdocs.yml').read_text())
        extensions = cfg.get('markdown_extensions', [])
        ext_names = {e if isinstance(e, str) else next(iter(e)) for e in extensions}
        assert 'attr_list' in ext_names, "anchor preservation depends on attr_list"
        assert 'md_in_html' in ext_names, "anchor preservation depends on md_in_html"
    ```
  - Notes: `Path(__file__).resolve().parent.parent` resolves to repo root regardless of pytest's CWD (closes F6). PyYAML is now an explicit dev dep (Task 11).

### Acceptance Criteria

- [ ] **AC 1 — Worker liveness gauge, happy path:** Given an `AppConfig` row with key `worker_last_iteration_at` and a valid ISO-8601 `value`, when `/metrics` is scraped, the body contains a value line `esb_worker_last_iteration_timestamp_seconds <float>` matching the parsed timestamp's epoch seconds.

- [ ] **AC 2 — Worker liveness gauge, never-run:** Given no `AppConfig` row with that key, when `/metrics` is scraped, `esb_worker_last_iteration_timestamp_seconds` does not appear in the body.

- [ ] **AC 3 — Worker writes timestamp once per poll cycle:** Given `_record_iteration_timestamp()` is invoked, when it returns, exactly one `AppConfig` row with key `worker_last_iteration_at` exists; `value` parses as ISO-8601 within ±5 s of `datetime.now(UTC)`.

- [ ] **AC 4a — Helper internal rollback path verified by real DB error:** Given `db.drop_all(tables=[AppConfig.__table__])` is executed, when `_record_iteration_timestamp()` is invoked, then no exception escapes; `caplog` contains `'Failed to update worker last-iteration timestamp'`; AND a subsequent `db.session.execute(select(PendingNotification)).all()` (against the still-existing `pending_notifications` table) succeeds without raising `PendingRollbackError`. **Removing `db.session.rollback()` from the helper would cause the follow-up query to raise `PendingRollbackError`** — so this AC genuinely verifies the rollback is necessary.

- [ ] **AC 4b — Worker loop survives a buggy helper raising arbitrary `Exception`:** Given `_record_iteration_timestamp` is patched to raise `RuntimeError('boom')` on every call, AND `get_pending_notifications` is patched to return `[]` for the first two calls and raise `KeyboardInterrupt` on the third, AND `notification_service.time` is mocked, when `run_worker_loop()` is invoked, then `get_pending_notifications` is called exactly 3 times (proving the loop ran two iterations past the first helper failure), `caplog` contains `'BUG: _record_iteration_timestamp raised unexpectedly'`, and the loop exits via `KeyboardInterrupt` (not via the `RuntimeError`).

- [ ] **AC 5 — `/metrics` graceful degradation on real AppConfig table absence:** Given `db.drop_all(tables=[AppConfig.__table__])`, when `/metrics` is scraped, then HTTP `200` (not `500`); body does NOT contain `esb_worker_last_iteration_timestamp_seconds`; body DOES contain both Socket Mode gauges AND `esb_pending_notifications_count` (the existing collector is unaffected since `pending_notifications` is a different table). A warning is logged with substring `Failed to query worker_last_iteration_at from AppConfig`.

- [ ] **AC 5b — DB-error log rate-limiting:** Given the `app_config` table is missing, when `/metrics` is scraped twice, then the first scrape logs a warning with `exc_info` (full traceback); the second scrape logs a warning whose message contains the exception class+text but does NOT include `exc_info`/traceback.

- [ ] **AC 6 — `esb_socket_mode_enabled` reflects whether `init_slack` entered the setup block:** Given `init_slack(app)` enters the Socket Mode setup block (no early return), then `esb_socket_mode_enabled 1.0` appears in `/metrics`. Given any of the four early-return paths fired, then `esb_socket_mode_enabled 0.0` appears.

- [ ] **AC 7 — `esb_socket_mode_connected` reflects handler-binding state:** Given `_socket_handler is not None`, then `esb_socket_mode_connected 1.0` appears in `/metrics`. Given `_socket_handler is None` (whether never bound, released by `_shutdown_socket()`, or any setup-block exception), then `esb_socket_mode_connected 0.0` appears.

- [ ] **AC 8 — Three reachable Socket Mode states are explicitly tested at the route level:** The reachable matrix is `(enabled=True, connected=True)`, `(enabled=True, connected=False)`, `(enabled=False, connected=False)`. The fourth combination `(enabled=False, connected=True)` is unreachable in the new unified-setup design (Task 2 sets `_socket_mode_intended = True` before binding `_socket_handler`, so any state with `connected=True` must have `enabled=True`). Tasks 7.4-7.6 explicitly cover the three reachable states.

- [ ] **AC 9 — Existing metrics unchanged:** `esb_pending_notifications_count` and `esb_oldest_pending_notification_timestamp_seconds` retain their names, types, labels, and emission semantics from #32.

- [ ] **AC 10 — `/metrics` endpoint stability:** GET `/metrics` returns HTTP `200`, `Content-Type` includes `text/plain` and `version=`, body parses as valid Prometheus exposition format, no auth required.

- [ ] **AC 11 — `PYTHONUNBUFFERED=1` enforced by automated test:** `tests/test_compose.py::test_compose_pythonunbuffered_set_on_app_and_worker` passes by loading `docker-compose.yml` with PyYAML (explicit dev dep) and asserting the var on both services. Path resolution is CWD-independent.

- [ ] **AC 12 — `mkdocs.yml` HTML pass-through enforced by test:** `tests/test_compose.py::test_mkdocs_enables_html_passthrough_for_anchor_preservation` passes by asserting `attr_list` and `md_in_html` are listed under `markdown_extensions`. Path resolution is CWD-independent.

- [ ] **AC 13 — Documentation, new section exists** with seven subsections in order: Overview; Prometheus Metrics; Container and Process Liveness; Log-Based Alerting (Loki); What to Alert On; Grafana Dashboards; Relationship to New Relic.

- [ ] **AC 14 — Documentation, old subsection migrated with anchor preservation:** Under `## Ongoing Maintenance`, the previous `### Prometheus Metrics` subsection is gone; a forward-pointer line including a literal `<a id="prometheus-metrics"></a>` HTML anchor and a Markdown link to the new section replaces it.

- [ ] **AC 15 — Documentation, metric and alert tables updated:** Five-row metrics table; example alert rules include the existing `ESBNotificationQueueStuck` (verbatim), `ESBWorkerStalled` (`for: 1m`), `ESBWorkerNeverRan` (`for: 5m`, `absent()`), `ESBSocketModeFailedAtBoot` (`for: 5m`, with `unless on(instance) up == 0`).

- [ ] **AC 16 — Documentation, complementary-rules note present:** The "Prometheus Metrics" subsection includes an explicit note that `ESBWorkerStalled` and `ESBWorkerNeverRan` are complementary and should both be loaded — covering "worker was alive but stopped" and "metric is missing entirely" respectively.

- [ ] **AC 17 — Documentation, Loki substrings are verified and stream-disambiguated:** The "What to detect / Log substring" table contains substrings that appear verbatim at the cited source line ranges. The per-notification delivery-failure substring is `Notification ` (capital N + trailing space) so it matches the format-string log line and NOT the JSON mutation log (which starts with `{` and uses lowercase `notification`). Permanent-fail signal documented separately as a JSON mutation-log event with two alerting options.

- [ ] **AC 18 — Documentation, five caveats present:** The "Prometheus Metrics" subsection includes five `!!! note` admonitions: clock-skew/NTP, single-gunicorn-worker, information disclosure, `ESBSocketModeFailedAtBoot` shutdown safety (`for: 5m unless up == 0`), and `/metrics` endpoint resilience (graceful degradation + log rate-limiting).

- [ ] **AC 19 — Lint and tests pass:** `make lint` exits `0`. `make test` exits `0`. New tests present and passing: 3 in `test_notification_service.py`, 8 in `test_metrics_service.py`, 6 in `test_metrics_view.py`, 2 in `test_compose.py` = **19 new tests**.

## Additional Context

### Dependencies

- `prometheus_client` — already a runtime dependency.
- `AppConfig` model — already exists.
- `sqlalchemy.exc.SQLAlchemyError` — standard SQLAlchemy.
- **`PyYAML` — added explicitly to `requirements-dev.txt` in this PR (Task 11).** Was previously transitive via `mkdocs`; this PR removes the transitive accident.
- No new Docker services, no new external integrations.

### Testing Strategy

- **Unit / service tests**: 11 new tests across `tests/test_services/test_metrics_service.py` (8) and `tests/test_services/test_notification_service.py` (3). Use SQLite in-memory DB and existing fixtures.
- **Route / integration tests**: 6 new tests in `tests/test_views/test_metrics_view.py`.
- **Config-invariant tests**: 2 new tests in `tests/test_compose.py` (new file). YAML-load + assertion. CWD-independent path resolution.
- **DB-error simulation: real, surgical, and verifying.** Tests drop only the `app_config` table via `db.drop_all(tables=[AppConfig.__table__])`. This (a) produces a real `OperationalError` (SQLite) or `ProgrammingError` (MariaDB) that exercises actual session-corruption semantics, (b) leaves `pending_notifications` intact so the existing collector is unaffected, and (c) makes the rollback verification non-vacuous — without `db.session.rollback()`, the follow-up query raises `PendingRollbackError`.
- **Worker-loop test patches `notification_service.time`** so backoff sleeps don't actually run; closes pass-3 F14.
- **Worker-loop continuation verified by call-counting `get_pending_notifications`** rather than a contradictory helper-second-call flag; closes pass-3 F1.
- **Module-global hygiene**: tests reset `esb.slack._bolt_app`, `_socket_handler`, and `metrics_service._app_config_query_failed_once` before each test (autouse fixture).
- **Manual verification**: After implementation:
  - `docker compose up -d --build`
  - `curl http://localhost:5000/metrics` — confirm gauge lines for all five metrics. Wait ~30 s; re-curl; confirm `esb_worker_last_iteration_timestamp_seconds` is recent.
  - `docker compose stop worker`; wait 2 m; verify `ESBWorkerStalled` would fire.
  - Drop `app_config` table manually; curl `/metrics` — confirm 200, worker-timestamp omitted, single-line warning logged on the second scrape.
  - Restart app; observe `esb_socket_mode_*` transitions.

### Notes

- **Known limitation: `(False, True)` Socket Mode state is unreachable** in the new unified-setup design — `_socket_mode_intended = True` is set before `_socket_handler` is bound, so any `connected=True` observation implies `enabled=True`. (Closes pass-3 F7.)
- **Known limitation: import-time failures in the Socket Mode setup block now produce `(True, False)`** — actionable. The `try/except Exception` covers ImportError, instantiation errors, and connect errors with the same `Failed to set up Slack Socket Mode` warning. (Closes pass-3 F12.)
- **Known limitation: `esb_socket_mode_connected` transitions 1→0 at process shutdown** (`_shutdown_socket()`); `ESBSocketModeFailedAtBoot` uses `for: 5m` and `unless up == 0` to absorb gunicorn worker reloads and full app outages. (Closes pass-3 F9.)
- **Known limitation: single-gunicorn-worker assumption.** Multi-worker deployments make the Socket Mode metrics non-deterministic; out of scope.
- **Known limitation: clock-skew sensitivity.** NTP and a threshold ≥ 4× `poll_interval` are recommended in the doc.
- **Known limitation: information disclosure on `/metrics`.** The Socket Mode gauges allow distinguishing Slack-not-configured from Slack-failed-at-boot from Slack-working. Acceptable on a trusted network; called out for operators considering wider exposure.
- **Known limitation: rapid back-to-back helper calls in the same uncommitted unit of work** would each take the "row not exists" branch. Single-writer + sequential poll loop rules this out in production.
- **Known limitation: a programming bug in `_record_iteration_timestamp`** (i.e., a non-`SQLAlchemyError` exception escaping the helper) leaves the worker-timestamp metric stale even though notification processing continues. The defensive call-site wrapper in Task 1 logs `BUG: ...` at ERROR level — operators should monitor for this substring in Loki and treat it as a code defect, not an ESBWorkerStalled false alarm. (Closes pass-3 F5.)
- **`PYTHONUNBUFFERED=1` on app + automated YAML-load check is load-bearing.** Closes pass-2 F7.
- **Lazy + dotted import in `metrics_service`** is for monkeypatch-surface preservation, not circular-import avoidance — documented in an inline code comment so future "cleanup" doesn't break the test design.
- **MkDocs config (HTML pass-through) enforced by test.** Closes pass-2 F11.
- **Loki substring `Notification ` (capital N + trailing space) uniquely matches the format-string log line** and not the JSON mutation log. Closes pass-3 F11.
- **DB-error log rate-limiting** prevents log flooding on pre-migration deployments. Closes pass-3 F10.
- **Performance: ~one extra DB query per scrape.** Negligible.
- **Future considerations (out of scope):**
  - Counter-based slack-delivery metrics — dropped.
  - Live Socket Mode WebSocket-state gauge — requires upstream Slack Bolt change.
  - Multi-process Socket Mode coordination.
  - `/metrics` authentication for less-trusted deployments.
  - In-process caching of `worker_last_iteration_at` for aggressive scrape intervals.
  - Wrapping `_PendingNotificationsCollector` in graceful-degradation try/except — not motivated by this spec.
  - Refactoring `run_worker_loop` to extract `_one_poll_iteration()` for cleaner unit-testing — would obviate the `KeyboardInterrupt`-stubbing pattern.
