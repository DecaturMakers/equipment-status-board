---
title: 'QR Code Template Support'
slug: 'qr-code-template'
created: '2026-06-06'
status: 'completed'
stepsCompleted: [1, 2, 3, 4]
tech_stack: ['Python 3.14', 'Flask', 'Flask-WTF', 'Pillow', 'qrcode[pil]', 'pyzbar (tests)', 'Jinja2', 'pytest']
files_to_modify:
  - 'esb/config.py'
  - 'esb/__init__.py'
  - 'esb/services/qr_service.py'
  - 'esb/views/equipment.py'
  - 'esb/templates/equipment/qr.html'
  - 'esb/static/js/app.js'
  - 'tests/test_services/test_qr_service.py'
  - 'tests/test_views/test_equipment_views.py'
  - 'tests/test_app.py'
  - 'tests/conftest.py'
  - 'docs/administrators.md'
code_patterns:
  - 'Service layer: business logic in esb/services/, views delegate'
  - 'Env config: flat class attributes on Config via os.environ.get (bound at import time)'
  - 'Startup normalization in create_app (UPLOAD_PATH precedent)'
  - 'QR crispness: integer module sizing + Image.NEAREST'
  - 'Text fitting: _fit_text shrink-to-fit with ellipsis + 8pt dpi-scaled floor (single-line)'
  - 'lru_cache font loading'
test_patterns:
  - 'pytest classes per feature (TestRenderQRPng, TestEquipmentQR)'
  - 'pyzbar decode() to verify QR validity'
  - 'Pixel-level assertions (difference between renders, pure B/W in QR region)'
  - 'conftest fixtures: app (function-scoped), staff_client, make_equipment, configured_base_url'
---

# Tech-Spec: QR Code Template Support

**Created:** 2026-06-06

## Overview

### Problem Statement

QR code stickers are currently rendered as plain generated images (QR + text rows on a white canvas). Decatur Makers wants branded sticker output (e.g., the "Oops" template) with the QR code and machine name composited into a designed template image — without losing the existing size/device preset and preview workflow. (GitHub Issue #57)

### Solution

Add a new `QR_TEMPLATE_CONFIG_PATH` environment variable on the existing `Config` class holding a filesystem path to a JSON file. The JSON defines (relative to itself): the template PNG path, pixel bounding boxes for the QR code, machine name, and optional URL (one box per element), plus an optional font file path for the text. When configured, `qr_service` scales the template to the selected preset's canvas (aspect ratio preserved, centered on white), **white-fills each enabled element's bbox** (template mock-ups carry placeholder content inside the bboxes), then draws the QR (integer module size, NEAREST) and text directly into the scaled template — keeping the QR crisp and decodable at final resolution. Config is validated fail-fast at app startup. WiFi info is disabled when a template is active.

### Scope

**In Scope:**

- New `QR_TEMPLATE_CONFIG_PATH` env var + JSON template-config loading and fail-fast startup validation (missing/malformed JSON, missing image/font, malformed or out-of-bounds bboxes)
- Template rendering path in `qr_service` — scale template to fit preset canvas, map bboxes by the same factor, white-fill enabled bboxes, draw QR into its bbox at integer module size with NEAREST, fit name/URL text within their bboxes using the template font (fallback to vendored DejaVu bold)
- **QR scannability after scaling**: rendering approach must preserve QR validity (post-scale integer module sizing; `module_px < 5` warning and too-small `ValueError` guards applied to the scaled bbox); tests must decode the final output with pyzbar to prove it
- Form/view/template changes: WiFi controls hidden & ignored when template active; `include_name` (default ON with template) / `include_url` toggles kept (URL toggle hidden when no `url_bbox` in JSON); preview route honors all of this
- Tests using `tests/qr_code_template.png` + `tests/Poppins-Bold.ttf` with the issue's "safe drawable area" bboxes
- Document the new env var + JSON format in `docs/administrators.md`

**Out of Scope:**

- Admin UI for uploading/managing templates (filesystem + env var only)
- Multiple templates / per-equipment template selection
- Any change to the existing non-template **PNG rendering** path (incl. WiFi rows). (Exception: Task 9.4 fixes the initial preview-src boolean serialization in `qr.html`, which also corrects a latent non-template re-render bug — an HTML-only change, not a rendering change.)
- WiFi info rendering inside templates (bake it into the template image if needed — but see the URL-bbox collision note in Technical Decisions)
- Multi-line text wrapping — name/URL are rendered single-line via the existing `_fit_text` shrink/ellipsize (a deliberate deviation from the issue's mock-up, which shows a two-line name; see Notes)

## Context for Development

### Codebase Patterns

- **Service layer**: all rendering logic lives in `esb/services/qr_service.py`; views (`esb/views/equipment.py`) delegate and handle flash/HTTP concerns. `qr_service` must not import forms (enforced by `TestNoFormImport`).
- **Env config**: flat class attributes on `Config` in `esb/config.py` are bound via `os.environ.get('VAR', default)` **at module import time** — setting env vars at test time has no effect; tests must patch the config class attribute or `app.config`. `TestingConfig` subclasses it (SQLite in-memory, CSRF off).
- **Startup hook**: `create_app()` in `esb/__init__.py` normalizes `UPLOAD_PATH` right after `app.config.from_object(...)` — precedent for fail-fast template-config validation/parsing at the same spot.
- **QR crispness invariants** (`qr_service.render_qr_png`): QR drawn at `box_size=1`, scaled to `module_px * native` with `Image.NEAREST`; `module_px < 5` logs a "scannability may be marginal" warning; `avail < native` raises `ValueError('URL is too long for preset…')`; canvas capped at `MAX_CANVAS_PX = 50_000_000` px.
- **Text fitting**: `_fit_text(text, max_width_px, max_height_px, font_path, dpi)` shrinks from `max_height_px` toward an 8 pt dpi-scaled floor, then ellipsizes via binary search; returns `(font, '')` when nothing fits. Single-line only — no wrapping. Fonts loaded via `@lru_cache`d `_load_font(path, size)`.
- **View flow**: `qr` route (GET form / POST download via `send_file`) and `qr_preview` route (GET inline PNG, `Cache-Control: private, max-age=300`). Both call `get_normalized_base_url()` (raises `ValueError` → flash+redirect on form, 404 on preview). WiFi choices built dynamically from `config_service` values. **On POST the form is constructed with all four wifi values as validation choices** (`equipment.py:289-294`) because `SelectField.pre_validate` rejects data not in choices; clamping happens after `validate_on_submit()` (line 314).
- **Form**: `QRGenerateForm` (`esb/forms/equipment_forms.py:130`) — `size`/`device` selects from preset tuples, `wifi_info` select with dynamic choices via `__init__(wifi_choices=...)`, `include_name`/`include_url` booleans (both default False).
- **Preview JS** (`esb/static/js/app.js:239-276`): debounced rebuild of `img.src` from form fields. The `wifi_info` and `device` lookups are guarded against absence (`if (wifiInfo)`), but the `include_name`/`include_url` lookups at `app.js:259-260` assume the elements exist — removing the URL checkbox from the DOM without guarding throws a TypeError that kills the preview updater (fixed in Task 9). `img.onerror` shows the `#qr-preview-error` message.

### Files to Reference

| File | Purpose |
| ---- | ------- |
| `esb/services/qr_service.py` | Existing renderer — presets, module sizing, `_fit_text`, guards; template path goes here |
| `esb/views/equipment.py:275-405` | `qr` / `qr_preview` routes, WiFi choice building/clamping |
| `esb/forms/equipment_forms.py:130-156` | `QRGenerateForm` |
| `esb/templates/equipment/qr.html` | QR page UI — form controls + live preview img |
| `esb/static/js/app.js:239-276` | Debounced preview URL builder |
| `esb/config.py` | `Config` class — new env var lives here |
| `esb/__init__.py` (`create_app`) | Startup validation hook (UPLOAD_PATH precedent at line ~39) |
| `esb/utils/text.py` | `get_normalized_base_url`, `slugify_filename` |
| `tests/test_services/test_qr_service.py` | Service test patterns incl. pyzbar decode, pixel assertions |
| `tests/test_views/test_equipment_views.py:1549` | `TestEquipmentQR` view test class |
| `tests/test_app.py` | Existing `create_app(...)` tests — startup fail-fast tests go here |
| `tests/conftest.py:166` | `configured_base_url` fixture (precedent for a template-config fixture); `app` fixture is function-scoped (`conftest.py:36-47`) |
| `tests/qr_code_template.png` | Example template fixture (1500×1800 RGB) — a **mock-up containing placeholder content inside every bbox** (sample name "Resaw Bandsaw", solid-red "QR Code" square, sample URL text) |
| `tests/Poppins-Bold.ttf` | Example template font fixture |
| `docs/administrators.md` | Env var documentation (documents `ESB_BASE_URL` etc.) |
| `requirements.txt` | `qrcode[pil]`, `Pillow`, `pyzbar` already present — no new deps |

### Technical Decisions

- **Env var**: `QR_TEMPLATE_CONFIG_PATH` — filesystem path to the JSON config file. Empty/unset → feature off, existing rendering unchanged.
- **JSON schema** (paths relative to the JSON file's directory; bboxes are flat `[x0, y0, x1, y1]` pixel arrays in template-native coordinates, PIL convention):

  ```json
  {
    "image": "template.png",
    "font": "Poppins-Bold.ttf",
    "qr_bbox": [509, 949, 1011, 1451],
    "name_bbox": [240, 540, 1259, 925],
    "url_bbox": [140, 1490, 1359, 1675]
  }
  ```

  `image`, `qr_bbox`, `name_bbox` required; `font`, `url_bbox` optional. Unknown keys are ignored (no rejection required). **Deliberate deviation from the issue's wording**: the issue scopes the optional font to "the machine name" — this spec applies it to both name and URL text for visual consistency. Fallback font is the vendored DejaVuSans-Bold, resolved **package-relative** (`os.path.join(os.path.dirname(esb.__file__), 'static', 'fonts', 'DejaVuSans-Bold.ttf')`) so the loader needs no app context — do NOT use `current_app.static_folder` here.
- **White-fill semantics (placeholder replacement)**: template images are typically designed as mock-ups with sample content inside the bboxes (the example fixture has "Resaw Bandsaw" in the name bbox, a solid red field reading "QR Code" in the QR bbox, and sample URL text in the URL bbox). Before drawing each **enabled** element, its scaled bbox is filled solid white: `qr_bbox` always (the QR is always drawn), `name_bbox` iff `include_name`, `url_bbox` iff `include_url` (and the bbox exists). A disabled element's bbox is left untouched — its template artwork (including any placeholder) shows as-is, which is the operator's choice. White-filling the QR bbox also guarantees contrast and a clean margin around the QR regardless of artwork, and makes the variable margin (from module flooring) uniform white instead of a colored ring.
- **URL bbox vs. baked-in WiFi text**: in the example template, the baked "Must be on Decatur Makers Wifi" line sits inside the URL bbox. With white-fill, enabling `include_url` deliberately **replaces** that area (WiFi line erased, URL drawn); leaving it unchecked preserves the baked WiFi text. Admins must choose one or the other per download — document this collision explicitly (Task 12).
- **Render order (scannability)**: scale the template to the output size FIRST (factor `s = min(canvas_w/tpl_w, canvas_h/tpl_h)`, LANCZOS), map bboxes by `s`, white-fill enabled bboxes, then draw the QR at integer module size with `Image.NEAREST` and fit text into the scaled bboxes. The QR is never resampled after drawing — modules stay pure black/white at final resolution. Composite is centered on a white canvas of the preset's exact pixel dimensions (output size/DPI metadata identical to non-template path).
- **Upscaling allowed**: no cap on `s` — on canvases larger than 1500×1800 (e.g. Letter @ 300dpi) the template upscales to fill; raster quality degrades gracefully while the QR is still drawn crisp at final resolution.
- **Scannability guards on scaled QR bbox**: `module_px = min(scaled_bbox_w, scaled_bbox_h) // native` (native includes the 4-module quiet zone from `border=4`); `module_px < 1` → `ValueError` (flashed on form / 400 on preview, like existing guards); `module_px < 5` → log warning. Tests decode final PNGs with pyzbar at 300 dpi presets; low-DPI devices (180/203 dpi) on small presets can legitimately produce 1 px modules that pass the guard but may not scan — covered by the warning and documented (see Notes).
- **One bbox per text element** (the issue's "close fit" boxes are informational only; the example uses its safe drawable areas).
- **Form behavior with template active**: `wifi_info` control hidden and ignored (forced to `'none'` — see Task 8 for the WTForms validation-ordering requirement); `include_name` **defaults to checked** on GET (the issue treats the machine name as integral to the template; the toggle remains so users can opt out); `include_url` checkbox kept, hidden (and ignored) when JSON has no `url_bbox`.
- **Single-line text**: name and URL render via the existing single-line `_fit_text` (shrink toward the 8 pt floor, then ellipsize). No wrapping — admins should size the name bbox for one line (documented in Task 12; wrapping is a future consideration).
- **Fail fast**: env var set but config invalid (unreadable/malformed JSON, missing keys, bad bbox geometry — non-int coords, x1≤x0/y1≤y0, outside image bounds — missing/unloadable image or font) → raise at `create_app()` startup with a specific message.
- **Config object plumbing**: parse/validate once at startup into a frozen dataclass (e.g. `QRTemplate` with resolved absolute paths + bboxes + image dimensions), stored on `app.config['QR_TEMPLATE']`; views pass it to `render_qr_png(..., template=...)`. Service stays form-free and template loading stays testable in isolation.
- **Per-render template I/O accepted**: each render re-opens the template PNG and LANCZOS-resizes it to the canvas (up to ~8.4 MP for Letter @ 300dpi). This cost is consciously accepted: the preview is debounced (150 ms) and browser-cached (`Cache-Control: private, max-age=300`), and downloads are one-shot. If profiling ever shows it matters, cache the decoded native image on the `QRTemplate` (loaded once at startup) — out of scope now.

## Implementation Plan

### Tasks

- [x] Task 1: Add `QR_TEMPLATE_CONFIG_PATH` to config
  - File: `esb/config.py`
  - Action: Add `QR_TEMPLATE_CONFIG_PATH = os.environ.get('QR_TEMPLATE_CONFIG_PATH', '')` to the `Config` class (alongside `ESB_BASE_URL`).
  - Notes: Empty string = feature disabled. No override needed in `TestingConfig` (default empty keeps existing tests on the non-template path). Remember: this binds at import time — tests patch the class attribute, never the env var (see Task 11).

- [x] Task 2: Add `QRTemplate` dataclass + `load_template_config()` loader to the QR service
  - File: `esb/services/qr_service.py`
  - Action: Add a frozen dataclass `QRTemplate` holding: `image_path: str` (absolute), `font_path: str` (absolute; when JSON omits `font`, the vendored DejaVu fallback resolved package-relative: `os.path.join(os.path.dirname(esb.__file__), 'static', 'fonts', 'DejaVuSans-Bold.ttf')` — NOT via `current_app`), `qr_bbox`, `name_bbox`, `url_bbox: tuple[int, int, int, int] | None`, `image_w: int`, `image_h: int`. Add `load_template_config(json_path: str) -> QRTemplate` that:
    1. Reads and parses the JSON file (raise `ValueError` with the path on unreadable file / malformed JSON)
    2. Requires keys `image`, `qr_bbox`, `name_bbox`; allows optional `font`, `url_bbox`. Unknown keys are ignored (no rejection required).
    3. Resolves `image`/`font` relative to the JSON file's directory; verifies the image opens via PIL (record its size) and the font loads via `ImageFont.truetype` (size probe, e.g. 12)
    4. Validates each bbox: list/tuple of exactly 4 ints, `x1 > x0`, `y1 > y0`, all within `[0, image_w] × [0, image_h]` — note the exclusive convention means `x1 == image_w` / `y1 == image_h` are **legal** (full-bleed boxes); do not reject them
    5. Raises `ValueError` with a specific, human-readable message for every failure mode
  - Notes: Pure function — must not use `current_app` or require an app context (Task 6 tests it bare; the module itself already imports `current_app` at `qr_service.py:13` for other functions, which is fine — the loader just can't touch it). Do not import forms (enforced by `TestNoFormImport`).

- [x] Task 3: Fail-fast startup validation in the app factory
  - File: `esb/__init__.py`
  - Action: In `create_app()`, immediately after the `UPLOAD_PATH` normalization block: if `app.config.get('QR_TEMPLATE_CONFIG_PATH')` is non-empty, call `qr_service.load_template_config(path)` and store the result on `app.config['QR_TEMPLATE']`; otherwise set `app.config['QR_TEMPLATE'] = None`. Let the loader's `ValueError` propagate (app fails to start with the loader's message).
  - Notes: Import `qr_service` locally inside `create_app` (matches the existing local-import style, avoids import cycles).

- [x] Task 4: Template rendering path in `render_qr_png`
  - File: `esb/services/qr_service.py`
  - Action: Add keyword param `template: QRTemplate | None = None` to `render_qr_png()`. When `template` is not None, ignore all `wifi_*` args and render via a new `_render_template_png(equipment, preset, dpi, include_name, include_url, base_url, template)` helper:
    1. Compute `canvas_w_px`/`canvas_h_px` from preset × dpi exactly as today; apply the existing `MAX_CANVAS_PX` guard
    2. Open the template image and **normalize its mode**: if it has an alpha channel (RGBA/LA/P-with-transparency), composite it onto a white background first, then `.convert('RGB')` — design exports are frequently RGBA, and `Image.paste` without a mask renders transparent regions as raw (often black) RGB. Then scale factor `s = min(canvas_w_px / image_w, canvas_h_px / image_h)` (upscaling allowed, no cap); resize to `(round(image_w*s), round(image_h*s))` with `Image.LANCZOS`; paste centered on a white `RGB` canvas of the exact preset dimensions; record paste offsets `(off_x, off_y)`
    3. Map each bbox to canvas coordinates: `(off_x + round(x0*s), off_y + round(y0*s), off_x + round(x1*s), off_y + round(y1*s))`
    4. **White-fill the scaled `qr_bbox`**. Fill mechanism matters: bboxes use the exclusive PIL box convention, but `ImageDraw.rectangle` endpoints are **inclusive** — using it naively fills one extra row/column and breaks the pixel-exact tests. Fill via `canvas.paste((255, 255, 255), (x0, y0, x1, y1))` (paste boxes are exclusive) or `rectangle((x0, y0, x1 - 1, y1 - 1))`. Same mechanism for the name/URL fills in steps 6–7. The fill replaces any placeholder artwork and guarantees QR contrast/margin
    5. Build the QR exactly as today (`ERROR_CORRECT_M`, `box_size=1`, `border=4`, same `qr_url`); compute `module_px = min(scaled_qr_bbox_w, scaled_qr_bbox_h) // native`; if `module_px < 1` raise `ValueError` ("QR template box is too small at this size/resolution — choose a larger size or higher-resolution printer."); if `module_px < 5` log the existing-style scannability warning; `NEAREST`-resize to `module_px * native` and paste centered within the scaled QR bbox
    6. If `include_name`: **white-fill the scaled `name_bbox`**, then draw `equipment.name` into it via a new helper `_draw_text_in_bbox(canvas, text, bbox, font_path, dpi)` (don't reuse `_draw_text_row` directly — it hardcodes the DejaVu path via `current_app.static_folder` and an `isfile`/`RuntimeError` check that must be skipped for the startup-validated template font). The helper uses `_fit_text` for width fitting, **and must additionally constrain rendered ink height**: `_fit_text` shrinks for width only, but real fonts' ink (ascenders/diacritics + descenders) can substantially exceed the em size — measured up to ~1.26× for Poppins-Bold with accented capitals — so after fitting, measure the actual `textbbox` and keep shrinking while ink height > bbox height. **Floor semantics**: the ink-height loop is permitted to shrink below `_fit_text`'s 8 pt dpi-scaled floor (small scaled bboxes — e.g. the URL bbox at `sticker_1`/300 dpi is only 31 px tall vs. a 33 px floor — make the floor unachievable); if ink still cannot fit at a hard minimum (e.g. 4 px), render nothing (`''`), matching `_fit_text`'s existing give-up degradation — the bbox stays white-filled and blank. Drawn ink must never extend outside the white-filled bbox onto template artwork. Center the result in the bbox. If `include_name` is False, leave the bbox untouched (template artwork shows).
    7. If `include_url` and `template.url_bbox` is not None: **white-fill the scaled `url_bbox`**, then draw `qr_url` the same way (same helper, same ink-height constraint). If unchecked or absent, leave untouched.
    8. Save PNG with `dpi=(dpi, dpi)` metadata and return bytes
  - Notes: The QR is drawn at final resolution and never resampled afterward — modules stay pure black/white. White-fill happens AFTER the LANCZOS resize so fill edges are hard (no antialiasing inside the bbox). The existing non-template code path must remain unchanged. Per-render template open+resize cost is accepted (see Technical Decisions).

- [x] Task 5: Conftest fixture for template config
  - File: `tests/conftest.py`
  - Action: Add a **factory fixture** `make_qr_template_config(url_bbox=True, font=True)` (one prescribed shape — not separate variant fixtures and not indirect parametrization, since some tests need both configs in one module). Each call: writes a JSON file into `tmp_path` referencing `tests/qr_code_template.png` and `tests/Poppins-Bold.ttf` (via `os.path.relpath` from `tmp_path`, or by copying the fixtures into `tmp_path`) with bboxes `qr=[509, 949, 1011, 1451]`, `name=[240, 540, 1259, 925]`, and (when `url_bbox=True`) `url=[140, 1490, 1359, 1675]`, omitting `font` when `font=False`; calls `qr_service.load_template_config()` on it; installs the result on `app.config['QR_TEMPLATE']`; returns the `QRTemplate`. Fixture teardown restores the original config value (None). Also add a thin `qr_template_config` convenience fixture that calls the factory with defaults — Task 10's tests use it by name, so it is required, not optional.
  - Notes: Keep the factory in conftest so both service and view tests use it. The `font=False` knob supports the configured-font-vs-fallback difference test (Task 7). The `app` fixture is function-scoped, so per-test config mutation is safe.

- [x] Task 6: Service tests — loader validation
  - File: `tests/test_services/test_qr_service.py`
  - Action: New `TestLoadTemplateConfig` class covering: valid full config (absolute paths resolved, image size recorded, font resolved); valid config omitting `font` (falls back to the package-relative vendored DejaVu path) and omitting `url_bbox` (None); unknown JSON keys ignored; and `ValueError` for each failure mode — nonexistent JSON path, malformed JSON, missing each required key, bbox not 4 ints, `x1 <= x0`, bbox exceeding image bounds, nonexistent image file, nonexistent font file, non-font file as font. Also a render test (can live in `TestRenderQRPngTemplate`) using a small generated **RGBA template with transparent regions** verifying transparency flattens to white in the output (mode-normalization from Task 4 step 2).
  - Notes: Build configs in `tmp_path`; no app context needed.

- [x] Task 7: Service tests — template rendering & scannability
  - File: `tests/test_services/test_qr_service.py`
  - Action: New `TestRenderQRPngTemplate` class. IMPORTANT: the fixture template contains placeholder content inside every bbox, so presence-of-pixels assertions are vacuous — assert **differences between renders** instead:
    - Output dimensions exactly match preset × dpi for a representative spread (square sticker, landscape `avery_5163`, `letter`) — letterboxing white bars included
    - **Decode verification**: pyzbar-decodes the final PNG and asserts the payload URL for at minimum `sticker_2`/300dpi (downscale), `sticker_1`/300dpi (aggressive downscale, ~84 px QR bbox → ~2 px modules), and `letter`/300dpi (upscale)
    - **QR bbox purity**: every pixel inside the scaled QR bbox (computed with the same `off + round(coord*s)` mapping as the renderer) is pure black or pure white — valid because the bbox is white-filled before the QR is pasted
    - Template artwork visible: non-white pixels outside the three bboxes
    - **Name toggle (difference assertion)**: render with `include_name=True` vs `False`; pixels inside the scaled name bbox differ between the two; pixels outside all bboxes are identical. That differs-inside / identical-outside pair is the complete assertion — do NOT try to compare the `False` render against an independently-scaled "bare template" reference (there is no bare render — the QR is always drawn — and reproducing bit-exact LANCZOS+rounding in the test is fragile). (Also do NOT use bbox-corner whiteness as the discriminator for name/URL — the fixture's placeholder text is centered well inside those bboxes, so their corners are already white in the bare template; a corner check only discriminates for the QR bbox, whose placeholder is a solid red field.) Use a descender-free equipment name (e.g. 'Bandsaw') or one sized well below the bbox so the outside-bbox-identical assertion isn't sensitive to ink metrics — the ink-height constraint in Task 4 step 6 is what guarantees containment generally
    - **URL toggle (difference assertion)**: same pattern for `include_url` with the url_bbox config — run it at `sticker_1_5` or larger (at `sticker_1` the scaled URL bbox is shorter than usable ink heights, and the Task 4 floor semantics may legitimately render nothing); with the no-url-bbox config, `include_url=True` output is pixel-identical to `include_url=False`
    - **Configured font actually used**: render with the Poppins config vs a `font=False` (DejaVu-fallback) config from the factory fixture; pixels inside the scaled name bbox must differ — catches a silent fallback that would otherwise pass every other test
    - WiFi args ignored: pixel-identical (decoded `img.tobytes()` equality, the existing idiom from `test_wifi_unknown_value_renders_no_wifi` — not raw PNG bytes) for `wifi_info='password'` vs `wifi_info='none'` when template passed
    - Too-small guard: contrived tiny preset raises `ValueError` mentioning the template box
    - Marginal module warning: small preset logs 'scannability may be marginal' (caplog pattern from `test_marginal_module_size_logs_warning`)
    - PNG embeds dpi metadata (parametrized like `test_png_embeds_dpi_metadata`)
  - Notes: Reuse `BASE_URL` constant and pixel-assertion idioms already in the file. Keep decode assertions on 300 dpi presets; do NOT add decode assertions at 180/203 dpi on small presets (1 px modules — legitimately marginal).

- [x] Task 8: View changes — template-aware `qr` and `qr_preview` routes
  - File: `esb/views/equipment.py`
  - Action: In both routes read `template = current_app.config.get('QR_TEMPLATE')`. When template is active:
    - `qr` GET: construct the form with static `[('none', 'None')]` wifi choices, set `form.wifi_info.data = 'none'`, and set `form.include_name.data = True` (template default ON)
    - `qr` POST — **WTForms ordering requirement**: keep constructing the form with the existing four-value validation choices (`equipment.py:289-294`) so a crafted `wifi_info` does not fail `SelectField.pre_validate` and bounce the request; after `validate_on_submit()` passes, unconditionally force `wifi_info = 'none'` (skip the clamp/flash logic entirely — no "settings changed" message). If no `url_bbox`, force `form.include_url.data = False` regardless of submitted value. Pass `template=template` to `render_qr_png()`
    - **All form-render paths, not just GET**: the shared `_render_form_with_real_choices()` closure (`equipment.py:299-311`) is also the render path for POST validation failures and the `ValueError`/`RuntimeError` flash paths (lines 335, 339, 353). The `template_active=True` / `template_has_url_bbox=...` context vars AND the template-mode wifi handling (keep choices `[('none', 'None')]`, data `'none'` — do NOT reset to the real wifi choices) must live in/around that closure so the WiFi select and URL checkbox cannot reappear when a template-active POST fails.
    - `qr_preview`: ignore the `wifi_info` query param entirely (treat as 'none'); ignore `include_url` when no `url_bbox`; pass `template=template` to `render_qr_png()`
  - Notes: Non-template behavior must be completely unchanged. The existing `ValueError → flash / 400` and `OSError/RuntimeError → 500` handling already covers the new guard errors.

- [x] Task 9: UI changes — conditional form controls + preview JS guard + error message
  - File: `esb/templates/equipment/qr.html`, `esb/static/js/app.js`
  - Action:
    1. `qr.html`: wrap the WiFi select `div` in `{% if not template_active %}`; wrap the `include_url` checkbox `div` in `{% if not template_active or template_has_url_bbox %}`. Default both context vars (`template_active`, `template_has_url_bbox`) so non-template rendering is unaffected.
    2. `app.js:259-260`: guard the checkbox lookups against absence — `var incUrlEl = form.querySelector('[name="include_url"]'); var incUrl = incUrlEl && incUrlEl.checked ? '1' : '';` (same defensive pattern for `include_name` is cheap insurance). An unguarded `.checked` on a missing element throws a TypeError and kills the whole preview updater.
    3. `qr.html:53`: broaden the `#qr-preview-error` text so it also covers the new failure cause, e.g. append "— or, with a template configured, the QR area may be too small at this size/resolution."
    4. `qr.html:50` — **initial preview src boolean serialization bug**: the initial `img src` is built with `include_name=form.include_name.data`, which serializes Python `True` as the string `'True'`; the preview parser only accepts `('1', 'true', 'on')` (`equipment.py:374-375`, case-sensitive), so it parses as False. With the new template-mode default (`include_name` checked on GET), the first-load preview would silently omit the name until the user touches a field. Fix the template to emit `'1' if form.include_name.data else ''` (same for `include_url`). This also fixes the same latent bug on failed-POST re-renders in non-template mode.
  - Notes: The existing `if (wifiInfo)` guard already handles the removed WiFi select.

- [x] Task 10: View tests — template-active behavior
  - File: `tests/test_views/test_equipment_views.py`
  - Action: New `TestEquipmentQRTemplate` class (using `configured_base_url` + `qr_template_config`), following the style of the existing `TestEquipmentQR` class at line 1549:
    - GET form: WiFi select absent from HTML; `include_name` present and **checked by default**; `include_url` present; with no-url-bbox config, `include_url` absent
    - POST download: returns PNG attachment with preset's exact pixel dimensions; payload decodes (pyzbar) to the public equipment URL
    - POST with crafted `wifi_info='password'` succeeds (no validation bounce) and returns a PNG pixel-identical (decoded `tobytes()` equality) to a POST without the param
    - Preview GET: 200 image/png; `wifi_info` param ignored; `include_url=1` ignored when config has no url_bbox
    - **Initial preview src**: GET form HTML's `#qr-preview` src contains `include_name=1` (not `include_name=True`) when template active — locks in the Task 9.4 serialization fix
    - **Too-small guard through the routes** (AC 8): with a long `ESB_BASE_URL` (inflating the QR's native module count — e.g. the `'http://' + 'example'*20 + '.com:5000'` pattern from `test_marginal_module_size_logs_warning`) and `sticker_1` + a 203 dpi device, POST flashes the too-small `ValueError` message and re-renders; the equivalent preview GET returns 400
    - Existing non-template tests in `TestEquipmentQR` still pass untouched (regression gate)
  - Notes: Follow the established assertion idioms in `TestEquipmentQR`.

- [x] Task 11: App-factory startup tests
  - File: `tests/test_app.py`
  - Action: Tests that `create_app('testing')` raises `ValueError` when `QR_TEMPLATE_CONFIG_PATH` points at a missing/invalid JSON, that a valid path yields a populated `app.config['QR_TEMPLATE']`, and that unset leaves it `None`. **Config classes bind env vars at import time, so `monkeypatch.setenv` does NOT work** — use `monkeypatch.setattr(TestingConfig, 'QR_TEMPLATE_CONFIG_PATH', str(path))` (import `TestingConfig` from `esb.config`) before calling `create_app('testing')`.
  - Notes: `tests/test_app.py` already exercises `create_app(...)` directly — follow its patterns. The conftest `app` fixture is function-scoped; these tests create their own apps and don't interact with it.

- [x] Task 12: Document the feature for administrators
  - File: `docs/administrators.md`
  - Action: Add a section documenting `QR_TEMPLATE_CONFIG_PATH`: the JSON schema (with the example above), relative-path semantics, bbox format/units (template-native pixels, `[x0, y0, x1, y1]`), and these behavioral points:
    - The template should be supplied at the maximum resolution it will be printed at (it is scaled to output size; upscaling softens artwork while the QR itself stays crisp)
    - **White-fill semantics**: each enabled element's bbox is filled white before drawing, so mock-up templates with placeholder content (sample name/QR/URL) render correctly; a disabled toggle leaves that bbox's artwork untouched (e.g. unchecking "Include name" on the example template shows its placeholder name)
    - The machine-name toggle defaults to ON when a template is active
    - Name/URL text is single-line (shrinks then ellipsizes) — size the name bbox for one line of the longest expected name
    - WiFi info is disabled when a template is active (bake it into the artwork); **caution**: if baked WiFi text sits inside `url_bbox` (as in the example template), enabling the URL replaces it
    - URL text renders only when `url_bbox` is present AND the URL toggle is checked
    - Low-resolution devices (180/203 dpi) on small stickers can produce marginal (1–2 px module) QR codes — a warning is logged; prefer 300+ dpi for small templated stickers
    - Small-to-medium templated stickers commonly log the marginal-scannability warning even at 300 dpi (e.g. the example template at 2″/300 dpi yields 4 px modules — under the 5 px threshold). This is expected steady-state behavior, not an error; verify scans physically when in doubt
    - The app fails to start if the config is invalid
    - **Docker deployment**: `QR_TEMPLATE_CONFIG_PATH` affects every process that calls `create_app()` — the `app` container, the `worker` container, and CLI commands. Both `app` and `worker` load the same `.env` (`docker-compose.yml:9,52`), so the template directory (JSON + image + font) must be volume-mounted into **both** containers at the same path; mounting it only into `app` leaves the worker crash-looping at startup and notifications stop
  - Notes: Match the existing env-var documentation style in that file.

### Acceptance Criteria

- [x] AC 1: Given `QR_TEMPLATE_CONFIG_PATH` is unset, when any QR form/preview/download is exercised, then behavior is unchanged and the entire existing QR test suite passes unmodified (WiFi controls present, plain white-canvas rendering, `include_name` default unchecked). One deliberate exception: the initial preview-src serialization fix (Task 9.4) changes the GET/re-render HTML's preview query string from `include_name=True` to `include_name=1`/omitted — a bug fix that makes the preview honor a checked box on failed-POST re-renders.
- [x] AC 2: Given a valid template config, when a QR PNG is downloaded for any size preset **at 300 dpi or higher** (and whose canvas passes the `MAX_CANVAS_PX` guard — e.g. Letter @ 1200 dpi correctly errors instead, per AC 9), then the PNG has exactly the preset's pixel dimensions and embedded DPI metadata, shows the template artwork outside the bboxes, and pyzbar-decodes to `{base_url}/public/equipment/{id}`. (Low-DPI devices — 180/203 dpi — on small presets can legitimately produce 1 px modules that render with a warning but may not scan; see the Notes risk section. Dimension/metadata/artwork clauses still apply at all DPIs.)
- [x] AC 3: Given a template is active, when the output canvas is smaller than the template (downscale) or larger (upscale, e.g. US Letter), then the template scales proportionally (aspect preserved, centered on white) and the QR — drawn at integer module size into its white-filled bbox after scaling — still decodes.
- [x] AC 4: Given a template is active, when the form loads, then `include_name` is checked by default; when checked, the scaled name bbox is white-filled (replacing any placeholder artwork) and the equipment name renders in it using the configured font (single-line shrink-to-fit/ellipsis); when unchecked, the name bbox shows the template's own artwork untouched.
- [x] AC 5: Given a template config with `url_bbox`, when `include_url` is checked, then the scaled URL bbox is white-filled (replacing any baked artwork, e.g. the example's WiFi line) and the URL renders within it; given a config without `url_bbox`, then the `include_url` checkbox is absent from the form and a crafted `include_url` POST/preview param produces output pixel-identical (decoded `tobytes()` equality) to unchecked.
- [x] AC 6: Given a template is active, when the QR form is loaded, then the WiFi select is absent; and when a crafted WiFi value is submitted (POST field) or passed (preview query param), then the request succeeds (no validation rejection) and output is pixel-identical (decoded `tobytes()` equality) to `wifi_info='none'`.
- [x] AC 7: Given `QR_TEMPLATE_CONFIG_PATH` is set but invalid (missing file, malformed JSON, missing required key, bad/out-of-bounds bbox, missing image, missing/unloadable font), when `create_app()` runs, then startup fails with a `ValueError` naming the specific problem.
- [x] AC 8: Given a preset/DPI combination where the scaled QR bbox cannot fit at least 1 px per module, when generating, then a `ValueError` is flashed on the form (and the preview returns 400, with the broadened preview error message covering this cause); given a marginal (<5 px/module) result, then a scannability warning is logged and rendering proceeds.
- [x] AC 9: Given a template is active, when an oversized canvas is requested (e.g. Letter @ 1200 dpi), then the existing `MAX_CANVAS_PX` guard still raises before any template work.
- [x] AC 10: Given a template is active, when any render completes, then every pixel inside the scaled QR bbox is pure black or pure white (white-fill + NEAREST invariant — no placeholder ring, no antialiasing).

## Additional Context

### Dependencies

No new dependencies: `qrcode[pil]`, `Pillow`, and `pyzbar` (decode verification) are already in `requirements.txt`.

### Testing Strategy

- **Unit (service)**: `TestLoadTemplateConfig` — valid configs + every fail-fast mode; `TestRenderQRPngTemplate` — dimensions, decode verification (pyzbar) across downscale/aggressive-downscale/upscale at 300 dpi, whole-bbox QR purity (valid thanks to white-fill), name/URL **difference** assertions (the fixture's placeholder content makes presence assertions vacuous), WiFi-ignored byte equality, guard errors/warnings, DPI metadata. Fixtures: `tests/qr_code_template.png` (1500×1800 mock-up with placeholder content in all bboxes) + `tests/Poppins-Bold.ttf` with the issue's safe-area bboxes (Name `[240, 540, 1259, 925]`, QR `[509, 949, 1011, 1451]`, URL `[140, 1490, 1359, 1675]`).
- **Integration (views)**: `TestEquipmentQRTemplate` — form control visibility/defaults, download/preview behavior, wifi/include_url param hardening. Startup fail-fast tests in `tests/test_app.py` via `monkeypatch.setattr(TestingConfig, ...)`.
- **Regression gate**: the entire existing QR suite (`TestRenderQRPng*`, `TestEquipmentQR`) must pass unmodified — the non-template path is untouched.
- **Manual**: set `QR_TEMPLATE_CONFIG_PATH` to a config referencing the example template; load the QR page (WiFi gone, name checked by default, URL toggle present), check live preview at several sizes/devices, download `sticker_2` @ 300 dpi and `letter` @ 300 dpi, print or screen-scan both with a phone camera; verify the placeholder name/QR/URL areas are cleanly replaced.

### Notes

- GitHub Issue #57; fixtures already committed at `tests/qr_code_template.png` and `tests/Poppins-Bold.ttf`
- Example template native size: 1500×1800 RGB; QR bbox is 502×502 px native. **The example is a mock-up**: every bbox contains placeholder content (name "Resaw Bandsaw", red "QR Code" square, sample URL) — the white-fill semantics exist precisely so such templates render correctly.
- **Deliberate deviations from Issue #57 wording** (for stakeholder awareness): (1) the optional font applies to both name and URL text, not just the machine name; (2) the machine name remains user-toggleable (default ON with template) rather than unconditional; (3) text is single-line — the issue's mock-up shows a two-line wrapped name, but wrapping is out of scope (future consideration); (4) the issue says the template is "dynamically scaled **down** as needed" — this spec also scales **up** when the output canvas exceeds the template (e.g. Letter @ 300 dpi), since the alternative (a small centered sticker on a large page) is less useful; artwork softens on upscale while the QR stays crisp; (5) the white-fill/placeholder semantics are an interpretive addition not present in the issue: enabled elements' bboxes are white-filled before drawing (so mock-up templates render correctly), while a **disabled** toggle leaves that bbox's artwork untouched — meaning unchecking "Include name" with the example template prints its placeholder name ("Resaw Bandsaw"). This is deliberate: a real user would only uncheck the name toggle if the resulting output is acceptable for their template.
- **Expected log noise**: with the example template, even the form's default selection (`sticker_2` @ 300 dpi) yields ~4 px modules — under the `<5` warning threshold — so the marginal-scannability warning fires on every default-settings preview and download. This is accepted (the warning is informational and the 2″ output does scan); revisit the threshold or log level for the template path only if it proves noisy in practice.
- **Risk — tiny-preset decode flakiness**: at `sticker_1`/300 dpi, `s = min(300/1500, 300/1800) ≈ 0.167` (height-limited), so the scaled QR bbox is ≈ 84 px → ~2 px modules. Pure-B/W NEAREST output on a white-filled bbox at 2 px/module decodes reliably in pyzbar (verified empirically during spec review by rendering the prescribed pipeline and decoding — note the existing `test_wifi_header_small_preset` is NOT precedent for this: it exercises 5 px modules), but if a CI flake appears, pin the decode assertions to ≥1.5″ presets and keep `sticker_1` as a render-only (no-decode) test. At 180/203 dpi the same preset yields ~50–57 px bboxes → 1 px modules, which pass the `module_px ≥ 1` guard but are realistically unscannable — the `<5` warning fires and the admin docs advise 300+ dpi for small templated stickers; no decode tests at those combinations.
- **Quiet zone**: the QR image carries its own 4-module white border (`border=4`), and the bbox is white-filled before pasting, so artwork adjacent to (or formerly inside) the QR bbox cannot violate the quiet zone or contrast — no extra padding logic and no "plain background" requirement on the artwork.
- **Operator responsibility (documented, not enforced)**: supplying the template at the maximum resolution it will be printed at — upscaling softens artwork (the QR itself stays crisp).
- **Future (out of scope)**: multi-line name wrapping; multiple templates / per-equipment selection; admin upload UI; per-element font overrides; caching the decoded template image if preview profiling warrants.

## Review Notes

- Adversarial review completed (2026-06-07, isolated subagent, diff-only context)
- Findings: 16 total, 10 fixed, 6 skipped
- Resolution approach: auto-fix (findings classified "real" and not spec-accepted)
- Fixed: F1 (non-string image/font paths now raise the specific ValueError), F2 (startup validation forces a full image decode so truncated data fails fast), F3 (bbox overlap validation at load time — overlapping white-fills could erase the QR), F6 (DecompressionBombError caught at startup → ValueError; at render → RuntimeError for the views' handlers), F7 (conftest clears host QR_TEMPLATE_CONFIG_PATH from TestingConfig), F8 (direct tests for the ink-height shrink loop, ellipsization, and render-nothing path + end-to-end descender containment test), F10 (docs document the blank-box outcome; degradation now logs a warning), F11 (text re-ellipsized at the final font size instead of keeping the floor-font prefix), F12 (template-mode checkbox labels drop the "above/below QR" wording), F16 (QR construction + marginal warning deduped into _build_qr/_qr_to_image/_warn_if_marginal)
- Skipped: F4 (marginal-warning log noise — explicitly accepted in Notes), F5 (per-render template I/O — explicitly accepted in Technical Decisions), F9 (test bbox-mapping oracle mirrors renderer math — inherent, mitigated by decode/dimension tests), F13 (on-disk image swap after startup — out-of-band mutation, accepted), F14 (wifi config queried/passed but ignored in template mode — matches existing view structure), F15 (qr_bbox unusable at every preset passes startup — preset/DPI-dependent geometry can't be fully validated at boot; per-request guard + docs cover it)

### Round 2 (post-commit re-review)

- Adversarial review of the full committed diff (2026-06-07, isolated subagent)
- Findings: 13 total, 10 fixed, 3 skipped
- Resolution approach: auto-fix
- Fixed: R1 (width-constrained bboxes now shrink below the 8 pt floor instead of going blank — unified sub-floor loop covering width and ink height), R2 (template input image capped at MAX_CANVAS_PX at load; PIL's own bomb check only rejects above ~179 MP), R4 (render-time dimension check — a post-startup image swap with different dimensions raises RuntimeError instead of silently distorting), R5 (POST path blanks WiFi credentials in template mode, matching qr_preview), R6 (duplicate/inaccurate warning blocks collapsed into one accurate message; dead break removed), R8 (_open_template_rgb uses a context manager like the loader), R9 (conftest import-time TestingConfig mutation replaced with an autouse monkeypatch fixture), R10 (docs: any Pillow format accepted, EXIF orientation not applied, 50 MP cap), R12 (new tests: sub-floor width shrink, LA/P-transparency flattening, render-time bomb → 500 through the view, include_name POST round-trip, oversized-input and stale-dimension errors), R13 (module docstring covers the template path)
- Skipped: R3 (per-render template I/O — accepted in Technical Decisions), R7 (_HARD_MIN_TEXT_PX not dpi-scaled — spec prescribes the 4 px give-up bound; it is a degradation limit, not a legibility target), R11 (marginal-warning log noise — accepted in Notes)
- Behavior change from R1: unusably narrow boxes now degrade to a tiny ellipsis before going blank (test updated accordingly)
