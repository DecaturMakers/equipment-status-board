# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Equipment Status Board (ESB) — a Flask web application for tracking equipment status and repairs at Decatur Makers makerspace. Features equipment registry, repair tracking, status dashboard, Slack integration, and QR code equipment pages.

## Common Commands

```bash
make setup          # Create venv + install dev dependencies
make db-up          # Start MariaDB container
make migrate        # Apply Alembic migrations (requires running DB)
make run            # Flask dev server with debug mode (port 5000)
make worker         # Background notification delivery worker
make test           # Run all tests: pytest tests/ -v
make test-e2e       # Run e2e tests only: pytest tests/e2e/ -v
make lint           # Lint: ruff check esb/ tests/
```

Run a single test file or test function:
```bash
venv/bin/python -m pytest tests/test_services/test_equipment_service.py -v
venv/bin/python -m pytest tests/test_views/test_equipment.py::test_create_equipment -v
```

## Database Migrations

The MariaDB database runs in a Docker container (`docker-compose.yml`). There is no local MySQL/MariaDB installation. To generate or apply Alembic migrations:

1. Ensure the DB container is running: `docker compose up -d db`
2. Get the container's IP: `docker inspect equipment-status-board-db-1 --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}'`
3. Run flask db commands with the container IP:

```bash
source venv/bin/activate
DATABASE_URL="mysql+pymysql://root:esb_dev_password@<CONTAINER_IP>/esb" flask db migrate -m "Description"
DATABASE_URL="mysql+pymysql://root:esb_dev_password@<CONTAINER_IP>/esb" flask db upgrade
```

The container IP changes on restart, so always inspect it fresh. The DB port (3306) is **not** mapped to the host.

## Architecture

**Stack:** Python 3.14, Flask, Flask-SQLAlchemy, MariaDB (Docker), Slack Bolt SDK, Jinja2 templates.

**Application factory** in `esb/__init__.py` — `create_app(config_name)` initializes extensions, registers blueprints, Slack handlers, CLI commands, and Jinja filters.

**Service layer pattern** — all business logic lives in `esb/services/`. Views never query models directly; they delegate to service functions (e.g., `equipment_service.create_equipment()`, `repair_service.update_repair()`).

**Key layers:**
- `esb/models/` — SQLAlchemy ORM models (Equipment, Area, RepairRecord, User, etc.)
- `esb/services/` — Business logic, validation, audit logging
- `esb/views/` — Flask blueprints: `equipment_bp`, `repairs_bp`, `admin_bp`, `public_bp`, `auth_bp`
- `esb/forms/` — Flask-WTF form classes with CSRF protection
- `esb/slack/` — Slack Bolt integration (slash commands, modals, event handlers)
- `esb/utils/` — `@role_required` decorator, `log_mutation()` audit helper, Jinja filters

**RBAC roles:** `staff` (full access), `technician` (repairs + equipment view), `member` (view + report problems).

**Notification system:** `PendingNotification` model queued by services, delivered by background worker (`flask worker run`) polling every 30s with retry/backoff.

**Status derivation:** `status_service` computes equipment status (green/yellow/red) from open repair records.

## Testing

Tests use SQLite in-memory DB (`TestingConfig` in `esb/config.py`). CSRF is disabled in test config. Key fixtures in `tests/conftest.py`: `app`, `client`, `db`, `staff_client`, `tech_client`, `make_equipment`, `make_area`, `make_repair_record`.

## Linting

Ruff with 120-char line length, target Python 3.13 (configured in `pyproject.toml`).

## Docker Deployment

`docker-compose.yml` defines three services: `app` (gunicorn on port 5000), `db` (MariaDB 12.2.2), `worker` (notification processor). DB data persists in a Docker volume.

## Releases

Releases are fully automated by `.github/workflows/release.yml`, which runs on every push to `main`. The workflow reads the `version` field from `pyproject.toml`, compares it against the most recent GitHub release tag, and if the `pyproject.toml` version is strictly greater:

1. Builds and pushes the Docker image to `ghcr.io/decaturmakers/equipment-status-board` with both `:<version>` and `:latest` tags
2. Creates the git tag `v<version>` and pushes it
3. Creates a GitHub Release with auto-generated notes (from PR titles via `gh api releases/generate-notes`) and a Docker pull snippet

If the `pyproject.toml` version is not higher than the latest tag, the workflow no-ops.

**To cut a release: bump `version` in `pyproject.toml` (semver — patch for fixes, minor for new features, major for breaking changes) and push to `main`.** That is the entire procedure. Do not create tags manually — the workflow does it. Do not maintain a separate `CHANGELOG.md` — release notes are auto-generated from merged PR titles.
