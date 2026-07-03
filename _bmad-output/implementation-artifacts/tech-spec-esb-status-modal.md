---
title: '/esb-status Modal with Per-Area Detail'
slug: 'esb-status-modal'
created: '2026-07-03'
status: 'completed'
stepsCompleted: [1, 2, 3, 4, 5, 6]
tech_stack: [Python 3.14, Flask, slack-bolt 1.27, Block Kit, pytest]
files_to_modify: [esb/slack/handlers.py, esb/slack/forms.py, tests/test_slack/test_handlers.py, tests/test_slack/test_forms.py]
code_patterns: [views_open on command ack, views_update on button action, _ensure_app_context wrapper, Block Kit builders in forms.py]
test_patterns: [_register_and_capture harness, MagicMock ack/client/body, per-class autouse setup fixture, factory helpers _create_area/_create_equipment/_create_repair_record]
---

# Tech-Spec: /esb-status Modal with Per-Area Detail

**Created:** 2026-07-03

## Overview

### Problem Statement

The UX for the `/esb-status` Slack command is confusing (GitHub issue #70). The
slash command is available anywhere, but the bot replies with an **ephemeral
message** via `chat_postEphemeral`. Two problems follow:

1. The bot can only post responses in channels it is a member of.
2. Less-experienced Slack users are confused by ephemeral ("Only visible to
   you") messages appearing in a channel.

### Solution

Rework the `/esb-status` handler to open a **modal** (`client.views_open`) that
shows the equipment status summary. Each area gets a **"View details" button**;
clicking it swaps the modal in place (`client.views_update`) to that area's
detailed status, which includes a **"Back to summary"** button.

### Scope

**In Scope:**
- Replace the ephemeral reply with a modal opened via `views_open`.
- Summary modal: one section per non-empty area with a "View details" button
  accessory (per-area buttons, not a dropdown).
- Area-detail modal view (reachable by button) + "Back to summary" navigation
  via `views_update`.
- Preserve the text-argument shortcut: `/esb-status <name>` opens the modal
  directly on the matched result.
- New Block Kit builders in `esb/slack/forms.py` and new `@bolt_app.action`
  handlers in `esb/slack/handlers.py`.

**Out of Scope:**
- Equipment-level detail as its own modal level (area detail already lists each
  item's status). Area-level detail only.
- Any change to `status_service` data functions
  (`get_area_status_dashboard`, `get_single_area_status_dashboard`).
- Any change to the web dashboard, kiosk, or static-page rendering.
- Reworking other slash commands.

## Context for Development

### Codebase Patterns

- **Modal open pattern:** `/esb-reserve` (`handlers.py:77-95`) and `/esb-report`
  (`handlers.py:389-407`) call `ack()` first, then
  `client.views_open(trigger_id=body['trigger_id'], view=<block-kit dict>)`.
  `trigger_id` is valid ~3s, so the dashboard query must run between `ack()` and
  `views_open` (it does today — one `get_area_status_dashboard()` call).
- **In-place modal update pattern:** button actions registered with
  `@bolt_app.action('<action_id>')` call `ack()` then
  `client.views_update(view_id=body['view']['id'], view=<new view>)`. The action
  reads its payload value from `body['actions'][0]['value']` — see
  `reservation_start_reserve` (`handlers.py:97-127`).
- **App context:** every handler body that touches DB/services must be wrapped
  in `with _ensure_app_context(app):` (`handlers.py:11-27`). `_resolve_esb_user`
  and `forms.py` builders assume they're already inside such a wrapper.
- **Block Kit builders** live in `esb/slack/forms.py` (e.g.
  `build_problem_report_modal`, `build_repair_dispatcher_modal`). Slack caps
  modal titles at 24 chars and button/option text at 75 — truncate explicitly
  where needed (only `build_repair_action_modal` currently does, at
  `forms.py:633`; the other builders happen to use short static titles). (F8)
- **Button pattern precedent:** `reservation_forms.py` renders buttons inside
  **`actions` blocks** (via the `_button(text, action_id, value, style, url)`
  helper at `reservation_forms.py:83`), each in a uniquely-identified block such
  as `reservation_tool_{id}_actions_block` (`reservation_forms.py:143-146`).
  Note: **no `section`-with-`accessory` button exists anywhere in the codebase**
  (`grep -rn accessory esb/` returns nothing). A `section` with a `button`
  accessory *is* valid Block Kit, but it is a NEW pattern here (F4) — see Task 1
  for the chosen approach and the `block_id` requirement (F5).
- **Existing text formatters** (`format_status_summary`,
  `format_area_status_detail`, `format_equipment_status_detail`,
  `format_equipment_list`) are used **only** by the `/esb-status` handler.
  After the rework: `format_area_status_detail` is reused inside
  `build_area_status_modal`, and `format_status_summary`'s per-area logic is
  shared via the extracted `_area_summary_mrkdwn` helper. The error fallback is
  a static string — it does NOT call these formatters. That leaves
  `format_equipment_status_detail` and `format_equipment_list` unused, and
  `status_service.get_equipment_status_detail` (its only caller is the old
  handler, `handlers.py:625`) also becomes unreferenced (G3). Since
  `status_service` is out of scope, leave `get_equipment_status_detail` as-is;
  the two dead `forms.py` formatters are optional cleanup — see Notes.

### Test Harness (critical for writing tests)

- `tests/test_slack/test_handlers.py` uses `_register_and_capture(app)`
  (lines 13-42): a `MagicMock` Bolt app whose `.command/.view/.action`
  decorators capture handler fns into a dict keyed
  `command:/esb-status`, `action:<id>`, `view:<callback_id>`.
- Handlers are invoked directly:
  `handlers['command:/esb-status'](ack=ack, body=body, client=client)` with
  `MagicMock()` for `ack`/`client`. Assertions inspect
  `client.views_open.call_args.kwargs['view']` /
  `client.views_update.call_args.kwargs['view']`.
- Data factories: `_create_area`, `_create_equipment`, `_create_repair_record`,
  `_create_user` (imported from `tests.conftest`). Forms tests use fixtures
  `make_area`, `make_equipment`, `make_repair_record`.

### Files to Reference

| File | Purpose |
| ---- | ------- |
| esb/slack/handlers.py | `handle_esb_status` (596-639) to rewrite; add `@bolt_app.action` handlers for view-area + back-to-summary |
| esb/slack/forms.py | Add `build_status_summary_modal` + `build_area_status_modal`; existing formatters (20-162) |
| esb/slack/reservation_forms.py | Reference: `_button` helper (83), views_open/views_update flow |
| esb/services/status_service.py | `get_area_status_dashboard()` (186) and `get_single_area_status_dashboard(area_id)` (288) — used unchanged; latter raises `AreaNotFound`/`AreaArchived` |
| esb/utils/exceptions.py | Canonical home of `AreaNotFound` / `AreaArchived` (27-36); `AreaArchived` subclasses `AreaNotFound` — import from here (G1), not the `status_service` re-export |
| esb/services/equipment_service.py | `get_area_by_name` (43), `search_equipment_by_name` (441) — used unchanged for the text-arg path |
| tests/test_slack/test_handlers.py | `TestEsbStatusCommand` (1143-1361) — rewrite for modal assertions; `_register_and_capture` (13) |
| tests/test_slack/test_forms.py | `TestFormatStatusSummary` (261), `TestFormatAreaStatusDetail` (417) — add modal-builder tests |

### Technical Decisions

- **Per-area buttons** (confirmed): each area section in the summary modal has a
  "View details" **button accessory** with `action_id='esb_status_view_area'`
  and `value=str(area.id)`. A single shared action_id keyed off the value is
  fine, **but each area section MUST carry a distinct `block_id`** (e.g.
  `f'esb_status_area_{area.id}_block'`) so the reused action_id is never
  ambiguous — mirroring how the reservation buttons live in per-item
  `reservation_tool_{id}_actions_block` blocks (F5).
- **Back navigation** (confirmed): area-detail modal has a "Back to summary"
  button (`action_id='esb_status_back_to_summary'`); its handler re-queries the
  dashboard and `views_update`s back to the summary. No `private_metadata`
  needed — both views rebuild from a fresh query.
- **Text-arg behavior** (confirmed, "preserve"): resolve arg the same way the
  current handler does — `get_area_by_name(arg)` first (area takes precedence),
  then `search_equipment_by_name(arg)`. Open the modal directly on:
  - area match → that area's detail view;
  - exactly one equipment match → **that equipment's area** detail view
    (area-detail only, no equipment-level modal). If resolving that area raises
    `AreaNotFound`/`AreaArchived` (the matched tool's area is archived), fall
    back to the **summary view**, not an error (F3);
  - no match or multiple matches → the summary view (no error text needed; the
    summary is a safe landing).
- **Area detail only** (confirmed): no equipment-level modal drill-down.
- **Error fallback (F1/F2):** wrap the handler body in try/except; on a genuinely
  unexpected exception, fall back to `client.chat_postEphemeral(channel=
  body['user_id'], user=body['user_id'], text=<error>)`. **Post to the user's DM
  (`body['user_id']`), NOT `body['channel_id']`** — the whole point of this
  feature is that the bot cannot post into channels it is not a member of, so a
  `channel_id` ephemeral would fail silently in exactly the scenario we're
  fixing (repair handlers already DM `body['user']['id']`, `handlers.py:459,591`).
  Note the deep-link `AreaArchived`/`AreaNotFound` cases above are NOT errors —
  they route to the summary view before this fallback is ever reached.
- **Block limits:** modals allow ≤100 blocks and ≤3000 chars per section text.
  Summary renders one section per non-empty area (fine for makerspace scale).
  Area detail reuses `format_area_status_detail` output as one section's mrkdwn.

## Implementation Plan

Do the tasks in order. Tasks 1-2 are pure additive builders (no behavior change
until Task 3 wires them in), so the suite stays green between commits.

- [x] **Task 1: Add `build_status_summary_modal(dashboard_data)` to `esb/slack/forms.py`**
  - File: `esb/slack/forms.py`
  - Action: Add a builder that returns a Block Kit **modal** view dict for the
    equipment status summary.
  - Details:
    - Signature: `def build_status_summary_modal(dashboard_data):`
    - `type: 'modal'`, `callback_id: 'esb_status_summary'`,
      `title: {'type': 'plain_text', 'text': 'Equipment Status'}`,
      `close: {'type': 'plain_text', 'text': 'Close'}` (no `submit` — this modal
      is navigation-only, not a form).
    - Empty case: if `dashboard_data` is falsy or every area has no equipment
      (mirror the `format_status_summary` guard at `forms.py:37`), return a modal
      with a single section `'No equipment has been registered yet.'`.
    - First block: a `section` with mrkdwn `:bar_chart: *Equipment Status Summary*`.
    - For each area in `dashboard_data` where `area_data['equipment']` is
      non-empty (skip empty areas, matching current summary behavior):
      - Compute green/yellow/red counts (reuse the loop at `forms.py:48-51`).
      - Build one `section` block with a **distinct `block_id`**
        `f'esb_status_area_{area.id}_block'` (F5 — required so the shared
        `action_id` is unambiguous) whose mrkdwn text is the count line
        (`*{area.name}* — {g} :white_check_mark: operational, {y} :warning:
        degraded, {r} :x: down`) followed, on their own lines, by one bullet per
        **non-green** item (`• {emoji} *{name}* — {truncated desc} (ETA: ...)`,
        reusing `_STATUS_EMOJI`, `_truncate`, `_NON_GREEN_DESC_TRUNCATE` and the
        ETA formatting from `forms.py:60-74`).
      - Attach an `accessory` button to that section (NEW pattern — no existing
        section accessory in the codebase; see Codebase Patterns note):
        `{'type': 'button', 'text': {'type': 'plain_text', 'text': 'View details'},
        'action_id': 'esb_status_view_area', 'value': str(area.id)}`.
    - To avoid duplicating logic, extract **only the per-area line-building**
      from `format_status_summary` into a module-private helper (e.g.
      `_area_summary_mrkdwn(area_data) -> str` returning the count-line + bullets
      for one area) and call it from BOTH `format_status_summary` and
      `build_status_summary_modal`. **The header line (`:bar_chart: *Equipment
      Status Summary*`, `forms.py:40`) and the trailing tip (`forms.py:76-77`)
      stay in `format_status_summary`, NOT in the shared helper** (F11) — they
      are outside the per-area loop, and moving them would break the
      `'\n'.join` output. Keep `format_status_summary`'s output byte-identical
      (its tests at `test_forms.py:261-415` must still pass).
  - Notes: Section mrkdwn cap is 3000 chars; makerspace areas stay well under.
    Modal block cap is 100; one section per non-empty area is safe.

- [x] **Task 2: Add `build_area_status_modal(area_data)` to `esb/slack/forms.py`**
  - File: `esb/slack/forms.py`
  - Action: Add a builder returning the area-detail **modal** view dict.
  - Details:
    - Signature: `def build_area_status_modal(area_data):` where `area_data` has
      the shape `{'area': Area, 'equipment': [...]}` returned by
      `get_single_area_status_dashboard()` (one entry of the dashboard list).
    - `type: 'modal'`, `callback_id: 'esb_status_area_detail'`,
      `title: {'type': 'plain_text', 'text': area.name[:24]}`,
      `close: {'type': 'plain_text', 'text': 'Close'}`.
    - Blocks:
      1. A `section` whose mrkdwn is `format_area_status_detail(area_data)` (reuse
         the existing formatter for byte-identical detail text).
      2. A `divider`.
      3. An `actions` block containing one button:
         `{'type': 'button', 'text': {'type': 'plain_text', 'text': '⬅ Back to summary'},
         'action_id': 'esb_status_back_to_summary', 'value': 'summary'}`.
  - Notes: `format_area_status_detail` already handles the empty-area case
    (`_No equipment in this area._`). Single-section detail text is under the
    3000-char cap at makerspace scale.

- [x] **Task 3: Rewrite `handle_esb_status` in `esb/slack/handlers.py` to open a modal**
  - File: `esb/slack/handlers.py` (replace body of `handle_esb_status`, 596-639)
  - Action: `ack()` first, then resolve the text arg, then `client.views_open`
    with the appropriate modal. Fall back to an ephemeral error on exception.
  - Details:
    - Keep `ack()` as the first statement and `search_term =
      body.get('text', '').strip()`.
    - Wrap the rest in `with _ensure_app_context(app):` and a `try/except`.
    - Inside try:
      - Import `status_service` and `equipment_service`.
      - Determine the initial view:
        - If `search_term` is empty → `view =
          build_status_summary_modal(status_service.get_area_status_dashboard())`.
        - Else, resolve the arg (preserve current precedence). Import the
          canonical exception with `from esb.utils.exceptions import
          AreaNotFound` (G1 — do NOT rely on the `status_service` re-export) so
          the deep-link resolution can distinguish "archived/missing area →
          summary" from a real failure. To keep both deep-link branches
          consistent (G4), resolve the target area id first, then share ONE
          guarded lookup:
          - `target_area_id = None`.
          - `area = equipment_service.get_area_by_name(search_term)`; if not None
            → `target_area_id = area.id`. (`get_area_by_name` returns only
            non-archived areas, so this normally won't raise — but the shared
            guard below still covers a rare archive-race.)
          - Else `matches = equipment_service.search_equipment_by_name(search_term)`;
            if exactly one match with an area → `target_area_id = match.area_id`.
          - Now resolve the view:
            - If `target_area_id is not None`: **try**
              `area_data = get_single_area_status_dashboard(target_area_id)` →
              `view = build_area_status_modal(area_data)`; **except `AreaNotFound`
              (parent of `AreaArchived`) → fall back to
              `build_status_summary_modal(get_area_status_dashboard())` (F3/G4)**.
              The matched area/tool is valid but its area is archived, so the
              summary is the safe landing, not an error — and BOTH deep-link
              branches (area-name and equipment) now handle this identically.
            - Else (no area match; zero, multiple, or area-less equipment
              matches) → `build_status_summary_modal(get_area_status_dashboard())`.
      - `client.views_open(trigger_id=body['trigger_id'], view=view)`.
    - `except Exception:` — `logger.warning('Error processing /esb-status
      command', exc_info=True)` then post to the **user's DM** (F1/F2):
      `client.chat_postEphemeral(channel=body['user_id'],
      user=body['user_id'], text=':x: An error occurred while checking equipment
      status. Please try again.')`.
  - Notes: The `AreaNotFound`/`AreaArchived` deep-link case is handled *inline*
    (routes to summary), NOT via the outer except — so a valid but
    archived-area tool never surfaces the error message. The outer except is for
    genuinely unexpected failures (DB down, Slack API error, `views_open`
    trigger_id expiry). Catch `AreaNotFound` (the parent class) to cover both it
    and `AreaArchived`.

- [x] **Task 4: Add the two `@bolt_app.action` handlers in `esb/slack/handlers.py`**
  - File: `esb/slack/handlers.py` (add inside `register_handlers`, near the
    `/esb-status` command handler)
  - Action: Handle the "View details" and "Back to summary" buttons with
    `views_update`.
  - Details:
    - Both handlers must, on error, `views_update` the open modal to a minimal
      error view — **do NOT** leave the "pick one" choice open (F7). Add a tiny
      local helper (mirroring `_update_reservation_error_modal`,
      `handlers.py:63-69`) that builds a close-only modal with a single section
      (e.g. `:x: Could not load equipment status. Please try again.`) and calls
      `client.views_update(view_id=body['view']['id'], view=<error modal>)`.
    - `@bolt_app.action('esb_status_view_area')` →
      `def handle_esb_status_view_area(ack, body, client):`
      - `ack()` first.
      - `with _ensure_app_context(app):` and `try/except`:
        - `area_id = int(body['actions'][0]['value'])`.
        - `area_data = status_service.get_single_area_status_dashboard(area_id)`.
        - `client.views_update(view_id=body['view']['id'],
          view=build_area_status_modal(area_data))`.
      - `except Exception:` → `logger.warning(...)` then `views_update` the modal
        to the error view via the helper above (keeps the open modal from going
        stale; no ephemeral, which could hit the channel-membership problem).
    - `@bolt_app.action('esb_status_back_to_summary')` →
      `def handle_esb_status_back_to_summary(ack, body, client):`
      - `ack()` first.
      - `with _ensure_app_context(app):` and `try/except` (F6 — same treatment as
        `view_area`; do NOT leave this handler unguarded):
        - `dashboard = status_service.get_area_status_dashboard()`.
        - `client.views_update(view_id=body['view']['id'],
          view=build_status_summary_modal(dashboard))`.
      - `except Exception:` → `logger.warning(...)` then `views_update` to the
        error view via the helper.
  - Notes: Action payloads put the clicked button under `body['actions'][0]`
    and the current view id under `body['view']['id']` (see
    `reservation_start_reserve`, `handlers.py:106,121-122`).

- [x] **Task 5: Rewrite `TestEsbStatusCommand` and add action-handler tests in `tests/test_slack/test_handlers.py`**
  - File: `tests/test_slack/test_handlers.py` (`TestEsbStatusCommand`, 1143-1361)
  - Action: Replace `chat_postEphemeral`-text assertions with `views_open`/
    `views_update` view assertions; add tests for the two action handlers.
  - Details (rewrite each existing case to the modal equivalent):
    - `test_handler_registered` — keep.
    - no-args → `client.views_open` called once; view `callback_id ==
      'esb_status_summary'`; a section text contains `Equipment Status Summary`.
    - area-name arg (`'woodshop'`) → `views_open` view `callback_id ==
      'esb_status_area_detail'`, title text `Woodshop`.
    - area precedence over equipment (`'Woodshop'` with a `Woodshop Helper`
      equipment present) → view is `esb_status_area_detail`, not a summary.
    - single equipment arg (`'SawStop'`) → `views_open` with
      `esb_status_area_detail` for SawStop's area (Woodshop).
    - multiple matches (`'Saw'`) → `views_open` with `esb_status_summary`
      (fallback), NOT an ephemeral list.
    - no match (`'NonexistentThing'`) → `views_open` with `esb_status_summary`.
    - empty dashboard (all equipment deleted) → `views_open` summary modal whose
      section says `No equipment`.
    - `ack` called before `views_open` (adapt `test_ack_called_before_response`
      to record order of `ack` vs `views_open`).
    - service error → patch `equipment_service.search_equipment_by_name` (or
      `status_service.get_area_status_dashboard`) to raise; assert
      `client.chat_postEphemeral` called with error text **and `channel ==
      body['user_id']`** (DM fallback, F1), and `views_open` NOT called.
    - archived-area deep-link (F3/F10): create equipment in an area, then archive
      the area; `/esb-status <equipment name>` → `views_open` with
      `esb_status_summary` (fallback), NOT `chat_postEphemeral`. (Use the
      area-archive service/helper; confirm `search_equipment_by_name` still
      returns the non-archived equipment.)
  - New action tests (new class, e.g. `TestEsbStatusActions`). Include a
    complete body dict with `user`/`channel` keys for realism/consistency with
    the command tests (G2 — note the action handlers' error path only reads
    `body['view']['id']` and `views_update`s; it does **not** DM or read
    `user`/`channel`, so those keys are for realism, not to avoid a `KeyError`):
    - `esb_status_view_area`: body `{'actions': [{'value': str(area.id)}],
      'view': {'id': 'V1'}, 'user': {'id': 'U1'}, 'channel': {'id': 'C1'}}` →
      `client.views_update` called with view `callback_id ==
      'esb_status_area_detail'` and correct title.
    - `esb_status_view_area` error path: patch
      `status_service.get_single_area_status_dashboard` to raise → assert
      `client.views_update` called with an error modal (section text contains
      'Could not load'), not left stale.
    - `esb_status_back_to_summary`: body `{'view': {'id': 'V1'},
      'user': {'id': 'U1'}, 'channel': {'id': 'C1'}}` → `client.views_update`
      with `callback_id == 'esb_status_summary'`.
    - `esb_status_back_to_summary` error path (F6): patch
      `status_service.get_area_status_dashboard` to raise → assert
      `client.views_update` called with the error modal.
    - All handlers call `ack()` first.

- [x] **Task 6: Add modal-builder unit tests in `tests/test_slack/test_forms.py`**
  - File: `tests/test_slack/test_forms.py`
  - Action: Add `TestBuildStatusSummaryModal` and `TestBuildAreaStatusModal`.
  - Details:
    - Summary builder: given a dashboard with a green + a red item across areas,
      assert modal `type == 'modal'`, `callback_id == 'esb_status_summary'`,
      each non-empty area yields a section with an `accessory` button whose
      `action_id == 'esb_status_view_area'` and `value == str(area.id)`;
      non-green item names appear; empty areas are skipped; empty dashboard →
      single 'No equipment' section.
    - Area builder: assert `callback_id == 'esb_status_area_detail'`, title text
      == area name (≤24 chars), detail text matches
      `format_area_status_detail(area_data)`, and a 'Back to summary' button with
      `action_id == 'esb_status_back_to_summary'` is present.
    - Verify `format_status_summary` output is unchanged (existing tests cover
      this; run them).

- [x] **Task 7: Run lint + full test suite**
  - Action: `make lint` and `make test`. Fix any ruff (120-col) issues.
  - Notes: All existing `TestEsbStatusCommand` assertions are replaced in Task 5;
    ensure no other test references the old ephemeral behavior.

### Acceptance Criteria

- [ ] **AC 1 (happy path, no arg):** Given equipment exists across areas, when a
  user runs `/esb-status` with no argument, then the bot calls `views_open` with
  a modal (`callback_id: esb_status_summary`) whose first section reads
  ":bar_chart: *Equipment Status Summary*" and each non-empty area has a "View
  details" button — and no ephemeral message is posted.
- [ ] **AC 2 (area button → detail):** Given the summary modal is open, when the
  user clicks an area's "View details" button (`action_id:
  esb_status_view_area`), then the bot calls `views_update` on the same
  `view['id']` with the area-detail modal (`callback_id:
  esb_status_area_detail`) titled with that area's name and listing its
  equipment statuses.
- [ ] **AC 3 (back navigation):** Given the area-detail modal is open, when the
  user clicks "Back to summary" (`action_id: esb_status_back_to_summary`), then
  the bot calls `views_update` with the summary modal (`callback_id:
  esb_status_summary`).
- [ ] **AC 4 (text arg → area):** Given an area named "Woodshop", when a user
  runs `/esb-status woodshop` (case-insensitive), then the modal opens directly
  on the Woodshop area-detail view.
- [ ] **AC 5 (area precedence):** Given an area "Woodshop" and an equipment
  "Woodshop Helper", when a user runs `/esb-status Woodshop`, then the modal
  opens on the area-detail view (area name match wins over equipment search).
- [ ] **AC 6 (text arg → single equipment's area):** Given exactly one equipment
  matches the arg and belongs to an area, when a user runs `/esb-status <name>`,
  then the modal opens on that equipment's **area** detail view.
- [ ] **AC 7 (ambiguous / no match → summary):** Given the arg matches zero or
  multiple equipment and no area, when a user runs `/esb-status <arg>`, then the
  modal opens on the summary view (no error text, no ephemeral list).
- [ ] **AC 8 (empty state):** Given no equipment is registered, when a user runs
  `/esb-status`, then the summary modal contains a single section reading "No
  equipment has been registered yet."
- [ ] **AC 9 (ack ordering):** Given any `/esb-status` invocation, when the
  handler runs, then `ack()` is called before `views_open` (trigger_id used
  promptly).
- [ ] **AC 10 (error fallback → DM):** Given a service call raises an unexpected
  exception, when a user runs `/esb-status`, then the bot logs a warning and
  posts the ":x: An error occurred..." ephemeral to the **user's DM**
  (`channel == body['user_id']`), not the invoking channel, and does not open a
  modal.
- [ ] **AC 11 (no regression in text formatters):** Given the existing
  `format_status_summary` / `format_area_status_detail` tests, when the suite
  runs, then they still pass (formatter output unchanged; logic only extracted
  into a shared helper — header and trailing tip remain in
  `format_status_summary`).
- [ ] **AC 12 (archived-area deep-link → summary):** Given a non-archived
  equipment item whose area has been archived, when a user runs `/esb-status
  <that equipment name>`, then the modal opens on the **summary** view (the
  `AreaArchived` raise is caught inline and routed to summary), and no error
  ephemeral is posted.
- [ ] **AC 13 (action error → error modal):** Given the "View details" or "Back
  to summary" handler's service call raises, when the button is clicked, then
  the bot calls `views_update` with a close-only error modal (section contains
  "Could not load"), leaving no stale view — no channel ephemeral.

## Additional Context

### Dependencies

- No new external libraries. Uses existing `slack-bolt` / `slack-sdk`
  (`views_open`, `views_update`, `@bolt_app.action`) already in the project.
- Depends on existing services (unchanged): `status_service.get_area_status_dashboard`,
  `status_service.get_single_area_status_dashboard`,
  `equipment_service.get_area_by_name`, `equipment_service.search_equipment_by_name`.
- No DB migration, no config change.

### Testing Strategy

- **Unit (forms):** `tests/test_slack/test_forms.py` — new
  `TestBuildStatusSummaryModal`, `TestBuildAreaStatusModal`; existing formatter
  tests must remain green (regression guard on the extracted helper).
- **Unit (handlers):** `tests/test_slack/test_handlers.py` — rewrite
  `TestEsbStatusCommand` for modal assertions via
  `client.views_open.call_args.kwargs['view']`; add `TestEsbStatusActions` for
  the two `@bolt_app.action` handlers via
  `client.views_update.call_args.kwargs['view']`. Use `_register_and_capture`
  which already captures actions under `action:<id>`.
- **Manual (optional, needs a live Slack workspace):** run `/esb-status` in a
  channel the bot is NOT a member of and confirm the modal opens (proving the
  channel-membership limitation is gone); click through area detail and back.
- **Commands:** `make lint`; `make test`;
  `venv/bin/python -m pytest tests/test_slack/ -v`.

### Notes

- **Risk — trigger_id expiry:** `views_open` needs the ~3s-valid `trigger_id`.
  The single dashboard query between `ack()` and `views_open` matches what
  `/esb-reserve` already does, so latency is acceptable. Do not add slow work
  before `views_open`.
- **Risk — stale text formatters:** after the rework, `format_status_summary`
  and `format_area_status_detail` remain (reused inside builders);
  `format_equipment_status_detail` and `format_equipment_list` become unused. Leaving
  them is harmless; removing them (and their tests) is optional cleanup — the
  spec keeps them to minimize blast radius. Decide during Task 3 whether to
  delete the two now-dead formatters.
- **Known limitation:** the modal is navigation-only (no search box inside it).
  Users still type the area/equipment name as a slash-command arg to deep-link;
  in-modal search is a possible future enhancement (out of scope).
- **Future:** could add equipment-level detail as a third modal level, or a
  refresh button. Explicitly out of scope for issue #70.
- **Version bump:** this is a user-facing feature — bump the `version` minor in
  `pyproject.toml` when merging (per CLAUDE.md release process). Not part of the
  code tasks above; do it at PR time.

## Review Notes

- Adversarial review completed (step 5) via an isolated subagent seeing only the diff.
- Findings: 14 total, 7 fixed, 7 skipped. Resolution approach: auto-fix real items + F3.
- **Fixed:**
  - **F3 (error delivery):** the error fallback now replies via the slash
    command's `response_url` (Bolt's `respond(response_type='ephemeral', ...)`)
    instead of `chat_postEphemeral(channel=user_id, ...)`. `response_url` is a
    temporary webhook that works even when the bot is not a member of the
    invoking channel — the exact limitation this feature fixes — and is more
    robust than posting an ephemeral to a user-id-as-channel. **This supersedes
    the AC 10 / "Error fallback (F1/F2)" decision above**, which called for a DM
    via `chat_postEphemeral`.
  - **F4 (dead code):** removed the now-unreferenced `format_status_summary`,
    `format_equipment_status_detail`, and `format_equipment_list` from
    `forms.py` plus their tests. `format_area_status_detail` and the extracted
    `_area_summary_mrkdwn` are retained (used by the builders).
    `status_service.get_equipment_status_detail` was left as-is (out of scope).
  - **F8 (test gap):** added a test for the `views_open`-itself-fails path
    (asserts the `respond` fallback still fires).
  - **F9 (test gap):** builder tests now assert Block Kit limits (≤100 blocks,
    ≤3000 chars per section text).
  - **F12 (swallowed secondary failure):** the command `except` now wraps the
    fallback `respond` in its own try/except so a secondary delivery failure is
    logged, not propagated.
  - **F13 (docstring):** `_area_summary_mrkdwn` docstring no longer references
    the removed `format_status_summary`.
  - **F14 (brittle test):** the archived-area deep-link test now pins the
    mechanism (asserts the matched equipment's `area_id` is the archived area).
- **Skipped:**
  - **F1 / F2 (Block Kit section 3000-char / 100-block caps):** real but the
    spec explicitly accepted them at makerspace scale; builder tests now guard
    against a regression at the tested scale (F9).
  - **F5 (loss of not-found feedback):** intended per AC 6 / AC 7 (summary is
    the safe landing).
  - **F6 (equipment with `area_id is None`):** not reproducible — `equipment.area_id`
    is `NOT NULL` at the schema level, so the branch is unreachable defensive
    code; the guard is kept as harmless defense.
  - **F7 (`trigger_id` expiry race):** inherent to the `views_open` flow and
    already acknowledged in Notes; mirrors `/esb-reserve`.
  - **F10 (command DMs vs actions update-in-place):** necessary asymmetry — the
    command has no open modal yet (must reply out-of-band), while the action
    handlers have a live view to `views_update`.
  - **F11 (shared `action_id` across area buttons):** valid Block Kit — button
    action_id uniqueness is per-block, and each area section carries a distinct
    `block_id`.

## Post-Implementation Verification

- `make lint` — clean.
- `make test` — 1805 passed (dead-formatter tests removed with their functions).
- `venv/bin/python -m pytest tests/test_slack/ -v` — all green.
