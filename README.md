# Equipment Status Board

[![CI](https://github.com/DecaturMakers/equipment-status-board/actions/workflows/ci.yml/badge.svg)](https://github.com/DecaturMakers/equipment-status-board/actions/workflows/ci.yml)
[![Docs](https://github.com/DecaturMakers/equipment-status-board/actions/workflows/docs.yml/badge.svg)](https://github.com/DecaturMakers/equipment-status-board/actions/workflows/docs.yml)
[![GitHub release](https://img.shields.io/github/v/release/DecaturMakers/equipment-status-board)](https://github.com/DecaturMakers/equipment-status-board/releases)

A web application for tracking equipment status and coordinating repairs at community makerspaces, originally developed for [Decatur Makers](https://decaturmakers.org). Provides a single source of truth so members know what's working, technicians know what needs fixing, and staff can coordinate it all.

## Features

- **Equipment Registry & Status Tracking** — Maintain a registry of all equipment organized by area, with live green/yellow/red status derived from open repair records
- **Repair Workflow** — 10-status repair lifecycle (New through Resolved/Closed) with append-only timeline preserving diagnostic notes, photos, and assignment history
- **QR Code Equipment Pages** — Scan a QR sticker on any piece of equipment to instantly see its status, known issues, documentation, and report a problem
- **Kanban Board** — Visual overview of all active repairs by status with aging indicators to spot stuck items
- **Kiosk Display** — Large-screen auto-refreshing status grid for wall-mounted monitors in the space
- **Static Status Page** — Lightweight externally hosted page for checking status from anywhere (pushes to local directory, S3, or Google Cloud Storage)
- **Slack Integration** — Report problems, check status, create and triage repairs via slash commands (`/esb-report`, `/esb-status`, `/esb-repair`); automated notifications for new reports, status changes, and more
- **Role-Based Access** — Three user types: Members (public, no login), Technicians (repair management), Staff (full administration)

## Quick Start

See the [Administrators Guide](https://decaturmakers.github.io/equipment-status-board/administrators/) for full deployment instructions. The short version:

```bash
git clone https://github.com/DecaturMakers/equipment-status-board.git
cd equipment-status-board
cp .env.example .env    # Edit with your settings
docker compose up -d
docker compose exec app flask db upgrade
docker compose exec app flask seed-admin admin admin@example.com --password changeme
```

## Documentation

Full user guides and administrator documentation are available at:

**[decaturmakers.github.io/equipment-status-board](https://decaturmakers.github.io/equipment-status-board/)**

- [Members Guide](https://decaturmakers.github.io/equipment-status-board/members/) — Checking status, scanning QR codes, reporting problems
- [Technicians Guide](https://decaturmakers.github.io/equipment-status-board/technicians/) — Repair queue, managing repairs, Slack commands
- [Staff Guide](https://decaturmakers.github.io/equipment-status-board/staff/) — Kanban board, equipment management, user administration
- [Administrators Guide](https://decaturmakers.github.io/equipment-status-board/administrators/) — Deployment, configuration, Slack setup, maintenance

## Tech Stack

- **Python 3.14** / **Flask** — Web framework
- **MariaDB** — Database (runs in Docker)
- **Docker Compose** — Container orchestration (app + db + worker)
- **Slack Bolt SDK** — Slack integration
- **boto3** — S3 static page publishing
- **google-cloud-storage** — GCS static page publishing
- **qrcode** — QR code generation

## License

[MIT](LICENSE) — Copyright (c) 2026 Jason Antman
