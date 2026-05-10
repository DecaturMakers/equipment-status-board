---
title: 'Monitoring and Alerting Guide + System-Health Metrics'
slug: 'monitoring-and-alerting'
created: '2026-05-10'
status: 'ready-for-dev'
stepsCompleted: [1, 2, 3, 4]
revision: 3
revision_notes: 'Second adversarial-review pass applied — 18 findings addressed (revision 2 introduced regressions: fictional IntegrityError race, function-local `_shutdown`, mis-stated semantics for `connected`, dead naive-ISO branch, unverified Promtail/MkDocs assumptions, manual-only PYTHONUNBUFFERED check, semantics drift in SLACK_SOCKET_MODE_CONNECT access).'
tech_stack:
  - 'Python 3.14'
  - 'Flask'
  - 'Flask-SQLAlchemy + SQLAlchemy 2.x style'
  - 'MariaDB (production) / SQLite (tests)'
  - 'prometheus_client'
  - 'slack-bolt + slack_sdk (Socket Mode)'
  - 'pytest'
  - 'MkDocs Material — docs site (markdown_extensions: attr_list, md_in_html, admonition, pymdownx.details, pymdownx.superfences, tables, toc with permalink)'
files_to_modify:
  - 'docs/administrators.md'
  - 'docker-compose.yml'
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
  - "Worker-loop tests break the loop by stubbing get_pending_notifications/sleep paths to raise KeyboardInterrupt or SystemExit (which propagates past the inner `except Exception:` guard) — _shutdown is function-local and not externally settable"
test_patterns:
  - "Service-layer tests in tests/test_services/test_metrics_service.py — use 'app' fixture; assert against rendered exposition text via regex (_extract_metric helper)"
  - "Route-level tests in tests/test_views/test_metrics_view.py — use 'client' fixture; GET /metrics, assert 200 and substring match on metric name lines"
  - 'Worker-loop tests in tests/test_services/test_notification_service.py — use SQLite in-memory DB; for full-iteration tests, stub get_pending_notifications to raise KeyboardInterrupt after the desired number of iterations'
  - 'Pin module attribute monkeypatch via the import idiom: `import esb.slack as _slack` in metrics_service, then `monkeypatch.setattr("esb.slack.is_socket_mode_connected", ...)` resolves correctly at call time'
  - 'YAML-load assertions on docker-compose.yml live in a dedicated tests/test_compose.py — small enough not to need a fixture'
issue: 12
related_issues: [32]
---

# Tech-Spec: Monitoring and Alerting Guide + System-Health Metrics

**Created:** 2026-05-10
**Issue:** [#12 — Monitoring and alerting](https://github.com/jantman/equipment-status-board/issues/12)
**Related:** #32 (initial Prometheus endpoint and worker-resilience hardening)
**Revision:** 3 (second adversarial-review pass applied)

## Overview

### Problem Statement

The Administrator Guide (`docs/administrators.md`) lacks a dedicated "Monitoring and Alerting" section. Issue #32 added two notification-queue gauges to a `/metrics` endpoint, but operators deploying ESB with Prometheus + Loki + Grafana have no documented guidance on what signals indicate ESB itself is unhealthy. The existing `/metrics` endpoint exposes only queue gauges — nothing about worker liveness as a scrapable metric (the heartbeat is a file inside the worker container, unreadable from the app process), nothing distinguishing "Socket Mode intentionally off" from "Socket Mode tried and failed at boot," and nothing about per-instance app availability beyond the existing Docker healthcheck and autoheal sidecar.

In addition, application-side stdout is currently subject to Python's default block buffering (only the worker container has `PYTHONUNBUFFERED=1`), so app log lines reach Loki/Promtail with multi-second lag — invalidating any low-latency log-based alerting recommended by this section unless that asymmetry is fixed.

### Solution

Three-part change:

1. **Documentation:** Add a new top-level `## Monitoring and Alerting` section to `docs/administrators.md` (peer of the existing "New Relic Monitoring (Optional)" section). Promote the existing "Prometheus Metrics" subsection (currently under "Ongoing Maintenance") into this new section, preserving the original `#prometheus-metrics` HTML anchor at the forward-pointer location for backward link compatibility (the project's `mkdocs.yml` enables `attr_list` and `md_in_html`, so raw inline HTML passes through). Cover Prometheus, Loki (substring guidance with verified substrings — no full LogQL), Grafana (high-level dashboard guidance — no JSON), container-level liveness (`up{}` and cAdvisor — brief), a "What to alert on" checklist (system-health only), an explicit clock-skew / NTP caveat for the `time() - <gauge>` style of alert, and an explicit caveat that the Socket Mode metrics assume the current single-gunicorn-worker deployment. Note that Prom/Loki/Grafana and New Relic are complementary.

2. **Code:** Expand `/metrics` with **three** new system-health-only gauges:
   - `esb_worker_last_iteration_timestamp_seconds` (gauge, DB-backed via `AppConfig` key `worker_last_iteration_at`) — Unix epoch seconds of the worker's most recent successful poll cycle. The metric reads the row's `value` field (parsed from ISO-8601). The row's `updated_at` is informational only. Omitted when the row does not exist; operators alert with `absent()` paired with a `for: 5m` minimum to ride out cold-deploy time-to-first-poll. Also omitted (with a warning logged) if the underlying DB query raises `SQLAlchemyError` — so a missing `app_config` table on a fresh, pre-migration deployment does **not** cause `/metrics` to return 500.
   - `esb_socket_mode_enabled` (gauge, in-process, always emitted) — `1` if `init_slack` reached the point where it was about to call `SocketModeHandler.connect()` (i.e., `SLACK_BOT_TOKEN` set, `SLACK_APP_TOKEN` set, not `TESTING`, and `SLACK_SOCKET_MODE_CONNECT == 'true'`); `0` if any of those gates short-circuited startup. The flag is set by `init_slack` itself at the conditional-tail of those gates — it cannot drift from `init_slack`'s actual code path.
   - `esb_socket_mode_connected` (gauge, in-process, always emitted) — `1` if a Bolt `SocketModeHandler` is currently bound (`_socket_handler is not None`); `0` if it was never bound or has been released. In normal operation, transitions `1 → 0` only at process shutdown via `_shutdown_socket()`. The actionable failure mode is `enabled == 1 AND connected == 0`.

   No counters, no business metrics, no auth on `/metrics`.

3. **Operational fix:** Add `PYTHONUNBUFFERED=1` to the `app` service in `docker-compose.yml` so app stdout reaches Docker's log driver (and Loki/Promtail) without Python's block buffer interposing. Add a small automated test (`tests/test_compose.py`) that loads the YAML and asserts the var is set on both `app` and `worker` so a future regression cannot silently drop the line.

### Scope

**In Scope:**

- New `## Monitoring and Alerting` section in `docs/administrators.md`
- Reorganization of the existing "Prometheus Metrics" subsection into that new section, with an HTML `<a id="prometheus-metrics"></a>` anchor preserved at the forward-pointer location (verified to render under the project's MkDocs config — `attr_list` + `md_in_html` are both enabled in `mkdocs.yml`)
- Three new gauges on `/metrics`: `esb_worker_last_iteration_timestamp_seconds`, `esb_socket_mode_enabled`, `esb_socket_mode_connected`
- Worker writes its last-iteration timestamp to `AppConfig` (key `worker_last_iteration_at`) once per successful poll cycle, with explicit `db.session.rollback()` on caught `SQLAlchemyError`
- New `_record_iteration_timestamp()` helper in `esb/services/notification_service.py`
- New public functions `is_socket_mode_enabled()` and `is_socket_mode_connected()` in `esb/slack/__init__.py`, with `_socket_mode_intended` flag set by `init_slack` itself at the connect-call site (eliminating semantics drift with the existing config-access pattern)
- Defensive `try/except SQLAlchemyError` in the new `/metrics` collector so a missing or unreachable `app_config` table degrades gracefully (omit the metric + log) rather than 500-ing the endpoint
- Loki guidance with verified error-string substrings against the actual codebase (no placeholder text); permanent-fail signal documented as a JSON-stream entry with both substring and Promtail-JSON-stage options
- An `absent()`-based example alert YAML for `esb_worker_last_iteration_timestamp_seconds` with explanation of the cold-deploy `for:` clause
- Clock-skew / NTP note (worker clock vs. Prometheus `time()`)
- Multi-gunicorn-worker caveat for the Socket Mode metrics (current Dockerfile pins `--workers 1`)
- Brief note on container-level liveness via `up{}` / cAdvisor
- Note that New Relic and Prom/Loki/Grafana are complementary
- `PYTHONUNBUFFERED=1` added to `app` service in `docker-compose.yml`, with an automated YAML-load assertion in `tests/test_compose.py`
- Service-layer + route-level + worker-loop tests for all new behavior, including (a) the helper's internal-fail rollback path, (b) the worker-loop's survival of a buggy helper that raises arbitrary `Exception`, (c) `/metrics` graceful-degradation when the AppConfig query raises, and (d) the docker-compose YAML check
- Cross-link from "Ongoing Maintenance" to the new Monitoring section

**Out of Scope:**

- Full LogQL queries, Loki label selectors, parser configurations, or Grafana dashboard JSON
- Business metrics (repair counts, equipment counts, user activity, login rates, page-view counters)
- Slack delivery success/failure counters (intentionally dropped — Loki on log strings covers it at lower complexity)
- Static page push freshness/failure metric (already represented in queue-staleness gauge)
- DB connectivity gauge (already represented by `up{}` and queue gauge errors)
- Changes to existing New Relic integration
- Installing or configuring Prometheus / Loki / Grafana themselves
- Authentication for `/metrics` (stays unauthenticated; trusted-network deployment) — note the **incremental information disclosure** in Notes
- Alertmanager / alert routing configuration
- Any new Docker / docker-compose services
- Live (mid-life) Socket Mode WebSocket connection-state detection — Slack Bolt does not expose hooks for this
- Multi-process Socket Mode coordination (single-worker is the documented deployment)
- IntegrityError-race hardening for the AppConfig write — under single-writer (one worker container, no app-side writers), the race cannot occur. The existing `try/except SQLAlchemyError` covers `IntegrityError` as a side effect, but it is not the motivating failure mode (the motivating mode is `OperationalError` from a transient DB drop / pool eviction).

## Context for Development

### Codebase Patterns

- **Metrics collector pattern:** Custom collector class implementing `collect()` and yielding `GaugeMetricFamily`; registered into a fresh `CollectorRegistry` per scrape inside `render_metrics()` (`esb/services/metrics_service.py:84-92`). Avoids cross-request state.
- **Single-query snapshot:** Aggregates that need to be consistent come from one combined `SELECT` (e.g., `_query_pending_stats()` at `esb/services/metrics_service.py:27-52`). New gauges may add a separate query for unrelated state (e.g. `AppConfig`).
- **Omit when N/A:** When a gauge has no meaningful value, do not emit it. Operators alert with `absent()`. Same pattern applies on a transient query failure: omit + log a warning, do not raise out of `collect()`.
- **Worker entry point:** `flask worker run` CLI is registered in `esb/__init__.py:149-157` and invokes `notification_service.run_worker_loop()` at `esb/services/notification_service.py:322`. Worker is a CLI process — it has **no HTTP listener**, so worker-side metrics must reach the app via the database.
- **Worker shutdown semantics:** `_shutdown` is a **function-local** variable inside `run_worker_loop()` (`esb/services/notification_service.py:334`), assigned `nonlocal` from a SIGTERM-handler closure defined inside the same function. It is **not** externally settable. Tests that need to terminate the loop must stub `get_pending_notifications` (or another in-loop call) to raise `KeyboardInterrupt` / `SystemExit` after the desired number of iterations — both are `BaseException` subclasses that propagate past the loop's inner `except Exception:` guard at line 399 and exit `run_worker_loop()` cleanly. (Pure `Exception` would be caught and the loop would back off and continue.)
- **Heartbeat write sites:** `_write_heartbeat()` at `esb/services/notification_service.py:29-37` is called at three points: startup (line 355), after each DB poll (line 369), and after each notification processed (line 397). The new `_record_iteration_timestamp()` is inserted on the line **immediately following** the post-poll heartbeat write at line 369 (i.e., the body of the loop, not the function-definition line at 322).
- **`_write_heartbeat` catches `OSError` specifically (not `Exception`).** The new `_record_iteration_timestamp` catches `SQLAlchemyError` specifically (the relevant DB-error superclass) and explicitly rolls back the session before returning. Broad `except Exception` is reserved for the outermost worker-loop guard.
- **AppConfig key-value pattern:** `esb/models/app_config.py` is a single-row-per-key table (`key` unique, `value` text, `updated_at` with both `default=` and `onupdate=`). The metric reads the **`value` field** (ISO-8601 string written by the worker via `datetime.now(UTC).isoformat()`). The DB column `updated_at` is set by SQLAlchemy's lifecycle hook and is informational only — these two timestamps may differ by sub-second on insert and are not guaranteed to agree.
- **ISO-8601 round-trip:** Worker writes `datetime.now(UTC).isoformat()` (always offset-bearing); `datetime.fromisoformat()` returns an aware datetime. **No naive-ISO handling is needed** — the previous "if naive, treat as UTC" branch was dead code and is omitted. On parse failure (`ValueError`), the collector logs a warning and omits the metric.
- **Slack Bolt initialization** (verified file lines, current main):
  - Bolt `App` constructed at `esb/slack/__init__.py:42`
  - Five distinct early-return paths leave `_socket_handler` as `None`: missing `SLACK_BOT_TOKEN` (lines 27-29), missing `SLACK_APP_TOKEN` (lines 31-33), `TESTING=True` (lines 51-53), `SLACK_SOCKET_MODE_CONNECT.lower() != 'true'` (lines 56-58), or `connect()` raised (lines 67-70). Only the last is alertable.
  - Successful `connect()` at line 65, log substring `Slack Socket Mode connected` at line 66.
  - Failure-at-connect log substring `Failed to connect Slack Socket Mode — app will run without Slack` at line 68.
  - `_shutdown_socket()` at lines 92-105 sets `_socket_handler = None` on graceful shutdown; this means `is_socket_mode_connected()` transitions from `1` to `0` at shutdown — documented in the gauge HELP text and AC7.
- **Slack Bolt has no public connection-state callbacks** — confirmed during investigation. The `esb_socket_mode_connected` gauge intentionally reflects only handler-binding state, not WebSocket-up state.
- **`_socket_mode_intended` is set inside `init_slack` at the same code path that decides to call `connect()`.** Specifically, `init_slack` initializes the flag to `False` at the top, then assigns it `True` immediately before `_socket_handler.connect()` (line 65). This eliminates any possibility of the gauge disagreeing with the actual init code path — they are the same code path. The previous revision computed the flag from a separate boolean expression evaluating `app.config.get(...)` calls, which could have drifted from `init_slack`'s subscript-style access; that drift no longer exists.
- **Slack module-globals are reset by existing tests:** `tests/test_slack/test_init.py` does `slack_mod._bolt_app = None; slack_mod._socket_handler = None` in setUp (lines 51-52), tearDown (lines 74-75), and across other test classes (lines 151-152). New metrics tests touching `_socket_handler` follow the same pattern. Resetting `_socket_mode_intended` in tests is **not** necessary, because `init_slack(app)` reassigns it on every TestingConfig setup (the autouse fixture's `app` request triggers this) — but tests that don't request `app` still need to monkeypatch the accessor function, not the underlying module-global.
- **Logging (corrected from revision 1).** `PYTHONUNBUFFERED=1` is currently set **only on the `worker` service** in `docker-compose.yml` (line 51). The `app` service is not configured for unbuffered stdout. This spec adds the variable to the `app` service so log-based alerting on app-side log lines is not silently delayed. An automated YAML-load assertion in `tests/test_compose.py` enforces this going forward.
- **Mutation logger** at `esb/utils/logging.py` emits **structured JSON** via `json.dumps(...)` (`logging.py:36-42`). Permanent-fail events are logged here as `log_mutation('notification.permanently_failed', ...)` (`notification_service.py:141-147`); the rendered line is a single-line JSON document containing `"event": "notification.permanently_failed"` (verified by reading `log_mutation`'s formatter). Loki guidance presents two equivalent options: substring match on `notification.permanently_failed` (works regardless of JSON whitespace) or Promtail JSON-stage parsing for structured-field alerting.

### Files to Reference

| File | Purpose |
| ---- | ------- |
| `docs/administrators.md` | The doc being edited; gains the new top-level "Monitoring and Alerting" section |
| `docker-compose.yml` | Add `PYTHONUNBUFFERED=1` to the `app` service environment |
| `mkdocs.yml` | Read-only reference; verifies `attr_list` + `md_in_html` are enabled (raw HTML anchor in Task 8 will pass through) |
| `esb/services/metrics_service.py` | Existing collector; add a new collector class for the three new gauges, with try/except around the AppConfig query |
| `esb/__init__.py` | `/metrics` and `/health` routes; CLI registration for `flask worker run` |
| `esb/services/notification_service.py` | Worker run loop; add `_record_iteration_timestamp()` helper and call site |
| `esb/models/app_config.py` | `AppConfig` model — backing store for `worker_last_iteration_at` |
| `esb/slack/__init__.py` | Slack Bolt + Socket Mode initialization; gains two public accessors and a private `_socket_mode_intended` flag set inside `init_slack` |
| `esb/utils/logging.py` | Mutation logger reference (`logging.py:36-42` — `json.dumps`-based JSON output) |
| `tests/conftest.py` | Test fixtures (`app`, `client`, `db`) reused by new metric tests |
| `tests/test_services/test_metrics_service.py` | Service-layer tests; existing `_extract_metric` regex pattern |
| `tests/test_views/test_metrics_view.py` | Route-level tests; existing GET `/metrics` substring-assert pattern |
| `tests/test_services/test_notification_service.py` | Worker-loop tests |
| `tests/test_slack/test_init.py` | Reference for module-global reset pattern (lines 51-52, 74-75, 151-152) |
| `tests/test_compose.py` (new) | YAML-load assertion that `PYTHONUNBUFFERED=1` is set on both `app` and `worker` services |

### Technical Decisions

- **No new authentication on `/metrics`** — stays unauthenticated, trusted-network deployment. Note (Known Limitations) acknowledges incremental information disclosure from the new gauges.
- **System-health metrics only** — no business / activity metrics.
- **`AppConfig` reused, no new table** — single key/value row sufficient. `value` (ISO-8601 string) is **authoritative** for the metric; `updated_at` is informational and not read by the metric.
- **Worker writes timestamp at the after-poll heartbeat site only** — one write per `poll_interval` (default 30s).
- **Three-gauge Socket Mode design.** Splitting `enabled` (intent — set by `init_slack` at the connect-call site) from `connected` (state — `_socket_handler is not None`) lets operators write `enabled == 1 AND connected == 0` for the only actionable failure case (Slack tried-and-failed at boot).
- **`_socket_mode_intended` is set by `init_slack` at the connect-call site, not by a parallel boolean expression elsewhere.** This eliminates the entire class of "gauge says one thing, init said another" drift identified in adversarial review pass 2 (F7).
- **`esb_socket_mode_connected` is not labeled "startup state only".** The previous wording was inaccurate: `_shutdown_socket()` deliberately sets `_socket_handler = None`, so the gauge does transition `1 → 0` at process shutdown. The HELP text and AC reflect actual behavior: "1 if a Bolt SocketModeHandler is currently bound; 0 if never bound or released. In normal operation, transitions 1→0 only at shutdown."
- **`/metrics` graceful degradation on DB error.** New `_WorkerStatusCollector` wraps the `AppConfig` query in `try/except SQLAlchemyError`. On error: log a warning, omit the worker-timestamp metric, still emit the two Socket Mode gauges. This protects the endpoint from returning 500 on a fresh deployment whose `app_config` table doesn't yet exist (or any other transient DB failure). The existing `_PendingNotificationsCollector` does **not** have this guard today and is out of scope for this PR.
- **Loki guidance — verified substrings only.** Every "log substring" entry in the doc table is taken verbatim from the actual `logger.error/warning/info` call sites cited in this spec by file:line. No placeholder entries.
- **Permanent-fail signal lives in the structured JSON mutation log.** The doc names this signal explicitly, **verifies the format is JSON** (via `logging.py:36-42`), and gives operators two alerting options: substring match on `notification.permanently_failed` (robust to JSON-whitespace variation) or Promtail JSON-stage parsing for structured fields.
- **Narrow `except` clause + explicit rollback for the worker timestamp write.** Helper catches `SQLAlchemyError`, rolls back, logs warning. Broad `except Exception` is **not** used — would absorb programming errors. The outer worker-loop's `except Exception:` (existing, line 399) is the appropriate catch-all for a buggy helper raising arbitrary exceptions; AC4b verifies the loop survives that case.
- **IntegrityError race is not the motivating failure mode.** Under single-writer deployment (one worker container, no app-side writers), the unique-key race cannot occur. The `try/except SQLAlchemyError` covers `IntegrityError` as a subclass for free; the *motivating* mode is `OperationalError` from a transient DB drop, pool eviction, or table-not-yet-migrated. AC5 tests `OperationalError`, not `IntegrityError`.
- **Pinned import idiom for monkeypatch surface.** `metrics_service` does `import esb.slack as _slack` (lazy, inside `collect()`) and calls `_slack.is_socket_mode_enabled()` / `_slack.is_socket_mode_connected()` — module-attribute lookup at call time. Tests then `monkeypatch.setattr('esb.slack.is_socket_mode_connected', lambda: True)` and the patch is observed. The lazy form is **not** to avoid circular imports (none exist) — it is to (a) defer Flask app-context dependencies and (b) preserve the monkeypatch surface. This rationale is documented inline in the code comment.
- **Single gunicorn worker is a deployment assumption** for the Socket Mode metrics (current `Dockerfile` pins `--workers 1`). Documented as a caveat in the admin guide.
- **Clock-skew caveat.** `time() - <gauge>` mixes Prometheus's clock and the worker's clock. Doc recommends NTP and a threshold ≥ 4× `poll_interval`.
- **Anchor preservation verified against MkDocs config.** `mkdocs.yml` enables `attr_list` and `md_in_html`, so `<a id="prometheus-metrics"></a>` renders as a navigable anchor. Spec includes an AC asserting this config is present (so a future plugin change that strips inline HTML can't silently break the anchor).
- **`PYTHONUNBUFFERED=1` on app + automated YAML check.** Without it, app-side log lines pass through Python's block buffer; without an automated check, a regression silently re-introduces the buffering. New `tests/test_compose.py` loads `docker-compose.yml` with PyYAML and asserts the var is set on both services.
- **Performance trade-off: ~one extra DB query per scrape** (the `AppConfig` SELECT). Negligible at default scrape intervals; documented.
- **Metric naming.** Continue the `esb_` prefix convention from #32. All three new metrics are gauges.
- **`/metrics` exposition stability.** The two existing metrics keep their names, types, and emission semantics. No backward-incompatible changes.

## Implementation Plan

### Tasks

Tasks are ordered by dependency.

- [ ] **Task 1: Worker writes `worker_last_iteration_at` to `AppConfig` once per poll cycle**
  - File: `esb/services/notification_service.py`
  - Action: Add a private helper `_record_iteration_timestamp() -> None`. Body:
    1. `now_iso = datetime.now(UTC).isoformat()`
    2. `try:`
    3. &nbsp;&nbsp;&nbsp;&nbsp;`row = db.session.execute(select(AppConfig).where(AppConfig.key == 'worker_last_iteration_at')).scalar_one_or_none()`
    4. &nbsp;&nbsp;&nbsp;&nbsp;`if row is None:`
    5. &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;`db.session.add(AppConfig(key='worker_last_iteration_at', value=now_iso))`
    6. &nbsp;&nbsp;&nbsp;&nbsp;`else:`
    7. &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;`row.value = now_iso`
    8. &nbsp;&nbsp;&nbsp;&nbsp;`db.session.commit()`
    9. `except SQLAlchemyError:`
    10. &nbsp;&nbsp;&nbsp;&nbsp;`db.session.rollback()`
    11. &nbsp;&nbsp;&nbsp;&nbsp;`logger.warning('Failed to update worker last-iteration timestamp', exc_info=True)`
    12. &nbsp;&nbsp;&nbsp;&nbsp;`return`
  - Imports to add (top of file): `from sqlalchemy.exc import SQLAlchemyError`, `from sqlalchemy import select` (if not already imported), `from esb.models.app_config import AppConfig`.
  - Action (continued): In the loop body of `run_worker_loop()` (function defined at line 322), insert a call to `_record_iteration_timestamp()` on the line immediately following the existing post-poll `_write_heartbeat(heartbeat_path)` call at line 369. Do **not** call it at the startup-heartbeat site (line 355) or per-notification site (line 397).
  - Notes: The narrow `except SQLAlchemyError` covers `OperationalError` (transient DB / pool / missing-table), `IntegrityError` (cannot occur under single-writer; covered for free), `InvalidRequestError`, etc. Programming errors (`AttributeError`, `TypeError`, etc.) propagate to the outer worker-loop guard at line 399, which logs `Error in worker polling loop` and backs off — that path is already well-tested.

- [ ] **Task 2: `_socket_mode_intended` set inside `init_slack`; expose two accessors**
  - File: `esb/slack/__init__.py`
  - Action: Add a module-level `_socket_mode_intended: bool = False` near the existing module-globals at lines 9-11.
  - Action: In `init_slack(app)`, immediately before the `_socket_handler.connect()` call at line 65, add `global _socket_mode_intended; _socket_mode_intended = True`. **All five existing early-return paths** (lines 27-29, 31-33, 51-53, 56-58, 67-70) leave `_socket_mode_intended` at its initial `False` value, which is the intended behavior — only the connect-attempt path sets it to `True`.
    Important: **also** add `global _socket_mode_intended; _socket_mode_intended = False` at the very top of `init_slack()` (immediately after the docstring) so that re-invoking `init_slack` (test fixtures) correctly resets the intent flag.
  - Action: Add two public functions at module scope:
    1. `def is_socket_mode_enabled() -> bool: return _socket_mode_intended` — Docstring: "Returns True iff the most recent `init_slack()` call reached the SocketModeHandler.connect() invocation. False on every early-return path. Reflects what `init_slack` actually decided to do, not a parallel re-evaluation of config."
    2. `def is_socket_mode_connected() -> bool: return _socket_handler is not None` — Docstring: "Returns True iff a Bolt SocketModeHandler is currently bound. Transitions True→False at process shutdown via `_shutdown_socket()`. Slack Bolt does not expose mid-life WebSocket connection-state callbacks; this gauge is binding-state, not WebSocket-up state."
  - Notes: Keep `_socket_handler` and `_socket_mode_intended` private. The two accessor functions are the only new public symbols.

- [ ] **Task 3: `_WorkerStatusCollector` with the worker-timestamp gauge and graceful DB-error handling**
  - File: `esb/services/metrics_service.py`
  - Action: Add a new collector class `_WorkerStatusCollector` next to `_PendingNotificationsCollector`. In `collect()`:
    1. Wrap the worker-timestamp lookup in `try/except SQLAlchemyError`:
       ```python
       try:
           row = db.session.execute(
               select(AppConfig).where(AppConfig.key == 'worker_last_iteration_at')
           ).scalar_one_or_none()
       except SQLAlchemyError:
           logger.warning('Failed to query worker_last_iteration_at from AppConfig; omitting metric', exc_info=True)
           row = None
       ```
    2. If `row is not None`: `try: ts = datetime.fromisoformat(row.value); yield GaugeMetricFamily('esb_worker_last_iteration_timestamp_seconds', "Unix timestamp (seconds) of the worker's last successful poll. Omitted if the worker has never run or the AppConfig query failed.", value=ts.timestamp())`. On `ValueError` (parse failure): `logger.warning('Failed to parse worker last-iteration timestamp value=%r', row.value, exc_info=True)` and continue (omit the metric).
    3. If `row is None`: do not yield the gauge.
  - Action: After the worker-timestamp logic, emit the two Socket Mode gauges (Task 4).
  - Action: Register `_WorkerStatusCollector()` in `render_metrics()` alongside `_PendingNotificationsCollector()`.
  - Imports to add: `import logging`, `logger = logging.getLogger(__name__)` (if not present), `from sqlalchemy.exc import SQLAlchemyError`, `from sqlalchemy import select`, `from esb.models.app_config import AppConfig`.
  - Notes: **No naive-ISO branch** — worker writes `datetime.now(UTC).isoformat()` which is always offset-bearing; `fromisoformat()` returns aware. `ValueError` on parse is the only handling needed. The metric reads `row.value` (authoritative); `row.updated_at` is not read.

- [ ] **Task 4: `esb_socket_mode_enabled` and `esb_socket_mode_connected` gauges (in the same collector)**
  - File: `esb/services/metrics_service.py`
  - Action: Inside `_WorkerStatusCollector.collect()` (after the worker-timestamp logic), use a **lazy, dotted** import:
    ```python
    # Lazy + dotted import preserves the monkeypatch surface used by tests:
    # tests do monkeypatch.setattr('esb.slack.is_socket_mode_enabled', ...)
    # which only takes effect at attribute-lookup time. A top-level
    # `from esb.slack import is_socket_mode_enabled` would bind the symbol
    # into this module and silently miss the patch.
    import esb.slack as _slack
    ```
    Then yield two gauges:
    1. `GaugeMetricFamily('esb_socket_mode_enabled', '1 if init_slack reached the SocketModeHandler.connect() invocation; 0 on any of the five early-return paths. Reflects what init_slack actually decided to do.', value=1.0 if _slack.is_socket_mode_enabled() else 0.0)`
    2. `GaugeMetricFamily('esb_socket_mode_connected', '1 if a Bolt SocketModeHandler is currently bound; 0 if never bound or released. Transitions 1->0 only at process shutdown in normal operation.', value=1.0 if _slack.is_socket_mode_connected() else 0.0)`
  - Action: **Always emit** both. `0` is meaningful for both.
  - Notes: The inline code comment about the import idiom is mandatory — it documents *why* the import is lazy + dotted, so future "cleanup" commits don't break the test design.

- [ ] **Task 5: Worker-loop tests — three tests covering helper, loop survival, and `OperationalError`**
  - File: `tests/test_services/test_notification_service.py`
  - Action: Add three tests using existing `app`, `db`, `monkeypatch`, `caplog`, `tmp_path` fixtures.
    1. `test_record_iteration_timestamp_writes_appconfig_row`:
       - Invoke `notification_service._record_iteration_timestamp()` once.
       - Query `AppConfig` for `key='worker_last_iteration_at'`; assert the row exists and `datetime.fromisoformat(row.value)` is within ±5 s of `datetime.now(UTC)`.
    2. `test_record_iteration_timestamp_recovers_from_operational_error`:
       - Patch `db.session.execute` (via `monkeypatch.setattr(db.session, 'execute', ...)`) to raise `OperationalError('mock', None, Exception('mock'))` on first call only — use a small stateful wrapper that delegates to the original after the first call.
       - Invoke `_record_iteration_timestamp()`; assert no exception escapes; `caplog` contains `'Failed to update worker last-iteration timestamp'`.
       - Restore the patch (`monkeypatch.undo()` is fine here since the test is single-fixture-scoped).
       - Perform an unrelated `AppConfig` write on the same session (e.g., `db.session.add(AppConfig(key='canary', value='ok')); db.session.commit()`) and assert the commit succeeds — proving the rollback left the session usable. (Closes adversarial-review F2 — `OperationalError` is the realistic failure mode under single-writer; `IntegrityError` race is not.)
    3. `test_worker_loop_survives_buggy_helper_raising_exception`:
       - Patch `notification_service._record_iteration_timestamp` to raise `RuntimeError('boom')` on the *first* call and to set a flag on the *second* call so the test knows the loop continued.
       - Patch `notification_service.get_pending_notifications` to:
         - return `[]` on the first call (lets the loop reach the helper),
         - on the second call, raise `KeyboardInterrupt` (terminates the loop cleanly — `KeyboardInterrupt` is `BaseException`, not caught by the inner `except Exception:` at line 399).
       - Use `tmp_path / 'hb'` for the heartbeat path, `poll_interval=0.01`.
       - `with pytest.raises(KeyboardInterrupt): notification_service.run_worker_loop(heartbeat_path=str(tmp_path / 'hb'), poll_interval=0.01)`.
       - Assert: the second-call flag was set (loop continued past the buggy helper); `caplog` contains `'Error in worker polling loop'` (the outer-loop guard logged the `RuntimeError`).
       - Notes: **Do not** try to set `_shutdown` directly — it is function-local. Use `KeyboardInterrupt` to break out. (Closes adversarial-review F1 — the previous spec's `_shutdown=True` mechanism was undefined.)

- [ ] **Task 6: Service-layer metrics tests — five tests including DB-error degradation**
  - File: `tests/test_services/test_metrics_service.py`
  - Action: Add an `autouse=True` function-scoped fixture (or method-level setUp) that resets `esb.slack._bolt_app = None; esb.slack._socket_handler = None` before each test. (Resetting `_socket_mode_intended` is **not** needed — `init_slack(app)` reassigns it on every TestingConfig setup via the `app` fixture.) Add a small `_make_app_config(key, value)` helper analogous to the existing `_make_pending` (lines 17-27).
  - Action: Add five tests (all using the existing `_extract_metric` regex helper and `app` fixture):
    1. `test_worker_last_iteration_timestamp_emitted_when_present`: insert AppConfig row with known ISO-8601 timestamp; call `render_metrics()`; extract metric; assert float value equals expected epoch seconds (within 1 µs).
    2. `test_worker_last_iteration_timestamp_omitted_when_absent`: no row; call `render_metrics()`; assert substring `'esb_worker_last_iteration_timestamp_seconds'` is NOT in body.
    3. `test_worker_last_iteration_timestamp_omitted_on_db_error`: monkeypatch `db.session.execute` (or the specific `select(AppConfig)...` call path) to raise `OperationalError('mock', None, Exception('mock'))`; call `render_metrics()`; assert NO exception, body returned successfully, `esb_worker_last_iteration_timestamp_seconds` is NOT in body, the two `esb_socket_mode_*` gauges ARE in body, and `caplog` contains `'Failed to query worker_last_iteration_at from AppConfig'`. (Closes adversarial-review F3 — graceful degradation on missing table.)
    4. `test_socket_mode_enabled_emits_one_when_intent_true`: `monkeypatch.setattr('esb.slack.is_socket_mode_enabled', lambda: True)`; assert body contains `esb_socket_mode_enabled 1.0`.
    5. `test_socket_mode_enabled_emits_zero_when_intent_false`: `monkeypatch.setattr('esb.slack.is_socket_mode_enabled', lambda: False)`; assert body contains `esb_socket_mode_enabled 0.0`.
  - Action: Add **two** more tests (so 7 total in this file) for `is_socket_mode_connected` — split rather than parametrized to avoid the `lambda v=v: v` late-binding pitfall:
    6. `test_socket_mode_connected_emits_one_when_handler_bound`: `monkeypatch.setattr('esb.slack.is_socket_mode_connected', lambda: True)`; assert body contains `esb_socket_mode_connected 1.0`.
    7. `test_socket_mode_connected_emits_zero_when_handler_unbound`: `monkeypatch.setattr('esb.slack.is_socket_mode_connected', lambda: False)`; assert body contains `esb_socket_mode_connected 0.0`.

- [ ] **Task 7: Route-level metrics tests — five tests with module-global reset**
  - File: `tests/test_views/test_metrics_view.py`
  - Action: Add the same autouse fixture as Task 6 to reset `_bolt_app` and `_socket_handler` before each test.
  - Action: Add five tests using the existing `client` fixture:
    1. `test_metrics_endpoint_includes_worker_timestamp_when_present`: insert AppConfig row; GET `/metrics`; assert `200`; body contains `'esb_worker_last_iteration_timestamp_seconds'`.
    2. `test_metrics_endpoint_omits_worker_timestamp_when_absent`: no row; GET `/metrics`; assert `200`; body does NOT contain `'esb_worker_last_iteration_timestamp_seconds'`.
    3. `test_metrics_endpoint_returns_200_when_appconfig_query_raises`: monkeypatch the `select(AppConfig)...` execute to raise `OperationalError`; GET `/metrics`; assert `200` (not 500), body does NOT contain `'esb_worker_last_iteration_timestamp_seconds'`, body DOES contain `'esb_socket_mode_enabled'` and `'esb_socket_mode_connected'`.
    4. `test_metrics_endpoint_socket_mode_both_one_when_connected`: monkeypatch both Slack accessors to return `True`; GET `/metrics`; assert body contains `'esb_socket_mode_enabled 1.0'` AND `'esb_socket_mode_connected 1.0'`.
    5. `test_metrics_endpoint_socket_mode_both_zero_when_disabled`: monkeypatch both accessors to return `False`; GET `/metrics`; assert body contains `'esb_socket_mode_enabled 0.0'` AND `'esb_socket_mode_connected 0.0'`.

- [ ] **Task 8: Reorganize the existing "Prometheus Metrics" subsection out of "Ongoing Maintenance" with anchor preservation**
  - File: `docs/administrators.md`
  - Action: Delete the `### Prometheus Metrics` subsection currently at lines 346-377. In its place insert exactly:
    ```markdown
    <a id="prometheus-metrics"></a>

    For metrics, log-based alerting, and recommended dashboards, see [Monitoring and Alerting](#monitoring-and-alerting) below.
    ```
  - Notes: The literal HTML `<a id="prometheus-metrics"></a>` preserves the old anchor. Verified safe under the project's MkDocs config: `mkdocs.yml` enables both `attr_list` and `md_in_html`, so raw inline HTML passes through. The deleted content is reused (with additions) by Task 9.

- [ ] **Task 9: Add new top-level "Monitoring and Alerting" section**
  - File: `docs/administrators.md`
  - Action: Insert a new top-level `## Monitoring and Alerting` section immediately after `## New Relic Monitoring (Optional)` and before `## Ongoing Maintenance`. Subsections in order:
    1. **`### Overview`** — One paragraph: ESB exposes Prometheus metrics on `/metrics` (unauthenticated; trusted-network deployment); logs to stdout/stderr (consume with Loki/Promtail; both `app` and `worker` containers run unbuffered Python via `PYTHONUNBUFFERED=1`); metrics are designed for direct Grafana panel use. Complementary to the optional New Relic integration. This guide gives recommended *signals*, not a turnkey configuration.
    2. **`### Prometheus Metrics`** — Reuse the existing scrape config example verbatim. Five-row metrics table:

       | Metric | Type | Description | Emission |
       |--------|------|-------------|----------|
       | `esb_pending_notifications_count` | gauge | Number of rows in `pending_notifications` with `status='pending'` | Always |
       | `esb_oldest_pending_notification_timestamp_seconds` | gauge | Unix epoch seconds of the oldest pending row's `created_at` | Omitted when queue empty (alert with `absent()`) |
       | `esb_worker_last_iteration_timestamp_seconds` | gauge | Unix epoch seconds of the worker's last successful poll cycle (read from `AppConfig.value`; `updated_at` is informational only) | Omitted when worker has never run, or when the AppConfig query fails (alert with `absent()`, **`for: 5m` minimum** to ride out cold-deploy time-to-first-poll and transient DB blips) |
       | `esb_socket_mode_enabled` | gauge | `1` if `init_slack` reached the SocketModeHandler.connect() invocation (tokens set, not `TESTING`, opt-in flag true); `0` on any of the five early-return paths | Always |
       | `esb_socket_mode_connected` | gauge | `1` if a Bolt SocketModeHandler is currently bound; `0` if never bound or released. Transitions 1→0 only at process shutdown in normal operation. | Always |

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
         expr: esb_socket_mode_enabled == 1 and esb_socket_mode_connected == 0
         for: 2m
         annotations:
           summary: "ESB intended to run Slack Socket Mode but the handler failed at boot"
       ```
       Add a `!!! note` admonition:
       > **Clock skew.** The `ESBWorkerStalled` rule mixes Prometheus's `time()` (Prometheus server clock) with a worker-written timestamp (worker container clock). Run NTP on every node, and pick the threshold to be at least ~4× `poll_interval` (so 120s for the default 30s) to absorb expected drift. The `for: 5m` on `ESBWorkerNeverRan` rides out cold-deploy time-to-first-poll *and* transient DB blips that briefly cause the metric to be omitted.

       Add a second `!!! note`:
       > **Single-worker assumption.** These metrics assume the current single-gunicorn-worker deployment (`--workers 1` in the Dockerfile). Scaling app-side gunicorn workers makes the Socket Mode metrics non-deterministic across scrapes (each worker process runs its own `init_slack`).

       Add a third `!!! note`:
       > **Information disclosure.** The Socket Mode gauges let any unauthenticated reader of `/metrics` distinguish "Slack not configured" from "Slack configured but failed at boot" from "Slack working." Acceptable on a trusted network (the documented deployment); something to be aware of if `/metrics` is ever exposed more broadly.
    3. **`### Container and Process Liveness`** — 2-3 sentences. `up{job="esb"} == 0` for ≥ 1 m indicates the app process is not responding to scrapes. cAdvisor / `container_last_seen`-style metrics catch container restart loops. Don't tutorialize.
    4. **`### Log-Based Alerting (Loki)`** — Intro paragraph: ESB writes logs to stdout/stderr; both `app` and `worker` containers run with `PYTHONUNBUFFERED=1`, so default Loki/Promtail Docker discovery captures lines without buffering latency. Then a *verified* "What to detect / Log substring" table:

       | What to detect | Source | Log substring |
       |----------------|--------|---------------|
       | Worker poll-cycle failure (any exception in the loop body) | `notification_service.py:402-405` | `Error in worker polling loop` |
       | Slack delivery exception (per notification) | `notification_service.py:390-393` | `delivery failed` (full line: `Notification %d delivery failed: %s`) |
       | Worker heartbeat write failure | `notification_service.py:35-37` | `Failed to update worker heartbeat at` |
       | Worker last-iteration write failure | (introduced by this PR) | `Failed to update worker last-iteration timestamp` |
       | Slack Socket Mode failed at boot | `esb/slack/__init__.py:67-69` | `Failed to connect Slack Socket Mode` |
       | Generic ERROR-level traffic | any | `ERROR` (level) and/or `Traceback` |

       Then a separate paragraph: **Permanent-fail signal lives in the structured JSON mutation log.** When a notification is permanently failed after `MAX_RETRIES`, `esb/utils/logging.py:36-42` writes a single-line JSON record (via `json.dumps`) to logger `esb.mutations` containing the field `event: notification.permanently_failed`. Two equivalent alerting options:
       - **Substring match** on `notification.permanently_failed` — simplest; works regardless of JSON-whitespace variation.
       - **Promtail JSON-stage parsing** — extract the `event` field as a structured Loki label for richer queries. Use a Promtail `match` stage to apply the JSON parser only to lines starting with `{`, since the regular Python logger and the mutation logger share the same stdout stream.

       End with: "Operators write their own LogQL queries and alert rules; this guide intentionally lists signals, not queries."
    5. **`### What to Alert On`** — Bulleted punch list (≤ 7 items):
       - **App down** — `up{job="esb"} == 0` for ≥ 1 m
       - **Worker stalled** — the `ESBWorkerStalled` rule above
       - **Worker never ran since deploy / DB reset** — the `ESBWorkerNeverRan` rule above
       - **Notification queue stuck** — the existing `ESBNotificationQueueStuck` rule
       - **Slack Socket Mode failed at boot** — the `ESBSocketModeFailedAtBoot` rule above
       - **Elevated rate of Slack delivery failures** — Loki on `delivery failed` exceeding a per-minute threshold
       - **Container flapping** — cAdvisor restart-count rate (or equivalent)
    6. **`### Grafana Dashboards`** — 2-3 sentences. Metrics are designed for direct panel use (gauge stats; time-series rendering `time() - <timestamp_gauge>`). ESB does not ship dashboard JSON.
    7. **`### Relationship to New Relic`** — 2-3 sentences. Different observation layers (server-side metrics + structured logs vs. APM + browser monitoring); complementary; can run together.
  - Notes: Match existing heading levels, table formatting, fenced code blocks, and `!!!` admonition syntax. Cross-link from this section back to `## New Relic Monitoring (Optional)` once.

- [ ] **Task 10: Add `PYTHONUNBUFFERED=1` to the `app` service in `docker-compose.yml`**
  - File: `docker-compose.yml`
  - Action: In the `app` service's `environment:` block, add a new entry: `- PYTHONUNBUFFERED=1`. (The `worker` service already has it.)
  - Notes: Single-line change.

- [ ] **Task 11: Automated YAML-load assertion for `PYTHONUNBUFFERED` on both services**
  - File: `tests/test_compose.py` (new)
  - Action: New test file with one small test:
    ```python
    import yaml
    from pathlib import Path

    def test_compose_pythonunbuffered_set_on_app_and_worker():
        compose = yaml.safe_load(Path('docker-compose.yml').read_text())
        for service_name in ('app', 'worker'):
            env = compose['services'][service_name].get('environment', [])
            # environment can be a list of "KEY=VALUE" strings or a dict
            if isinstance(env, list):
                assert 'PYTHONUNBUFFERED=1' in env, (
                    f"{service_name} missing PYTHONUNBUFFERED=1; log lines will buffer"
                )
            else:
                assert env.get('PYTHONUNBUFFERED') in ('1', 1), (
                    f"{service_name} missing PYTHONUNBUFFERED=1; log lines will buffer"
                )
    ```
  - Notes: PyYAML is already a transitive dependency (used by other ESB code paths). If for some reason it isn't, add it to dev deps. Single-test file is sufficient — no fixture needed.

- [ ] **Task 12: Automated assertion that `mkdocs.yml` enables `attr_list` and `md_in_html`**
  - File: `tests/test_compose.py` (extend the same file)
  - Action: Add a second test:
    ```python
    def test_mkdocs_enables_html_passthrough_for_anchor_preservation():
        cfg = yaml.safe_load(Path('mkdocs.yml').read_text())
        extensions = cfg.get('markdown_extensions', [])
        # Extensions can be plain strings or dict-with-config entries
        ext_names = {e if isinstance(e, str) else next(iter(e)) for e in extensions}
        assert 'attr_list' in ext_names, "anchor preservation in administrators.md depends on attr_list"
        assert 'md_in_html' in ext_names, "anchor preservation in administrators.md depends on md_in_html"
    ```
  - Notes: Same file as Task 11 keeps the YAML-config-invariant tests together.

### Acceptance Criteria

- [ ] **AC 1 — Worker liveness gauge, happy path:** Given an `AppConfig` row with key `worker_last_iteration_at` and a valid ISO-8601 `value`, when an operator GETs `/metrics`, then the response body contains a value line `esb_worker_last_iteration_timestamp_seconds <float>` where `<float>` equals the Unix epoch seconds of the parsed timestamp.

- [ ] **AC 2 — Worker liveness gauge, never-run:** Given no `AppConfig` row with key `worker_last_iteration_at`, when an operator GETs `/metrics`, then the substring `esb_worker_last_iteration_timestamp_seconds` does not appear in the body.

- [ ] **AC 3 — Worker writes timestamp once per poll cycle:** Given `_record_iteration_timestamp()` is invoked, when it returns, then exactly one `AppConfig` row with key `worker_last_iteration_at` exists; its `value` parses as ISO-8601 and equals `datetime.now(UTC)` within ±5 s.

- [ ] **AC 4a — Helper internal-fail rollback path:** Given `db.session.execute` raises `SQLAlchemyError` while `_record_iteration_timestamp()` is running, when the exception is caught, then `db.session.rollback()` is called, a warning is logged with substring `Failed to update worker last-iteration timestamp`, no exception escapes the helper, and a subsequent unrelated commit on the same session succeeds (no `PendingRollbackError`).

- [ ] **AC 4b — Worker loop survives a buggy helper raising arbitrary `Exception`:** Given `_record_iteration_timestamp` is patched to raise `RuntimeError('boom')` on the first call, when the worker loop runs (and is terminated on a subsequent iteration via a `KeyboardInterrupt` in stubbed `get_pending_notifications`), then the loop reaches a second iteration (proving it survived the first failure), `caplog` contains `Error in worker polling loop` (the outer-loop guard caught the `RuntimeError`), and `run_worker_loop()` exits via `KeyboardInterrupt` rather than via the `RuntimeError`.

- [ ] **AC 5 — `/metrics` graceful degradation on AppConfig query failure:** Given the `AppConfig` query in `_WorkerStatusCollector` raises `OperationalError` (simulating missing table or transient DB failure), when an operator GETs `/metrics`, then the response is HTTP `200` (not `500`), the body does NOT contain `esb_worker_last_iteration_timestamp_seconds`, the body DOES contain `esb_socket_mode_enabled` and `esb_socket_mode_connected`, and a warning is logged with substring `Failed to query worker_last_iteration_at from AppConfig`.

- [ ] **AC 6 — `esb_socket_mode_enabled` reflects `init_slack`'s actual code path:** Given `init_slack(app)` reaches the `_socket_handler.connect()` call (no early return), when an operator GETs `/metrics`, then the response contains `esb_socket_mode_enabled 1.0`. Given `init_slack(app)` takes any of the five early-return paths (no `SLACK_BOT_TOKEN`; no `SLACK_APP_TOKEN`; `TESTING=True`; `SLACK_SOCKET_MODE_CONNECT.lower() != 'true'`; `connect()` raised), then the response contains `esb_socket_mode_enabled 0.0`.

- [ ] **AC 7 — `esb_socket_mode_connected` reflects handler-binding state:** Given `_socket_handler is not None`, when an operator GETs `/metrics`, then the response contains `esb_socket_mode_connected 1.0`. Given `_socket_handler is None` (whether never bound or released by `_shutdown_socket()`), then the response contains `esb_socket_mode_connected 0.0`.

- [ ] **AC 8 — Both Socket Mode gauges always emitted across the four enumerated states:** For each of the four `(enabled, connected)` combinations `{(True, True), (True, False), (False, False)}` exercised in tests (the (False, True) state is unreachable in normal code paths since `connected==True` requires the connect-call path which sets `enabled==True`), both `esb_socket_mode_enabled` and `esb_socket_mode_connected` value lines appear in the response.

- [ ] **AC 9 — Existing metrics unchanged:** `esb_pending_notifications_count` and `esb_oldest_pending_notification_timestamp_seconds` retain their names, types, labels, and emission semantics from #32.

- [ ] **AC 10 — `/metrics` endpoint stability:** GET `/metrics` returns HTTP `200`, `Content-Type` includes `text/plain` and `version=`, body parses as valid Prometheus exposition format, no authentication required.

- [ ] **AC 11 — `PYTHONUNBUFFERED=1` set on both `app` and `worker` services, enforced by a test:** Given `tests/test_compose.py::test_compose_pythonunbuffered_set_on_app_and_worker`, when `make test` is run, then the test passes by loading `docker-compose.yml` with PyYAML and asserting `PYTHONUNBUFFERED=1` is present in the `environment` of both services.

- [ ] **AC 12 — `mkdocs.yml` HTML pass-through enforced by a test:** Given `tests/test_compose.py::test_mkdocs_enables_html_passthrough_for_anchor_preservation`, when `make test` is run, then the test passes by asserting `attr_list` and `md_in_html` are listed under `markdown_extensions`.

- [ ] **AC 13 — Documentation, new section exists:** A top-level `## Monitoring and Alerting` section exists in `docs/administrators.md` immediately after `## New Relic Monitoring (Optional)`, containing exactly seven subsections in order: Overview; Prometheus Metrics; Container and Process Liveness; Log-Based Alerting (Loki); What to Alert On; Grafana Dashboards; Relationship to New Relic.

- [ ] **AC 14 — Documentation, old subsection migrated with anchor preservation:** Under `## Ongoing Maintenance`, the previous `### Prometheus Metrics` subsection is gone; a forward-pointer line including a literal `<a id="prometheus-metrics"></a>` HTML anchor and a Markdown link to the new section replaces it.

- [ ] **AC 15 — Documentation, metric and alert tables updated:** The new `### Prometheus Metrics` subsection's table includes one row each for the five metrics. Example alert rules include the existing `ESBNotificationQueueStuck` (verbatim), the new `ESBWorkerStalled`, the new `ESBWorkerNeverRan` (`for: 5m`), and the new `ESBSocketModeFailedAtBoot` (`enabled == 1 AND connected == 0`).

- [ ] **AC 16 — Documentation, Loki substrings are verified:** The "What to detect / Log substring" table contains only substrings that appear verbatim (or as unambiguous prefixes) at the cited source line ranges: `Error in worker polling loop` (notification_service.py:402-405), `delivery failed` (notification_service.py:390-393), `Failed to update worker heartbeat at` (notification_service.py:35-37), `Failed to update worker last-iteration timestamp` (introduced in this PR), `Failed to connect Slack Socket Mode` (esb/slack/__init__.py:67-69). The permanent-fail signal is documented as a JSON mutation-log event with two alerting options (substring on `notification.permanently_failed`, or Promtail JSON-stage parsing with a `match` stage).

- [ ] **AC 17 — Documentation, three caveats present:** The new "Prometheus Metrics" subsection includes three `!!! note` admonitions: clock-skew/NTP guidance for `time() - <gauge>` rules; single-gunicorn-worker assumption for the Socket Mode metrics; information-disclosure note about the Socket Mode gauges on the unauthenticated `/metrics` endpoint.

- [ ] **AC 18 — Lint and tests pass:** `make lint` exits `0`. `make test` exits `0`. The new tests are present and pass: 3 in `test_notification_service.py`, 7 in `test_metrics_service.py`, 5 in `test_metrics_view.py`, 2 in `test_compose.py` = **17 new tests**.

## Additional Context

### Dependencies

- `prometheus_client` — already a runtime dependency (introduced in #32). No new packages.
- `AppConfig` model — already exists at `esb/models/app_config.py`. No schema migration required.
- `sqlalchemy.exc.SQLAlchemyError` — standard SQLAlchemy import.
- `PyYAML` — used by Task 11/12 tests. PyYAML is a standard transitive dependency in Python web stacks; verify it's already in dev deps before relying on it. If it isn't, add it (one line in `requirements-dev.txt` or equivalent).
- No new Docker services, no new external integrations.

### Testing Strategy

- **Unit / service tests**: 10 new tests across `tests/test_services/test_metrics_service.py` (7) and `tests/test_services/test_notification_service.py` (3). Reuse SQLite in-memory DB, the `_extract_metric` regex helper, and `app`, `db`, `monkeypatch`, `caplog` fixtures.
- **Route / integration tests**: 5 new tests in `tests/test_views/test_metrics_view.py`. Use the `client` fixture; mirror the existing GET `/metrics` substring-assert style.
- **Config-invariant tests**: 2 new tests in `tests/test_compose.py` (new file). YAML-load + assertion. No fixture needed; ~10 LOC each.
- **Module-global hygiene**: tests in `test_metrics_service.py` and `test_metrics_view.py` reset only `esb.slack._bolt_app` and `_socket_handler` before each test (mirrors `tests/test_slack/test_init.py:51-52` precedent). `_socket_mode_intended` is **not** in the reset list because `init_slack(app)` reassigns it on every TestingConfig setup; resetting it would be redundant and the spec acknowledges this explicitly.
- **Worker-loop loop-termination pattern**: tests use `KeyboardInterrupt` (raised from a stubbed `get_pending_notifications` after the desired number of iterations) to break out of `run_worker_loop`. `KeyboardInterrupt` is `BaseException`, not caught by the inner `except Exception:` guard at line 399, so it propagates cleanly. Documented in `code_patterns` so future test authors don't reach for `_shutdown=True` (which is function-local and not externally settable).
- **High-risk-mode coverage**: AC4a (helper internal fail) and AC4b (loop survives buggy helper raising `Exception`) are split into separate ACs and separate tests — the previous single-AC version conflated two non-overlapping outcomes (adversarial-review F5).
- **Realistic-failure-mode coverage**: Task 5 test 2 simulates `OperationalError` (transient DB / pool / missing-table), not `IntegrityError` (which cannot occur under single-writer). The narrow `except SQLAlchemyError` covers `IntegrityError` as a side effect.
- **Manual verification**: After implementation:
  - `docker compose up -d --build`
  - `curl http://localhost:5000/metrics` — confirm gauge lines: `esb_pending_notifications_count`, `esb_socket_mode_enabled`, `esb_socket_mode_connected`. Wait ~30 s for one worker poll cycle; re-curl; confirm `esb_worker_last_iteration_timestamp_seconds` is recent.
  - `docker compose stop worker`; wait 2 m; verify the `ESBWorkerStalled` rule (if loaded) would fire.
  - Drop the `app_config` table manually; curl `/metrics` again — confirm 200 with the worker timestamp omitted and a warning logged (graceful-degradation manual check).
  - `docker compose exec app python -c "import sys; sys.stdout.write('marker '); sys.stdout.flush()"` — confirm app log lines reach `docker logs <app>` immediately (PYTHONUNBUFFERED working).

### Notes

- **Known limitation: `esb_socket_mode_connected` transitions 1→0 at process shutdown** (when `_shutdown_socket()` runs). This is correct behavior — the gauge reflects handler-binding state, not WebSocket-up state. Documented in the gauge HELP text and AC7. (Closes adversarial-review F4 — the previous "startup state only" framing was wrong.)
- **Known limitation: single-gunicorn-worker assumption.** With `--workers 1` (current Dockerfile), `_socket_handler` is per-process and stable. Scaling workers introduces non-determinism; out of scope.
- **Known limitation: clock-skew sensitivity.** `time() - <gauge>` mixes Prometheus and worker clocks. NTP and a threshold ≥ 4× `poll_interval` are recommended in the doc.
- **Known limitation: information disclosure on `/metrics`.** The Socket Mode gauges let any unauthenticated reader on the trusted network distinguish "Slack not configured" from "Slack configured but failed at boot" from "Slack working." Acceptable on a trusted network; called out in the doc for operators considering wider exposure. (Closes adversarial-review F10.)
- **Known limitation: rapid back-to-back helper calls in the same uncommitted unit of work would each take the "row not exists" branch.** Single-writer + sequential poll loop rules this out in production. Documented for completeness. (Closes adversarial-review F18.)
- **`PYTHONUNBUFFERED=1` on app + automated check is load-bearing.** Without the var, the entire low-latency log-alerting story breaks; without the test, a regression silently re-introduces the buffering. Both are required.
- **High-risk item — non-fatal worker write semantics.** A regression here (broad `except`, missing rollback, or the helper raising into the loop) could re-introduce the silent-stall failure class that #32 hardened against. AC4a + AC4b explicitly cover the negative paths.
- **Loki guidance ships verified substrings only.** Every entry is taken from a source line cited in this spec. The permanent-fail signal is verified to be JSON (via `logging.py:36-42`); both substring and Promtail JSON-stage options are documented.
- **Lazy + dotted import in `metrics_service` is for monkeypatch-surface preservation, not circular-import avoidance.** The reason is documented in an inline code comment on the import line, so a future "cleanup" commit doesn't move the import to module top and silently break the test design. (Closes adversarial-review F12.)
- **MkDocs config (HTML pass-through) is enforced by a test** so a future plugin change cannot silently strip the `<a id="prometheus-metrics"></a>` anchor. (Closes adversarial-review F11.)
- **Performance: ~one extra DB query per scrape** (the AppConfig SELECT). Negligible at default scrape intervals.
- **Future considerations (out of scope):**
  - Counter-based slack-delivery metrics — dropped.
  - Live Socket Mode WebSocket-state gauge — requires upstream Slack Bolt change.
  - Multi-process Socket Mode coordination.
  - `/metrics` authentication for less-trusted deployments.
  - In-process caching of `worker_last_iteration_at` for aggressive scrape intervals.
  - Refactoring `run_worker_loop` to extract `_one_poll_iteration()` for cleaner unit-testing — would obviate the `KeyboardInterrupt`-stubbing pattern.
