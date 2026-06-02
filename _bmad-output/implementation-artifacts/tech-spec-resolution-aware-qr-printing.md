---
title: 'Resolution-Aware QR Label Printing'
slug: 'resolution-aware-qr-printing'
created: '2026-06-02'
status: 'completed'
stepsCompleted: [1, 2, 3, 4]
tech_stack: ['Python 3.14', 'Flask', 'Flask-WTF (WTForms SelectField)', 'qrcode[pil]', 'Pillow (PIL)', 'pytest', 'vanilla JS (esb/static/js/app.js)']
files_to_modify: ['esb/services/qr_service.py', 'esb/forms/equipment_forms.py', 'esb/views/equipment.py', 'esb/templates/equipment/qr.html', 'esb/static/js/app.js', 'tests/test_services/test_qr_service.py', 'tests/test_views/test_equipment_views.py', 'docs/staff.md', 'docs/manual_testing.md', 'docs/images/qr-generation.png']
code_patterns: ['Frozen dataclass preset + tuple + by-key dict (QRSizePreset / QR_SIZE_PRESETS / QR_PRESETS_BY_KEY)', 'Service returns in-memory PNG bytes; views send_file', 'WTForms SelectField choices built from preset tuples', 'Live preview via debounced JS rebuilding qr_preview URL', 'ValueError from service -> flash danger + re-render form']
test_patterns: ['pytest classes grouping behaviors', 'parametrize over QR_SIZE_PRESETS', 'PIL Image.open(BytesIO) dimension/pixel assertions', 'pyzbar decode for payload', 'view tests via staff_client/tech_client + configured_base_url fixture', 'template assertions on response.data substrings']
---

# Tech-Spec: Resolution-Aware QR Label Printing

**Created:** 2026-06-02

## Overview

### Problem Statement

QR code labels are rendered at a **hardcoded 300 DPI** (`_DPI = 300` in `esb/services/qr_service.py`), so every label's pixel size is fixed at `physical_inches × 300`. The generated PNG carries **no DPI metadata**. As a result, labels print at the wrong physical size on any printer whose resolution is not 300 DPI:

- On a **1200 DPI** laser printer, a "4×4" label is a 1200×1200 px image. Printed at native pixels it is ~1″; printed "fit to page" it fills a letter sheet — never the intended 4″.
- On a **Sato M-84Pro-2 thermal label printer @ 203 dpi** (a raster device where 1 dot = 1 px), the 1200×1200 px image spans 1200 ÷ 203 ≈ 5.9″, overflowing a 4″-wide label and clipping to roughly a quarter of the image.

### Solution

Decouple physical size from a fixed DPI. Introduce **named printer/device presets**, each carrying a DPI value. Render each label at `physical_inches × selected_device_DPI` and **embed DPI metadata** into the output PNG so the OS/CUPS "actual size" print path reproduces the correct physical dimensions. The existing size presets and PNG output format are retained; a device/DPI selector is added to the generation form, preview, and download paths.

### Scope

**In Scope:**

- New named **device/DPI presets**: `Thermal Label (203 dpi)`, `Brother P-Touch (180 dpi)`, `Laser/Inkjet (300 dpi)`, `Laser/Inkjet (600 dpi)`, `Laser/Inkjet (1200 dpi)`. Default = **300 dpi** (backward compatible).
- DPI-parameterized rendering in `esb/services/qr_service.py` (replace the `_DPI = 300` constant with a per-call DPI argument threaded through `_px`/`_pt_to_px` and `render_qr_png`).
- **Embed DPI metadata** in the saved PNG (Pillow `save(..., dpi=(d, d))`).
- Wire the DPI selection through `QRGenerateForm` (new `SelectField`), the `/equipment/<id>/qr` (download) and `/equipment/<id>/qr/preview` views, and the `equipment/qr.html` template (selector + live-preview data binding).
- Update unit tests (`tests/test_services/test_qr_service.py`) and view tests (`tests/test_views/test_equipment_views.py`) for DPI-driven dimensions and metadata.
- Update user documentation (`docs/staff.md` QR Code Labels section, `docs/manual_testing.md` section 11) including a refreshed screenshot (`docs/images/qr-generation.png`) if the form UI changes.

**Out of Scope:**

- PDF / vector output formats.
- Raw raster-to-printer / direct printing from ESB (no print pipeline integration).
- Label-design-software export paths.
- Changing the existing size preset list (1/1.5/2/3/4″ stickers, Avery 5160/5163, US Letter).

## Context for Development

### Codebase Patterns

- **Preset model.** Sizes use a frozen dataclass `QRSizePreset(key, label, width_in, height_in)`, a `QR_SIZE_PRESETS` tuple, and a `QR_PRESETS_BY_KEY` dict (`esb/services/qr_service.py:26-45`). **The new device/DPI presets must mirror this exact pattern**: `QRDevicePreset(key, label, dpi)`, `QR_DEVICE_PRESETS`, `QR_DEVICES_BY_KEY`.
- **DPI is currently a module global** `_DPI = 300` (`qr_service.py:16`) consumed by `_px()` (`:48`) and `_pt_to_px()` (`:52`). `_pt_to_px(_MIN_FONT_PT)` also drives the font floor inside `_fit_text` (`:295`) and the WiFi `min_row_px` (`:82`). DPI therefore must be threaded *through the call chain*, not just into `_px`.
- **Service returns PNG bytes**, saved via `canvas.save(buf, format='PNG')` (`:181`) — no `dpi=` kwarg today, so the PNG has no physical-size metadata. Pillow embeds DPI when saving with `dpi=(d, d)`.
- **Form choices** are list-comprehended from preset tuples (`esb/forms/equipment_forms.py:133-138`), `SelectField` + `DataRequired()` → unknown keys are auto-rejected by WTForms.
- **Two render entry points**: `qr()` download (`esb/views/equipment.py:275-342`) resolves `preset = QR_PRESETS_BY_KEY[form.size.data]` and calls `render_qr_png`; `qr_preview()` (`:345-389`) reads query params (`size`, `include_name`, `include_url`, `wifi_info`), aborts 400 on unknown size, and serves an inline PNG with `Cache-Control: private, max-age=300`.
- **Live preview JS** (`esb/static/js/app.js:239-263`) is a debounced (150 ms) listener on `#qr-form` that rebuilds `qr_preview` query params from form fields. A new `device` field must be added here AND to the template's initial preview `src` (`equipment/qr.html:46`).
- **Error UX**: a `ValueError` from the service is caught in `qr()` and flashed as `danger` while re-rendering the form (`:323-325`); `qr_preview()` maps `ValueError` → `abort(400)`.

### Files to Reference

| File | Purpose |
| ---- | ------- |
| `esb/services/qr_service.py` | Core: replace `_DPI` global with a per-call `dpi`; add `QRDevicePreset`/`QR_DEVICE_PRESETS`/`QR_DEVICES_BY_KEY`; thread `dpi` through `_px`,`_pt_to_px`,`render_qr_png`,`_draw_text_row`,`_draw_wifi_header_row`,`_fit_text`; embed PNG DPI on save; add oversized-canvas guard. |
| `esb/forms/equipment_forms.py` | `QRGenerateForm` (`:130-150`) — add `device` `SelectField` (choices from `QR_DEVICE_PRESETS`, default `laser_300`). |
| `esb/views/equipment.py` | `qr()` and `qr_preview()` — resolve selected device → `dpi`, pass to `render_qr_png`; preview reads `device` query param (default `laser_300`, abort 400 on unknown). |
| `esb/templates/equipment/qr.html` | Add device `<select>`; add `device` to initial preview `src` (`:46`); update the static "300 DPI" caption (`:49`). |
| `esb/static/js/app.js` | QR preview IIFE (`:239-263`) — include `device` in the rebuilt preview URL params. |
| `tests/test_services/test_qr_service.py` | Update `test_dimensions_match_preset_at_300_dpi` + WiFi-budget math (hardcodes `*300`, `int(8*300/72+0.5)` at `:53,:466`); add device-preset + DPI-dimension + PNG-metadata + oversized-guard tests. |
| `tests/test_views/test_equipment_views.py` | QR view tests (`:1552-1864`) — add device dropdown render, download-honors-DPI, preview-includes-device, invalid-device handling. |
| `docs/staff.md` | "QR Code Labels" section (`:132-158`) — document the printer/device selector and how to match it to your printer; refresh `images/qr-generation.png`. |
| `docs/manual_testing.md` | Section 11 "QR Code Label Generation" (`:302-327`) — add device-resolution test steps + expected physical-size results. |
| `docs/images/qr-generation.png` | Regenerate screenshot to show the new device selector. |

### Technical Decisions

- **DPI source = named device preset, not a free numeric field.** Device presets (default first): `laser_300` "Laser/Inkjet (300 dpi)" *(default, backward-compatible)*, `laser_600` "Laser/Inkjet (600 dpi)", `laser_1200` "Laser/Inkjet (1200 dpi)", `thermal_203` "Thermal Label (203 dpi)" *(generic — covers the Sato M-84Pro-2 and similar; intentionally NOT Sato-branded)*, `ptouch_180` "Brother P-Touch (180 dpi)".
- **`render_qr_png` gains a keyword-only `dpi: int = 300`.** Defaulting to 300 keeps every existing service-level test green and the legacy default path **dimensionally identical** (same pixel size and visual content). The output **bytes** differ slightly because the new `dpi=` save kwarg adds a `pHYs` metadata chunk even at 300 dpi — so no test should assert byte-equality against old fixtures. The `_px`/`_pt_to_px` helpers take `dpi` as an argument (drop the `_DPI` global).
- **Low-DPI scannability is a known trade-off.** With `box_size=1, border=4, ERROR_CORRECT_M`, small stickers at the new low-DPI devices produce few pixels per module: a 1″ sticker at 180 dpi and at 203 dpi (with a realistic base URL) yields `module_px = 4`, tripping the existing `module_px < 5` "scannability may be marginal" warning (`qr_service.py:128`). This is acceptable (the warning already exists and only logs), but it is **documented** in `docs/staff.md` (Task 9.3) so users avoid tiny labels on low-res printers. No code change to the threshold.
- **Embed DPI metadata** via `canvas.save(buf, format='PNG', dpi=(dpi, dpi))` so the CUPS/OS "actual size" print path reproduces the intended physical inches. This is the fix for the desktop-printer mis-scaling; correct pixel count is the fix for the thermal-printer clipping.
- **Preview honors the selected device DPI** (renders at the real DPI) so the preview faithfully predicts the download — including the `avail < native` "URL too long" boundary, which is DPI-sensitive. The preview `<img>` remains scaled to ≤400 px for display.
- **No stale-cache risk from the new `device` param.** `qr_preview` serves via `send_file(BytesIO(...))`, which (with no filename) emits **no ETag/Last-Modified**, so there is no conditional-request 304 keyed on URL. The `Cache-Control: private, max-age=300` is a private per-URL cache; adding `device` to the query string simply produces a distinct cache key, so changing the device yields a fresh render with no risk of serving a previously-cached preview at a different DPI.
- **Oversized-canvas guard.** Because high DPI × large physical size can produce enormous canvases (US Letter @ 1200 dpi ≈ 10200×13200 ≈ 134 MP), `render_qr_png` raises a friendly `ValueError` when `canvas_w_px * canvas_h_px` exceeds a cap (proposed **50 MP**), reusing the existing flash-danger / abort-400 paths. (4″ sticker @ 1200 dpi = 23 MP and Letter @ 600 dpi = 34 MP both pass.) **Memory note:** a 50 MP RGB canvas is ~150 MB resident, and the render holds the QR intermediate + PNG-encode buffer concurrently, so the transient peak is ~2–3×. The primary goal is preventing the 134 MP catastrophe; if the deployment runs many concurrent gunicorn workers under a tight container memory limit (`docker-compose.yml` `app` service), consider lowering the cap (e.g. 35 MP, which still allows Letter @ 600 dpi but blocks Letter @ 1200) — the constant is the single tuning point. Treat 50 MP as a deliberate, adjustable default, not a proven-safe constant.
- **No DB/migration, no new dependency** — Pillow already supports the `dpi` save kwarg.

### Technical Preferences & Constraints (from discovery)

- **Print pipeline is the OS print dialog (CUPS):** the user saves the PNG and prints it via the system dialog. This is why the fix is *raster sizing + embedded DPI metadata* (not vector/PDF). Correct DPI metadata lets CUPS "actual size" produce the right physical dimensions; correct pixel count makes raw/native raster paths (thermal) fit the label.
- **DPI selection via named device presets** (not a raw numeric DPI field). Preset labels are device-oriented and friendly: `Thermal Label (203 dpi)` (covers the Sato M-84Pro-2 and similar 203-dpi thermal printers — intentionally generic, not Sato-specific), `Brother P-Touch (180 dpi)`, and `Laser/Inkjet` at 300/600/1200 dpi.
- **Default device = 300 dpi** to preserve existing output dimensions/visual content for the legacy default (raw bytes change slightly due to the added `pHYs` chunk — see Technical Decisions).
- **Keep PNG and existing size presets.** Only the DPI/pixel scaling and metadata change.
- **Documentation must be updated** alongside code: end-user (`docs/staff.md`) and manual test plan (`docs/manual_testing.md`), with a refreshed screenshot if the form gains a visible field.

### Known landmarks (orientation only — the Tasks below carry the authoritative, exact line citations)

- `esb/services/qr_service.py` — `_DPI = 300` (line ~16), `_px()` / `_pt_to_px()` helpers (lines ~48–53), `QR_SIZE_PRESETS` (lines ~34–45), `render_qr_png()` (lines ~56–182), PNG save call.
- `esb/forms/equipment_forms.py` — `QRGenerateForm` (lines ~130–150).
- `esb/views/equipment.py` — `qr()` (lines ~277–342) and `qr_preview()` (lines ~347–389).
- `esb/templates/equipment/qr.html` — size selector + preview `src` binding.
- `tests/test_services/test_qr_service.py` — `test_dimensions_match_preset_at_300_dpi` and module-uniformity tests.
- `tests/test_views/test_equipment_views.py` — QR form/download/preview tests (~line 1550+).
- `docs/staff.md` (QR Code Labels, ~line 132), `docs/manual_testing.md` (section 11, ~line 302), `docs/images/qr-generation.png`.

## Implementation Plan

### Tasks

> Ordered lowest-level-first. Each task is independently completable; later tasks depend on earlier ones.

- [x] **Task 1: Add the device/DPI preset model to the service.**
  - File: `esb/services/qr_service.py`
  - Action: After `QR_PRESETS_BY_KEY` (line 45), add a frozen dataclass and tuple/dict mirroring the size-preset pattern:
    ```python
    @dataclass(frozen=True)
    class QRDevicePreset:
        key: str
        label: str
        dpi: int

    QR_DEVICE_PRESETS: tuple[QRDevicePreset, ...] = (
        QRDevicePreset('laser_300', 'Laser/Inkjet (300 dpi)', 300),
        QRDevicePreset('laser_600', 'Laser/Inkjet (600 dpi)', 600),
        QRDevicePreset('laser_1200', 'Laser/Inkjet (1200 dpi)', 1200),
        QRDevicePreset('thermal_203', 'Thermal Label (203 dpi)', 203),
        QRDevicePreset('ptouch_180', 'Brother P-Touch (180 dpi)', 180),
    )
    QR_DEVICES_BY_KEY: dict[str, QRDevicePreset] = {p.key: p for p in QR_DEVICE_PRESETS}
    DEFAULT_DEVICE_KEY = 'laser_300'
    ```
  - Notes: Keep `laser_300` first so it is the natural default. `thermal_203` label is intentionally generic (covers the Sato M-84Pro-2), not Sato-branded.

- [x] **Task 2: Parameterize the service by DPI (replace the `_DPI` global).**
  - File: `esb/services/qr_service.py`
  - Action:
    1. Delete the module global `_DPI = 300` (line 16).
    2. Change helpers to take `dpi`: `def _px(inches: float, dpi: int) -> int: return int(inches * dpi + 0.5)` and `def _pt_to_px(pt: int, dpi: int) -> int: return int(pt * dpi / 72 + 0.5)`.
    3. Add `dpi: int = 300` as a keyword-only param to `render_qr_png` (in the existing `*,` keyword block).
    4. Update the two `_px(...)` calls (lines 72-73) to `_px(preset.width_in, dpi)` / `_px(preset.height_in, dpi)`.
    5. Update the WiFi `min_row_px = _pt_to_px(_MIN_FONT_PT) + 4` (line 82) to pass `dpi`.
    6. Thread `dpi` into the draw helpers that compute the font floor: add a **keyword-only `dpi: int = 300`** param to `_draw_text_row`, `_draw_wifi_header_row`, and `_fit_text`; replace `_pt_to_px(_MIN_FONT_PT)` inside `_fit_text` (line 295) with `_pt_to_px(_MIN_FONT_PT, dpi)`. **The `= 300` default is mandatory, not optional** — `_fit_text` already has four direct callers in `TestFitText` (`tests/test_services/test_qr_service.py:264, 275, 283, 295`) that pass no `dpi`; a required param would break all four. Keyword-only (`*`) still prevents a forgotten *positional* from silently shifting an existing arg, while the default keeps those callers green.
    7. **Pass `dpi` at EVERY production call site — there are two layers:**
       - **From `render_qr_png`:** the `_draw_text_row(...)` calls at lines 161, 168, 173 and the `_draw_wifi_header_row(...)` call at line 156.
       - **From inside `_draw_wifi_header_row` (easy to miss — the WiFi-header fallback branches):** its two internal `_fit_text(...)` calls at lines **217** and **243**, and its three internal `_draw_text_row(...)` calls at lines **213**, **238**, and **248**. With the `= 300` default these won't raise `TypeError` if missed, but they will **silently keep a 300-dpi font floor** at other DPIs — so all five MUST forward `dpi` for correct text sizing on thermal/low-DPI labels.
  - Notes: Default `dpi=300` on `render_qr_png` and on these helpers keeps the legacy path and all current `*300` test assertions valid. The 8 pt font floor is physical, so scaling it by DPI is correct.

- [x] **Task 3: Embed DPI metadata in the PNG + add the oversized-canvas guard.**
  - File: `esb/services/qr_service.py`
  - Action:
    1. Change the save call (line 181) to `canvas.save(buf, format='PNG', dpi=(dpi, dpi))`.
    2. Immediately after computing `canvas_w_px`/`canvas_h_px` (after line 73), add:
       ```python
       MAX_CANVAS_PX = 50_000_000
       if canvas_w_px * canvas_h_px > MAX_CANVAS_PX:
           raise ValueError(
               f'{preset.label} at {dpi} dpi is too large to render — '
               'choose a lower-resolution printer or a smaller size.'
           )
       ```
  - Notes: Module-level `MAX_CANVAS_PX` constant is fine too. Guard runs before the expensive QR/image work. Reuses the existing `ValueError` → flash-danger / abort-400 handling. **Be aware:** adding the `dpi=` save kwarg injects a `pHYs` chunk into the PNG even at 300 dpi, so the output bytes change vs. today (a tiny sample PNG grows ~20 bytes). **Pixel dimensions are unchanged**, but do NOT write any test asserting byte-identical output against pre-change fixtures.

- [x] **Task 4: Add the `device` field to the generation form.**
  - File: `esb/forms/equipment_forms.py`
  - Action: In `QRGenerateForm` (lines 130-142), import `QR_DEVICE_PRESETS` from `esb.services.qr_service` (alongside the existing `QR_SIZE_PRESETS` import) and add, after `size`:
    ```python
    device = SelectField(
        'Printer / device',
        choices=[(p.key, p.label) for p in QR_DEVICE_PRESETS],
        validators=[DataRequired()],
        default='laser_300',
    )
    ```
  - Notes: `DataRequired` + `SelectField` auto-rejects unknown keys, matching the `size` field's behavior.

- [x] **Task 5: Thread the selected device → DPI through both views.**
  - File: `esb/views/equipment.py`
  - Action:
    1. In `qr()` (after resolving `preset`, ~line 312): `device = qr_service.QR_DEVICES_BY_KEY[form.device.data]` and pass `dpi=device.dpi` to `render_qr_png(...)` (~line 314). Add `device=%s` to the existing "QR downloaded" log line (line 330-334) — add **both** the `device=%s` format token in the message string **and** a matching `device.key` argument in the args tuple (the current line already logs `preset=%s ... wifi_info=%s`; a token without its arg, or vice-versa, raises a `TypeError`/`%`-format error at log time).
    2. In `qr_preview()` (~line 355): read `device_key = request.args.get('device', qr_service.DEFAULT_DEVICE_KEY)`, look up `device = qr_service.QR_DEVICES_BY_KEY.get(device_key)`, `if device is None: abort(400)` (mirroring the `size` handling at lines 356-358), and pass `dpi=device.dpi` to `render_qr_png(...)`.
    3. **Clamp an invalid `device` on form re-render (purely a UI guard, NOT a TOCTOU fix).** On a failed POST, WTForms leaves `form.device.data` set to the submitted (possibly bogus) value, and the template feeds it straight into the preview `src` (Task 6.2) → a broken 400 preview image. In the `_render_form_with_real_choices()` helper (`equipment.py:299-303`, the shared re-render path), add: `if form.device.data not in qr_service.QR_DEVICES_BY_KEY: form.device.data = qr_service.DEFAULT_DEVICE_KEY` so the re-rendered preview always points at a valid device. **Distinction from the `wifi_info` clamp:** the existing `wifi_info` clamp in this helper exists because WiFi choices are *dynamic* and can legitimately go stale (config TOCTOU). `device` choices are *static*, so a bogus value can only arrive via a crafted/replayed POST that already failed validation — this clamp is solely to keep the re-rendered preview `src` valid, not to reconcile live choices. Structurally similar, different rationale.
  - Notes: POST builds the form with `validation_choices` only for `wifi_info`; `device` choices are static on the form, so the device value is validated by WTForms automatically — but validation failure does NOT sanitize `form.device.data`, hence the explicit clamp in step 3.

- [x] **Task 6: Wire the device selector into the template + live preview JS.**
  - File: `esb/templates/equipment/qr.html`
  - Action:
    1. Add a `<select>` block for `form.device` immediately after the `size` block (lines 22-25), same markup pattern.
    2. Add `device=form.device.data or 'laser_300'` to the initial preview `src` `url_for(...)` (line 46).
    3. Replace the **entire** caption line (`qr.html:49`, currently `Preview is scaled to fit; downloaded PNG is at 300 DPI.`) with a device-aware version that **keeps** the scaling clause, e.g. *"Preview is scaled to fit. The downloaded PNG is sized to your selected printer resolution and physical size."* (Replace the whole `<p>` text, not just the `300 DPI` substring.)
    4. **Graceful preview failure (G3 / oversized + invalid-device cases).** When the selected size+device trips the oversized guard or is otherwise invalid, `qr_preview` now returns HTTP 400 and the `<img>` would show a raw broken-image icon with no explanation. Add a sibling element (e.g. `<span id="qr-preview-error" class="text-danger small d-none">Preview unavailable at this size and resolution — the label is too large to render. Choose a lower resolution or smaller size.</span>`) and wire an `onerror`/`onload` toggle (see JS action) so the user gets a readable message instead of a broken image. The *download* path already flashes a danger message; this closes the preview-side gap.
  - File: `esb/static/js/app.js`
  - Action:
    1. In the QR preview IIFE (lines 246-255), read the device field and add it to `params`: `var device = form.querySelector('[name="device"]'); if (device) params.set('device', device.value);`.
    2. **Attach `img.onerror` / `img.onload` ONCE at IIFE init** (alongside the `var img = ...` lookup at `app.js:243`, *not* inside `update()`), so they persist across every debounced `img.src` reassignment: `onerror` reveals `#qr-preview-error` and hides the `<img>`; `onload` hides the error and re-shows the `<img>`. This degrades a 400 preview response to the readable message from Task 6.3 step 4 rather than a broken-image icon. (Handlers are pure state-setters, so they do not race the 150 ms debounce or the `change` listener.)

- [x] **Task 7: Update + extend service tests.**
  - File: `tests/test_services/test_qr_service.py`
  - Action:
    1. Keep `test_dimensions_match_preset_at_300_dpi` (lines 48-54) as-is (default dpi=300 still valid). Add a parametrized `test_dimensions_match_preset_at_dpi` over several DPIs (e.g. 180, 203, 600, 1200). **The expected size MUST use the same round-half-up the code uses — `int(v * dpi + 0.5)` — NOT Python's `round()`.** Python's `round()` is banker's rounding and diverges from `int(x+0.5)` for at least `sticker_1_5 @ 203 dpi` (code → 305, `round()` → 304) and `avery_5160 @ 180 dpi` (code → 473, `round()` → 472), which would make a `round()`-based test fail. Assert `img.size == (int(p.width_in*dpi+0.5), int(p.height_in*dpi+0.5))`.
    2. Update the WiFi-budget reconstruction test (lines ~461-475) `min_row_px = int(8 * 300 / 72 + 0.5) + 4` — keep at 300 for the default-DPI case (still correct).
    3. Add `TestQRDevicePresets`: **exact count `len(QR_DEVICE_PRESETS) == 5`** (mirrors the existing `test_has_eight_entries` at `:25`; the count is load-bearing — Task 8.1 asserts 5 labels), keys unique, default `laser_300` present & dpi 300, by-key roundtrip.
    4. Add `test_png_embeds_dpi_metadata`: render at dpi=203, then assert with **integer-rounded tolerance, NOT exact equality** — Pillow round-trips DPI through a rational, so `Image.open(...).info['dpi']` returns floats like `(202.9968, 202.9968)`, never `(203, 203)`. Assert e.g. `dpi = img.info['dpi']; assert tuple(round(v) for v in dpi) == (203, 203)` (or `pytest.approx((203, 203), abs=1)`). Verify the same for dpi=300 (`info['dpi']` ≈ `(299.9994, …)` → rounds to 300).
    5. Add `test_oversized_canvas_raises`: `render_qr_png(eq, letter_preset, dpi=1200, base_url=...)` raises `ValueError` (Letter @ 1200 = 10200×13200 ≈ 134.6 MP > 50 MP cap); and `test_large_but_allowed_ok`: 4″ sticker @ 1200 dpi succeeds with size `(4800, 4800)` (= 23.04 MP, under the cap). Also sanity-check Letter @ 600 dpi (5100×6600 = 33.66 MP) does NOT raise. **Cost note:** the 23 MP render allocates ~70 MB and runs a full QR encode/resize/PNG-encode — it is a deliberately heavy test. To keep `make test` fast, prefer asserting the *guard boundary* via the cheaper Letter@1200 raise, and keep the large *successful* render minimal (or mark it `@pytest.mark.slow` if the project adopts that marker) rather than rendering several multi-MP images.
    6. **The four existing `TestFitText` callers (`:264, 275, 283, 295`) must keep passing unchanged** thanks to the `dpi=300` default (Task 2 step 6). Optionally add one `_fit_text(..., dpi=203)` case asserting the returned font's pixel size honors the lower DPI floor, to lock in the fan-out fix from Task 2 step 7.

- [x] **Task 8: Update + extend view tests.**
  - File: `tests/test_views/test_equipment_views.py`
  - Action (within the QR test class, ~lines 1552-1864):
    1. `test_qr_form_shows_device_dropdown`: GET form contains a `name="device"` select with the 5 device labels.
    2. `test_post_qr_download_honors_device_dpi`: POST with `device=thermal_203` + `size=sticker_4` returns a PNG whose `Image.open(...).size == (812, 812)` and **rounded** DPI `tuple(round(v) for v in img.info['dpi']) == (203, 203)` (NOT exact `== (203, 203)` — see Task 7.4).
    3. `test_post_qr_download_unknown_device_rejected`: POST a **complete payload with only `device` invalid** — `{'size': 'sticker_2', 'device': 'bogus', 'wifi_info': 'none', 'submit': 'Download QR Code'}` — so the re-render is attributable specifically to device validation, not a missing/invalid size or `wifi_info`. (The existing `test_post_qr_download_unknown_size_rejected` at `:1616` omits other fields, so do NOT blindly clone its payload shape — it would not isolate device validation.) Assert the response is the form page (200, contains the form), not a PNG attachment.
    4. `test_qr_preview_includes_device_param`: assert the **server-rendered initial preview `src`** (`qr.html:46`) contains `device=` (the JS reload is client-side and not testable here — see AC8b); `test_get_qr_preview_invalid_device_400`: `GET .../qr/preview?device=bogus` → 400; `test_get_qr_preview_default_device_when_missing`: omitting `device` succeeds (defaults to 300 dpi).
    5. `test_post_qr_download_oversized_flashes_danger`: POST a **complete valid payload except for the oversized combo** — `{'size': 'letter', 'device': 'laser_1200', 'wifi_info': 'none', 'submit': 'Download QR Code'}` — so the re-render is driven by the guard's `ValueError`, not by an unrelated WTForms validation miss (same isolation rationale as Task 8.3). Assert no attachment and that the response body contains the guard's danger text (e.g. `b'too large to render'`) — mirrors the existing URL-too-long flash assertion at `:1646`. **Note:** unlike the existing ValueError-path view tests (`:1628-1661`), which monkeypatch `render_qr_png` to raise, this test deliberately does a *real* render to exercise the guard end-to-end; this convention deviation is intentional. This is the AC5 coverage the original spec lacked.
    6. `test_get_qr_preview_oversized_400`: `GET .../qr/preview?size=letter&device=laser_1200` → **HTTP 400** (the oversized guard raises `ValueError` → `qr_preview` `abort(400)`). This is the automated coverage for AC5's preview-side clause, which the prior revision asserted but never tested.

- [x] **Task 9: Update user + manual-test documentation, including screenshot.**
  - File: `docs/staff.md`
  - Action: *(The `:150`/`:152` absolute line numbers below refer to the file's current state; inserting the new device/WiFi steps in 9.1/9.4 will push them down. Edit this section top-to-bottom and locate `:150`/`:152` by their quoted text, not their pre-edit line numbers.)*
    1. In "QR Code Labels → Generating a QR code label" (the numbered procedure at `docs/staff.md:142-148`), add a step describing the **Printer / device** selector: choose the preset matching your printer's resolution (Thermal Label 203 dpi, Brother P-Touch 180 dpi, Laser/Inkjet 300/600/1200 dpi); explain that this makes the printed label come out at the correct physical size and that "Laser/Inkjet (300 dpi)" is the safe default for most office printers. Add a short note that very large sizes at very high resolution (e.g. US Letter at 1200 dpi) are rejected — pick a lower resolution.
    2. **Reconcile the stale fixed-DPI line:** replace `docs/staff.md:150` ("All output is rendered at 300 DPI so labels print sharply at any of the listed sizes.") with text explaining output is rendered at the *selected device's* DPI.
    3. **Update the small-sticker tip at `docs/staff.md:152`:** it currently warns that URL text is truncated on ≤2″ stickers. Add that on **low-resolution devices (180/203 dpi)** the QR modules on ≤1″ stickers may be small enough to scan unreliably — prefer a larger sticker or a higher-resolution printer for tiny labels.
    4. **Pre-existing gap to close while here:** the numbered procedure (`docs/staff.md:142-148`) documents size, include-name, include-url, preview, and download but **never documents the existing WiFi Info dropdown** (`qr.html:26-29`). Since this task already edits this exact procedure, add a brief step describing the WiFi Info selector (None / Header / SSID / Password) alongside the new device step, so the docs aren't left describing the new field while still omitting an older one.
  - File: `docs/images/qr-generation.png`
  - Action: Regenerate the screenshot of `/equipment/<id>/qr` so it shows the new device dropdown. (Run the app per `make run`, navigate to the QR page for a sample equipment item with `ESB_BASE_URL` set, capture the form.)
  - File: `docs/manual_testing.md`
  - Action:
    1. In section 11 (lines 302-327), add steps to: (a) select each device preset and confirm the downloaded PNG's pixel dimensions equal `int(size_inches × device_dpi + 0.5)`; (b) confirm the PNG embeds matching DPI metadata — `identify -verbose file.png | grep Resolution` if ImageMagick is installed, or the dependency-free `python -c "from PIL import Image; print(Image.open('file.png').info['dpi'])"` — noting it reports ~`(202.9968, 202.9968)` for a 203 dpi label, which is expected rational rounding; (c) confirm a 4″ label at "Thermal Label (203 dpi)" prints full-size (no clipping) on a 203-dpi printer and that US Letter @ 1200 dpi shows a friendly "too large" error.
    2. **Fix the stale existing assertions:** step 7 at `:314` ("Download the label at the 2" sticker preset; open the PNG and verify it is 300 DPI") and step 9 at `:316` ("Download the US Letter preset and verify the PNG is 2550×3300 px") and the Expected-Results line at `:324` ("letter → 2550×3300 px at 300 DPI") all assume the old fixed 300 dpi. Reword them to specify the device used (e.g. "at the default Laser/Inkjet 300 dpi device, US Letter → 2550×3300 px") so they remain correct and don't contradict the new device-aware steps.

### Acceptance Criteria

- [x] **AC1 (Happy path — thermal):** Given a configured `ESB_BASE_URL` and equipment item, when a user selects size `4"×4" sticker` and device `Thermal Label (203 dpi)` and downloads, then the PNG is exactly **812×812 px** (`int(4×203+0.5)`) and its embedded DPI metadata **rounds to** `(203, 203)` (Pillow stores it as a rational, so `img.info['dpi']` ≈ `(202.9968, 202.9968)`; assert via `round()`/`pytest.approx`, not exact equality).
- [x] **AC2 (Happy path — high-res laser):** Given the same item, when the user selects `4"×4" sticker` and `Laser/Inkjet (1200 dpi)`, then the PNG is **4800×4800 px** with embedded DPI metadata that rounds to `(1200, 1200)`.
- [x] **AC3 (Backward compatibility):** Given a request that does not specify a device (legacy/default), when the label renders, then it uses **300 dpi** and produces the **same pixel dimensions** as before this change (e.g. 4″ → 1200×1200), and `render_qr_png(...)` called without `dpi=` defaults to 300. (Note: the raw PNG **bytes** are NOT identical to the pre-change output — the new `dpi=` save kwarg adds a `pHYs` chunk even at 300 dpi. Only dimensions and visual content are preserved.)
- [x] **AC4 (Correct physical print — manual/assumption, non-gating):** Given a downloaded PNG with embedded DPI metadata, when it is printed via the OS/CUPS dialog at "actual size", then it prints at its intended physical inches regardless of the printer's native resolution. *This depends on the external print stack honoring the `pHYs` chunk and cannot be verified in CI; it is validated only by the manual print step in `docs/manual_testing.md` §11 and is treated as a documented assumption, not an automated gating criterion.*
- [x] **AC5 (Oversized guard):** Given size `US Letter page (8.5"×11")` and device `Laser/Inkjet (1200 dpi)`, when the user attempts to download, then a `ValueError` is raised and the form re-renders with a flashed danger message advising a lower resolution or smaller size (and `qr_preview` returns HTTP 400) — no out-of-memory render occurs.
- [x] **AC6 (Unknown device — download):** Given a POST whose `device` value is not a known preset key, when the form is submitted, then WTForms validation fails and the form re-renders without producing a PNG attachment.
- [x] **AC7 (Unknown device — preview):** Given `GET /equipment/<id>/qr/preview?device=bogus`, when requested, then the response is HTTP 400; and given the `device` param is omitted, then the preview renders at the default 300 dpi.
- [x] **AC8a (Live preview — automated):** Given the rendered QR form, when the page loads, then the preview `<img>` initial `src` includes a `device=` query param, and `GET /equipment/<id>/qr/preview?...&device=<key>` renders at that device's DPI (verifiable with a Flask test client by asserting the returned PNG's dimensions/metadata for the given size+device).
- [x] **AC8b (Live preview JS reload — manual/e2e, non-gating):** Given the QR form in a browser, when the user changes the device dropdown, then `app.js` rebuilds the preview URL with the new `device` param and the `<img>` reloads. *This is client-side JS and is not exercisable by the Flask test client; it is covered by the manual `docs/manual_testing.md` §11 steps, not by an automated unit/view test.*
- [x] **AC9 (Docs):** Given the updated documentation, when a staff user reads `docs/staff.md`, then the printer/device selector and its purpose are described, the screenshot `docs/images/qr-generation.png` shows the dropdown, and `docs/manual_testing.md` section 11 includes device-resolution verification steps.

## Additional Context

### Dependencies

- **No new packages.** `qrcode[pil]` + Pillow are already present; Pillow's `Image.save(..., dpi=(d, d))` provides the metadata. No DB schema change, no Alembic migration, no config/env var.
- **Internal coupling:** `esb/forms/equipment_forms.py` imports the new `QR_DEVICE_PRESETS` from `esb/services/qr_service.py` (same direction the existing `QR_SIZE_PRESETS` import already flows), so Task 4 depends on Task 1. Tasks 5/6 depend on Tasks 1-4. Tests (7/8) depend on the code tasks. Docs (9) depend on the final UI from Task 6.

### Testing Strategy

- **Unit (service) — `tests/test_services/test_qr_service.py`:** device-preset structure; DPI-driven dimensions across multiple DPIs (parametrized); default-DPI backward compatibility (existing `*300` assertions stay green); embedded PNG DPI metadata (`Image.info['dpi']`); oversized-canvas `ValueError`; a large-but-allowed render (4″@1200 = 4800²). Existing module-uniformity, payload-decode, and WiFi-budget tests must continue to pass unchanged at the default DPI.
- **Integration (view) — `tests/test_views/test_equipment_views.py`:** device dropdown renders with all 5 labels; download honors device DPI (dimensions + metadata); unknown device rejected on POST; preview includes/round-trips `device`, returns 400 on invalid device, defaults when omitted. Use existing `staff_client` / `configured_base_url` fixtures.
- **Lint:** `make lint` (ruff, 120 col) must pass for all touched Python files.
- **Manual:** follow the expanded `docs/manual_testing.md` section 11 — verify pixel dimensions = `inches × dpi`, embedded DPI via `identify -verbose`, a real 4″ thermal print is full-size (no clipping), and the Letter@1200 "too large" error path. Capture the refreshed screenshot here.
- **Full suite:** `make test` green; `make test-e2e` unaffected.

### Notes

- **Pre-mortem / risks:**
  - *Threading `dpi` through helpers is the main footgun.* `_pt_to_px(_MIN_FONT_PT)` itself is called in exactly **two** places today (WiFi `min_row_px` at `:82`, and the `_fit_text` floor at `:295`), both silently using the `_DPI` global. The larger trap is the **call-graph fan-out**: `render_qr_png` → `_draw_wifi_header_row` → (`_fit_text` ×2 at `:217,:243`, `_draw_text_row` ×3 at `:213,:238,:248`). Every one of those nested calls must forward `dpi`. Because the helpers carry `dpi=300` defaults (required — `TestFitText` calls `_fit_text` directly, see Task 2 step 6), a missed site does **not** raise; it silently renders text at a 300-dpi floor on a non-300 label. So this drift is *not* caught by a `TypeError` — it must be caught by review against the Task 2 step 7 checklist and, ideally, a font-size assertion in a low-DPI text-rendering test.
  - *Memory/latency at high DPI* — mitigated by the 50 MP guard (Task 3). Note the guard cap is a single constant; if a legitimate large-format need arises, raise it deliberately.
  - *Preview cost* — high-DPI previews are larger to encode, but the preview is debounced (150 ms) and cached 5 min; acceptable. If it becomes a problem, a future optimization could render the preview at a capped DPI (deferred — would break preview/download fidelity at the `avail < native` boundary, so not done now).
- **Known limitations:** still raster PNG only (no PDF/vector); ESB does not print directly — the user prints the downloaded PNG via their OS. Both are explicitly out of scope.
- **Future considerations (out of scope):** optional PDF output for desktop printers; a free-form numeric DPI override for unlisted devices; per-equipment or org-wide default device preference; SVG output.

## Review Notes

- Adversarial review completed (general adversarial review task, isolated subagent).
- Findings: 12 total (11 + 1 bonus), 5 fixed, 7 skipped.
- Resolution approach: auto-fix the "real" findings.
- **Fixed:**
  - F8: Generic preview-failure message (was hardcoded "too large to render"; `img.onerror` fires for any failed load — 404/500/network — so the message is now non-specific).
  - F7: Download filename now encodes the device key (`qr-<id>-<name>-<device>.png`) so per-device labels for the same item no longer collide.
  - F11: Extended `test_png_embeds_dpi_metadata` parametrization to 180/600/1200 dpi (was 203/300 only).
  - F9: `test_post_qr_download_unknown_device_rejected` now asserts the device-clamp branch ran (re-rendered preview `src` carries `device=laser_300`, not `device=bogus`).
  - Bonus: `render_qr_png` now raises `ValueError` on `dpi <= 0` (defensive guard on the public service entry point).
- **Skipped (spec-mandated decisions or DPI-invariant non-issues):**
  - F1 (`MAX_CANVAS_PX` adjustable-constant), F5 (`module_px < 5` threshold), F6 (helper `dpi=300` defaults), F10 (WiFi-Info doc step) — all explicitly required by the tech-spec.
  - F3/F4 (claimed high-DPI font overflow) — invalid: `min_px` and the reserved bands both scale linearly with DPI, so the ratio is identical to the pre-change 300-dpi behavior (DPI-invariant; not a regression).
  - F2 (device-validation comment) — reviewer conceded the logic is correct.
- Final: `make lint` clean; full suite 1546 passed.
