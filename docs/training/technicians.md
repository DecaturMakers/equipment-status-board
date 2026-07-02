---
marp: true
theme: default
paginate: true
size: 16:9
html: true
title: "ESB — Technician Training"
footer: "Equipment Status Board · Technician Training"
---

<!--
RENDER:  npx @marp-team/marp-cli docs/training/technicians.md --html --allow-local-files -o technicians.pdf
         (swap -o technicians.html or technicians.pptx for other formats)
Images live in ../images relative to this file.
PRESENTER: fill in the ESB web address posted in your space.
-->

<style>
:root{
  --blue:#0d6efd; --ink:#1f2937; --muted:#6b7280;
  --green:#198754; --yellow:#b8860b; --red:#dc3545;
}
section{ font-size:24px; padding:46px 58px; color:var(--ink); }
section.lead{ justify-content:center; text-align:center; }
section.lead h1{ font-size:58px; color:var(--blue); margin-bottom:4px; }
section.lead h3{ color:var(--muted); font-weight:400; margin-top:0; }
h1{ color:var(--blue); font-size:36px; margin-bottom:8px; }
h2{ color:var(--ink); font-size:30px; border-bottom:3px solid var(--blue); padding-bottom:6px; }
ul{ line-height:1.38; }
ul ul{ font-size:0.9em; }
strong{ color:#111827; }
code{ background:#111827; color:#e5e7eb; padding:2px 8px; border-radius:6px; font-size:0.88em; }
.cmd{ display:inline-block; background:#111827; color:#fff; font-family:monospace;
      padding:5px 12px; border-radius:8px; }
blockquote{ border:1px solid #d1d5db; border-left:5px solid var(--blue); border-radius:8px;
            padding:10px 18px; background:#f9fafb; font-size:0.8em; color:#111827; }
blockquote p{ margin:4px 0; }
.chips span{ display:inline-block; color:#fff; font-weight:700; padding:4px 14px;
             border-radius:16px; margin:0 8px 6px 0; font-size:0.8em; }
.green{ background:var(--green);} .yellow{ background:var(--yellow);} .red{ background:var(--red);}
.access{ border:2px solid var(--blue); border-radius:10px; padding:12px 20px;
         background:#eef4ff; font-size:0.88em; }
.note{ color:var(--muted); font-size:0.8em; }
table{ font-size:0.8em; }
</style>

<!-- _class: lead -->

# Equipment Status Board
### Technician Training

Work the repair queue from the web or from Slack

<!-- Presenter: 25–30 min. Audience = volunteer repair techs with accounts. They already know the member-facing basics; this deck is the repair workflow + tech Slack commands. -->

---

## What's different for you

- You have an **account** — everything members do, **plus** the repair workflow
- Your home base is the **Repair Queue**
- You can do most day-to-day work from **Slack** — claim, set ETA, change status, resolve
- Deeper edits (severity, reassign, multi-field) happen in the **web UI**

<p class="note">Roles: <strong>technician</strong> = repairs + equipment. <strong>staff</strong> = all that + create/edit equipment and admin. Staff inherits every technician ability.</p>

---

## Where the tools work 📶 (important for you)

<div class="access">

**Slack works anywhere.** Use it when you're off-site.

The **web UI and QR pages are on the makerspace network** — reach them **on WiFi**, **or over VPN** if you have access.

</div>

- This is the technician advantage: triage and update repairs **from home via VPN or Slack**
- A QR sticker scanned off-network still won't open unless you're on VPN

<!-- Presenter: members do NOT get VPN — that access is technicians only. -->

---

## Logging in

![bg right:48% fit](../images/login-page.png)

- Staff create your account; you get a **temporary password** (usually via **Slack DM**)
- Go to the ESB web address → enter **username + password**
- First thing: **Change Password** (top-right nav)
- After login you land on the **Repair Queue**

<p class="note">No self-signup. Forgot your password? A staff member resets it.</p>

---

## Status & severity — how the colors are computed

<div class="chips">
<span class="green">✓ Operational</span>
<span class="yellow">! Degraded</span>
<span class="red">✗ Down</span>
</div>

- Equipment status is **derived live** from its **open repair records** — never set by hand
- It reflects the **highest-severity open repair**:

| Severity you set | Equipment shows |
|---|---|
| **Down** | 🔴 Down |
| **Degraded** | 🟡 Degraded |
| **Not Sure** | 🟡 Degraded |
| *(no open repairs)* | 🟢 Operational |

- Close every open repair and the machine returns to **green** automatically

---

## The Repair Queue

![bg right:50% fit](../images/repair-queue-desktop.png)

- Default sort: **Down first, then oldest** — top = most urgent
- **Filters:** Area · Status · Assignee (**All / Mine / Unassigned**)
- Click a column to sort; click a row to open the record
- Inline quick actions:
  - **Claim** — on `New` items → assigns you, moves to `Assigned`
  - **Resolve** — opens a note prompt, sets `Resolved`

<p class="note">Filtered URLs are shareable/bookmarkable: <code>?area=</code>, <code>?status=</code>, <code>?assignee=me</code></p>

---

## The Queue on your phone

![bg right:34% fit](../images/repair-queue-mobile.png)

- Rows become **stacked cards** — equipment, severity, status, area, age
- Built for **one-handed** use at the workbench
- Same Claim / Resolve actions
- On WiFi or VPN, this is your shop-floor triage view

---

## The Repair Record

![bg right:48% fit](../images/repair-record-detail.png)

- Top: equipment, status, severity, assignee, description
- **Add a Note** — what you found, tried, ordered
- **Upload a diagnostic photo/video**
- **Timeline** below = the **institutional memory**:
  - every status / severity / assignee / ETA change + notes + photos, with who & when

<p class="note">Read the timeline first — don't redo diagnosis someone already did.</p>

---

## Working a repair — the Edit screen

- One **Edit** form changes everything; batch it and **save once**:
  - **Status** · **Severity** · **Assignee** · **ETA** · **Specialist description** · **Duplicate-of**
- Every change writes a **timeline entry** automatically
- Quick paths for the two common actions (no full edit needed):
  - **Claim** → assigns you (and `New` → `Assigned`)
  - **Resolve** → requires a note, sets `Resolved`
- Set an **ETA** on anything waiting — it shows on the dashboard and tells everyone when to expect the tool back

---

## The repair workflow — statuses

| Status | Use it when… |
|---|---|
| **New** | Just reported, not yet assessed *(starting point)* |
| **Assigned** | You've taken ownership (Claim does this) |
| **In Progress** | Actively diagnosing / fixing |
| **Parts Needed** | Diagnosed; parts must be sourced |
| **Parts Ordered** | Ordered — note order + ETA |
| **Parts Received** | In hand, ready to install |
| **Needs Specialist** | Beyond current skills/tools — note what's needed |
| **Resolved** | Fixed, back in service |
| **Closed – No Issue Found** | Couldn't reproduce a problem |
| **Closed – Duplicate** | Tracked elsewhere — link the other record |

<p class="note">First 7 are "open" (and are the Kanban columns); last 3 are closed and clear the status.</p>

---

## Creating a repair record (web)

![bg right:50% fit](../images/create-repair-form-desktop.png)

- **Equipment page → Report Issue** — opens this form with the **equipment pre-selected**
- Or **Repairs → New** and pick the equipment
- Required: **Equipment + Description**; optional severity / assignee / safety / consumable
- Save → you're taken to the new record

<p class="note">Members' reports land here too, as <code>New</code>.</p>

---

## Equipment registry & docs

![bg right:50% fit](../images/equipment-registry-desktop.png)

- **Equipment** nav → browse everything, filter by area, **Export CSV**
- Open any item for specs, **manuals, photos, and links**
- Pull up the manual mid-repair from your phone
- If staff enable **technician doc editing**, you can add manuals / photos / links you find

<p class="note">Creating, editing, or archiving equipment itself is staff-only.</p>

---

## Slack — three commands

| Command | Who | What |
|---|---|---|
| <span class="cmd">/esb-status</span> | anyone | Check status — all areas, one area, or one machine |
| <span class="cmd">/esb-report</span> | anyone | Quick member-style problem report |
| <span class="cmd">/esb-repair</span> | **tech/staff** | Your work command — dispatcher + create record |

- Slack maps you to your ESB account by **email**, and re-checks your role at every step
- This is how you stay on top of repairs **off-network**

---

## Slack — `/esb-repair` with no argument (dispatcher)

- Type <span class="cmd">/esb-repair</span> → modal lists **open repairs grouped by area**
- Pick one → **Continue** → choose one **Action**:

> ○ **Claim (assign to me)** — `New` → `Assigned`, else just sets assignee
> ○ **Set ETA** — pick a date
> ○ **Set Status** — In Progress / Closed – Duplicate / Closed – No Issue Found
> ○ **Resolve with Note** — note required → `Resolved`

- **No repair ID needed** — easiest path for routine in-Slack updates

---

## Slack — `/esb-repair <equipment>` (create)

- Type <span class="cmd">/esb-repair Shapeoko</span> → **create-record modal** opens
- Exact name match → equipment **pre-selected**; otherwise pick from the dropdown
- Fill description, severity, assignee, status → submit

> ✅ Repair #43 created for **Shapeoko CNC** (Laser / CNC)

<p class="note">An argument always means "create". No argument always means the dispatcher.</p>

---

## Slack — notifications you'll see

Posted to the equipment's **area channel** + cross-posted to **#oops**:

- 🚨 new report ·   ⚠️ **SAFETY RISK** prefix
- 🔧 severity changed ·   🔄 status changed ·   👤 assignee changed
- 📅 ETA set/changed ·   ✅ resolved / closed ·   ❌ error

<p class="note">Direct messages are only used to deliver your temporary password. Slash-command replies are private (ephemeral) to you.</p>

---

## When you still need the web UI

Slack covers claim / ETA / status / resolve / create. Use the **web record** for:

- Changing **severity**
- **Reassigning** to someone else
- Setting a **specialist description**
- **Uploading diagnostic photos**
- Editing **several fields at once**

<p class="note">Rule of thumb: quick updates in Slack, detailed work on <code>/repairs/&lt;id&gt;</code> in the browser.</p>

---

## Recap — technician cheat sheet

- **Log in → Repair Queue.** Change your temp password first.
- **Triage:** Down-first, oldest-first; filter to **Mine** / **Unassigned**
- **Claim → work → note everything → Resolve** (note required)
- Status is **derived** from open repairs; close them and it goes green
- **Slack <span class="cmd">/esb-repair</span>** for off-network claim/ETA/status/resolve
- 📶 Web + QR on **WiFi or VPN**; Slack anywhere
- **Read the timeline** before you start

<p class="note">Full reference: Help / Docs → Technicians Guide.</p>
