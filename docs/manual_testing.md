# Manual Testing Scenarios

Eleven scenarios for manual verification of the Equipment Status Board's core user flows. Each scenario lists preconditions, steps, and expected results.

## Prerequisites

- Application running locally (`make run`) with a seeded database
- At least one area configured with a Slack channel mapping
- At least one piece of equipment in each status (operational, degraded, down)
- User accounts: one Staff, one Technician
- Slack workspace connected with the app installed
- Background worker running (`make worker`)
- `ESB_BASE_URL` configured in the environment (required for QR label generation)

---

## 1. QR Code Equipment Page — Status Check

**Role:** Unauthenticated member

**Steps:**

1. Open `/public/equipment/<id>` for a piece of equipment that has an open "Down" repair record.
2. Observe the page loads without any login prompt.
3. Verify the equipment name, area, and a large red status indicator are visible above the fold.
4. Verify the issue description and ETA (if set) are displayed.
5. Scroll to "Known Issues" and confirm the open repair record appears.
6. Repeat with an operational (green) equipment — confirm no issues section is shown and the status indicator is green.

**Expected Results:**

- Page loads instantly with no authentication required.
- Status indicator color and text match the equipment's derived status.
- Open repair records are listed under Known Issues.
- Equipment documentation links (manuals, training videos) are accessible from the page.

---

## 2. QR Code Equipment Page — Problem Report Submission

**Role:** Unauthenticated member

**Steps:**

1. Open `/public/equipment/<id>` for any equipment.
2. Scroll to the "Report a Problem" form.
3. Fill in reporter name and problem description (both required).
4. Set severity to "Down" and check the safety risk flag.
5. Submit the form.
6. Observe the confirmation page.

**Expected Results:**

- Form rejects submission if name or description is blank.
- On success, a confirmation page is shown with links to the relevant area Slack channel and #oops.
- A new repair record is created with status "New," severity "Down," and the safety flag set.
- A Slack notification is posted to the area channel and #oops, with a :warning: indicator for the safety flag.
- The equipment's status on the public dashboard updates to red.

---

## 3. Public Status Dashboard and Kiosk Mode

**Role:** Unauthenticated member

**Steps:**

1. Open `/public/` and verify a color-coded grid of all equipment organized by area.
2. Confirm equipment cards show green, yellow, or red indicators matching their current status.
3. Click an equipment card and verify it navigates to the public equipment page (`/public/equipment/<id>`).
4. Open `/public/kiosk` (or `/public/?kiosk=true`).
5. Confirm the kiosk layout is full-width with large fonts and no navigation chrome.
6. Wait 60+ seconds and verify the page auto-refreshes without a full page reload or visible flicker.

**Expected Results:**

- Dashboard accurately reflects all non-archived equipment grouped by area.
- Kiosk mode auto-refreshes and remains readable at room distance.
- No login prompt on any public page.

---

## 4. Technician — Repair Queue Triage and Record Update

**Role:** Technician (authenticated)

**Steps:**

1. Log in as a Technician user. Verify you land on the repair queue (`/repairs/queue`).
2. Confirm the queue shows columns: Equipment, Severity, Area, Age, Status, Assignee.
3. Verify default sort is severity (Down first), then age (oldest first).
4. Use the Area filter dropdown to filter to a single area; confirm only matching records appear.
5. Click a repair record with status "New" to open its detail page.
6. Self-assign the repair (set assignee to yourself).
7. Change status to "In Progress."
8. Add a diagnostic note (e.g., "Motor brushes worn, needs replacement").
9. Save all changes.

**Expected Results:**

- Queue displays correctly on both desktop (table) and mobile (cards).
- Filtering narrows results to the selected area.
- On the detail page, the append-only timeline shows the status change, assignee change, and note — each with timestamp and author.
- The equipment's public status page reflects the updated repair information.

---

## 5. Technician — Full Repair Lifecycle

**Role:** Technician (authenticated)

**Steps:**

1. Open a repair record currently in "In Progress" status.
2. Change status to "Parts Needed" and add a note identifying the part.
3. Save. Then reopen and change status to "Parts Ordered," set an ETA date.
4. Save. Then reopen and change status to "Parts Received."
5. Save. Then reopen and change status to "Resolved," add a closing note.
6. Verify the complete timeline shows all transitions.
7. Navigate to the repair's equipment detail page (`/equipment/<id>`) and scroll to the "Repair History" card.

**Expected Results:**

- Each status transition is recorded in the timeline with timestamp and author.
- ETA appears on the public equipment page while the repair is open.
- After resolving, the equipment's derived status returns to green (assuming no other open repairs).
- Slack notifications fire for configured events (severity change, ETA update, resolution).
- The Repair History card on the equipment detail page lists this repair (newest first) with a green "Resolved" badge; clicking the row navigates to `/repairs/<id>`. Closed-without-resolution records (e.g., "Closed - No Issue Found", "Closed - Duplicate") render with a gray badge.

---

## 6. Staff — Kanban Board and Aging Indicators

**Role:** Staff (authenticated)

**Steps:**

1. Log in as a Staff user. Verify you land on the Kanban board (`/repairs/kanban`).
2. Confirm columns exist for: New, Assigned, In Progress, Parts Needed, Parts Ordered, Parts Received, Needs Specialist.
3. Verify resolved/closed repairs are not shown on the board.
4. Identify a repair card that has been in its current column for 3+ days — confirm it has a "warm" visual indicator.
5. Identify a repair card in its column for 6+ days — confirm it has a "hot" (urgent) visual indicator.
6. Click a repair card and verify it opens the repair detail page.

**Expected Results:**

- Kanban board accurately reflects all open repairs in their current status columns.
- Aging indicators visually distinguish recent, warm (3-5 days), and hot (6+ days) items.
- On mobile, columns collapse into an accordion layout.

---

## 7. Staff — Equipment and Area Administration

**Role:** Staff (authenticated)

**Steps:**

1. Navigate to `/equipment/new` and create a new piece of equipment with name, area, manufacturer, and model.
2. After creation, navigate to the equipment detail page and verify all fields are shown.
3. Edit the equipment to add a description and documentation link. Save.
4. Navigate to `/admin/areas` and create a new area with a name and Slack channel.
5. Navigate to `/admin/users` and create a new Technician user with a username, email, and Slack handle.
6. Verify the temporary password is delivered via Slack DM.
7. Archive the equipment created in step 1. Verify it no longer appears on the public dashboard.
8. Navigate to `/equipment/` (the equipment registry). Click the "Export CSV" button.
9. Apply an area filter from the registry filter controls, then click "Export CSV" again.
10. Append `?include_archived=1` to the export URL and download once more.

**Expected Results:**

- Equipment CRUD operations succeed and are reflected on public pages.
- New area appears in area filter dropdowns and equipment forms.
- New user can log in with the temporary password and sees the Technician experience.
- Archived equipment is hidden from active views but its repair history is preserved.
- CSV download opens cleanly in Excel/LibreOffice with a UTF-8 BOM, includes columns for id, name, manufacturer, model, serial_number, area, acquisition_date/source/cost, warranty_expiration, description, is_archived, created_at, and updated_at.
- Filtered export contains only equipment from the selected area; default export omits archived items, while `include_archived=1` includes them.
- Cells whose text begins with `=`, `+`, `-`, or `@` are defused (leading apostrophe) to prevent spreadsheet formula injection.

---

## 8. Slack — Status Query and Problem Reporting

**Role:** Any Slack workspace member

**Steps:**

1. In Slack, type `/esb-status` with no arguments. Verify an ephemeral message shows all areas with operational/degraded/down counts.
2. Type `/esb-status SawStop` (or another equipment name). Verify the response includes equipment status, any open issue description, ETA, and assignee.
3. Type `/esb-report`. Verify a modal opens with fields for equipment (dropdown), reporter name, description, severity, safety risk checkbox, and consumable checkbox.
4. Fill in the modal and submit.
5. Verify an ephemeral confirmation message appears.

**Expected Results:**

- `/esb-status` returns accurate, current status information.
- `/esb-report` creates a repair record identical to one submitted via the web form.
- Slack notifications post to the appropriate area channel and #oops.
- The new repair appears in the web repair queue.

---

## 9. Slack — Repair Update via Modal

**Role:** Technician or Staff (with Slack account mapped to ESB user)

**Steps:**

1. Note the ID of an open repair record (e.g., #42).
2. In Slack, type `/esb-update 42`.
3. Verify a modal opens pre-populated with the repair's current status, severity, assignee, and ETA.
4. Change the status to "In Progress," add a note, and assign to yourself.
5. Submit the modal.
6. Open the same repair record in the web UI (`/repairs/42`).

**Expected Results:**

- Modal fields reflect the repair's current state.
- After submission, an ephemeral confirmation appears in Slack.
- The web UI timeline shows the status change, note, and assignee update — attributed to the correct ESB user (mapped from Slack identity).
- Slack notifications fire per configuration.

---

## 9b. Slack UX (issue #34)

**Role:** Technician or Staff (with Slack account mapped to ESB user)

**Status query and detail formats:**

1. `/esb-status` (no args) → ephemeral message has the per-area count line followed by a bullet list of every non-green item (severity emoji + name + brief description + ETA when set), and ends with the footer hint pointing at `/esb-status <area name>`.
2. `/esb-status <area-name>` (any case) → area-detail view: `:bar_chart: *<area>*` header, every equipment item with its status emoji + label, and for each non-green item a blockquote with issue / ETA / assignee.
3. `/esb-status <equipment-name>` → existing single-equipment detail view (regression).
4. `/esb-status <name>` where `<name>` matches BOTH an area exactly AND an equipment substring → area-detail view wins (precedence rule).

**`/esb-report` regression:**

5. `/esb-report` opens the existing problem-report modal. (Confirms the dispatcher refactor did not leak into the member-report path.)

**`/esb-repair` dispatcher (no args):**

6. `/esb-repair` (no args) with at least one open repair → dispatcher modal opens, showing options grouped by area (alphabetical), each option labelled `#<id> <equipment> — <status>` with severity / assignee description.
7. Pick a repair → second modal pushes on top.
8. For each of the four actions in the action modal, verify behavior + ephemeral confirmation emoji matches the legend:
    - **Claim** on a `New` repair → status moves to `Assigned`, you are the assignee. Confirmation contains `:arrows_counterclockwise:`.
    - **Claim** on an `Assigned` / `In Progress` repair → assignee changes to you, status unchanged.
    - **Set ETA** → record's ETA updates. Confirmation contains `:calendar:`.
    - **Set Status** → `In Progress` confirmation contains `:arrows_counterclockwise:`; `Closed - Duplicate` / `Closed - No Issue Found` confirmation contains `:white_check_mark:`.
    - **Resolve with Note** → status moves to `Resolved`, the note appears as a timeline entry. Confirmation contains `:white_check_mark:`.
9. `/esb-repair` (no args) when there are no open repairs → ephemeral `:wrench: No open repairs.` (no modal).

**`/esb-repair <equipment>` regression:**

10. `/esb-repair <name>` where `<name>` matches exactly one piece of equipment → create-record modal opens with that equipment pre-selected.
11. `/esb-repair <name>` where `<name>` matches multiple → create-record modal opens with no preselection.

**Outbound notifications:**

12. Trigger one of each event with their corresponding emoji prefix:
    - `new_report` (without safety_risk) → `:rotating_light:`.
    - `new_report` (with safety_risk) → `:warning: *SAFETY RISK* :warning:`.
    - `severity_changed` → `:wrench:`.
    - `eta_updated` → `:calendar:`.
    - `status_changed` (e.g., `New` → `In Progress` via dispatcher) → `:arrows_counterclockwise:`.
    - `resolved` with `new_status='Resolved'` → `:white_check_mark:`, text reads "back in service".
    - `resolved` with `new_status='Closed - Duplicate'` → `:white_check_mark:`, text reads "closed: Closed - Duplicate" (NOT "back in service").
    - `resolved` with `new_status='Closed - No Issue Found'` → same closure-text behavior.

**Admin toggle:**

13. As Staff, navigate to **Admin → App Configuration**. Toggle off "Repair status changed (open transitions)", save. Now perform an open-status transition via the dispatcher → verify no Slack notification posts. Toggle back on; verify subsequent transitions resume notifying.

**`/esb-update` regression:**

14. `/esb-update <id>` opens the existing full-edit modal unchanged.

---

## 10. Authentication and Role-Based Access Control

**Role:** All roles

**Steps:**

1. While logged out, attempt to access `/repairs/queue`. Verify redirect to login page.
2. While logged out, access `/public/` and `/public/equipment/<id>`. Verify no login required.
3. Log in as a Technician. Verify you cannot access `/admin/users` or `/admin/areas` (403 or redirect).
4. Verify the Technician can access `/repairs/queue`, `/repairs/<id>`, and `/equipment/`.
5. Log in as a Staff user. Verify full access to admin pages, Kanban board, equipment management, and repair operations.
6. As Staff, navigate to `/admin/config` and toggle a notification setting (e.g., disable "ETA Updated" notifications). Trigger the event and verify no notification is sent.

**Expected Results:**

- Authenticated routes redirect to login when accessed without a session.
- Public routes are accessible without authentication.
- Technicians are restricted from admin functions but have full repair and equipment view access.
- Staff have unrestricted access to all application features.
- Notification configuration changes take effect immediately.

---

## 11. QR Code Label Generation

**Role:** Technician or Staff (authenticated)

**Steps:**

1. Confirm `ESB_BASE_URL` is set in the server environment (e.g., `http://esb.example.com:8080`).
2. Log in and navigate to any non-archived equipment's detail page (`/equipment/<id>`).
3. Verify the "Generate QR Code" button is enabled (not greyed out).
4. Click the button to open `/equipment/<id>/qr`.
5. Select each size preset in turn (1"–4" stickers, Avery 5160, Avery 5163, US Letter) and verify the live preview updates to match.
6. Select each **Printer / device** preset in turn (Laser/Inkjet 300/600/1200 dpi, Thermal Label 203 dpi, Brother P-Touch 180 dpi) and verify the live preview updates.
7. Toggle the "Include equipment name" and "Include target URL" checkboxes and verify the preview updates accordingly.
8. For each device preset, download a label and confirm the PNG's pixel dimensions equal `int(size_inches × device_dpi + 0.5)` — e.g. a 4" sticker at Thermal Label (203 dpi) → 812×812 px; at Laser/Inkjet (1200 dpi) → 4800×4800 px.
9. Confirm the PNG embeds matching DPI metadata. With ImageMagick: `identify -verbose file.png | grep Resolution`. Dependency-free: `python -c "from PIL import Image; print(Image.open('file.png').info['dpi'])"`. Note that a 203 dpi label reports approximately `(202.9968, 202.9968)` — this is expected rational rounding, not a bug.
10. Confirm a 4" label at **Thermal Label (203 dpi)** prints full-size (no clipping) on a 203-dpi thermal printer, and that selecting **US Letter** at **Laser/Inkjet (1200 dpi)** shows a friendly "too large to render" error instead of downloading.
11. Print (or view at actual size) a downloaded label and scan it with a phone camera.
12. At the default Laser/Inkjet (300 dpi) device, download the US Letter preset and verify the PNG is 2550×3300 px.
13. Stop the server, unset `ESB_BASE_URL`, restart, and reload the equipment detail page.
14. On an archived equipment item, confirm the QR button does not render and that `GET /equipment/<id>/qr` returns 404.

**Expected Results:**

- The live preview on `/equipment/<id>/qr` reflects size, device, and label-content options in real time.
- Scanning the downloaded/printed QR code resolves to `${ESB_BASE_URL}/public/equipment/<id>`.
- Rendered PNG dimensions match the selected size × device DPI (e.g., at the default Laser/Inkjet 300 dpi device, US Letter → 2550×3300 px), and the PNG carries embedded DPI metadata matching the selected device.
- US Letter at Laser/Inkjet (1200 dpi) is rejected with a friendly "too large" danger message rather than rendering.
- When `ESB_BASE_URL` is unset, the "Generate QR Code" button renders as disabled with tooltip "ESB_BASE_URL not configured"; hitting the route directly redirects to the equipment detail page with a danger flash describing the validation failure.
- Invalid `ESB_BASE_URL` values (non-http(s) schemes, embedded credentials, whitespace, paths/queries/fragments) are rejected with a specific flashed error instead of being rendered into the QR payload.
- Archived equipment hides the QR button and the QR route returns 404.
