---
title: 'QR Code WiFi Header'
slug: 'qr-wifi-header'
created: '2026-05-26'
status: 'ready-for-dev'
stepsCompleted: [1, 2, 3, 4]
tech_stack: ['Python 3.14', 'Flask', 'Flask-SQLAlchemy', 'Flask-WTF/WTForms', 'Pillow', 'qrcode', 'MariaDB (Docker)', 'Alembic']
files_to_modify: ['esb/services/qr_service.py', 'esb/forms/equipment_forms.py', 'esb/views/equipment.py', 'esb/forms/admin_forms.py', 'esb/views/admin.py', 'esb/templates/equipment/qr.html', 'esb/templates/admin/config.html', 'esb/static/js/app.js', 'esb/static/fonts/NotoEmoji[wght].ttf (new)', 'esb/static/fonts/OFL-NotoEmoji.txt (new)', 'tests/test_services/test_qr_service.py', 'tests/test_views/test_equipment_views.py', 'tests/test_views/test_admin_views.py']
code_patterns: ['service-layer delegation', 'config_service.get_config(key, default) / set_config(key, value, changed_by)', 'AppConfigForm with BooleanField/StringField + admin view GET-populate/POST-save pattern', 'QR render_qr_png builds Pillow canvas with reserved_top/reserved_bottom text rows', '_draw_text_row auto-sizes text via _fit_text with DejaVuSans-Bold.ttf', 'QR form JS live-preview debounces change events and rebuilds URLSearchParams', 'QRGenerateForm uses WTForms SelectField/BooleanField']
test_patterns: ['SQLite in-memory DB (TestingConfig)', 'CSRF disabled in tests', 'staff_client/tech_client/client fixtures', 'configured_base_url fixture sets ESB_BASE_URL', 'monkeypatch for error path testing', 'pyzbar.decode for QR payload verification', 'Pillow pixel inspection for text rendering verification']
---

# Tech-Spec: QR Code WiFi Header

**Created:** 2026-05-26

## Overview

### Problem Statement

ESB is only accessible on the LAN, but QR codes printed on equipment labels don't indicate this. Users scanning a QR code while not connected to the makerspace WiFi get a confusing dead link with no explanation of why. Labels need to visually communicate the WiFi requirement and optionally show the network name and password so users can connect.

### Solution

Add a "Must be on WiFi" header row at the very top of generated QR label images, with optional SSID and password text below it. WiFi detail level is controlled via a dropdown on the QR generation form with hierarchical options (None / Header only / Header+SSID / Header+SSID+Password). SSID and password values are stored as runtime `AppConfig` settings managed through the existing Admin UI at `/admin/config`. Dropdown options that require unconfigured values are hidden from the form. The default dropdown selection is also configurable via Admin UI.

**Font note:** The WiFi emoji (🛜 U+1F6DC) is NOT in DejaVuSans-Bold.ttf. We will bundle Google's **Noto Emoji** monochrome font (`NotoEmoji[wght].ttf`, ~1.9 MB, SIL OFL 1.1 license) which contains the glyph as a clean black-and-white WiFi icon. The rendering code uses Noto Emoji for the 🛜 character and DejaVuSans-Bold for all text.

### Scope

**In Scope:**
- Three new `AppConfig` keys: `wifi_ssid`, `wifi_password`, `wifi_info_default`
- Admin UI fields on `/admin/config` for WiFi SSID, password, and default dropdown value
- New "WiFi Info" dropdown on QR generation form (None / Header only / +SSID / +SSID+Password)
- Rendering WiFi header row(s) at the very top of the QR label image (above equipment name)
- Live preview updates when WiFi dropdown changes
- Configurable default selection for the WiFi dropdown
- Tests for new service logic, form behavior, and view behavior

**Out of Scope:**
- WiFi QR code (a separate QR that auto-joins the network)
- Changes to the public equipment page HTML
- Network connectivity detection or auto-redirect logic

## Context for Development

### Codebase Patterns

- **Service layer**: All business logic in `esb/services/`. Views never query models directly; they delegate to service functions. Config values read via `config_service.get_config(key, default)`.
- **Admin config pattern**: `AppConfig` model is a simple key-value store (`key: str`, `value: str`). `AppConfigForm` in `esb/forms/admin_forms.py` has one field per setting. The `app_config()` view in `esb/views/admin.py` populates form fields from config on GET, iterates a `config_keys` list on POST and calls `set_config()` for changed values. Boolean fields stored as `'true'`/`'false'` strings, text fields as plain strings.
- **QR rendering pipeline**: `qr_service.render_qr_png()` computes `reserved_top` (15% of height if `include_name`) and `reserved_bottom` (15% if `include_url`). The QR code is sized to fit the remaining space minus margin. Text rows are drawn via `_draw_text_row()` which calls `_fit_text()` to auto-size the font (shrink from max → 8pt floor, then truncate with ellipsis). Font: `esb/static/fonts/DejaVuSans-Bold.ttf`.
- **QR form + preview**: `QRGenerateForm` uses `SelectField` (size) + `BooleanField` (include_name, include_url). The `qr.html` template shows a live preview via `<img id="qr-preview">`. JavaScript in `app.js:239-261` listens for `change` events on `#qr-form`, debounces 150ms, builds `URLSearchParams` from form values, and updates `img.src` to hit the `/qr/preview` endpoint.
- **Preview endpoint**: `qr_preview()` reads query params (`size`, `include_name`, `include_url`) and calls `render_qr_png()`. Returns inline PNG with 5-minute cache header.
- **Download endpoint**: `qr()` POST handler calls `render_qr_png()` and returns as attachment with filename `qr-{id}-{slugified-name}.png`.

### Files to Reference

| File | Purpose | Key Lines |
| ---- | ------- | --------- |
| `esb/services/qr_service.py` | QR rendering — `render_qr_png()`, `_draw_text_row()`, `_fit_text()` | L56-129 (render), L132-154 (draw_text), L157-193 (fit_text) |
| `esb/services/config_service.py` | `get_config(key, default)` / `set_config(key, value, changed_by)` | L13-28, L31-71 |
| `esb/forms/equipment_forms.py` | `QRGenerateForm` — size, include_name, include_url | L130-141 |
| `esb/forms/admin_forms.py` | `AppConfigForm` — existing config form fields | L33-42 |
| `esb/views/equipment.py` | `qr()` and `qr_preview()` route handlers | L233-307 |
| `esb/views/admin.py` | `app_config()` — GET populate, POST iterate config_keys | L247-290 |
| `esb/templates/equipment/qr.html` | QR form with live preview `#qr-preview` img | Full file (48 lines) |
| `esb/templates/admin/config.html` | Admin config page — card sections with form fields | Full file (93 lines) |
| `esb/static/js/app.js` | QR preview JS — debounced change handler builds URLSearchParams | L239-261 |
| `tests/test_services/test_qr_service.py` | QR service tests — pixel inspection, pyzbar decode, fit_text | Full file (307 lines) |
| `tests/test_views/test_equipment_views.py` | QR view tests — form rendering, download, preview | L1549-1740 |
| `tests/test_views/test_admin_views.py` | Admin config tests — GET form, POST save, mutation logging | L890-953, L955-1050 |

### Technical Decisions

- **AppConfig over env vars**: WiFi settings are managed by staff through the Admin UI, not by sysadmins through environment variables. This allows runtime changes without redeployment.
- **WiFi header at top**: Placed above equipment name so it's the first thing seen on the label, reinforcing the WiFi requirement.
- **Hierarchical dropdown**: Single select with options filtered by available config. Prevents nonsensical combos (e.g. password without SSID). Cleaner than multiple checkboxes.
- **Configurable default**: `wifi_info_default` config key lets admins set the default dropdown value so users don't have to change it every time.
- **Two-font rendering**: Use Noto Emoji (`NotoEmoji[wght].ttf`, monochrome, SIL OFL 1.1) for the 🛜 emoji glyph and DejaVuSans-Bold for text. Noto Emoji is a variable font (weight 300–700); use weight 700 for bold to match. The emoji is rendered separately from text to avoid font-fallback complexity in Pillow.
- **WiFi text rendering approach**: Reuse the existing `_draw_text_row()` mechanism for text portions. The WiFi header line renders the emoji and "Must be on WiFi" text side-by-side in the top reserved region. SSID/password lines render as additional stacked `_draw_text_row()` calls below the header. Each WiFi line gets its own reserved row region at the very top of the canvas, above the equipment name region.
- **Dynamic form choices**: The `QRGenerateForm` `wifi_info` SelectField choices must be computed at form instantiation time (not class definition time) because they depend on runtime DB config. This can be done by passing choices to the constructor or by overriding `__init__` to query config_service.

## Implementation Plan

### Tasks

#### WiFi Info Dropdown Values

The `wifi_info` field uses these values throughout the stack (form, view, service, JS):

| Value | Label | Renders |
|-------|-------|---------|
| `none` | None | No WiFi info |
| `header` | 🛜 Must be on WiFi | Emoji + "Must be on WiFi" text |
| `ssid` | 🛜 Must be on WiFi + SSID | Header line + "Network: {ssid}" line |
| `password` | 🛜 Must be on WiFi + SSID + Password | Header + SSID + "Password: {password}" line |

---

- [ ] **Task 1: Vendor Noto Emoji font**
  - File: `esb/static/fonts/NotoEmoji[wght].ttf` (new)
  - Action: Download `NotoEmoji[wght].ttf` from `https://raw.githubusercontent.com/google/fonts/main/ofl/notoemoji/NotoEmoji%5Bwght%5D.ttf` and place in `esb/static/fonts/`.
  - File: `esb/static/fonts/OFL-NotoEmoji.txt` (new)
  - Action: Download the SIL OFL 1.1 license text from the same Google Fonts repo directory and save alongside the font.

- [ ] **Task 2: Add WiFi fields to Admin Config form**
  - File: `esb/forms/admin_forms.py`
  - Action: Add three new fields to `AppConfigForm`:
    - `wifi_ssid = StringField('WiFi Network Name (SSID)', validators=[Length(max=100)])` — optional text field
    - `wifi_password = StringField('WiFi Password', validators=[Length(max=100)])` — optional text field
    - `wifi_info_default = SelectField('Default WiFi Info on QR Labels', choices=[...])` — dropdown with the four `wifi_info` values. Choices are static here (all four values always shown in admin); the QR form is where we filter dynamically.
  - Notes: Import `Length` validator (already imported in the file). The admin always sees all four options so they can set a default even before configuring SSID/password — they may configure SSID later.

- [ ] **Task 3: Update Admin Config view to handle WiFi settings**
  - File: `esb/views/admin.py`
  - Action: In the `app_config()` view function:
    - **GET**: Populate `form.wifi_ssid.data`, `form.wifi_password.data`, and `form.wifi_info_default.data` from `config_service.get_config()` with defaults `''`, `''`, and `'none'` respectively.
    - **POST**: Add a new `string_config_keys` list: `[('wifi_ssid', ''), ('wifi_password', ''), ('wifi_info_default', 'none')]`. For each, read `getattr(form, key).data` (the raw string, not bool conversion), compare to current config, and call `set_config()` if changed.
  - Notes: The existing boolean config_keys loop does `'true' if getattr(form, key).data else 'false'`. The new string fields need direct string comparison. Add a separate loop or extend the existing pattern with a type flag.

- [ ] **Task 4: Update Admin Config template with WiFi section**
  - File: `esb/templates/admin/config.html`
  - Action: Add a new Bootstrap card section between "Technician Permissions" and "Notification Triggers" cards:
    ```
    <div class="card mb-4">
      <div class="card-header"><h5 class="card-title mb-0">WiFi / QR Label Settings</h5></div>
      <div class="card-body">
        <div class="mb-3">
          <label for="{{ form.wifi_ssid.id }}" class="form-label">{{ form.wifi_ssid.label.text }}</label>
          {{ form.wifi_ssid(class="form-control") }}
          <div class="form-text">Network name shown on QR labels. Leave blank to hide SSID-related options.</div>
        </div>
        <div class="mb-3">
          <label for="{{ form.wifi_password.id }}" class="form-label">{{ form.wifi_password.label.text }}</label>
          {{ form.wifi_password(class="form-control") }}
          <div class="form-text">WiFi password shown on QR labels. Leave blank to hide password option.</div>
        </div>
        <div class="mb-3">
          <label for="{{ form.wifi_info_default.id }}" class="form-label">{{ form.wifi_info_default.label.text }}</label>
          {{ form.wifi_info_default(class="form-select") }}
          <div class="form-text">Default selection for the WiFi Info dropdown on the QR code generation form.</div>
        </div>
      </div>
    </div>
    ```

- [ ] **Task 5: Add `wifi_info` field to QR Generation form**
  - File: `esb/forms/equipment_forms.py`
  - Action: Add a `wifi_info` `SelectField` to `QRGenerateForm`. Since choices depend on runtime config (which SSID/password are configured), accept `wifi_choices` as a constructor parameter:
    - Add `__init__(self, *args, wifi_choices=None, **kwargs)` that sets `self.wifi_info.choices = wifi_choices or [('none', 'None')]` after calling `super().__init__()`.
    - Define the field: `wifi_info = SelectField('WiFi Info')` with no static choices.
  - Notes: The view will compute available choices and pass them in. Default value is also set by the view based on `wifi_info_default` config.

- [ ] **Task 6: Build WiFi choices helper in equipment view**
  - File: `esb/views/equipment.py`
  - Action: Add a helper function `_build_wifi_choices()` that:
    1. Reads `wifi_ssid` and `wifi_password` from `config_service.get_config()`.
    2. Always includes `('none', 'None')`.
    3. Always includes `('header', '🛜 Must be on WiFi')` (this option requires no config).
    4. If `wifi_ssid` is non-empty, includes `('ssid', '🛜 WiFi + SSID')`.
    5. If both `wifi_ssid` and `wifi_password` are non-empty, includes `('password', '🛜 WiFi + SSID + Password')`.
    6. Returns the choices list and a dict `{'wifi_ssid': ..., 'wifi_password': ...}` for the renderer.
  - Action: Also add `_get_wifi_default()` that reads `wifi_info_default` from config, validates it against available choices, and falls back to `'none'` if the configured default isn't in the available choices.

- [ ] **Task 7: Update `qr()` and `qr_preview()` views to pass WiFi params**
  - File: `esb/views/equipment.py`
  - Action in `qr()` (GET/POST handler, L233-273):
    - Call `_build_wifi_choices()` to get choices and wifi config values.
    - Call `_get_wifi_default()` to get the default.
    - Instantiate `QRGenerateForm(wifi_choices=choices)`.
    - On GET, set `form.wifi_info.data = default` if not already submitted.
    - On POST (`validate_on_submit`), pass `wifi_info=form.wifi_info.data` and `wifi_ssid`/`wifi_password` values to `render_qr_png()`.
    - Pass wifi config to template context for initial preview URL.
  - Action in `qr_preview()` (L276-307):
    - Read `wifi_info` from `request.args.get('wifi_info', 'none')`.
    - Read wifi config values from `config_service`.
    - Pass `wifi_info`, `wifi_ssid`, `wifi_password` to `render_qr_png()`.

- [ ] **Task 8: Extend `render_qr_png()` to render WiFi info**
  - File: `esb/services/qr_service.py`
  - Action: Add new parameters to `render_qr_png()`:
    - `wifi_info: str = 'none'` — one of `'none'`, `'header'`, `'ssid'`, `'password'`
    - `wifi_ssid: str = ''`
    - `wifi_password: str = ''`
  - Action: Compute WiFi rows to render based on `wifi_info` value:
    - `'none'` → 0 rows
    - `'header'` → 1 row: emoji + "Must be on WiFi"
    - `'ssid'` → 2 rows: header + "Network: {wifi_ssid}"
    - `'password'` → 3 rows: header + SSID + "Password: {wifi_password}"
  - Action: Calculate `reserved_wifi` as `num_wifi_rows * int(canvas_h_px * 0.08)` (8% of canvas height per WiFi line). This is added to the top of the canvas, above `reserved_top` (equipment name).
  - Action: Shift the equipment name row down by `reserved_wifi`. Shift the QR paste position down by `reserved_wifi`.
  - Action: Render WiFi rows at the top:
    - For the header row: render the 🛜 emoji using Noto Emoji font, then "Must be on WiFi" text using DejaVuSans-Bold, positioned side-by-side and centered horizontally.
    - For SSID/password rows: render using `_draw_text_row()` with DejaVuSans-Bold as usual.
  - Notes: Add a `_draw_wifi_header_row()` helper for the compound emoji+text rendering. Load Noto Emoji font path as `os.path.join(current_app.static_folder, 'fonts', 'NotoEmoji[wght].ttf')`.

- [ ] **Task 9: Update QR form template with WiFi dropdown**
  - File: `esb/templates/equipment/qr.html`
  - Action: Add the `wifi_info` dropdown to the form, between the size dropdown and the include_name checkbox:
    ```html
    <div class="mb-3">
      <label for="{{ form.wifi_info.id }}" class="form-label">{{ form.wifi_info.label.text }}</label>
      {{ form.wifi_info(class="form-select") }}
    </div>
    ```
  - Action: Update the initial preview `<img>` src URL to include `wifi_info` parameter.

- [ ] **Task 10: Update QR preview JavaScript to include WiFi param**
  - File: `esb/static/js/app.js`
  - Action: In the QR preview update function (L246-253), add `wifi_info` to the URLSearchParams:
    ```js
    var wifiInfo = form.querySelector('[name="wifi_info"]');
    if (wifiInfo) params.set('wifi_info', wifiInfo.value);
    ```
  - Notes: The `change` event listener on the form already catches all `<select>` changes, so the WiFi dropdown triggers preview updates automatically.

- [ ] **Task 11: Add QR service tests for WiFi rendering**
  - File: `tests/test_services/test_qr_service.py`
  - Action: Add tests to `TestRenderQRPng`:
    - `test_wifi_header_renders_pixels_at_top` — with `wifi_info='header'`, verify non-white pixels exist in the top WiFi region.
    - `test_wifi_none_renders_no_wifi_pixels` — with `wifi_info='none'`, verify the top region is all white (same as current behavior).
    - `test_wifi_ssid_renders_two_rows` — with `wifi_info='ssid'`, verify both header and SSID regions have non-white pixels.
    - `test_wifi_password_renders_three_rows` — with `wifi_info='password'`, verify all three WiFi regions have non-white pixels.
    - `test_wifi_header_qr_still_decodes` — with `wifi_info='header'`, verify pyzbar can still decode the QR payload (text didn't overlap QR region).
    - `test_wifi_info_default_none` — verify default `wifi_info='none'` produces same output as without the parameter.
  - Notes: Follow existing test patterns (pixel inspection, pyzbar decode). Use `sticker_4` preset for sufficient room.

- [ ] **Task 12: Add QR view tests for WiFi functionality**
  - File: `tests/test_views/test_equipment_views.py`
  - Action: Add tests to `TestEquipmentQR`:
    - `test_qr_form_shows_wifi_dropdown` — verify `name="wifi_info"` appears in the form HTML.
    - `test_qr_form_wifi_choices_no_config` — with no WiFi config, verify only `none` and `header` options are present.
    - `test_qr_form_wifi_choices_ssid_only` — with `wifi_ssid` config set, verify `ssid` option appears but `password` does not.
    - `test_qr_form_wifi_choices_ssid_and_password` — with both config set, verify all four options appear.
    - `test_qr_form_wifi_default_from_config` — with `wifi_info_default='header'`, verify the dropdown defaults to `header`.
    - `test_qr_form_wifi_default_fallback` — with `wifi_info_default='password'` but no wifi_password config, verify fallback to `none`.
    - `test_qr_preview_includes_wifi_param` — verify preview endpoint accepts `wifi_info` query param.
    - `test_qr_download_with_wifi_header` — POST with `wifi_info=header`, verify PNG attachment returned.
  - Notes: Use `config_service.set_config()` in test setup to configure WiFi values.

- [ ] **Task 13: Add Admin Config tests for WiFi settings**
  - File: `tests/test_views/test_admin_views.py`
  - Action: Add tests (new class `TestAppConfigWiFi` or extend `TestAppConfig`):
    - `test_config_shows_wifi_fields` — GET `/admin/config` shows `wifi_ssid`, `wifi_password`, `wifi_info_default` fields.
    - `test_config_saves_wifi_ssid` — POST with `wifi_ssid=MyNetwork`, verify `config_service.get_config('wifi_ssid')` returns `'MyNetwork'`.
    - `test_config_saves_wifi_password` — POST with `wifi_password=secret123`, verify config saved.
    - `test_config_saves_wifi_info_default` — POST with `wifi_info_default=header`, verify config saved.
    - `test_config_clears_wifi_ssid` — POST with empty `wifi_ssid`, verify config saved as empty string.
    - `test_config_wifi_mutation_logging` — verify `set_config` audit log entries for WiFi config changes.

- [ ] **Task 14: Run full test suite and lint**
  - Action: Run `make test` and `make lint` to verify all changes pass.
  - Notes: Fix any ruff lint issues (120-char line length, import order). Fix any test failures.

### Acceptance Criteria

- [ ] **AC 1**: Given no WiFi config is set in AppConfig, when a user opens the QR generation form, then the WiFi Info dropdown shows only "None" and "🛜 Must be on WiFi" options.

- [ ] **AC 2**: Given `wifi_ssid` is set to "MakerSpace-Guest" in AppConfig, when a user opens the QR generation form, then the WiFi Info dropdown includes "🛜 WiFi + SSID" as an additional option.

- [ ] **AC 3**: Given both `wifi_ssid` and `wifi_password` are set in AppConfig, when a user opens the QR generation form, then all four WiFi Info options are available.

- [ ] **AC 4**: Given `wifi_info_default` is set to "header" in AppConfig, when a user opens the QR generation form, then the WiFi Info dropdown defaults to "🛜 Must be on WiFi".

- [ ] **AC 5**: Given `wifi_info_default` is set to "password" but `wifi_password` is not configured, when a user opens the QR generation form, then the dropdown defaults to "None" (graceful fallback).

- [ ] **AC 6**: Given a user selects "🛜 Must be on WiFi" and downloads a QR code, when the PNG is rendered, then the top of the image contains the WiFi emoji (from Noto Emoji font) and "Must be on WiFi" text above the equipment name.

- [ ] **AC 7**: Given a user selects "🛜 WiFi + SSID" with SSID configured as "MakerSpace-Guest", when the PNG is rendered, then the image shows the WiFi header line followed by "Network: MakerSpace-Guest" below it, both above the equipment name.

- [ ] **AC 8**: Given a user selects "🛜 WiFi + SSID + Password" with both configured, when the PNG is rendered, then the image shows WiFi header, SSID line, and password line, all above the equipment name.

- [ ] **AC 9**: Given a user changes the WiFi Info dropdown on the QR form, when the dropdown value changes, then the live preview image updates within 150ms (debounced) to reflect the new WiFi info selection.

- [ ] **AC 10**: Given a staff user navigates to `/admin/config`, when they view the page, then they see a "WiFi / QR Label Settings" card with fields for WiFi SSID, WiFi Password, and Default WiFi Info dropdown.

- [ ] **AC 11**: Given a staff user sets WiFi SSID to "MakerSpace" and saves, when they reload the config page, then the WiFi SSID field shows "MakerSpace" (value persisted via AppConfig).

- [ ] **AC 12**: Given a staff user clears the WiFi SSID field and saves, when a user opens the QR form, then the SSID and password dropdown options are no longer available.

- [ ] **AC 13**: Given WiFi info is set to "None", when the QR code is rendered, then the output is identical to the current behavior (no WiFi info, no extra reserved space at top).

- [ ] **AC 14**: Given a very small preset (1"×1" sticker) with WiFi header enabled, when the QR code is rendered, then the image renders without error (the existing marginal-module-size warning may fire but rendering completes).

- [ ] **AC 15**: Given the QR code is rendered with WiFi header, when scanned with a QR reader, then the QR payload still decodes correctly to the expected URL (WiFi text does not overlap the QR region).

## Additional Context

### Dependencies

No new Python packages required. Pillow and qrcode are already dependencies.

New vendored font: `NotoEmoji[wght].ttf` (~1.9 MB) from Google Fonts, licensed under SIL Open Font License 1.1. Include `OFL-NotoEmoji.txt` license file alongside the font in `esb/static/fonts/`.

### Testing Strategy

- Unit tests for `qr_service.render_qr_png()` with WiFi info options (verify image dimensions change, text rows are rendered)
- Unit tests for `QRGenerateForm` with dynamic WiFi choices based on config state
- View tests for `qr()` and `qr_preview()` routes with WiFi params
- Admin view tests for new config fields (GET populates, POST saves)
- Edge case: all WiFi config empty → dropdown shows only "None", default is "None"
- Edge case: SSID set but password empty → "Header+SSID+Password" option hidden

### Notes

- **Font limitation resolved**: DejaVuSans-Bold.ttf does NOT contain U+1F6DC (WiFi emoji). Verified via fontTools cmap inspection. Solution: bundle Google's Noto Emoji monochrome font which contains the glyph as a clean black-and-white WiFi icon (concentric arcs + dot in a rounded square). Rendering uses Noto Emoji for the emoji, DejaVuSans-Bold for text.
- For very small label presets (1"×1"), adding WiFi header rows reduces available QR space. The existing marginal-module-size warning in `render_qr_png()` will catch this — no additional blocking logic needed.
- The `_fit_text()` function handles graceful degradation: if text is too wide, it shrinks the font down to 8pt, then truncates with ellipsis. This will naturally handle long SSIDs/passwords.
- The `_load_font()` function uses `@lru_cache(maxsize=64)` so repeated renders at the same font size are fast.
- The admin config POST handler pattern iterates a `config_keys` list of `(key, default)` tuples. New WiFi string fields need different handling than booleans — the value is the string itself, not 'true'/'false'.
