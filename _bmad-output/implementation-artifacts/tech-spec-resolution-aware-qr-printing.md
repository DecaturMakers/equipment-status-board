---
title: 'Resolution-Aware QR Label Printing'
slug: 'resolution-aware-qr-printing'
created: '2026-06-02'
status: 'ready-for-dev'
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
- **`render_qr_png` gains a keyword-only `dpi: int = 300`.** Defaulting to 300 keeps every existing service-level test and the legacy default path byte-identical. The `_px`/`_pt_to_px` helpers take `dpi` as an argument (drop the `_DPI` global).
- **Embed DPI metadata** via `canvas.save(buf, format='PNG', dpi=(dpi, dpi))` so the CUPS/OS "actual size" print path reproduces the intended physical inches. This is the fix for the desktop-printer mis-scaling; correct pixel count is the fix for the thermal-printer clipping.
- **Preview honors the selected device DPI** (renders at the real DPI) so the preview faithfully predicts the download — including the `avail < native` "URL too long" boundary, which is DPI-sensitive. The preview `<img>` remains scaled to ≤400 px for display.
- **Oversized-canvas guard.** Because high DPI × large physical size can produce enormous canvases (US Letter @ 1200 dpi ≈ 10200×13200 ≈ 134 MP), `render_qr_png` raises a friendly `ValueError` when `canvas_w_px * canvas_h_px` exceeds a cap (proposed **50 MP**), reusing the existing flash-danger / abort-400 paths. (4″ sticker @ 1200 dpi = 23 MP and Letter @ 600 dpi = 34 MP both pass.)
- **No DB/migration, no new dependency** — Pillow already supports the `dpi` save kwarg.

### Technical Preferences & Constraints (from discovery)

- **Print pipeline is the OS print dialog (CUPS):** the user saves the PNG and prints it via the system dialog. This is why the fix is *raster sizing + embedded DPI metadata* (not vector/PDF). Correct DPI metadata lets CUPS "actual size" produce the right physical dimensions; correct pixel count makes raw/native raster paths (thermal) fit the label.
- **DPI selection via named device presets** (not a raw numeric DPI field). Preset labels are device-oriented and friendly: `Thermal Label (203 dpi)` (covers the Sato M-84Pro-2 and similar 203-dpi thermal printers — intentionally generic, not Sato-specific), `Brother P-Touch (180 dpi)`, and `Laser/Inkjet` at 300/600/1200 dpi.
- **Default device = 300 dpi** to preserve existing output byte-for-byte where possible for the legacy default.
- **Keep PNG and existing size presets.** Only the DPI/pixel scaling and metadata change.
- **Documentation must be updated** alongside code: end-user (`docs/staff.md`) and manual test plan (`docs/manual_testing.md`), with a refreshed screenshot if the form gains a visible field.

### Known landmarks (to be deep-investigated in Step 2)

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

- [ ] **Task 1: Add the device/DPI preset model to the service.**
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

- [ ] **Task 2: Parameterize the service by DPI (replace the `_DPI` global).**
  - File: `esb/services/qr_service.py`
  - Action:
    1. Delete the module global `_DPI = 300` (line 16).
    2. Change helpers to take `dpi`: `def _px(inches: float, dpi: int) -> int: return int(inches * dpi + 0.5)` and `def _pt_to_px(pt: int, dpi: int) -> int: return int(pt * dpi / 72 + 0.5)`.
    3. Add `dpi: int = 300` as a keyword-only param to `render_qr_png` (in the existing `*,` keyword block).
    4. Update the two `_px(...)` calls (lines 72-73) to `_px(preset.width_in, dpi)` / `_px(preset.height_in, dpi)`.
    5. Update the WiFi `min_row_px = _pt_to_px(_MIN_FONT_PT) + 4` (line 82) to pass `dpi`.
    6. Thread `dpi` into the draw helpers that compute the font floor: add `dpi` param to `_draw_text_row`, `_draw_wifi_header_row`, and `_fit_text`; replace `_pt_to_px(_MIN_FONT_PT)` inside `_fit_text` (line 295) with `_pt_to_px(_MIN_FONT_PT, dpi)`. Pass `dpi` from `render_qr_png` at every `_draw_text_row(...)`, `_draw_wifi_header_row(...)` call site (lines 156-178) and from `_draw_wifi_header_row` into its internal `_fit_text` calls.
  - Notes: Default `dpi=300` keeps the legacy path and all current `*300` test assertions valid. The 8 pt font floor is physical, so scaling it by DPI is correct.

- [ ] **Task 3: Embed DPI metadata in the PNG + add the oversized-canvas guard.**
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
  - Notes: Module-level `MAX_CANVAS_PX` constant is fine too. Guard runs before the expensive QR/image work. Reuses the existing `ValueError` → flash-danger / abort-400 handling.

- [ ] **Task 4: Add the `device` field to the generation form.**
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

- [ ] **Task 5: Thread the selected device → DPI through both views.**
  - File: `esb/views/equipment.py`
  - Action:
    1. In `qr()` (after resolving `preset`, ~line 312): `device = qr_service.QR_DEVICES_BY_KEY[form.device.data]` and pass `dpi=device.dpi` to `render_qr_png(...)` (~line 314). Add `preset=%s device=%s` to the existing "QR downloaded" log line (line 330-334).
    2. In `qr_preview()` (~line 355): read `device_key = request.args.get('device', qr_service.DEFAULT_DEVICE_KEY)`, look up `device = qr_service.QR_DEVICES_BY_KEY.get(device_key)`, `if device is None: abort(400)` (mirroring the `size` handling at lines 356-358), and pass `dpi=device.dpi` to `render_qr_png(...)`.
  - Notes: POST builds the form with `validation_choices` only for `wifi_info`; `device` choices are static on the form, so the device value is validated by WTForms automatically.

- [ ] **Task 6: Wire the device selector into the template + live preview JS.**
  - File: `esb/templates/equipment/qr.html`
  - Action:
    1. Add a `<select>` block for `form.device` immediately after the `size` block (lines 22-25), same markup pattern.
    2. Add `device=form.device.data or 'laser_300'` to the initial preview `src` `url_for(...)` (line 46).
    3. Update the caption (line 49) from "downloaded PNG is at 300 DPI" to something device-aware, e.g. *"Preview is scaled to fit. The downloaded PNG is sized to your selected printer resolution and physical size."*
  - File: `esb/static/js/app.js`
  - Action: In the QR preview IIFE (lines 246-255), read the device field and add it to `params`: `var device = form.querySelector('[name="device"]'); if (device) params.set('device', device.value);`.

- [ ] **Task 7: Update + extend service tests.**
  - File: `tests/test_services/test_qr_service.py`
  - Action:
    1. Update `test_dimensions_match_preset_at_300_dpi` (lines 48-54) — it stays valid (default dpi=300) but rename intent or keep; add a new parametrized `test_dimensions_match_preset_at_dpi` over a few `(dpi)` values asserting `img.size == (round(w*dpi), round(h*dpi))`.
    2. Update the WiFi-budget reconstruction test (lines ~461-475) `min_row_px = int(8 * 300 / 72 + 0.5) + 4` — keep at 300 for the default-DPI case (still correct).
    3. Add `TestQRDevicePresets`: device tuple non-empty, keys unique, default `laser_300` present & dpi 300, by-key roundtrip.
    4. Add `test_png_embeds_dpi_metadata`: render at dpi=203, assert `Image.open(...).info['dpi'] == (203, 203)` (allow float-eq tolerance).
    5. Add `test_oversized_canvas_raises`: `render_qr_png(eq, letter_preset, dpi=1200, base_url=...)` raises `ValueError`; and `test_large_but_allowed_ok`: 4″ sticker @ 1200 dpi succeeds with size `(4800, 4800)`.

- [ ] **Task 8: Update + extend view tests.**
  - File: `tests/test_views/test_equipment_views.py`
  - Action (within the QR test class, ~lines 1552-1864):
    1. `test_qr_form_shows_device_dropdown`: GET form contains a `name="device"` select with the 5 device labels.
    2. `test_post_qr_download_honors_device_dpi`: POST with `device=thermal_203` + `size=sticker_4` returns a PNG whose `Image.open(...).size == (812, 812)` and `info['dpi'] == (203, 203)`.
    3. `test_post_qr_download_unknown_device_rejected`: POST with `device=bogus` re-renders the form (WTForms validation fails) — no attachment.
    4. `test_qr_preview_includes_device_param`: rendered form's preview `src`/JS path round-trips the `device` param; `test_get_qr_preview_invalid_device_400`: `GET .../qr/preview?device=bogus` → 400; `test_get_qr_preview_default_device_when_missing`: omitting `device` succeeds (defaults to 300 dpi).

- [ ] **Task 9: Update user + manual-test documentation, including screenshot.**
  - File: `docs/staff.md`
  - Action: In "QR Code Labels → Generating a QR code label" (lines 140-154), add a step describing the **Printer / device** selector: choose the preset matching your printer's resolution (Thermal Label 203 dpi, Brother P-Touch 180 dpi, Laser/Inkjet 300/600/1200 dpi); explain that this makes the printed label come out at the correct physical size and that "Laser/Inkjet (300 dpi)" is the safe default for most office printers. Add a short note that very large sizes at very high resolution (e.g. US Letter at 1200 dpi) are rejected — pick a lower resolution.
  - File: `docs/images/qr-generation.png`
  - Action: Regenerate the screenshot of `/equipment/<id>/qr` so it shows the new device dropdown. (Run the app per `make run`, navigate to the QR page for a sample equipment item with `ESB_BASE_URL` set, capture the form.)
  - File: `docs/manual_testing.md`
  - Action: In section 11 "QR Code Label Generation" (lines 302-327), add steps to: (a) select each device preset and confirm the downloaded PNG's pixel dimensions equal `size_inches × device_dpi`; (b) confirm the PNG embeds matching DPI metadata (e.g. `identify -verbose file.png | grep Resolution`); (c) confirm a 4″ label at "Thermal Label (203 dpi)" prints full-size (no clipping) on a 203-dpi printer and that US Letter @ 1200 dpi shows a friendly "too large" error.

### Acceptance Criteria

- [ ] **AC1 (Happy path — thermal):** Given a configured `ESB_BASE_URL` and equipment item, when a user selects size `4"×4" sticker` and device `Thermal Label (203 dpi)` and downloads, then the PNG is exactly **812×812 px** (`round(4×203)`) and carries embedded DPI metadata `(203, 203)`.
- [ ] **AC2 (Happy path — high-res laser):** Given the same item, when the user selects `4"×4" sticker` and `Laser/Inkjet (1200 dpi)`, then the PNG is **4800×4800 px** with embedded DPI `(1200, 1200)`.
- [ ] **AC3 (Backward compatibility):** Given a request that does not specify a device (legacy/default), when the label renders, then it uses **300 dpi** and produces byte-for-byte the same dimensions as before this change (e.g. 4″ → 1200×1200), and `render_qr_png(...)` called without `dpi=` defaults to 300.
- [ ] **AC4 (Correct physical print):** Given a downloaded PNG with embedded DPI metadata, when it is printed via the OS/CUPS dialog at "actual size", then it prints at its intended physical inches regardless of the printer's native resolution.
- [ ] **AC5 (Oversized guard):** Given size `US Letter page (8.5"×11")` and device `Laser/Inkjet (1200 dpi)`, when the user attempts to download, then a `ValueError` is raised and the form re-renders with a flashed danger message advising a lower resolution or smaller size (and `qr_preview` returns HTTP 400) — no out-of-memory render occurs.
- [ ] **AC6 (Unknown device — download):** Given a POST whose `device` value is not a known preset key, when the form is submitted, then WTForms validation fails and the form re-renders without producing a PNG attachment.
- [ ] **AC7 (Unknown device — preview):** Given `GET /equipment/<id>/qr/preview?device=bogus`, when requested, then the response is HTTP 400; and given the `device` param is omitted, then the preview renders at the default 300 dpi.
- [ ] **AC8 (Live preview fidelity):** Given the QR form, when the user changes the device dropdown, then the live preview `<img>` reloads with the `device` query param included and is rendered at the selected device's DPI (scaled to fit the ≤400 px display).
- [ ] **AC9 (Docs):** Given the updated documentation, when a staff user reads `docs/staff.md`, then the printer/device selector and its purpose are described, the screenshot `docs/images/qr-generation.png` shows the dropdown, and `docs/manual_testing.md` section 11 includes device-resolution verification steps.

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
  - *Threading `dpi` through helpers is the main footgun* — `_pt_to_px(_MIN_FONT_PT)` is called in three places (WiFi `min_row_px`, `_fit_text` floor) and silently uses the global today. Missing one site means the font floor stays at 300-dpi pixels and text scales wrong at other DPIs. The Task 2 checklist enumerates every call site.
  - *Memory/latency at high DPI* — mitigated by the 50 MP guard (Task 3). Note the guard cap is a single constant; if a legitimate large-format need arises, raise it deliberately.
  - *Preview cost* — high-DPI previews are larger to encode, but the preview is debounced (150 ms) and cached 5 min; acceptable. If it becomes a problem, a future optimization could render the preview at a capped DPI (deferred — would break preview/download fidelity at the `avail < native` boundary, so not done now).
- **Known limitations:** still raster PNG only (no PDF/vector); ESB does not print directly — the user prints the downloaded PNG via their OS. Both are explicitly out of scope.
- **Future considerations (out of scope):** optional PDF output for desktop printers; a free-form numeric DPI override for unlisted devices; per-equipment or org-wide default device preference; SVG output.
