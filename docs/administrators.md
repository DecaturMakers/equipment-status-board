# Administrators Guide

This guide is for technical volunteers responsible for deploying and maintaining the Equipment Status Board. It covers Docker deployment, environment configuration, Slack App setup, and ongoing maintenance.

## Prerequisites

Before you begin, ensure you have:

- **Docker** and **Docker Compose** installed on the server
- **Git** for cloning the repository
- A server or machine on the makerspace local network (or accessible to members)
- A **Slack workspace** for Slack integration (check current Slack plan requirements for Socket Mode at api.slack.com)

## Installation & Deployment

### 1. Clone the Repository

```bash
git clone https://github.com/jantman/equipment-status-board.git
cd equipment-status-board
```

### 2. Configure Environment Variables

```bash
cp .env.example .env
```

Edit `.env` and set the required values. See the [Environment Variable Reference](#environment-variable-reference) below for details on each variable.

At minimum, you must change:

- `SECRET_KEY` — Set to a random string for production (e.g., `python3 -c "import secrets; print(secrets.token_hex(32))"`)
- `MARIADB_ROOT_PASSWORD` — Set a strong database password

### 3. Start All Services

```bash
docker compose up -d
```

This starts three containers: the web application, the MariaDB database, and the background notification worker.

### 4. Run Database Migrations

```bash
docker compose exec app flask db upgrade
```

This creates all required database tables.

### 5. Create the First Staff User

```bash
docker compose exec app flask seed-admin <username> <email> --password <password> [--slack-handle <handle>]
```

For example:

```bash
docker compose exec app flask seed-admin admin admin@example.com --password changeme123 --slack-handle @adminuser
```

This creates a user with the Staff role who can then log in and create additional users through the web interface.

The `--slack-handle` option is optional but recommended if your workspace uses Slack integration. Setting it enables the system to send the user password reset notifications via Slack DM. The handle should include the `@` prefix (e.g. `@username`). The Slack handle can also be set or updated later via the admin UI at **Admin → Users**.

### 6. Verify

Open `http://localhost:5000` in a browser (or the server's IP/hostname on port 5000). You should see the status dashboard. Log in with the Staff user you just created.

## Environment Variable Reference

| Variable | Description | Required | Default | Example |
|----------|-------------|----------|---------|---------|
| `SECRET_KEY` | Flask secret key for session signing. Must be random in production. | Yes | `dev-secret-change-me` | `a1b2c3d4e5f6...` (use `python3 -c "import secrets; print(secrets.token_hex(32))"`) |
| `DATABASE_URL` | SQLAlchemy database connection URL. In Docker, the hostname is `db`. | Yes | `mysql+pymysql://root:esb_dev_password@localhost/esb` | `mysql+pymysql://root:yourpassword@db/esb` |
| `ESB_BASE_URL` | Externally-reachable base URL of this ESB instance. Used as the prefix for QR code target URLs (the URL members' phones open when they scan a printed QR label). Must be set to enable QR code generation; otherwise the "Generate QR Code" button on each equipment detail page is disabled. Inside a container the request host is unreliable, so this must be set explicitly. Trailing slashes are stripped; must be an `http(s)://host[:port]` URL with no path, query, fragment, or credentials. | Yes | _(empty)_ | `http://esb.example.com:8080` |
| `MARIADB_ROOT_PASSWORD` | Root password for the MariaDB container. Must match the password in `DATABASE_URL`. | Yes | `esb_dev_password` | `strong-random-password` |
| `UPLOAD_PATH` | Directory for uploaded files (photos, documents). Relative to app root or absolute path. | No | `uploads` | `/app/uploads` |
| `UPLOAD_MAX_SIZE_MB` | Maximum upload file size in megabytes. | No | `500` | `100` |
| `SLACK_BOT_TOKEN` | Slack Bot User OAuth Token. Leave empty to disable Slack integration. | No | _(empty)_ | `xoxb-1234567890-...` |
| `SLACK_APP_TOKEN` | Slack App-Level Token for Socket Mode. Required for Slack integration. Leave empty to disable. | No | _(empty)_ | `xapp-1-...` |
| `SLACK_SOCKET_MODE_CONNECT` | Set to `true` to enable the Socket Mode WebSocket connection. Only the app container should set this; worker and other services should leave it unset. | No | _(empty)_ | `true` |
| `SLACK_OOPS_CHANNEL` | Slack channel for cross-area notifications. Can be set in `.env` (not included in `.env.example` by default). | No | `#oops` | `#equipment-alerts` |
| `STATIC_PAGE_PUSH_METHOD` | How to publish the static status page. Options: `local` (write to directory), `s3` (upload to S3 bucket via boto3), or `gcs` (upload to Google Cloud Storage bucket). | No | `local` | `s3` |
| `STATIC_PAGE_PUSH_TARGET` | Target for static page push. For `local`: a directory path. For `s3` and `gcs`: `bucket-name/optional/key/path` (key defaults to `index.html`). | No | _(empty)_ | `my-status-bucket/index.html` |
| `CLOUDFRONT_DISTRIBUTION_ID` | CloudFront distribution ID. Only meaningful when `STATIC_PAGE_PUSH_METHOD=s3`. When set, a CloudFront invalidation is issued for the uploaded key after every successful S3 upload, so the CDN serves the just-uploaded content immediately. Requires the IAM principal to have `cloudfront:CreateInvalidation` on the distribution. The AWS Free Tier covers 1000 invalidation paths per month; pushes more frequently than that will incur per-invalidation charges. | No | _(empty)_ | `EDFDVBD6EXAMPLE` |
| `FLASK_APP` | Flask application entry point. Do not change. | No | `esb:create_app` | `esb:create_app` |
| `FLASK_DEBUG` | Enable Flask debug mode. Set to `0` in production. | No | `1` | `0` |
| `AWS_ACCESS_KEY_ID` | AWS access key for S3 static page push. Only needed if `STATIC_PAGE_PUSH_METHOD=s3` and not using an IAM role. | No | _(empty)_ | `AKIAIOSFODNN7EXAMPLE` |
| `AWS_SECRET_ACCESS_KEY` | AWS secret key for S3 static page push. Only needed if `STATIC_PAGE_PUSH_METHOD=s3` and not using an IAM role. | No | _(empty)_ | `wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY` |
| `GOOGLE_APPLICATION_CREDENTIALS` | Path to Google Cloud service account JSON key file. Only needed if `STATIC_PAGE_PUSH_METHOD=gcs` and not using instance metadata or Workload Identity. | No | _(empty)_ | `/path/to/service-account.json` |
| `NEW_RELIC_LICENSE_KEY` | New Relic license key. Enables APM and browser monitoring when set. Leave empty to disable. | No | _(empty)_ | `abc123def456...` |
| `NEW_RELIC_APP_NAME` | Application name shown in the New Relic dashboard. | No | `Equipment Status Board` | `ESB Production` |

!!! warning
    Always set `SECRET_KEY` to a unique random value in production. The default value is insecure and only suitable for development.

!!! warning
    Set `FLASK_DEBUG=0` in production. Debug mode exposes detailed error pages and enables the interactive debugger.

## Docker Services

The application runs as three Docker containers defined in `docker-compose.yml`:

### App Service

The main web application. Runs Flask via Gunicorn with 1 worker process and 2 threads on port 5000.

- **Image:** Built from the project `Dockerfile` (Python 3.14-slim base)
- **Port:** 5000 (mapped to host)
- **Volume:** `./uploads` bind mount for persistent file storage (uploaded photos and documents)
- **Depends on:** `db` service (waits for healthy database)

### Database Service

MariaDB 12.2.2 database server. Stores all application data.

- **Image:** `mariadb:12.2.2`
- **Volume:** `mariadb_data` named volume for persistent data storage
- **Health check:** Pings the database every 10 seconds to verify availability
- **Port:** Not mapped to host (only accessible from other containers)

### Worker Service

Background notification processor. Polls the database every 30 seconds for pending notifications and delivers them via Slack.

- **Image:** Same as the app service
- **Command:** `flask worker run`
- **Depends on:** `db` service
- **Healthcheck:** The worker writes `/tmp/worker_heartbeat` at three points: once at startup, once after each DB poll returns, and once after each individual notification is processed. Docker reports the container as unhealthy if the heartbeat file is older than 180 seconds, which catches a wedged loop (e.g. silently dropped DB connection or a single Slack call hung past its timeout). Refreshing per-notification — rather than only at the end of an iteration — means a legitimately long batch of slow Slack calls cannot falsely trip the healthcheck.

### Autoheal Sidecar

Docker on its own does not restart unhealthy containers — it only marks them unhealthy. The `autoheal` service (`willfarrell/autoheal`) watches for containers labelled `autoheal=true` (the `worker` and `app` services) and restarts any that go unhealthy. It needs the host's Docker socket mounted so it can issue restart commands:

```yaml
autoheal:
  image: willfarrell/autoheal:latest
  environment:
    - AUTOHEAL_CONTAINER_LABEL=autoheal
  volumes:
    - /var/run/docker.sock:/var/run/docker.sock
  restart: unless-stopped
```

If you do not want autoheal running on your host, you can remove the service from `docker-compose.yml`; the worker's healthcheck will still reflect status in `docker compose ps`, you'll just need to restart it manually when it goes unhealthy.

All four services have a restart policy of `unless-stopped`, meaning they automatically restart after crashes or host reboots (unless explicitly stopped).

### Runtime Dependencies

The application Docker image includes these key Python packages:

- **Flask** — Web framework
- **SQLAlchemy / Flask-SQLAlchemy** — Database ORM
- **PyMySQL** — MariaDB database driver
- **slack-bolt / slack_sdk** — Slack integration (slash commands, modals, events via Socket Mode)
- **websocket-client** — WebSocket transport for Slack Socket Mode
- **boto3** — AWS S3 client for static page push (when using `s3` method)
- **google-cloud-storage** — Google Cloud Storage client for static page push (when using `gcs` method)
- **qrcode[pil]** — QR code generation for equipment pages
- **newrelic** — New Relic APM and browser monitoring agent (optional, activated by `NEW_RELIC_LICENSE_KEY`)
- **gunicorn** — Production WSGI server

## Slack App Configuration

Slack integration is optional — the core web application works without it. If you want Slack commands, notifications, and the status bot, follow these steps.

### 1. Create a Slack App

1. Go to [api.slack.com/apps](https://api.slack.com/apps) and click **Create New App**
2. Choose **From scratch**
3. Name the app (e.g., "Equipment Status Board") and select your workspace

### 2. Configure Bot Token Scopes

Under **OAuth & Permissions**, add these Bot Token OAuth Scopes:

- `chat:write` — Send messages and notifications
- `commands` — Register slash commands
- `users:read` — Look up user information
- `users:read.email` — Look up users by email
- `im:write` — Send direct messages (for temporary password delivery)

### 3. Enable Socket Mode

1. Go to **Settings > Socket Mode** in the Slack App settings
2. Turn on **Enable Socket Mode**
3. Create an App-Level Token with the `connections:write` scope
4. Name it (e.g., "esb-socket") and copy the token (starts with `xapp-`)

### 4. Set Up Slash Commands

Under **Slash Commands**, create four commands:

| Command | Description |
|---------|-------------|
| `/esb-report` | Report an equipment problem |
| `/esb-status` | Check equipment status (area or equipment name) |
| `/esb-repair` | Technician dispatcher (no args) or create a repair record (with arg) |
| `/esb-update` | Update a repair record (full edit) |

With Socket Mode enabled, slash commands are automatically routed to your app via WebSocket. No Request URL is needed.

### 5. Enable Event Subscriptions

Under **Event Subscriptions**:

1. Turn on **Enable Events**

Event subscriptions are not currently required but may be used for future features.

### 6. Install the App

1. Go to **Install App** and click **Install to Workspace**
2. Authorize the permissions

### 7. Copy Credentials

After installation:

1. Copy the **Bot User OAuth Token** (starts with `xoxb-`) and set it as `SLACK_BOT_TOKEN` in your `.env`
2. Copy the **App-Level Token** (starts with `xapp-`, created in step 3) and set it as `SLACK_APP_TOKEN` in your `.env`
3. Restart the app and worker: `docker compose restart app worker`

!!! note
    Socket Mode uses an outbound WebSocket connection — no public URL or reverse proxy is needed. Your ESB server can remain on a private network.

### Notification Trigger Configuration

Slack outbound notifications are governed by per-event app-config keys. Each is a boolean stored in `app_config` (string `'true'` / `'false'`) and toggled via the admin UI at **Admin → App Configuration**. All five default to `'true'`, so a fresh deployment inherits notifications automatically.

| Config key | Default | Fires on |
|------------|---------|----------|
| `notify_new_report` | `'true'` | A new problem report is filed (member or technician path). |
| `notify_resolved` | `'true'` | A repair record's status transitions to a closed status (`Resolved`, `Closed - Duplicate`, `Closed - No Issue Found`). |
| `notify_severity_changed` | `'true'` | A repair record's severity level changes. |
| `notify_status_changed` | `'true'` | A repair record's status changes between **open** states (e.g., `New` → `In Progress`, `Assigned` → `Parts Needed`). Closed-status transitions go through `notify_resolved` instead, so disabling this key does not silence resolutions. |
| `notify_eta_updated` | `'true'` | A repair record's ETA is set or changed. |

If `notify_resolved` is `'false'` AND a status transition lands on a closed status, no notification fires — the elif-structure does NOT fall through to `status_changed`.

## Static Status Page Setup

The static status page provides a lightweight, externally accessible version of the equipment status dashboard. It is regenerated and pushed automatically whenever equipment status changes.

### Configuration

Set the push method via the `STATIC_PAGE_PUSH_METHOD` environment variable:

- **`local`** — Writes the static page to a local directory specified by `STATIC_PAGE_PUSH_TARGET`. Useful for serving from a local web server or shared drive.
- **`s3`** — Uploads the static page to an S3 bucket specified by `STATIC_PAGE_PUSH_TARGET`. Requires AWS credentials configured in the environment (via `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` or an IAM role). Optionally set `CLOUDFRONT_DISTRIBUTION_ID` to also issue a CloudFront invalidation for the uploaded key after every successful upload (requires `cloudfront:CreateInvalidation` on the distribution).
- **`gcs`** — Uploads the static page to a Google Cloud Storage bucket specified by `STATIC_PAGE_PUSH_TARGET`. Uses Google's default credential chain (`GOOGLE_APPLICATION_CREDENTIALS` environment variable, GCE instance metadata, or Workload Identity). When using Docker with a service account key file, add a volume mount for the credentials file in `docker-compose.yml` (e.g., `- ./service-account.json:/app/service-account.json:ro`) and set `GOOGLE_APPLICATION_CREDENTIALS=/app/service-account.json`.

The static page is pushed by the background worker whenever it detects a status change during its polling cycle.

## New Relic Monitoring (Optional)

New Relic integration provides server-side APM (Application Performance Monitoring) and browser monitoring for end users. When enabled, it automatically instruments the Flask application, background worker, and injects browser monitoring JavaScript into all pages.

### Enabling New Relic

Set the `NEW_RELIC_LICENSE_KEY` environment variable in your `.env` file:

```bash
NEW_RELIC_LICENSE_KEY=your-license-key-here
NEW_RELIC_APP_NAME=Equipment Status Board
```

Restart all services after updating:

```bash
docker compose restart app worker
```

Both the web application and background worker will begin reporting to New Relic. Browser monitoring JavaScript is automatically injected into every page served by the application.

### Verifying

After enabling, check the New Relic dashboard for your application name. You should see:

- **APM data** — web transactions, throughput, error rates, and response times
- **Browser data** — page load times, JavaScript errors, and AJAX calls from end users

If no data appears, check the app and worker logs for New Relic-related errors:

```bash
docker compose logs app | grep -i "new.relic\|newrelic"
```

### Disabling

To disable New Relic, remove or comment out `NEW_RELIC_LICENSE_KEY` in your `.env` file and restart the services. When the license key is not set, no New Relic code is loaded and there is zero performance impact.

## Monitoring and Alerting

### Overview

ESB exposes Prometheus metrics on `/metrics` (unauthenticated; trusted-network deployment). Both the `app` and `worker` containers run with `PYTHONUNBUFFERED=1` so log lines reach Loki/Promtail without buffering latency. The metrics are designed for direct Grafana panel use. This section is complementary to the optional New Relic integration above; it gives recommended *signals*, not a turnkey configuration.

### Prometheus Metrics

Example scrape config:

```yaml
scrape_configs:
  - job_name: esb
    metrics_path: /metrics
    static_configs:
      - targets: ['esb.example.com:5000']
```

| Metric | Type | Description | Emission |
|--------|------|-------------|----------|
| `esb_pending_notifications_count` | gauge | Number of rows in `pending_notifications` with `status='pending'` | Always |
| `esb_oldest_pending_notification_timestamp_seconds` | gauge | Unix epoch seconds of the oldest pending row's `created_at` | Omitted when queue empty (alert with `absent()`) |
| `esb_worker_last_iteration_timestamp_seconds` | gauge | Unix epoch seconds of the worker's last successful poll cycle (read from `AppConfig.value`) | Omitted when worker has never run, or when the `AppConfig` query fails (alert with `absent()`, **`for: 5m` minimum**) |
| `esb_socket_mode_enabled` | gauge | `1` if `init_slack` entered the Socket Mode setup block (tokens set, not `TESTING`, opt-in flag true); `0` otherwise | Always |
| `esb_socket_mode_connected` | gauge | `1` if a Bolt SocketModeHandler is currently bound; `0` otherwise. Transitions 1→0 at process shutdown. | Always |

Example alert rules:

```yaml
- alert: ESBNotificationQueueStuck
  expr: time() - esb_oldest_pending_notification_timestamp_seconds > 300
  for: 1m
  annotations:
    summary: "ESB notification worker is not draining the queue"
```

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

**`ESBWorkerStalled` and `ESBWorkerNeverRan` are complementary and should both be loaded.** `ESBWorkerStalled` detects "worker was alive recently but stopped iterating" — fires on a normal stall but doesn't fire when the metric is missing entirely. `ESBWorkerNeverRan` detects the metric-missing case — fires on cold-deploy time-to-first-poll AND on transient `AppConfig` query failures. Together they cover the full failure space.

!!! note "Clock skew"
    `time() - <gauge>` rules mix Prometheus's clock with the worker container's clock. Run NTP on every node and pick the threshold ≥ 4× `poll_interval` (so 120s for the default 30s). Note the failure asymmetry: if the worker's clock runs *behind* Prometheus's, the rule fires aggressively; if the worker's clock runs *ahead*, `time() - gauge` goes negative and the rule is **silent forever**. NTP is mandatory, not optional.

!!! note "Single-worker assumption"
    These metrics assume the current single-gunicorn-worker deployment (`--workers 1`). Scaling app-side gunicorn workers makes the Socket Mode metrics non-deterministic across scrapes.

!!! note "Information disclosure"
    The Socket Mode gauges let any unauthenticated reader of `/metrics` distinguish "Slack not configured" from "Slack configured but failed at boot" from "Slack working." Acceptable on a trusted network; something to be aware of if `/metrics` is ever exposed more broadly.

!!! note "`ESBSocketModeFailedAtBoot` shutdown safety"
    The rule includes `unless on(instance) up == 0` to suppress the alert during a full app outage (where `up == 0` is already the dominant signal) and uses `for: 5m` to absorb gunicorn worker reloads (`--max-requests` recycling) where `_shutdown_socket()` briefly leaves state at `(1, 0)`. The `on(instance)` clause assumes targets share an `instance` label; if your relabeling adds richer labels (e.g. `cluster`, `env`) you may need `unless on(job, instance) up == 0` to keep the join correct.

!!! note "`/metrics` endpoint resilience"
    The endpoint returns HTTP 200 even when the `app_config` table is missing (e.g., on a fresh deployment that hasn't yet run `flask db upgrade`). The worker-timestamp metric is simply omitted; alert via `ESBWorkerNeverRan`. The first per-process query failure logs a full stack trace; subsequent failures log a one-line warning to avoid log flooding.

### Container and Process Liveness

`up{job="esb"} == 0` for ≥ 1 minute indicates the app is not responding to scrapes — covers OOM kills, gunicorn wedges, and network partitions. cAdvisor's `container_last_seen` (or its restart-count rate) catches container restart loops where the app keeps crashing fast enough that `up{}` may briefly recover between scrapes.

### Log-Based Alerting (Loki)

ESB writes logs to stdout/stderr; both the `app` and `worker` containers run with `PYTHONUNBUFFERED=1` so lines reach Promtail/Loki without Python's default block-buffering latency.

| What to detect | Source | Log substring |
|----------------|--------|---------------|
| Worker poll-cycle failure (any exception in the loop body) | `notification_service.py` (worker outer-try) | `Error in worker polling loop` |
| Slack delivery exception (per notification, app-log line) | `notification_service.py` (per-notification failure log) | `delivery failed:` (trailing colon required — uniquely matches the failure-line format string `'Notification %d delivery failed: %s'`; does NOT match the success log or the `NotImplementedError` log even though all three share the `Notification %d ...` prefix; also does not match the JSON mutation log) |
| Worker heartbeat write failure | `notification_service.py` (`_write_heartbeat`) | `Failed to update worker heartbeat at` |
| Worker last-iteration write failure | `notification_service.py` (`_record_iteration_timestamp`) | `Failed to update worker last-iteration timestamp` |
| Buggy iteration-timestamp helper | `notification_service.py` (worker-loop call site) | `BUG: _record_iteration_timestamp raised unexpectedly` |
| Slack Socket Mode setup failure (import / instantiation / connect) | `esb/slack/__init__.py` (unified setup `try`) | `Failed to set up Slack Socket Mode` |
| `/metrics` AppConfig query failure (first per process) | `esb/services/metrics_service.py` | `Failed to query worker_last_iteration_at from AppConfig` |
| Generic ERROR-level traffic | any | `ERROR` (level) and/or `Traceback` |

**Permanent-fail signal lives in the structured JSON mutation log.** When a notification is permanently failed after `MAX_RETRIES`, the mutation logger writes a single-line JSON record to logger `esb.mutations` containing `event: notification.permanently_failed`. Two equivalent alerting options:

- **Substring match** on `notification.permanently_failed` — simplest; works regardless of JSON-whitespace variation.
- **Promtail JSON-stage parsing** — extract `event` as a structured Loki label. Use a Promtail `match` stage to apply the JSON parser only to lines starting with `{`, since the regular Python logger and the mutation logger share the same stdout stream.

Operators write their own LogQL queries and alert rules; this guide intentionally lists signals, not queries. Note that the substrings in the table above are stable today but unanchored — a future log message containing the same text would also match. For a future-resistant query, anchor with the `Notification N` prefix (regex `Notification \d+ delivery failed:` for the per-notification case), or filter by log level.

### What to Alert On

- **App down** — `up{job="esb"} == 0` for ≥ 1 m
- **Worker stalled** — the `ESBWorkerStalled` rule
- **Worker never ran since deploy / DB reset** — the `ESBWorkerNeverRan` rule
- **Notification queue stuck** — the existing `ESBNotificationQueueStuck` rule
- **Slack Socket Mode failed at boot** — the `ESBSocketModeFailedAtBoot` rule (covers import, instantiation, and connect failures; suppressed during full app outage)
- **Elevated rate of Slack delivery failures** — Loki on `delivery failed:` substring exceeding a per-minute threshold
- **Container flapping** — cAdvisor restart-count rate

### Grafana Dashboards

The ESB metrics are designed for direct panel use — gauge panels for the Socket Mode and worker-timestamp metrics, time-series panels for the queue gauges, and log panels backed by the Loki substrings above. ESB does not ship a dashboard JSON; operators build the panels they actually want to watch.

### Relationship to New Relic

New Relic (above) and the Prometheus/Loki/Grafana stack here observe different layers and are complementary. New Relic provides per-transaction APM and end-user browser monitoring; Prometheus provides system-health gauges and log-based alerting suitable for on-call paging. They can run together with no additional configuration.

## Ongoing Maintenance

### Viewing Logs

```bash
# Application logs
docker compose logs -f app

# Worker logs (notification delivery)
docker compose logs -f worker

# Database logs
docker compose logs -f db
```

### Restarting Services

```bash
# Restart the web application
docker compose restart app

# Restart the notification worker
docker compose restart worker

# Restart all services
docker compose restart
```

### Applying Updates

```bash
# Pull latest code
git pull

# Rebuild containers
docker compose build

# Restart with new images
docker compose up -d

# Apply any new database migrations
docker compose exec app flask db upgrade
```

### Monitoring the Worker

The background worker processes pending notifications every 30 seconds. It includes retry logic with backoff for failed deliveries. Check the worker logs for:

- Successful notification deliveries
- Failed delivery attempts and retry counts
- Slack API errors (usually indicate an expired or invalid token)

```bash
docker compose logs -f worker
```

The worker container also exposes a Docker healthcheck driven by a heartbeat file (`/tmp/worker_heartbeat`) refreshed at three points: at startup, after each DB poll returns, and after each individual notification is processed. The healthcheck fails when the file is older than 180 seconds. To check current health:

```bash
docker inspect --format '{{.State.Health.Status}}' equipment-status-board-worker-1
```

If the worker is reported as `unhealthy`, the autoheal sidecar will restart it automatically (typically within a minute).

For metrics, log-based alerting, and recommended dashboards, see the [Monitoring and Alerting](#monitoring-and-alerting) section above. (External links to `#prometheus-metrics` continue to resolve — the new `### Prometheus Metrics` subsection auto-generates the same anchor.)

### Upload Storage

Uploaded files (equipment photos, documents, diagnostic images) are stored in the `./uploads/` directory, which is bind-mounted into the app container. Monitor disk usage on the host:

```bash
du -sh ./uploads/
```

### Database

MariaDB data is persisted in the `mariadb_data` Docker volume. This volume survives container restarts and `docker compose down`. It is only removed if you explicitly run `docker compose down -v` (which deletes volumes — **do not do this unless you intend to lose all data**).

## Troubleshooting

### App won't start

- Check that `DATABASE_URL` is correct and uses `db` as the hostname (not `localhost`) when running in Docker
- Verify the `db` service is healthy: `docker compose ps`
- Check app logs: `docker compose logs app`

### Slack commands not working

- Verify `SLACK_BOT_TOKEN` and `SLACK_APP_TOKEN` are set correctly in `.env`
- Verify Socket Mode is enabled in the Slack App settings and the app-level token has the `connections:write` scope
- Verify `SLACK_SOCKET_MODE_CONNECT=true` is set in the app service environment
- Check that the Slack App has the required OAuth scopes
- Check app logs for Slack-related errors: `docker compose logs app | grep -i slack`

### Notifications not delivering

- Verify the worker is running: `docker compose ps worker`
- Check worker logs: `docker compose logs -f worker`
- Confirm `SLACK_BOT_TOKEN` is valid and the bot is installed to the workspace
- Check that notification triggers are enabled in Admin > Config

### Static page not updating

- Verify `STATIC_PAGE_PUSH_METHOD` and `STATIC_PAGE_PUSH_TARGET` are set
- Check that the worker is running (it handles the push)
- For `s3` method: verify AWS credentials and bucket permissions
- For `gcs` method: verify Google Cloud credentials and bucket permissions
- For `local` method: verify the target directory exists and is writable
- Check worker logs for push errors
