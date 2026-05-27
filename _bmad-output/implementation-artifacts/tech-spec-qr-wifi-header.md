---
title: 'QR Code WiFi Header'
slug: 'qr-wifi-header'
created: '2026-05-26'
status: 'ready-for-dev'
stepsCompleted: [1, 2, 3, 4]
tech_stack: ['Python 3.14', 'Flask', 'Flask-SQLAlchemy', 'Flask-WTF/WTForms', 'Pillow', 'qrcode', 'MariaDB (Docker)']
files_to_modify: ['esb/services/qr_service.py', 'esb/forms/equipment_forms.py', 'esb/views/equipment.py', 'esb/forms/admin_forms.py', 'esb/views/admin.py', 'esb/templates/equipment/qr.html', 'esb/templates/admin/config.html', 'esb/static/js/app.js', 'esb/static/fonts/NotoEmoji-Bold.ttf (new)', 'esb/static/fonts/OFL-NotoEmoji.txt (new)', 'tests/test_services/test_qr_service.py', 'tests/test_views/test_equipment_views.py', 'tests/test_views/test_admin_views.py']
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

**Font note:** The WiFi emoji (🛜 U+1F6DC) is NOT in DejaVuSans-Bold.ttf. We will bundle a static Bold instance of Google's **Noto Emoji** monochrome font (`NotoEmoji-Bold.ttf`, ~200-400 KB, SIL OFL 1.1 license) extracted from the variable font at vendoring time using `fontTools`. It renders the glyph as a clean black-and-white WiFi icon. The rendering code uses Noto Emoji for the 🛜 character and DejaVuSans-Bold for all text.

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

| File | Purpose | Key Symbols |
| ---- | ------- | ----------- |
| `esb/services/qr_service.py` | QR rendering | `render_qr_png()`, `_draw_text_row()`, `_fit_text()`, `_load_font()`, `QR_SIZE_PRESETS` |
| `esb/services/config_service.py` | Runtime config CRUD | `get_config(key, default)`, `set_config(key, value, changed_by)` |
| `esb/forms/equipment_forms.py` | QR form definition | `QRGenerateForm` class — `size`, `include_name`, `include_url` fields |
| `esb/forms/admin_forms.py` | Admin config form | `AppConfigForm` class |
| `esb/views/equipment.py` | QR route handlers | `qr()` (GET/POST), `qr_preview()` (GET) |
| `esb/views/admin.py` | Admin config route | `app_config()` — GET populate, POST iterate `config_keys` |
| `esb/templates/equipment/qr.html` | QR form with live preview | `#qr-form`, `#qr-preview` img, `data-preview-base` |
| `esb/templates/admin/config.html` | Admin config page | Card sections with form fields |
| `esb/static/js/app.js` | QR preview JS | IIFE block: `#qr-form` change listener, `URLSearchParams`, debounce |
| `tests/test_services/test_qr_service.py` | QR service tests | `TestRenderQRPng`, `TestFitText` — pixel inspection, pyzbar decode |
| `tests/test_views/test_equipment_views.py` | QR view tests | `TestEquipmentQR` — form rendering, download, preview |
| `tests/test_views/test_admin_views.py` | Admin config tests | `TestAppConfig`, `TestAppConfigNotificationTriggers` |

### Technical Decisions

- **AppConfig over env vars**: WiFi settings are managed by staff through the Admin UI, not by sysadmins through environment variables. This allows runtime changes without redeployment.
- **WiFi header at top**: Placed above equipment name so it's the first thing seen on the label, reinforcing the WiFi requirement.
- **Hierarchical dropdown**: Single select with options filtered by available config. Prevents nonsensical combos (e.g. password without SSID). Cleaner than multiple checkboxes.
- **Configurable default**: `wifi_info_default` config key lets admins set the default dropdown value so users don't have to change it every time.
- **Two-font rendering**: Use Noto Emoji (`NotoEmoji-Bold.ttf`, monochrome, SIL OFL 1.1) for the 🛜 emoji glyph and DejaVuSans-Bold for text. The source font (`NotoEmoji-Bold.ttf`) is a variable font — to avoid runtime variable-font complexity (Pillow's `set_variation_by_name()` requires `fontTools`, and the existing `_load_font` LRU cache key doesn't include weight), **extract the Bold (wght=700) instance at vendoring time** using `fontTools`: `fontTools.instancer.instantiateVariableFont(font, {"wght": 700})` and save as `NotoEmoji-Bold.ttf`. This produces a static TrueType file that works with the existing `_load_font` cache and requires no additional runtime dependencies. The emoji is rendered separately from text to avoid font-fallback complexity in Pillow.
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
  - File: `esb/static/fonts/NotoEmoji-Bold.ttf` (new)
  - Action: Download the variable font `NotoEmoji[wght].ttf` from `https://raw.githubusercontent.com/google/fonts/main/ofl/notoemoji/NotoEmoji%5Bwght%5D.ttf`. Then extract the Bold (wght=700) static instance using fontTools:
    ```python
    from fontTools.ttLib import TTFont
    from fontTools.instancer import instantiateVariableFont
    font = TTFont('NotoEmoji[wght].ttf')
    instantiateVariableFont(font, {"wght": 700})
    font.save('esb/static/fonts/NotoEmoji-Bold.ttf')
    ```
    This produces a static TrueType file (~200-400 KB, much smaller than the 1.9 MB variable font) that works with the existing `_load_font` LRU cache without requiring `fontTools` at runtime.
  - Action: Verify U+1F6DC is present in the output font: `TTFont('NotoEmoji-Bold.ttf')['cmap'].getBestCmap()[0x1F6DC]` should return a glyph name without error.
  - File: `esb/static/fonts/OFL-NotoEmoji.txt` (new)
  - Action: Download the SIL OFL 1.1 license text from the same Google Fonts repo directory and save alongside the font.
  - Notes: `fontTools` is only needed at vendoring time (developer's machine), not at runtime or in Docker. The variable source file (`NotoEmoji[wght].ttf`) should NOT be committed — only the static `NotoEmoji-Bold.ttf` instance.

- [ ] **Task 2: Add WiFi fields to Admin Config form**
  - File: `esb/forms/admin_forms.py`
  - Action: Add three new fields to `AppConfigForm`:
    - `wifi_ssid = StringField('WiFi Network Name (SSID)', validators=[Length(max=100)])` — optional text field
    - `wifi_password = StringField('WiFi Password', validators=[Length(max=100)])` — optional text field
    - `wifi_info_default = SelectField('Default WiFi Info on QR Labels', choices=[('none', 'None'), ('header', 'WiFi header only'), ('ssid', 'WiFi header + SSID'), ('password', 'WiFi header + SSID + Password')])` — dropdown with all four values. Choices are static (all shown in admin regardless of config state); the QR form is where we filter dynamically. Note: admin labels are plain text (no emoji) for clarity.
  - Notes: Import `Length` validator (already imported in the file). The admin always sees all four options so they can set a default even before configuring SSID/password — they may configure SSID later.

- [ ] **Task 3: Update Admin Config view to handle WiFi settings**
  - File: `esb/views/admin.py`
  - Action: In the `app_config()` view function:
    - **GET**: Populate `form.wifi_ssid.data`, `form.wifi_password.data`, and `form.wifi_info_default.data` from `config_service.get_config()` with defaults `''`, `''`, and `'none'` respectively.
    - **POST**: Add a second loop after the existing boolean `config_keys` loop. Define `string_config_keys = [('wifi_ssid', ''), ('wifi_password', ''), ('wifi_info_default', 'none')]`. For each `(key, default)`, read `new_value = (getattr(form, key).data or '').strip()`, compare to `config_service.get_config(key, default)`, and call `set_config(key, new_value, changed_by=current_user.username)` if changed.
  - Notes: This is a separate loop from the boolean keys because string fields use the raw value directly (no `'true'`/`'false'` conversion). The `.strip()` prevents trailing whitespace in SSID/password values.

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
  - Action in `qr()` (GET/POST handler):
    - Call `_build_wifi_choices()` to get choices and wifi config values.
    - Call `_get_wifi_default()` to get the default.
    - Instantiate `QRGenerateForm(wifi_choices=choices)`.
    - On GET, set `form.wifi_info.data = default` if not already submitted.
    - On POST (`validate_on_submit`), pass `wifi_info=form.wifi_info.data` and `wifi_ssid`/`wifi_password` values to `render_qr_png()`.
    - Pass wifi config to template context for initial preview URL.
  - Action in `qr_preview()`:
    - Read `wifi_info` from `request.args.get('wifi_info', 'none')`.
    - Read wifi config values from `config_service`.
    - **Validate `wifi_info` against available config**: if `wifi_info='ssid'` but `wifi_ssid` is empty, or `wifi_info='password'` but `wifi_password` is empty, clamp `wifi_info` down to the highest valid level (e.g., `password`→`ssid`→`header`→`none`). This prevents crafted URLs from rendering blank "Network: " or "Password: " labels.
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
  - Action: Calculate `reserved_wifi` using size-aware row heights:
    1. Compute `min_row_px = _pt_to_px(_MIN_FONT_PT) + 4` (minimum font height + 4px padding ≈ 38px at 300 DPI). This is the absolute floor — any smaller and `_fit_text` / `_draw_text_row` will overflow vertically.
    2. Compute `pct_row_px = int(canvas_h_px * 0.10)` (10% of canvas height — target size for readability).
    3. Use `row_height = max(min_row_px, pct_row_px)`.
    4. Compute `reserved_wifi = num_wifi_rows * row_height`.
    5. Compute `total_reserved = reserved_wifi + reserved_top + reserved_bottom`.
    6. If `total_reserved > int(canvas_h_px * 0.55)`, reduce WiFi rows: cap `reserved_wifi = int(canvas_h_px * 0.55) - reserved_top - reserved_bottom`, then `row_height = max(min_row_px, reserved_wifi // num_wifi_rows)`. If even at `min_row_px` the total exceeds 55%, silently skip WiFi rendering (set `num_wifi_rows = 0`) and log a warning — the preset is too small for WiFi info.
    This ensures WiFi rows are never shorter than the minimum font, and the QR code always gets at least 45% of the canvas. Reserved WiFi space is added to the top of the canvas, above `reserved_top` (equipment name).
  - Action: Update ALL layout math to account for `reserved_wifi`:
    - `avail = min(canvas_w_px, canvas_h_px - reserved_wifi - reserved_top - reserved_bottom) - margin` — QR sizing must subtract `reserved_wifi` or the QR code will be oversized.
    - Equipment name row top: `row_top = reserved_wifi` (was `0`).
    - QR paste position: `paste_y = reserved_wifi + reserved_top + ((canvas_h_px - reserved_wifi - reserved_top - reserved_bottom) - qr_px) // 2` — centering denominator must include `reserved_wifi`.
    - URL row top: unchanged (`canvas_h_px - reserved_bottom`).
    - WiFi rows occupy `y=0` through `y=reserved_wifi`.
  - Action: Render WiFi rows at the top:
    - For the header row: render the 🛜 emoji using Noto Emoji font, then "Must be on WiFi" text using DejaVuSans-Bold, positioned side-by-side and centered horizontally.
    - For SSID/password rows: render using `_draw_text_row()` with DejaVuSans-Bold as usual.
  - Notes: Add a `_draw_wifi_header_row()` helper for the compound emoji+text rendering. Load Noto Emoji font path as `os.path.join(current_app.static_folder, 'fonts', 'NotoEmoji-Bold.ttf')`.
    **Sizing strategy for compound render**: Start with emoji height = `row_height - 4` (leave padding). Measure emoji width at that size. Then call `_fit_text('Must be on WiFi', max_width_px=max_text_width - emoji_width - gap, max_height_px=row_height, ...)` to get the text font+rendered string. Position emoji and text side-by-side, vertically centered within the row, horizontally centered as a group. If the combined width exceeds `max_text_width` (1.2× QR width), the text auto-shrinks/truncates via `_fit_text` since it receives the reduced `max_width_px`. On very narrow presets where even the emoji alone is wider than the canvas, fall back to text-only "Must be on WiFi" (no emoji).

- [ ] **Task 9: Update QR form template with WiFi dropdown**
  - File: `esb/templates/equipment/qr.html`
  - Action: Add the `wifi_info` dropdown to the form, between the size dropdown and the include_name checkbox:
    ```html
    <div class="mb-3">
      <label for="{{ form.wifi_info.id }}" class="form-label">{{ form.wifi_info.label.text }}</label>
      {{ form.wifi_info(class="form-select") }}
    </div>
    ```
  - Action: Update the initial preview `<img>` src URL to include `wifi_info` parameter. The existing `url_for()` call in the `src` attribute uses Jinja kwargs — add `wifi_info=form.wifi_info.data` to match the pattern used by `include_name` and `include_url`. The view (Task 7) must pass `form` to the template context with `wifi_info.data` already set to the default value.

- [ ] **Task 10: Update QR preview JavaScript to include WiFi param**
  - File: `esb/static/js/app.js`
  - Action: In the QR preview `update()` function (inside the `#qr-form` IIFE), add `wifi_info` to the URLSearchParams:
    ```js
    var wifiInfo = form.querySelector('[name="wifi_info"]');
    if (wifiInfo) params.set('wifi_info', wifiInfo.value);
    ```
  - Notes: The `change` event listener on the form already catches all `<select>` changes, so the WiFi dropdown triggers preview updates automatically. The preview endpoint has a 5-minute cache (`Cache-Control: private, max-age=300`). Since `wifi_info` is a URL param, different dropdown selections produce different cache entries. However, if an admin changes the SSID/password in the config while a user has the QR form open, the preview may show stale data for up to 5 minutes. This is acceptable — the downloaded PNG always renders with current config values (POST is not cached).

- [ ] **Task 11: Add QR service tests for WiFi rendering**
  - File: `tests/test_services/test_qr_service.py`
  - Action: Add tests to `TestRenderQRPng`:
    - `test_wifi_header_renders_pixels_at_top` — with `wifi_info='header'`, verify non-white pixels exist in the top WiFi region.
    - `test_wifi_none_renders_no_wifi_pixels` — with `wifi_info='none'`, verify the top region is all white (same as current behavior).
    - `test_wifi_ssid_renders_two_rows` — with `wifi_info='ssid'`, verify both header and SSID regions have non-white pixels.
    - `test_wifi_password_renders_three_rows` — with `wifi_info='password'`, verify all three WiFi regions have non-white pixels.
    - `test_wifi_header_qr_still_decodes` — with `wifi_info='header'`, verify pyzbar can still decode the QR payload (text didn't overlap QR region).
    - `test_wifi_info_default_none` — verify default `wifi_info='none'` produces pixel-identical image to calling without WiFi params (see AC 13).
    - `test_wifi_header_small_preset_renders_or_skips` — with `wifi_info='header'` on `sticker_1` preset, verify either: (a) the image renders successfully with non-white pixels at top and a decodable QR, OR (b) if the preset is too small for WiFi rows (row_height < min_row_px after capping), the image renders without WiFi info (graceful skip). This ensures the small-preset guard logic works.
    - `test_wifi_all_rows_small_preset` — with `wifi_info='password'` on `avery_5160` (shortest height preset with WiFi), verify the adaptive sizing either renders with capped row heights or gracefully skips WiFi.
  - Notes: Follow existing test patterns (pixel inspection, pyzbar decode). Use `sticker_4` for happy-path tests where room is guaranteed. Also test at least one small preset (`sticker_1` or `avery_5160`) for the edge cases.
    To compute WiFi region pixel boundaries in tests, replicate the layout math: `min_row_px = _pt_to_px(_MIN_FONT_PT) + 4`, `pct_row_px = int(canvas_h * 0.10)`, `row_height = max(min_row_px, pct_row_px)`. WiFi row N occupies `y=N*row_height` to `y=(N+1)*row_height`. Equipment name row (if present) starts at `y=reserved_wifi`. Crop and inspect each region independently.

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
    - **Update existing test**: `test_config_mutation_logging` currently asserts exactly 6 `app_config.updated` log entries. Adding the three new string fields (`wifi_ssid`, `wifi_password`, `wifi_info_default`) means POSTing `{'tech_doc_edit_enabled': 'y'}` without WiFi fields will cause WTForms to set them to `None`/empty, which may trigger spurious `set_config` calls if the empty value differs from the default. Fix: either include the WiFi fields in the test POST data with their default values, or update the assertion count. The exact fix depends on whether the POST handler's `(getattr(form, key).data or '').strip()` produces `''` for missing SelectField (it does — `None` becomes `''`), which differs from the default `'none'` for `wifi_info_default`. Most robust fix: include `wifi_info_default='none'` in all existing admin config test POSTs, or use `>=` assertion on log count in this specific test.

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

- [ ] **AC 9**: Given a user changes the WiFi Info dropdown on the QR form, when the dropdown value changes, then the live preview image URL is updated (after the existing 150ms debounce) to include the new `wifi_info` query parameter, and the preview re-renders to reflect the selection.

- [ ] **AC 10**: Given a staff user navigates to `/admin/config`, when they view the page, then they see a "WiFi / QR Label Settings" card with fields for WiFi SSID, WiFi Password, and Default WiFi Info dropdown.

- [ ] **AC 11**: Given a staff user sets WiFi SSID to "MakerSpace" and saves, when they reload the config page, then the WiFi SSID field shows "MakerSpace" (value persisted via AppConfig).

- [ ] **AC 12**: Given a staff user clears the WiFi SSID field and saves, when a user opens the QR form, then the SSID and password dropdown options are no longer available.

- [ ] **AC 13**: Given WiFi info is set to "None", when the QR code is rendered, then the output is pixel-identical to the current behavior (no WiFi info, no extra reserved space at top). "Pixel-identical" means: decode both PNGs to RGB pixel arrays and compare — every pixel must match. (PNG byte-identity is not required since metadata/compression may differ.)

- [ ] **AC 14**: Given a very small preset (1"×1" sticker) with WiFi header only enabled (no SSID/password), when the QR code is rendered, then the image renders without error (the existing marginal-module-size warning may fire but rendering completes). With all three WiFi rows + name + URL on a 1"×1" sticker, a ValueError from insufficient QR space is acceptable — the adaptive sizing limits total reserved text to 60% of canvas height to minimize this risk.

- [ ] **AC 15**: Given the QR code is rendered with WiFi header, when scanned with a QR reader, then the QR payload still decodes correctly to the expected URL (WiFi text does not overlap the QR region).

## Additional Context

### Dependencies

No new Python runtime dependencies. Pillow and qrcode are already installed.

**Build-time dependency**: `fontTools` (pip install fontTools) is needed once on the developer's machine to extract the Bold static instance from the Noto Emoji variable font. It is NOT needed at runtime or in the Docker image.

New vendored font: `NotoEmoji-Bold.ttf` (static Bold instance, ~200-400 KB) extracted from Google's Noto Emoji variable font, licensed under SIL Open Font License 1.1. Include `OFL-NotoEmoji.txt` license file alongside the font in `esb/static/fonts/`.

### Testing Strategy

- Unit tests for `qr_service.render_qr_png()` with WiFi info options (verify image dimensions change, text rows are rendered)
- Unit tests for `QRGenerateForm` with dynamic WiFi choices based on config state
- View tests for `qr()` and `qr_preview()` routes with WiFi params
- Admin view tests for new config fields (GET populates, POST saves)
- Edge case: all WiFi config empty → dropdown shows "None" and "🛜 Must be on WiFi" (header requires no config), default is "None"
- Edge case: SSID set but password empty → "Header+SSID+Password" option hidden

### Notes

- **Font limitation resolved**: DejaVuSans-Bold.ttf does NOT contain U+1F6DC (WiFi emoji). Verified via fontTools cmap inspection. Solution: bundle Google's Noto Emoji monochrome font (Bold static instance extracted from the variable font) which contains the glyph as a clean black-and-white WiFi icon (concentric arcs + dot in a rounded square). Rendering uses NotoEmoji-Bold.ttf for the emoji, DejaVuSans-Bold for text. U+1F6DC presence was verified in the source variable font via `fontTools` cmap check; Task 1 includes a verification step for the extracted static instance.
- For very small label presets (1"×1"), adding WiFi header rows reduces available QR space. The adaptive row sizing (Task 8) ensures WiFi rows are never shorter than the minimum font height. If WiFi rows + name + URL would exceed 55% of canvas height, WiFi rendering is silently skipped with a log warning. This prevents both vertical text overflow and QR code sizing failures on small presets.
- The `_fit_text()` function handles graceful degradation: if text is too wide, it shrinks the font down to 8pt, then truncates with ellipsis. This will naturally handle long SSIDs/passwords.
- The `_load_font()` function uses `@lru_cache(maxsize=64)` keyed on `(font_path, size_px)`. The vendored `NotoEmoji-Bold.ttf` is a static font, so it works with this cache without modification. No variable-font axis handling needed at runtime.
