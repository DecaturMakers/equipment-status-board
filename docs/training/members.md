---
marp: true
theme: default
paginate: true
size: 16:9
html: true
title: "ESB — Member Training"
footer: "Equipment Status Board · Member Training"
---

<!--
RENDER:  npx @marp-team/marp-cli docs/training/members.md --html --allow-local-files -o members.pdf
         (swap -o members.html or members.pptx for other formats)
Images live in ../images relative to this file.
PRESENTER: fill in the ESB web address posted in your space (the
  bracketed blanks on the dashboard slide).
-->

<style>
:root{
  --blue:#0d6efd; --ink:#1f2937; --muted:#6b7280;
  --green:#198754; --yellow:#b8860b; --red:#dc3545;
}
section{ font-size:25px; padding:48px 60px; color:var(--ink); }
section.lead{ justify-content:center; text-align:center; }
section.lead h1{ font-size:60px; color:var(--blue); margin-bottom:4px; }
section.lead h3{ color:var(--muted); font-weight:400; margin-top:0; }
h1{ color:var(--blue); font-size:38px; margin-bottom:8px; }
h2{ color:var(--ink); font-size:32px; border-bottom:3px solid var(--blue); padding-bottom:6px; }
ul{ line-height:1.4; }
ul ul{ font-size:0.9em; }
strong{ color:#111827; }
code{ background:#111827; color:#e5e7eb; padding:2px 8px; border-radius:6px; font-size:0.9em; }
.cmd{ display:inline-block; background:#111827; color:#fff; font-family:monospace;
      padding:5px 12px; border-radius:8px; }
blockquote{ border:1px solid #d1d5db; border-left:5px solid var(--blue); border-radius:8px;
            padding:10px 18px; background:#f9fafb; font-size:0.82em; color:#111827; }
blockquote p{ margin:4px 0; }
.chips span{ display:inline-block; color:#fff; font-weight:700; padding:4px 14px;
             border-radius:16px; margin:0 8px 6px 0; font-size:0.8em; }
.green{ background:var(--green);} .yellow{ background:var(--yellow);} .red{ background:var(--red);}
.access{ border:2px solid var(--blue); border-radius:10px; padding:12px 20px;
         background:#eef4ff; font-size:0.9em; }
.note{ color:var(--muted); font-size:0.8em; }
table{ font-size:0.86em; }
</style>

<!-- _class: lead -->

# Equipment Status Board
### Member Training

Check equipment before you use it · Report problems in seconds

<!-- Presenter: 10–15 min. Audience = any member, no account needed. Emphasize: ESB tells you if a tool works BEFORE you walk over, and reporting a problem takes 30 seconds. -->

---

## Why ESB exists

- **One place** to see whether any tool in the space is working — *before* you start a project
- Tracks every machine's status and the repairs in flight
- **Three ways to use it**, no account required:
  - 🖥️ **Web dashboard** — full status board in your browser
  - 📺 **Kiosk screens** — wall displays around the space
  - 📱 **QR stickers** — scan a specific machine
- Plus **Slack** for status checks and reporting from anywhere

<!-- Members never log in. The whole member experience is read + report. -->

---

## The only thing you must remember: the colors

<div class="chips">
<span class="green">✓ Operational</span>
<span class="yellow">! Degraded</span>
<span class="red">✗ Down</span>
</div>

| Color | Status | What it means |
|-------|--------|----------------|
| 🟢 Green | **Operational** | No known issues — good to go |
| 🟡 Yellow | **Degraded** | Works, but has a known problem (or not yet assessed) — use with care |
| 🔴 Red | **Down** | Not usable — **do not run it** |

- Status is **live** — it reflects the open repair reports right now

---

## Where each tool works 📶

<div class="access">

**Slack works anywhere** — your phone, home, on the road.

The **web dashboard and QR pages live on the makerspace network** — you must be **on WiFi** for those links to open.

</div>

- Scanning a QR sticker off-network → the page **won't load**. That's expected.
- Off-site and need status? Use **Slack** (next-to-last section).

<!-- Presenter: members do NOT get VPN — that's technicians only. -->

---

## Status Dashboard (web)

![bg right:54% fit](../images/status-dashboard-anon.png)

- Open the ESB web address in any browser — **no login**
- Every tracked machine, **grouped by area**
- Color-coded cards; non-green cards show the **issue + ETA**
- Bookmark it on your phone

<p class="note">Web address: [ posted in the space / ask staff ]</p>

---

## Kiosk Displays (in the space)

![bg right:52% fit](../images/kiosk-display.png)

- Large wall-mounted screens you can read across the room
- **Auto-refreshes** — always current
- Nothing to tap — **just look up** before you head to a tool

---

## QR Codes — scan a specific machine 📱

![bg right:34% fit](../images/qr-equipment-page-mobile.png)

- Every machine has a **QR sticker**
- Point your **phone camera** at it → tap the link (no app)
- Opens that machine's page showing:
  - Name + area, and a **big status indicator**
  - The current **issue** if it's not green
  - **Known Issues** already being worked
  - **Equipment Info** → manuals & docs

<p class="note">Reminder: you must be on WiFi for the link to open.</p>

---

## Before you report: check Known Issues

![bg right:34% fit](../images/qr-equipment-page-mobile.png)

- The QR page lists any **open repairs** for that machine
- If your problem is **already listed**, it's already in the queue — **no need to report again**
- Tap **Equipment Info & Documentation** for manuals, quick-starts, and training links staff have attached

---

## Reporting a Problem

![bg right:34% fit](../images/problem-report-form-mobile.png)

Found something broken and *not* already listed? Report it.

1. Scan the QR (or open the machine's page) → scroll to **Report a Problem**
2. Fill in:
   - **Your name** *(required)* · **Description** *(required)*
   - **Severity** — Down / Degraded / Not Sure
   - **Safety risk?** checkbox · optional **photo**
3. Tap **Submit Report**

---

## What happens after you report

![bg right:34% fit](../images/report-confirmation-mobile.png)

- A **repair record** is created instantly
- Status updates **everywhere** — dashboard, kiosk, QR page
- Technicians are **notified in Slack**
- Confirmation page tells you **which Slack channel** to follow for progress
- Re-scan the QR anytime to see the current repair status

---

## Slack — check status from anywhere

Type these in **any** Slack channel:

- <span class="cmd">/esb-status</span> — summary of every area
- <span class="cmd">/esb-status Woodshop</span> — full detail for one area
- <span class="cmd">/esb-status SawStop</span> — one specific machine

> *Equipment Status*
> *Woodshop* — ✅ 4   ⚠️ 1   ❌ 0
>   • ⚠️ DeWalt Planer — snipe on last 2″ *(ETA Jul 4)*
> *Laser / CNC* — ✅ 1   ⚠️ 1   ❌ 1
>   • ❌ Shapeoko CNC — Z-axis losing steps
> _Tip: /esb-status &lt;area&gt; for one-area detail_

<p class="note">Replies are only visible to you. Works off-network — Slack is in the cloud.</p>

---

## Slack — report a problem

- Type <span class="cmd">/esb-report</span> in any channel
- A **form pops up** — same fields as the web form:
  - Equipment · Your Name · Description · Severity · Safety risk
- Submit → instant confirmation with the **repair number**

> 🚨 *New problem report* — **Shapeoko CNC** (Laser / CNC)
> Severity: ❌ Down · reported by Jordan Lee
> Repair #42 created.

<p class="note">Great when you're not on WiFi, or already chatting in Slack.</p>

---

## Recap — your member cheat sheet

- 🟢🟡🔴 **Green good · Yellow caution · Red do-not-use**
- **Check first:** web dashboard, kiosk screens, or scan the QR
- **Report fast:** QR page form, or <span class="cmd">/esb-report</span> in Slack
- **From anywhere:** <span class="cmd">/esb-status</span> and <span class="cmd">/esb-report</span> in Slack
- 📶 Web + QR need **WiFi**; Slack works everywhere
- ✅ Check **Known Issues** before reporting a duplicate

<p class="note">More help: the <strong>Help / Docs</strong> link on the status page → Members Guide. Questions? Ask any staff member.</p>
