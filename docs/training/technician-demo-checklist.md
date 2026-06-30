# Technician Demo Checklist

Talking/demo points to hit when training technicians hands-on instead of using
the slide deck (`technicians.md`). Demo each live where you can.

- **Network access** — web UI + QR on WiFi **or over VPN** if you have access; Slack anywhere. Triage from home via VPN/Slack.
- **Log in** — staff-created account, temp password via Slack DM; **change your password first**; you land on the Repair Queue.
- **Status is derived** — from open repairs (Down→🔴, Degraded/Not Sure→🟡, none→🟢); close them all and it goes green automatically.
- **Repair Queue** — default sort Down-first/oldest; filters Area · Status · Assignee (All/Mine/Unassigned); inline **Claim** and **Resolve**; shareable filtered URLs; mobile = stacked cards.
- **Repair record** — read the **timeline first** (institutional memory); add notes; upload diagnostic photos.
- **Edit screen** — batch status / severity / assignee / ETA / specialist description / duplicate, save once; **set an ETA** on anything waiting.
- **The status workflow** — walk New → Assigned → In Progress → Parts (Needed/Ordered/Received) → Needs Specialist → Resolved; plus Closed–No Issue / Closed–Duplicate.
- **Create a record (web)** — Equipment page → Report Issue (pre-selects), or Repairs → New.
- **Equipment registry & docs** — browse, filter, Export CSV, pull up manuals mid-repair; add docs if staff enabled it.
- **Slack `/esb-repair`** — no arg = dispatcher (claim / set ETA / set status / resolve-with-note, no ID needed); with an equipment name = create a record.
- **Slack notifications** — posted to area channel + `#oops`; emoji legend (🚨 ⚠️ SAFETY 🔧 🔄 👤 📅 ✅ ❌); replies are private to you.
- **When to use the web instead of Slack** — changing severity, reassigning, specialist notes, photos, multi-field edits.
