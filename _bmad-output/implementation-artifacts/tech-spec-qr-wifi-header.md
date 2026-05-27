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
  - Notes: Import `Length` validator (already imported in the file). The admin always sees all four options so they can set a default even before configuring SSID/password — they may configure SSID later. Add `form-text` help under the default dropdown: "If the selected default requires SSID or password that is not configured above, users will see 'None' selected instead."

- [ ] **Task 3: Update Admin Config view to handle WiFi settings**
  - File: `esb/views/admin.py`
  - Action: In the `app_config()` view function:
    - **GET**: Populate `form.wifi_ssid.data`, `form.wifi_password.data`, and `form.wifi_info_default.data` from `config_service.get_config()` with defaults `''`, `''`, and `'none'` respectively.
    - **POST**: Add a second loop after the existing boolean `config_keys` loop. Define `string_config_keys = [('wifi_ssid', ''), ('wifi_password', ''), ('wifi_info_default', 'none')]`. For each `(key, default)`, read `new_value = (getattr(form, key).data or '').strip()`, compare to `config_service.get_config(key, default)`, and call `set_config(key, new_value, changed_by=current_user.username)` if changed.
  - Notes: This is a separate loop from the boolean keys because string fields use the raw value directly (no `'true'`/`'false'` conversion). The `.strip()` prevents trailing whitespace in SSID/password values. **Important**: For `wifi_info_default` (a SelectField), if the field is missing from POST data, WTForms sets `.data` to `None`. The coercion `(None or '').strip()` produces `''`, which differs from the default `'none'`, causing a spurious write. Fix: use `(getattr(form, key).data or default).strip()` instead of `(getattr(form, key).data or '').strip()` so that missing/None values fall back to the configured default, not empty string.

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
          <div class="form-text">WiFi password shown <strong>in plaintext</strong> on printed QR labels. Anyone who can see the label can read the password. Leave blank to hide password option.</div>
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
    - On POST: Re-compute WiFi choices from current config (config may have changed since GET). If `form.wifi_info.data` is not in the current choices, apply the same graceful-degradation clamping as the preview endpoint (password→ssid→header). If clamping occurred, flash an info message: "WiFi settings changed since you loaded this page — your download was adjusted to '{clamped_value}'." Then pass the (possibly clamped) `wifi_info` and wifi config values to `render_qr_png()`. Note: do NOT rely solely on `validate_on_submit()` for this — WTForms SelectField validation would reject a value not in choices and silently re-render the form with no explanation. Instead, manually validate/clamp `wifi_info` before calling `validate_on_submit()`, or override the form's choices before validation.
    - Update the audit log line to include `wifi_info`: `'QR downloaded: user=%s equipment_id=%s preset=%s include_name=%s include_url=%s wifi_info=%s'`.
    - Pass wifi config to template context for initial preview URL.
  - Action in `qr_preview()`:
    - Read `wifi_info` from `request.args.get('wifi_info', 'none')`.
    - Read wifi config values from `config_service`.
    - **Validate `wifi_info` against available config** (graceful degradation): if `wifi_info='password'` but `wifi_password` is empty, clamp to `'ssid'`; if `wifi_info='ssid'` but `wifi_ssid` is empty, clamp to `'header'`. The `header` option is always valid (requires no config). This means a crafted URL `?wifi_info=ssid` with no SSID configured renders a "Must be on WiFi" header rather than nothing — this is intentional: we always prefer showing *some* WiFi notice over showing none. The only way to get no WiFi info is `wifi_info=none`.
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
  - Action: Calculate text row heights using a **two-mode layout system** that preserves backward compatibility:

    **Mode A — No WiFi (`num_wifi_rows == 0`)**: Use the EXISTING layout logic unchanged:
    - `reserved_top = int(canvas_h_px * 0.15) if include_name else 0`
    - `reserved_bottom = int(canvas_h_px * 0.15) if include_url else 0`
    - `reserved_wifi = 0`
    This ensures pixel-identical output for `wifi_info='none'` (AC 13).

    **Mode B — WiFi active (`num_wifi_rows > 0`)**: Use a budget system for WiFi rows only. Name/URL rows keep their existing 15% allocation:
    1. `reserved_top = int(canvas_h_px * 0.15) if include_name else 0`
    2. `reserved_bottom = int(canvas_h_px * 0.15) if include_url else 0`
    3. `min_row_px = _pt_to_px(_MIN_FONT_PT) + 4` (= 37px at 300 DPI). Absolute floor for WiFi rows.
    4. `wifi_budget = int(canvas_h_px * 0.30)` — WiFi rows share up to 30% of canvas height.
    5. `wifi_row_height = wifi_budget // num_wifi_rows`.
    6. `wifi_row_height = max(wifi_row_height, min_row_px)` — never below min font.
    7. If `reserved_top + reserved_bottom + num_wifi_rows * wifi_row_height > int(canvas_h_px * 0.55)`: drop WiFi rows from bottom up (password → SSID → header) until total fits or WiFi rows reach 0. Update a local `effective_wifi_rows` variable (and corresponding `effective_wifi_info` — e.g., 'password'→'ssid' if password row dropped). Log a warning for each dropped row. **All subsequent rendering must use `effective_wifi_rows` / `effective_wifi_info`, not the original `wifi_info` parameter.** If `effective_wifi_rows` reaches 0, set `reserved_wifi = 0` — the remaining layout (name, QR, URL) is identical to Mode A by construction since `reserved_top`/`reserved_bottom` use the same 15% formula.
    8. If `effective_wifi_rows > 0`: `wifi_row_height = wifi_budget // effective_wifi_rows`. Else: `wifi_row_height = 0`.
    9. `reserved_wifi = effective_wifi_rows * wifi_row_height`.

    This keeps name/URL at their existing 15% sizes, gives WiFi rows up to 30%, and caps total text at 55% (15% + 15% + 30% max = 60% before capping; the drop loop handles overflow). The QR code gets at least 45% of canvas. WiFi rows at top, name row next, QR in middle, URL at bottom.
  - Action: Update ALL layout math to account for `reserved_wifi`:
    - `avail = min(canvas_w_px, canvas_h_px - reserved_wifi - reserved_top - reserved_bottom) - margin` — QR sizing must subtract `reserved_wifi` or the QR code will be oversized.
    - Equipment name row top: `row_top = reserved_wifi` (was `0`).
    - QR paste position: `paste_y = reserved_wifi + reserved_top + ((canvas_h_px - reserved_wifi - reserved_top - reserved_bottom) - qr_px) // 2` — centering denominator must include `reserved_wifi`.
    - URL row top: unchanged (`canvas_h_px - reserved_bottom`).
    - WiFi rows occupy `y=0` through `y=reserved_wifi`.
  - Action: Compute `max_text_width` for WiFi rows: use `max(int(qr_px * 1.2), int(canvas_w_px * 0.90))`. This ensures WiFi text on landscape-oriented presets (e.g., Avery 5160 at 2.625"×1") can use up to 90% of canvas width instead of being constrained to 120% of the small QR code. The existing `max_text_width = int(qr_px * 1.2)` continues to be used for equipment name and URL rows (backward compat).
  - Action: Render WiFi rows at the top:
    - For the header row: render the 🛜 emoji using Noto Emoji font, then "Must be on WiFi" text using DejaVuSans-Bold, positioned side-by-side and centered horizontally.
    - For SSID/password rows: render using `_draw_text_row()` with DejaVuSans-Bold as usual.
  - Notes: Add a `_draw_wifi_header_row()` helper for the compound emoji+text rendering. Load Noto Emoji font path as `os.path.join(current_app.static_folder, 'fonts', 'NotoEmoji-Bold.ttf')`. Include an `os.path.isfile()` guard with a diagnostic `RuntimeError` matching the existing pattern in `_draw_text_row()` (e.g., "QR WiFi emoji font missing at {path}. Ensure NotoEmoji-Bold.ttf is vendored in esb/static/fonts/.").
    **Sizing strategy for compound render**: 
    1. Call `_fit_text('Must be on WiFi', max_width_px=int(max_text_width * 0.75), max_height_px=wifi_row_height, ...)` to get the text font + rendered string. This gives text up to 75% of `max_text_width`.
    2. Set `emoji_size_px = text_font.size` (match the emoji to the *final* text font size, so they look proportional even after text shrinks).
    3. Load emoji font at `emoji_size_px`. Measure emoji width.
    4. If `emoji_width + gap + text_width > max_text_width`, re-run `_fit_text` with further reduced `max_width_px` to accommodate the emoji.
    5. Position emoji and text side-by-side, vertically centered within the row, horizontally centered as a group.
    6. If even the emoji alone at `min_row_px` is wider than `max_text_width`, fall back to text-only "Must be on WiFi" (no emoji). Note: the threshold is `max_text_width` (1.2× QR width), not canvas width.

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
    - `test_wifi_header_renders_pixels_at_top` — with `wifi_info='header'`, verify non-white pixels exist in the top WiFi region. Additionally, measure the horizontal extent of rendered content (leftmost to rightmost non-white pixel) and assert it spans at least 2× the height of the region (since emoji + "Must be on WiFi" text together should be much wider than a single glyph). This catches cases where only the emoji or only the text rendered.
    - `test_wifi_none_renders_no_wifi_pixels` — with `wifi_info='none'`, verify the top region is all white (same as current behavior).
    - `test_wifi_ssid_renders_two_rows` — with `wifi_info='ssid'`, verify both header and SSID regions have non-white pixels.
    - `test_wifi_password_renders_three_rows` — with `wifi_info='password'`, verify all three WiFi regions have non-white pixels.
    - `test_wifi_header_qr_still_decodes` — with `wifi_info='header'`, verify pyzbar can still decode the QR payload (text didn't overlap QR region).
    - `test_wifi_info_none_backward_compatible` — Render the same equipment item twice: once with `wifi_info='none'` (the new default) and once without the `wifi_info` parameter at all (to simulate pre-feature behavior). Decode both to RGB pixel arrays and assert they are identical. This validates AC 13's pixel-identity guarantee. Additionally, render with `wifi_info='none'` + `include_name=True` and verify the name row starts at `y=0` (not shifted down) — confirming `reserved_wifi == 0`.
    - `test_wifi_header_small_preset_renders_or_skips` — with `wifi_info='header'` on `sticker_1` preset, verify either: (a) the image renders successfully with non-white pixels at top and a decodable QR, OR (b) if the preset is too small for WiFi rows (row_height < min_row_px after capping), the image renders without WiFi info (graceful skip). This ensures the small-preset guard logic works.
    - `test_wifi_all_rows_small_preset` — with `wifi_info='password'` on `avery_5160` (shortest height preset with WiFi), verify the adaptive sizing either renders with capped row heights or gracefully skips WiFi.
  - Notes: Follow existing test patterns (pixel inspection, pyzbar decode). Use `sticker_4` for happy-path tests where room is guaranteed. Also test at least one small preset (`sticker_1` or `avery_5160`) for the edge cases.
    To compute pixel boundaries in tests, replicate the two-mode layout: when `num_wifi_rows > 0`, `wifi_budget = int(canvas_h * 0.30)`, `wifi_row_height = max(wifi_budget // num_wifi_rows, min_row_px)`, `reserved_wifi = num_wifi_rows * wifi_row_height`. WiFi row N occupies `y=N*wifi_row_height` to `y=(N+1)*wifi_row_height`. Name row starts at `y=reserved_wifi` with height `int(canvas_h * 0.15)`. When `num_wifi_rows == 0`, use existing 15% math unchanged. Crop and inspect each region independently.

- [ ] **Task 12: Add QR view tests for WiFi functionality**
  - File: `tests/test_views/test_equipment_views.py`
  - Action: Add tests to `TestEquipmentQR`:
    - `test_qr_form_shows_wifi_dropdown` — verify `name="wifi_info"` appears in the form HTML.
    - `test_qr_form_wifi_choices_no_config` — with no WiFi config, verify only `none` and `header` options are present.
    - `test_qr_form_wifi_choices_ssid_only` — with `wifi_ssid` config set, verify `ssid` option appears but `password` does not.
    - `test_qr_form_wifi_choices_ssid_and_password` — with both config set, verify all four options appear.
    - `test_qr_form_wifi_default_from_config` — with `wifi_info_default='header'`, verify the dropdown defaults to `header`.
    - `test_qr_form_wifi_default_fallback_no_password` — with `wifi_info_default='password'`, `wifi_ssid='MyNet'`, but no `wifi_password` config, verify fallback to `none` (password not in choices, configured default invalid).
    - `test_qr_form_wifi_default_fallback_no_ssid` — with `wifi_info_default='ssid'` but no `wifi_ssid` config, verify fallback to `none`.
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
    - **Update existing test**: `test_config_mutation_logging` currently asserts exactly 6 `app_config.updated` log entries when POSTing `{'tech_doc_edit_enabled': 'y'}`. After adding WiFi fields, the POST data must include `wifi_info_default='none'`, `wifi_ssid=''`, `wifi_password=''` to match their defaults and prevent spurious `set_config` calls. Update the POST data in this test (and any other admin config tests that POST partial data) to include the WiFi fields at their default values. Keep the exact-count assertion — do NOT use `>=` as that makes the test a no-op.

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

- [ ] **AC 14**: Given a very small preset (1"×1" sticker) with WiFi header only enabled (no SSID/password), when the QR code is rendered, then the image renders without error (the existing marginal-module-size warning may fire but rendering completes). With all three WiFi rows + name + URL on a 1"×1" sticker, WiFi rows may be dropped (password → SSID → header) if they can't fit at minimum font size within the 55% text budget. The QR code always gets at least 45% of the canvas.

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
- For very small label presets (1"×1"), adding WiFi header rows reduces available QR space. The two-mode layout (Task 8) preserves existing 15% name/URL sizing when WiFi is off, and allocates up to 30% for WiFi rows when active, capped so total text never exceeds 55%. If WiFi rows can't fit at minimum font height (37px at 300 DPI), they're dropped from bottom up (password → SSID → header). This prevents both vertical text overflow and QR code sizing failures on small presets.
- The `_fit_text()` function handles graceful degradation: if text is too wide, it shrinks the font down to 8pt, then truncates with ellipsis. This will naturally handle long SSIDs/passwords.
- **Pre-existing latent bug in `_fit_text`**: The step-based shrink loop (`size_px -= step`) can skip `min_px` when `max_height_px` is not congruent to `min_px` modulo `step`. WiFi text (SSID/password strings) is more likely to hit this than short equipment names. As part of Task 8, fix this: after the while loop exits (with `size_px < min_px`), check whether the **full text** fits at exactly `min_px`: `font = _load_font(font_path, min_px); if width_at(text, font) <= max_width_px: return font, text`. The font is already loaded at `min_px` on line 179 of the current code — the missing piece is the width check before jumping to truncation.
- The `_load_font()` function uses `@lru_cache(maxsize=64)` keyed on `(font_path, size_px)`. The vendored `NotoEmoji-Bold.ttf` is a static font, so it works with this cache without modification. No variable-font axis handling needed at runtime. Note: the WiFi feature adds a second font file and potentially more shrink iterations, which increases cache pressure. If preview performance degrades under concurrent load, consider increasing `maxsize` to 128.
- **Mode B `_fit_text` height constraint**: The `min_row_px` floor (37px) in Mode B ensures `_fit_text` always receives `max_height_px >= min_px` (33px), so the shrink loop always executes at least once. If for any reason `wifi_row_height` is passed to `_fit_text` at a value below `min_px`, the function's existing fallback (load font at `min_px` then truncate) will render text taller than the row — but Mode B's guard prevents this case.
- **Pre-existing TOCTOU race**: The admin config POST handler reads config, compares, then writes. Concurrent admin saves can produce duplicate audit log entries. This is a pre-existing limitation of the `config_service` pattern, not introduced by this feature.
