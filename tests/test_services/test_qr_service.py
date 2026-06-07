"""Tests for QR code generation service."""

import inspect
import io
import json
import logging
import os

import pytest
from PIL import Image, ImageDraw
from pyzbar.pyzbar import decode

from esb.services.qr_service import (
    DEFAULT_DEVICE_KEY,
    MAX_CANVAS_PX,
    QR_DEVICE_PRESETS,
    QR_DEVICES_BY_KEY,
    QR_PRESETS_BY_KEY,
    QR_SIZE_PRESETS,
    QRSizePreset,
    _draw_text_in_bbox,
    _fit_text,
    _px,
    load_template_config,
    render_qr_png,
)


BASE_URL = 'http://esb.test:5000'

# tests/ directory — the committed template fixtures live there.
TESTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestQRSizePresets:
    def test_has_eight_entries(self):
        assert len(QR_SIZE_PRESETS) == 8

    def test_keys_unique(self):
        keys = [p.key for p in QR_SIZE_PRESETS]
        assert len(keys) == len(set(keys))

    def test_by_key_roundtrip(self):
        for p in QR_SIZE_PRESETS:
            assert QR_PRESETS_BY_KEY[p.key].key == p.key

    def test_dimensions_positive(self):
        for p in QR_SIZE_PRESETS:
            assert p.width_in > 0
            assert p.height_in > 0


class TestQRDevicePresets:
    def test_has_five_entries(self):
        assert len(QR_DEVICE_PRESETS) == 5

    def test_keys_unique(self):
        keys = [p.key for p in QR_DEVICE_PRESETS]
        assert len(keys) == len(set(keys))

    def test_default_present_and_300_dpi(self):
        assert DEFAULT_DEVICE_KEY == 'laser_300'
        assert QR_DEVICES_BY_KEY['laser_300'].dpi == 300

    def test_by_key_roundtrip(self):
        for p in QR_DEVICE_PRESETS:
            assert QR_DEVICES_BY_KEY[p.key].key == p.key

    def test_dpi_values_positive(self):
        for p in QR_DEVICE_PRESETS:
            assert p.dpi > 0


class TestRenderQRPng:
    def test_returns_png_bytes(self, app, make_equipment):
        eq = make_equipment(name='TestEq')
        result = render_qr_png(eq, QR_PRESETS_BY_KEY['sticker_2'], base_url=BASE_URL)
        assert isinstance(result, bytes)
        assert Image.open(io.BytesIO(result)).format == 'PNG'

    @pytest.mark.parametrize('preset', list(QR_SIZE_PRESETS), ids=[p.key for p in QR_SIZE_PRESETS])
    def test_dimensions_match_preset_at_300_dpi(self, app, make_equipment, preset):
        eq = make_equipment(name='TestEq')
        result = render_qr_png(eq, preset, base_url=BASE_URL)
        img = Image.open(io.BytesIO(result))
        expected = (int(preset.width_in * 300 + 0.5), int(preset.height_in * 300 + 0.5))
        assert img.size == expected

    @pytest.mark.parametrize('dpi', [180, 203, 600, 1200])
    @pytest.mark.parametrize(
        'preset',
        [QR_PRESETS_BY_KEY['sticker_1_5'], QR_PRESETS_BY_KEY['avery_5160']],
        ids=['sticker_1_5', 'avery_5160'],
    )
    def test_dimensions_match_preset_at_dpi(self, app, make_equipment, preset, dpi):
        eq = make_equipment(name='TestEq')
        result = render_qr_png(eq, preset, dpi=dpi, base_url=BASE_URL)
        img = Image.open(io.BytesIO(result))
        # MUST use the same round-half-up the code uses, NOT Python's banker's round().
        expected = (int(preset.width_in * dpi + 0.5), int(preset.height_in * dpi + 0.5))
        assert img.size == expected

    @pytest.mark.parametrize('dpi', [180, 203, 300, 600, 1200])
    def test_png_embeds_dpi_metadata(self, app, make_equipment, dpi):
        eq = make_equipment(name='TestEq')
        result = render_qr_png(eq, QR_PRESETS_BY_KEY['sticker_2'], dpi=dpi, base_url=BASE_URL)
        img = Image.open(io.BytesIO(result))
        # Pillow round-trips DPI through a rational, so it returns floats like
        # (202.9968, 202.9968) — assert with integer-rounded tolerance, not exact equality.
        embedded = img.info['dpi']
        assert tuple(round(v) for v in embedded) == (dpi, dpi)

    def test_oversized_canvas_raises(self, app, make_equipment):
        eq = make_equipment(name='TestEq')
        # US Letter @ 1200 dpi = 10200×13200 ≈ 134.6 MP > 50 MP cap.
        with pytest.raises(ValueError, match='too large to render'):
            render_qr_png(eq, QR_PRESETS_BY_KEY['letter'], dpi=1200, base_url=BASE_URL)

    def test_large_but_allowed_ok(self, app, make_equipment):
        eq = make_equipment(name='TestEq')
        # 4″ sticker @ 1200 dpi = 4800×4800 = 23.04 MP, under the cap. This is the one
        # deliberately heavy render kept to prove a large canvas allocates and renders
        # end-to-end (and to cover AC2's 4800×4800 dimensions); the lighter under-cap
        # boundaries below are checked arithmetically to keep the suite CI-friendly.
        result = render_qr_png(eq, QR_PRESETS_BY_KEY['sticker_4'], dpi=1200, base_url=BASE_URL)
        assert Image.open(io.BytesIO(result)).size == (4800, 4800)

    def test_letter_at_600_dpi_under_cap(self):
        # US Letter @ 600 dpi = 5100×6600 = 33.66 MP, under the 50 MP cap, so it must NOT
        # trip the oversized guard. Verify the guard's pixel-count condition arithmetically
        # rather than allocating a ~101 MB canvas in CI.
        letter = QR_PRESETS_BY_KEY['letter']
        canvas_px = _px(letter.width_in, 600) * _px(letter.height_in, 600)
        assert canvas_px == 5100 * 6600
        assert canvas_px <= MAX_CANVAS_PX

    def test_payload_decodes_to_expected_url(self, app, make_equipment):
        eq = make_equipment(name='TestEq')
        # Force id 42 for stable assertion
        eq.id = 42
        result = render_qr_png(eq, QR_PRESETS_BY_KEY['sticker_3'], base_url=BASE_URL)
        decoded = decode(Image.open(io.BytesIO(result)))
        assert len(decoded) >= 1
        assert decoded[0].data.decode('utf-8') == f'{BASE_URL}/public/equipment/42'

    def test_name_text_renders(self, app, make_equipment):
        eq = make_equipment(name='Widget')
        result = render_qr_png(
            eq, QR_PRESETS_BY_KEY['sticker_4'],
            include_name=True, base_url=BASE_URL,
        )
        img = Image.open(io.BytesIO(result))
        # Top 15% row has non-white pixels (text drawn).
        top_row_height = int(img.height * 0.15)
        top = img.crop((0, 0, img.width, top_row_height)).convert('RGB')
        colors = {c for _, c in top.getcolors(maxcolors=256 * 256) or []}
        assert any(c != (255, 255, 255) for c in colors)
        # QR still decodes — text did not overlap QR region.
        decoded = decode(img)
        assert len(decoded) >= 1

    def test_name_omitted_by_default(self, app, make_equipment):
        """When include_name is False, no anti-aliased (gray) pixels appear anywhere.

        TrueType text rendering produces anti-aliased glyph edges (grays). The QR
        itself is pure black/white after NEAREST resize. If any gray pixel exists
        in the whole canvas, some text was drawn; if none exists, no text was drawn.
        """
        eq = make_equipment(name='Widget')
        result = render_qr_png(
            eq, QR_PRESETS_BY_KEY['sticker_3'], base_url=BASE_URL,
        )
        img = Image.open(io.BytesIO(result)).convert('RGB')
        colors = img.getcolors(maxcolors=256 * 256 * 256) or []
        non_binary = [c for _, c in colors if c not in ((0, 0, 0), (255, 255, 255))]
        assert non_binary == [], (
            f'found non-binary pixels {non_binary[:5]} — text was drawn despite include_name=False'
        )

    def test_name_drawn_produces_grays(self, app, make_equipment):
        """Sanity check: when include_name=True, anti-aliased grays do appear."""
        eq = make_equipment(name='Widget')
        result = render_qr_png(
            eq, QR_PRESETS_BY_KEY['sticker_4'],
            include_name=True, base_url=BASE_URL,
        )
        img = Image.open(io.BytesIO(result)).convert('RGB')
        colors = img.getcolors(maxcolors=256 * 256 * 256) or []
        non_binary = [c for _, c in colors if c not in ((0, 0, 0), (255, 255, 255))]
        assert non_binary, 'expected some anti-aliased text pixels when include_name=True'

    def test_url_text_toggle(self, app, make_equipment):
        eq = make_equipment(name='Widget')
        # With URL included, bottom 15% should contain non-white.
        result = render_qr_png(
            eq, QR_PRESETS_BY_KEY['sticker_4'],
            include_url=True, base_url=BASE_URL,
        )
        img = Image.open(io.BytesIO(result)).convert('RGB')
        bot_row_height = int(img.height * 0.15)
        bottom = img.crop((0, img.height - bot_row_height, img.width, img.height))
        colors = bottom.getcolors(maxcolors=256 * 256) or []
        assert any(c != (255, 255, 255) for _, c in colors)

    def test_text_width_cap(self, app, make_equipment):
        """Rendered text width ≤ 120% of QR width for extremely long name."""
        long_name = 'X' * 100
        eq = make_equipment(name=long_name)
        result = render_qr_png(
            eq, QR_PRESETS_BY_KEY['sticker_3'],
            include_name=True, base_url=BASE_URL,
        )
        img = Image.open(io.BytesIO(result)).convert('RGB')
        # Locate the non-white region in the top 15% band and measure its width.
        top_row_height = int(img.height * 0.15)
        top = img.crop((0, 0, img.width, top_row_height))
        width, height = top.size
        pixels = top.load()
        min_x, max_x = width, -1
        for y in range(height):
            for x in range(width):
                if pixels[x, y] != (255, 255, 255):
                    if x < min_x:
                        min_x = x
                    if x > max_x:
                        max_x = x
        assert max_x >= 0, 'expected some text pixels'
        measured_width = max_x - min_x + 1
        # QR is sized such that text_max = int(qr_px * 1.2). Compute qr_px from the canvas:
        canvas_w = img.width
        canvas_h = img.height
        reserved_top = int(canvas_h * 0.15)  # include_name=True
        reserved_bottom = 0
        margin = max(4, int(canvas_w * 0.02))
        avail = min(canvas_w, canvas_h - reserved_top - reserved_bottom) - margin
        # Native matrix size determined by qrcode — compute via same logic:
        import qrcode
        q = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=1, border=4)
        q.add_data(f'{BASE_URL}/public/equipment/{eq.id}')
        q.make(fit=True)
        native = len(q.get_matrix())
        module_px = avail // native
        qr_px = module_px * native
        assert measured_width <= int(qr_px * 1.2) + 2, (
            f'text width {measured_width} exceeds cap {int(qr_px * 1.2)}'
        )

    def test_qr_uses_nearest_resize(self, app, make_equipment):
        """Every pixel in the QR region is pure black or pure white (NEAREST, not LANCZOS)."""
        eq = make_equipment(name='TestEq')
        result = render_qr_png(
            eq, QR_PRESETS_BY_KEY['sticker_3'], base_url=BASE_URL,
        )
        img = Image.open(io.BytesIO(result)).convert('RGB')
        # Compute QR region:
        canvas_w, canvas_h = img.size
        margin = max(4, int(canvas_w * 0.02))
        avail = min(canvas_w, canvas_h) - margin
        import qrcode
        q = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=1, border=4)
        q.add_data(f'{BASE_URL}/public/equipment/{eq.id}')
        q.make(fit=True)
        native = len(q.get_matrix())
        module_px = avail // native
        qr_px = module_px * native
        x0 = (canvas_w - qr_px) // 2
        y0 = ((canvas_h) - qr_px) // 2
        qr_region = img.crop((x0, y0, x0 + qr_px, y0 + qr_px))
        colors = qr_region.getcolors(maxcolors=256 * 256) or []
        for _, c in colors:
            assert c in ((0, 0, 0), (255, 255, 255)), f'non-binary pixel {c} — anti-aliased?'

    def test_modules_have_uniform_pixel_width(self, app, make_equipment):
        """QR square width = native * module_px; runs within are multiples of module_px."""
        eq = make_equipment(name='TestEq')
        preset = QR_PRESETS_BY_KEY['sticker_4']
        result = render_qr_png(eq, preset, base_url=BASE_URL)
        img = Image.open(io.BytesIO(result)).convert('RGB')
        canvas_w, canvas_h = img.size
        margin = max(4, int(canvas_w * 0.02))
        avail = min(canvas_w, canvas_h) - margin
        import qrcode
        q = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=1, border=4)
        q.add_data(f'{BASE_URL}/public/equipment/{eq.id}')
        q.make(fit=True)
        native = len(q.get_matrix())
        module_px = avail // native
        qr_px = module_px * native
        assert module_px >= 1
        assert qr_px == native * module_px
        assert qr_px <= avail
        if module_px > 1:
            # Scan a horizontal row across the QR and verify runs are multiples of module_px.
            x0 = (canvas_w - qr_px) // 2
            y0 = ((canvas_h) - qr_px) // 2
            mid_y = y0 + qr_px // 2
            row = [img.getpixel((x, mid_y)) for x in range(x0, x0 + qr_px)]
            run_color = row[0]
            run_len = 1
            for px in row[1:]:
                if px == run_color:
                    run_len += 1
                else:
                    assert run_len % module_px == 0, (
                        f'run length {run_len} not a multiple of module_px {module_px}'
                    )
                    run_color = px
                    run_len = 1
            assert run_len % module_px == 0

    def test_raises_valueerror_on_overflow(self, app, make_equipment):
        """When native QR matrix > avail square, raise ValueError."""
        eq = make_equipment(name='TestEq')
        # Inject a contrived tiny preset smaller than any QR native matrix.
        tiny = QRSizePreset('tiny', '0.1"×0.1" tiny', 0.1, 0.1)
        with pytest.raises(ValueError, match='choose a larger preset'):
            render_qr_png(eq, tiny, base_url=BASE_URL)

    def test_marginal_module_size_logs_warning(self, app, make_equipment, caplog):
        """module_px < 5 logs a warning."""
        eq = make_equipment(name='TestEq')
        # sticker_1 + long URL → small modules
        long_base = 'http://' + ('example' * 20) + '.com:5000'
        logger_name = app.logger.name
        original_propagate = app.logger.propagate
        app.logger.propagate = True
        try:
            with caplog.at_level(logging.WARNING, logger=logger_name):
                render_qr_png(
                    eq, QR_PRESETS_BY_KEY['sticker_1'],
                    base_url=long_base,
                )
            messages = ' '.join(r.getMessage() for r in caplog.records)
            assert 'scannability may be marginal' in messages
        finally:
            app.logger.propagate = original_propagate


class TestFitText:
    def _font_path(self, app):
        import os
        return os.path.join(app.static_folder, 'fonts', 'DejaVuSans-Bold.ttf')

    def test_fits_as_is_when_short(self, app):
        font, rendered = _fit_text(
            'Hi', max_width_px=500, max_height_px=100,
            font_path=self._font_path(app),
        )
        assert rendered == 'Hi'
        # Font returned at starting size (max_height_px).
        assert font.size == 100

    def test_shrinks_when_long_but_fits_at_min(self, app):
        # A string that won't fit at max_height_px but fits at a smaller size above the floor.
        # max_width=120 at max_height=66 leaves room for shrinking to ~42px where 'abcd' fits.
        font, rendered = _fit_text(
            'abcd', max_width_px=120, max_height_px=66,
            font_path=self._font_path(app),
        )
        assert rendered == 'abcd'
        assert font.size < 66

    def test_truncates_with_ellipsis_when_too_long_at_min(self, app):
        font, rendered = _fit_text(
            'X' * 100, max_width_px=80, max_height_px=50,
            font_path=self._font_path(app),
        )
        assert rendered.endswith('…')
        # Measure rendered width ≤ cap.
        draw = ImageDraw.Draw(Image.new('RGB', (1, 1)))
        (left, _, right, _) = draw.textbbox((0, 0), rendered, font=font)
        assert right - left <= 80

    def test_returns_empty_when_ellipsis_alone_too_long(self, app):
        # max_width_px smaller than any ellipsis glyph at 8pt.
        font, rendered = _fit_text(
            'anything', max_width_px=1, max_height_px=50,
            font_path=self._font_path(app),
        )
        assert rendered == ''

    def test_low_dpi_lowers_font_floor(self, app):
        # A string too wide at any size down to the floor must shrink to the floor.
        # At 203 dpi the 8 pt floor is int(8*203/72+0.5)=23 px, lower than the 300 dpi
        # floor of 33 px — locks in the dpi fan-out fix.
        font, rendered = _fit_text(
            'X' * 60, max_width_px=40, max_height_px=400,
            font_path=self._font_path(app), dpi=203,
        )
        # Truncated to ellipsis at the lowered floor; font.size honors the 203 dpi floor.
        assert font.size == int(8 * 203 / 72 + 0.5)


class TestRenderQRPngWifi:
    """Tests for WiFi header rendering in QR PNGs."""

    def test_wifi_header_renders_pixels_at_top(self, app, make_equipment):
        eq = make_equipment(name='Widget')
        result = render_qr_png(
            eq, QR_PRESETS_BY_KEY['sticker_4'],
            base_url=BASE_URL, wifi_info='header',
        )
        img = Image.open(io.BytesIO(result)).convert('RGB')
        canvas_h = img.height
        wifi_budget = int(canvas_h * 0.30)
        wifi_row_height = wifi_budget
        top = img.crop((0, 0, img.width, wifi_row_height))
        pixels = top.load()
        min_x, max_x = img.width, -1
        for y in range(top.height):
            for x in range(top.width):
                if pixels[x, y] != (255, 255, 255):
                    min_x = min(min_x, x)
                    max_x = max(max_x, x)
        assert max_x >= 0, 'no non-white pixels in WiFi header region'
        content_width = max_x - min_x + 1
        assert content_width >= 2 * wifi_row_height, (
            f'content width {content_width} should span at least 2x row height {wifi_row_height}'
        )

    def test_wifi_none_renders_no_wifi_pixels(self, app, make_equipment):
        eq = make_equipment(name='Widget')
        result_none = render_qr_png(
            eq, QR_PRESETS_BY_KEY['sticker_4'],
            base_url=BASE_URL, wifi_info='none',
        )
        result_default = render_qr_png(
            eq, QR_PRESETS_BY_KEY['sticker_4'],
            base_url=BASE_URL,
        )
        img_none = Image.open(io.BytesIO(result_none)).convert('RGB')
        img_default = Image.open(io.BytesIO(result_default)).convert('RGB')
        assert img_none.tobytes() == img_default.tobytes()

    def test_wifi_ssid_renders_two_rows(self, app, make_equipment):
        eq = make_equipment(name='Widget')
        result = render_qr_png(
            eq, QR_PRESETS_BY_KEY['sticker_4'],
            base_url=BASE_URL, wifi_info='ssid', wifi_ssid='TestNet',
        )
        img = Image.open(io.BytesIO(result)).convert('RGB')
        canvas_h = img.height
        wifi_budget = int(canvas_h * 0.30)
        row_h = wifi_budget // 2
        for i in range(2):
            row = img.crop((0, i * row_h, img.width, (i + 1) * row_h))
            colors = {c for _, c in row.getcolors(maxcolors=256 * 256) or []}
            assert any(c != (255, 255, 255) for c in colors), f'WiFi row {i} is all white'

    def test_wifi_password_renders_three_rows(self, app, make_equipment):
        eq = make_equipment(name='Widget')
        result = render_qr_png(
            eq, QR_PRESETS_BY_KEY['sticker_4'],
            base_url=BASE_URL, wifi_info='password',
            wifi_ssid='TestNet', wifi_password='secret123',
        )
        img = Image.open(io.BytesIO(result)).convert('RGB')
        canvas_h = img.height
        wifi_budget = int(canvas_h * 0.30)
        row_h = wifi_budget // 3
        for i in range(3):
            row = img.crop((0, i * row_h, img.width, (i + 1) * row_h))
            colors = {c for _, c in row.getcolors(maxcolors=256 * 256) or []}
            assert any(c != (255, 255, 255) for c in colors), f'WiFi row {i} is all white'

    def test_wifi_header_qr_still_decodes(self, app, make_equipment):
        eq = make_equipment(name='Widget')
        eq.id = 42
        result = render_qr_png(
            eq, QR_PRESETS_BY_KEY['sticker_4'],
            base_url=BASE_URL, wifi_info='header',
        )
        decoded = decode(Image.open(io.BytesIO(result)))
        assert len(decoded) >= 1
        assert decoded[0].data.decode('utf-8') == f'{BASE_URL}/public/equipment/42'

    def test_wifi_info_none_backward_compatible(self, app, make_equipment):
        eq = make_equipment(name='Widget')
        result_none = render_qr_png(
            eq, QR_PRESETS_BY_KEY['sticker_4'],
            base_url=BASE_URL, wifi_info='none',
        )
        result_default = render_qr_png(
            eq, QR_PRESETS_BY_KEY['sticker_4'],
            base_url=BASE_URL,
        )
        img_none = Image.open(io.BytesIO(result_none)).convert('RGB')
        img_default = Image.open(io.BytesIO(result_default)).convert('RGB')
        assert img_none.tobytes() == img_default.tobytes()

        result_with_name = render_qr_png(
            eq, QR_PRESETS_BY_KEY['sticker_4'],
            base_url=BASE_URL, wifi_info='none', include_name=True,
        )
        img_name = Image.open(io.BytesIO(result_with_name)).convert('RGB')
        top_row_height = int(img_name.height * 0.15)
        top = img_name.crop((0, 0, img_name.width, top_row_height))
        colors = {c for _, c in top.getcolors(maxcolors=256 * 256) or []}
        assert any(c != (255, 255, 255) for c in colors), 'name row should start at y=0'

    def test_wifi_header_small_preset(self, app, make_equipment):
        eq = make_equipment(name='Widget')
        result = render_qr_png(
            eq, QR_PRESETS_BY_KEY['sticker_1'],
            base_url=BASE_URL, wifi_info='header',
        )
        img = Image.open(io.BytesIO(result))
        assert img.format == 'PNG'
        decoded = decode(img)
        assert len(decoded) >= 1

    def test_wifi_unknown_value_renders_no_wifi(self, app, make_equipment):
        """Service-layer defense: unknown wifi_info values produce no WiFi rows,
        identical to wifi_info='none'."""
        eq = make_equipment(name='Widget')
        result_bogus = render_qr_png(
            eq, QR_PRESETS_BY_KEY['sticker_4'],
            base_url=BASE_URL, wifi_info='bogus',
        )
        result_none = render_qr_png(
            eq, QR_PRESETS_BY_KEY['sticker_4'],
            base_url=BASE_URL, wifi_info='none',
        )
        img_bogus = Image.open(io.BytesIO(result_bogus)).convert('RGB')
        img_none = Image.open(io.BytesIO(result_none)).convert('RGB')
        assert img_bogus.tobytes() == img_none.tobytes()

    def test_wifi_all_rows_small_preset(self, app, make_equipment):
        eq = make_equipment(name='Widget')
        result = render_qr_png(
            eq, QR_PRESETS_BY_KEY['avery_5160'],
            base_url=BASE_URL, wifi_info='password',
            wifi_ssid='Net', wifi_password='pass',
        )
        img = Image.open(io.BytesIO(result))
        assert img.format == 'PNG'
        decoded = decode(img)
        assert len(decoded) >= 1

    def test_wifi_rows_respect_55_percent_budget(self, app, make_equipment):
        """Replicate the renderer's row-drop math and verify the QR is positioned
        as if total text reservation <= 55% of canvas."""
        eq = make_equipment(name='Widget')
        preset = QR_PRESETS_BY_KEY['sticker_1']
        result = render_qr_png(
            eq, preset,
            base_url=BASE_URL, wifi_info='password',
            wifi_ssid='Net', wifi_password='pass',
            include_name=True, include_url=True,
        )
        img = Image.open(io.BytesIO(result)).convert('RGB')
        canvas_h = img.height
        max_text_px = int(canvas_h * 0.55)
        reserved_top = int(canvas_h * 0.15)
        reserved_bottom = int(canvas_h * 0.15)

        # Replicate renderer's drop loop to compute effective wifi rows.
        min_row_px = int(8 * 300 / 72 + 0.5) + 4
        wifi_budget = int(canvas_h * 0.30)
        effective = 3
        while effective > 0:
            wifi_row_height = max(wifi_budget // effective, min_row_px)
            if reserved_top + reserved_bottom + effective * wifi_row_height <= max_text_px:
                break
            effective -= 1
        reserved_wifi = effective * wifi_row_height if effective > 0 else 0
        assert reserved_top + reserved_bottom + reserved_wifi <= max_text_px, (
            f'total reserved {reserved_top + reserved_bottom + reserved_wifi} exceeds 55% budget {max_text_px}'
        )

        # The QR code occupies the central band between reserved_wifi+reserved_top and
        # canvas_h - reserved_bottom. Verify the QR centerline pixel is in that range.
        qr_band_top = reserved_wifi + reserved_top
        qr_band_bottom = canvas_h - reserved_bottom
        # Find the topmost row in the QR band where black pixels appear.
        center_x = img.width // 2
        first_black_y = None
        for y in range(qr_band_top, qr_band_bottom):
            if img.getpixel((center_x, y)) == (0, 0, 0):
                first_black_y = y
                break
        assert first_black_y is not None, 'QR not found in expected band'
        assert first_black_y >= qr_band_top, (
            f'QR top {first_black_y} above expected band start {qr_band_top}'
        )


def _write_template_config(tmp_path, **overrides):
    """Write a template config JSON into tmp_path and return its path.

    Defaults reference the committed example fixtures; pass key=None to omit a
    key, or key=value to override.
    """
    config = {
        'image': os.path.relpath(os.path.join(TESTS_DIR, 'qr_code_template.png'), tmp_path),
        'font': os.path.relpath(os.path.join(TESTS_DIR, 'Poppins-Bold.ttf'), tmp_path),
        'qr_bbox': [509, 949, 1011, 1451],
        'name_bbox': [240, 540, 1259, 925],
        'url_bbox': [140, 1490, 1359, 1675],
    }
    config.update(overrides)
    config = {k: v for k, v in config.items() if v is not None}
    path = tmp_path / 'template_config.json'
    path.write_text(json.dumps(config))
    return str(path)


def _scaled_bbox(bbox, template, canvas_w, canvas_h):
    """Map a template-native bbox to canvas coordinates — same math as the renderer."""
    s = min(canvas_w / template.image_w, canvas_h / template.image_h)
    scaled_w = max(1, round(template.image_w * s))
    scaled_h = max(1, round(template.image_h * s))
    off_x = (canvas_w - scaled_w) // 2
    off_y = (canvas_h - scaled_h) // 2
    x0, y0, x1, y1 = bbox
    return (
        off_x + round(x0 * s), off_y + round(y0 * s),
        off_x + round(x1 * s), off_y + round(y1 * s),
    )


class TestLoadTemplateConfig:
    def test_valid_full_config(self, tmp_path):
        path = _write_template_config(tmp_path)
        template = load_template_config(path)
        assert os.path.isabs(template.image_path)
        assert template.image_path.endswith('qr_code_template.png')
        assert os.path.isabs(template.font_path)
        assert template.font_path.endswith('Poppins-Bold.ttf')
        assert (template.image_w, template.image_h) == (1500, 1800)
        assert template.qr_bbox == (509, 949, 1011, 1451)
        assert template.name_bbox == (240, 540, 1259, 925)
        assert template.url_bbox == (140, 1490, 1359, 1675)

    def test_font_omitted_falls_back_to_vendored_dejavu(self, tmp_path):
        import esb
        path = _write_template_config(tmp_path, font=None)
        template = load_template_config(path)
        expected = os.path.join(
            os.path.dirname(esb.__file__), 'static', 'fonts', 'DejaVuSans-Bold.ttf'
        )
        assert template.font_path == expected
        assert os.path.isfile(template.font_path)

    def test_url_bbox_omitted_is_none(self, tmp_path):
        path = _write_template_config(tmp_path, url_bbox=None)
        template = load_template_config(path)
        assert template.url_bbox is None

    def test_unknown_keys_ignored(self, tmp_path):
        path = _write_template_config(tmp_path, future_key='whatever', other=[1, 2])
        template = load_template_config(path)
        assert template.qr_bbox == (509, 949, 1011, 1451)

    def test_full_bleed_bbox_legal(self, tmp_path):
        # Exclusive convention: x1 == image_w / y1 == image_h must be accepted.
        # (Full image width, below the QR bbox so it doesn't overlap anything.)
        path = _write_template_config(tmp_path, url_bbox=[0, 1451, 1500, 1800])
        template = load_template_config(path)
        assert template.url_bbox == (0, 1451, 1500, 1800)

    def test_nonexistent_json_path_raises(self, tmp_path):
        with pytest.raises(ValueError, match='unreadable'):
            load_template_config(str(tmp_path / 'missing.json'))

    def test_malformed_json_raises(self, tmp_path):
        path = tmp_path / 'bad.json'
        path.write_text('{not json!')
        with pytest.raises(ValueError, match='not valid JSON'):
            load_template_config(str(path))

    def test_non_object_json_raises(self, tmp_path):
        path = tmp_path / 'list.json'
        path.write_text('[1, 2, 3]')
        with pytest.raises(ValueError, match='must be a JSON object'):
            load_template_config(str(path))

    @pytest.mark.parametrize('missing', ['image', 'qr_bbox', 'name_bbox'])
    def test_missing_required_key_raises(self, tmp_path, missing):
        path = _write_template_config(tmp_path, **{missing: None})
        with pytest.raises(ValueError, match=f"missing required key '{missing}'"):
            load_template_config(str(path))

    @pytest.mark.parametrize('bad_bbox', [
        [1, 2, 3],                      # wrong length
        [1, 2, 3, 4, 5],                # wrong length
        ['a', 2, 3, 4],                 # non-int
        [1.5, 2, 3, 4],                 # float
        [True, 2, 3, 4],                # bool is not an int here
        'not-a-list',
    ], ids=['len3', 'len5', 'str-coord', 'float-coord', 'bool-coord', 'not-list'])
    def test_bbox_not_4_ints_raises(self, tmp_path, bad_bbox):
        path = _write_template_config(tmp_path, qr_bbox=bad_bbox)
        with pytest.raises(ValueError, match='qr_bbox must be a list of exactly 4 integers'):
            load_template_config(str(path))

    @pytest.mark.parametrize('degenerate', [
        [100, 100, 100, 200],   # x1 == x0
        [200, 100, 100, 200],   # x1 < x0
        [100, 200, 200, 200],   # y1 == y0
        [100, 300, 200, 200],   # y1 < y0
    ], ids=['x-equal', 'x-inverted', 'y-equal', 'y-inverted'])
    def test_degenerate_bbox_raises(self, tmp_path, degenerate):
        path = _write_template_config(tmp_path, name_bbox=degenerate)
        with pytest.raises(ValueError, match='degenerate'):
            load_template_config(str(path))

    @pytest.mark.parametrize('out_of_bounds', [
        [-1, 0, 100, 100],
        [0, -5, 100, 100],
        [0, 0, 1501, 100],
        [0, 0, 100, 1801],
    ], ids=['neg-x0', 'neg-y0', 'x1-over', 'y1-over'])
    def test_out_of_bounds_bbox_raises(self, tmp_path, out_of_bounds):
        path = _write_template_config(tmp_path, url_bbox=out_of_bounds)
        with pytest.raises(ValueError, match='outside the template image bounds'):
            load_template_config(str(path))

    @pytest.mark.parametrize('bad_image', [123, '', ['a.png']], ids=['int', 'empty', 'list'])
    def test_non_string_image_raises_valueerror(self, tmp_path, bad_image):
        path = _write_template_config(tmp_path, image=bad_image)
        with pytest.raises(ValueError, match='image must be a non-empty string path'):
            load_template_config(str(path))

    @pytest.mark.parametrize('bad_font', [123, '', {'f': 1}], ids=['int', 'empty', 'dict'])
    def test_non_string_font_raises_valueerror(self, tmp_path, bad_font):
        path = _write_template_config(tmp_path, font=bad_font)
        with pytest.raises(ValueError, match='font must be a non-empty string path'):
            load_template_config(str(path))

    def test_truncated_image_data_raises_at_load(self, tmp_path):
        """Image.open parses only the header — validation must force a full decode."""
        src = os.path.join(TESTS_DIR, 'qr_code_template.png')
        with open(src, 'rb') as f:
            truncated = f.read(2000)
        (tmp_path / 'truncated.png').write_bytes(truncated)
        path = _write_template_config(tmp_path, image='truncated.png')
        with pytest.raises(ValueError, match='cannot open template image'):
            load_template_config(str(path))

    def test_decompression_bomb_raises_valueerror(self, tmp_path, monkeypatch):
        """DecompressionBombError subclasses Exception, not OSError — must still
        surface as the specific config ValueError, not a raw traceback."""
        monkeypatch.setattr(Image, 'MAX_IMAGE_PIXELS', 1000)
        path = _write_template_config(tmp_path)
        with pytest.raises(ValueError, match='cannot open template image'):
            load_template_config(str(path))

    @pytest.mark.parametrize('key,bbox', [
        # Overlapping the QR bbox would let a later white-fill erase the QR.
        ('name_bbox', [509, 540, 1259, 1000]),
        ('url_bbox', [140, 1400, 1359, 1675]),
    ], ids=['name-over-qr', 'url-over-qr'])
    def test_overlapping_bboxes_raise(self, tmp_path, key, bbox):
        path = _write_template_config(tmp_path, **{key: bbox})
        with pytest.raises(ValueError, match='overlap'):
            load_template_config(str(path))

    def test_name_url_overlap_raises(self, tmp_path):
        # Overlaps name_bbox [240, 540, 1259, 925] but not qr_bbox.
        path = _write_template_config(tmp_path, url_bbox=[240, 700, 1259, 900])
        with pytest.raises(ValueError, match='overlap'):
            load_template_config(str(path))

    def test_nonexistent_image_raises(self, tmp_path):
        path = _write_template_config(tmp_path, image='no-such-image.png')
        with pytest.raises(ValueError, match='cannot open template image'):
            load_template_config(str(path))

    def test_nonexistent_font_raises(self, tmp_path):
        path = _write_template_config(tmp_path, font='no-such-font.ttf')
        with pytest.raises(ValueError, match='cannot load font'):
            load_template_config(str(path))

    def test_non_font_file_as_font_raises(self, tmp_path):
        # The template PNG exists but is not loadable as a truetype font.
        path = _write_template_config(
            tmp_path,
            font=os.path.relpath(os.path.join(TESTS_DIR, 'qr_code_template.png'), tmp_path),
        )
        with pytest.raises(ValueError, match='cannot load font'):
            load_template_config(str(path))

    def test_oversized_template_image_raises(self, tmp_path, monkeypatch):
        """Input images are capped like output canvases — a huge template
        would be fully decoded and resized per render."""
        from esb.services import qr_service
        monkeypatch.setattr(qr_service, 'MAX_CANVAS_PX', 1000)
        path = _write_template_config(tmp_path)
        with pytest.raises(ValueError, match='exceeding the 1,000 px limit'):
            load_template_config(str(path))


class TestRenderQRPngTemplate:
    """Template rendering tests.

    The fixture template is a mock-up with placeholder content inside every
    bbox, so presence-of-pixels assertions are vacuous — these tests assert
    differences between renders instead.
    """

    @staticmethod
    def _render(eq, template, preset_key='sticker_2', dpi=300, **kwargs):
        return render_qr_png(
            eq, QR_PRESETS_BY_KEY[preset_key], dpi=dpi, base_url=BASE_URL,
            template=template, **kwargs,
        )

    @pytest.mark.parametrize(
        'preset_key', ['sticker_2', 'avery_5163', 'letter'],
    )
    def test_dimensions_match_preset(self, app, make_equipment, make_qr_template_config, preset_key):
        eq = make_equipment(name='Bandsaw')
        template = make_qr_template_config()
        result = self._render(eq, template, preset_key=preset_key)
        img = Image.open(io.BytesIO(result))
        preset = QR_PRESETS_BY_KEY[preset_key]
        assert img.size == (_px(preset.width_in, 300), _px(preset.height_in, 300))

    @pytest.mark.parametrize(
        'preset_key',
        ['sticker_2', 'sticker_1', 'letter'],
        ids=['downscale', 'aggressive-downscale', 'upscale'],
    )
    def test_qr_decodes_at_300dpi(self, app, make_equipment, make_qr_template_config, preset_key):
        eq = make_equipment(name='Bandsaw')
        eq.id = 42
        template = make_qr_template_config()
        result = self._render(eq, template, preset_key=preset_key)
        decoded = decode(Image.open(io.BytesIO(result)))
        assert len(decoded) >= 1
        assert decoded[0].data.decode('utf-8') == f'{BASE_URL}/public/equipment/42'

    def test_qr_bbox_pure_black_white(self, app, make_equipment, make_qr_template_config):
        """White-fill + NEAREST invariant: no placeholder ring, no antialiasing."""
        eq = make_equipment(name='Bandsaw')
        template = make_qr_template_config()
        result = self._render(eq, template)
        img = Image.open(io.BytesIO(result)).convert('RGB')
        qr_box = _scaled_bbox(template.qr_bbox, template, img.width, img.height)
        region = img.crop(qr_box)
        colors = region.getcolors(maxcolors=256 * 256) or []
        for _, c in colors:
            assert c in ((0, 0, 0), (255, 255, 255)), f'non-binary pixel {c} in QR bbox'

    def test_template_artwork_visible_outside_bboxes(
        self, app, make_equipment, make_qr_template_config,
    ):
        eq = make_equipment(name='Bandsaw')
        template = make_qr_template_config()
        result = self._render(eq, template)
        img = Image.open(io.BytesIO(result)).convert('RGB')
        # Blank the three bbox regions, then look for remaining artwork.
        for bbox in (template.qr_bbox, template.name_bbox, template.url_bbox):
            img.paste((255, 255, 255), _scaled_bbox(bbox, template, img.width, img.height))
        colors = img.getcolors(maxcolors=256 * 256 * 256) or []
        assert any(c != (255, 255, 255) for _, c in colors), (
            'expected template artwork outside the bboxes'
        )

    def test_name_toggle_difference(self, app, make_equipment, make_qr_template_config):
        # Descender-free name sized well below the bbox so the outside-bbox
        # comparison isn't sensitive to ink metrics.
        eq = make_equipment(name='Bandsaw')
        template = make_qr_template_config()
        result_on = self._render(eq, template, include_name=True)
        result_off = self._render(eq, template, include_name=False)
        img_on = Image.open(io.BytesIO(result_on)).convert('RGB')
        img_off = Image.open(io.BytesIO(result_off)).convert('RGB')
        name_box = _scaled_bbox(template.name_bbox, template, img_on.width, img_on.height)
        assert img_on.crop(name_box).tobytes() != img_off.crop(name_box).tobytes(), (
            'name bbox should differ between include_name on/off'
        )
        # Outside the name bbox the renders are identical.
        img_on.paste((0, 0, 0), name_box)
        img_off.paste((0, 0, 0), name_box)
        assert img_on.tobytes() == img_off.tobytes(), (
            'pixels outside the name bbox should be identical'
        )

    def test_name_off_leaves_placeholder_artwork(
        self, app, make_equipment, make_qr_template_config,
    ):
        """With include_name=False the mock-up's placeholder name shows as-is."""
        eq = make_equipment(name='Bandsaw')
        template = make_qr_template_config()
        result = self._render(eq, template, include_name=False)
        img = Image.open(io.BytesIO(result)).convert('RGB')
        name_box = _scaled_bbox(template.name_bbox, template, img.width, img.height)
        colors = img.crop(name_box).getcolors(maxcolors=256 * 256 * 256) or []
        assert any(c != (255, 255, 255) for _, c in colors), (
            'expected placeholder artwork in the untouched name bbox'
        )

    def test_url_toggle_difference(self, app, make_equipment, make_qr_template_config):
        eq = make_equipment(name='Bandsaw')
        template = make_qr_template_config()
        result_on = self._render(eq, template, include_url=True)
        result_off = self._render(eq, template, include_url=False)
        img_on = Image.open(io.BytesIO(result_on)).convert('RGB')
        img_off = Image.open(io.BytesIO(result_off)).convert('RGB')
        url_box = _scaled_bbox(template.url_bbox, template, img_on.width, img_on.height)
        assert img_on.crop(url_box).tobytes() != img_off.crop(url_box).tobytes()
        img_on.paste((0, 0, 0), url_box)
        img_off.paste((0, 0, 0), url_box)
        assert img_on.tobytes() == img_off.tobytes()

    def test_include_url_ignored_without_url_bbox(
        self, app, make_equipment, make_qr_template_config,
    ):
        eq = make_equipment(name='Bandsaw')
        template = make_qr_template_config(url_bbox=False)
        result_on = self._render(eq, template, include_url=True)
        result_off = self._render(eq, template, include_url=False)
        img_on = Image.open(io.BytesIO(result_on)).convert('RGB')
        img_off = Image.open(io.BytesIO(result_off)).convert('RGB')
        assert img_on.tobytes() == img_off.tobytes()

    def test_configured_font_actually_used(
        self, app, make_equipment, make_qr_template_config,
    ):
        """Catches a silent fallback to DejaVu that every other test would miss."""
        eq = make_equipment(name='Bandsaw')
        template_poppins = make_qr_template_config(font=True)
        template_dejavu = make_qr_template_config(font=False)
        result_poppins = self._render(eq, template_poppins, include_name=True)
        result_dejavu = self._render(eq, template_dejavu, include_name=True)
        img_p = Image.open(io.BytesIO(result_poppins)).convert('RGB')
        img_d = Image.open(io.BytesIO(result_dejavu)).convert('RGB')
        name_box = _scaled_bbox(template_poppins.name_bbox, template_poppins, img_p.width, img_p.height)
        assert img_p.crop(name_box).tobytes() != img_d.crop(name_box).tobytes(), (
            'Poppins and DejaVu renders should differ inside the name bbox'
        )

    def test_wifi_args_ignored(self, app, make_equipment, make_qr_template_config):
        eq = make_equipment(name='Bandsaw')
        template = make_qr_template_config()
        result_password = self._render(
            eq, template,
            wifi_info='password', wifi_ssid='TestNet', wifi_password='secret123',
        )
        result_none = self._render(eq, template, wifi_info='none')
        img_password = Image.open(io.BytesIO(result_password)).convert('RGB')
        img_none = Image.open(io.BytesIO(result_none)).convert('RGB')
        assert img_password.tobytes() == img_none.tobytes()

    def test_too_small_qr_bbox_raises(self, app, make_equipment, make_qr_template_config):
        eq = make_equipment(name='Bandsaw')
        template = make_qr_template_config()
        tiny = QRSizePreset('tiny', '0.1"×0.1" tiny', 0.1, 0.1)
        with pytest.raises(ValueError, match='template box is too small'):
            render_qr_png(eq, tiny, base_url=BASE_URL, template=template)

    def test_marginal_module_size_logs_warning(
        self, app, make_equipment, make_qr_template_config, caplog,
    ):
        eq = make_equipment(name='Bandsaw')
        template = make_qr_template_config()
        logger_name = app.logger.name
        original_propagate = app.logger.propagate
        app.logger.propagate = True
        try:
            with caplog.at_level(logging.WARNING, logger=logger_name):
                # sticker_1 @ 300 dpi → ~84 px scaled QR bbox → ~2 px modules.
                self._render(eq, template, preset_key='sticker_1')
            messages = ' '.join(r.getMessage() for r in caplog.records)
            assert 'scannability may be marginal' in messages
        finally:
            app.logger.propagate = original_propagate

    @pytest.mark.parametrize('dpi', [203, 300, 600])
    def test_png_embeds_dpi_metadata(self, app, make_equipment, make_qr_template_config, dpi):
        eq = make_equipment(name='Bandsaw')
        template = make_qr_template_config()
        result = self._render(eq, template, dpi=dpi)
        img = Image.open(io.BytesIO(result))
        assert tuple(round(v) for v in img.info['dpi']) == (dpi, dpi)

    def test_max_canvas_guard_raises_before_template_work(
        self, app, make_equipment, make_qr_template_config,
    ):
        eq = make_equipment(name='Bandsaw')
        template = make_qr_template_config()
        with pytest.raises(ValueError, match='too large to render'):
            render_qr_png(
                eq, QR_PRESETS_BY_KEY['letter'], dpi=1200,
                base_url=BASE_URL, template=template,
            )

    @pytest.mark.parametrize('mode', ['RGBA', 'LA', 'P'])
    def test_transparency_flattens_to_white(self, app, make_equipment, tmp_path, mode):
        """Transparent template regions must render white, not raw black RGB —
        for straight-alpha (RGBA/LA) and palette-transparency (P) images."""
        from esb.services.qr_service import load_template_config as load

        # Fully transparent 300×360 template: everything outside the
        # white-filled QR bbox must come out pure white.
        image_name = f'transparent_{mode}.png'
        if mode == 'RGBA':
            Image.new('RGBA', (300, 360), (0, 0, 0, 0)).save(tmp_path / image_name)
        elif mode == 'LA':
            Image.new('LA', (300, 360), (0, 0)).save(tmp_path / image_name)
        else:
            # Palette image whose only color (index 0, black) is transparent.
            Image.new('P', (300, 360), 0).save(tmp_path / image_name, transparency=0)
        config = {
            'image': image_name,
            'qr_bbox': [100, 190, 200, 290],
            'name_bbox': [20, 20, 280, 80],
        }
        json_path = tmp_path / f'transparent_{mode}_config.json'
        json_path.write_text(json.dumps(config))
        template = load(str(json_path))

        eq = make_equipment(name='Bandsaw')
        result = self._render(eq, template)
        img = Image.open(io.BytesIO(result)).convert('RGB')
        # Blank the QR bbox (the only drawn element), then everything left
        # must be pure white — transparent artwork flattened onto white.
        img.paste((255, 255, 255), _scaled_bbox(template.qr_bbox, template, img.width, img.height))
        colors = img.getcolors(maxcolors=256 * 256 * 256) or []
        non_white = [c for _, c in colors if c != (255, 255, 255)]
        assert non_white == [], f'transparent regions rendered as {non_white[:5]}'

    def test_image_size_changed_on_disk_raises(
        self, app, make_equipment, make_qr_template_config,
    ):
        """A post-startup swap to different dimensions must error, not silently
        distort the artwork against the validated bboxes."""
        import dataclasses
        eq = make_equipment(name='Bandsaw')
        template = make_qr_template_config()
        stale = dataclasses.replace(template, image_w=1000, image_h=1200)
        with pytest.raises(RuntimeError, match='changed size on disk'):
            render_qr_png(
                eq, QR_PRESETS_BY_KEY['sticker_2'], base_url=BASE_URL, template=stale,
            )


class TestDrawTextInBbox:
    """Direct tests for the template text helper — ink-height constraint,
    ellipsization, and the render-nothing degradation."""

    FONT = os.path.join(TESTS_DIR, 'Poppins-Bold.ttf')

    @staticmethod
    def _assert_ink_only_inside(canvas, bbox):
        outside = canvas.copy()
        outside.paste((255, 255, 255), bbox)
        colors = outside.getcolors(maxcolors=256 * 256 * 256) or []
        spill = [c for _, c in colors if c != (255, 255, 255)]
        assert spill == [], f'ink spilled outside bbox: {spill[:5]}'

    @staticmethod
    def _has_ink_inside(canvas, bbox):
        colors = canvas.crop(bbox).getcolors(maxcolors=256 * 256 * 256) or []
        return any(c != (255, 255, 255) for _, c in colors)

    def test_descenders_and_diacritics_stay_inside_bbox(self, app):
        """Ink (ascenders/diacritics + descenders) exceeds the em size for
        Poppins — the ink-height loop must shrink until it fits the bbox."""
        canvas = Image.new('RGB', (400, 100), 'white')
        bbox = (50, 40, 350, 64)  # 24 px tall — forces the ink-height shrink
        _draw_text_in_bbox(canvas, 'Äpjgy Qp', bbox, self.FONT, dpi=300)
        assert self._has_ink_inside(canvas, bbox), 'expected text to render'
        self._assert_ink_only_inside(canvas, bbox)

    def test_long_text_ellipsized_within_bbox(self, app):
        canvas = Image.new('RGB', (300, 60), 'white')
        bbox = (10, 10, 290, 50)
        _draw_text_in_bbox(canvas, 'X' * 200, bbox, self.FONT, dpi=300)
        assert self._has_ink_inside(canvas, bbox), 'expected truncated text to render'
        self._assert_ink_only_inside(canvas, bbox)

    def test_narrow_bbox_shrinks_below_width_floor(self, app):
        """A width-constrained box must shrink below _fit_text's 8 pt floor
        (67 px at 600 dpi) instead of going blank — the sub-floor loop covers
        width, not just ink height."""
        canvas = Image.new('RGB', (60, 320), 'white')
        bbox = (20, 10, 40, 310)  # 20 px wide, far below the 600 dpi floor
        _draw_text_in_bbox(canvas, 'B', bbox, self.FONT, dpi=600)
        assert self._has_ink_inside(canvas, bbox), 'expected sub-floor text, not a blank box'
        self._assert_ink_only_inside(canvas, bbox)

    def test_renders_nothing_when_bbox_unusably_small(self, app, caplog):
        canvas = Image.new('RGB', (50, 20), 'white')
        # 2 px wide — narrower than the ellipsis at the 4 px hard minimum.
        bbox = (0, 0, 2, 5)
        logger_name = app.logger.name
        original_propagate = app.logger.propagate
        app.logger.propagate = True
        try:
            with caplog.at_level(logging.WARNING, logger=logger_name):
                _draw_text_in_bbox(canvas, 'Name', bbox, self.FONT, dpi=300)
        finally:
            app.logger.propagate = original_propagate
        # Canvas untouched (box stays blank) and the degradation is logged.
        colors = canvas.getcolors(maxcolors=256 * 256) or []
        assert all(c == (255, 255, 255) for _, c in colors)
        messages = ' '.join(r.getMessage() for r in caplog.records)
        assert 'leaving the box blank' in messages

    def test_name_with_descenders_contained_in_full_render(
        self, app, make_equipment, make_qr_template_config,
    ):
        """End-to-end containment: a descender-heavy name must not leak ink
        outside the white-filled name bbox onto template artwork."""
        eq = make_equipment(name='Ärgjy Quilting Jig')
        template = make_qr_template_config()
        result_on = render_qr_png(
            eq, QR_PRESETS_BY_KEY['sticker_1_5'], base_url=BASE_URL,
            template=template, include_name=True,
        )
        result_off = render_qr_png(
            eq, QR_PRESETS_BY_KEY['sticker_1_5'], base_url=BASE_URL,
            template=template, include_name=False,
        )
        img_on = Image.open(io.BytesIO(result_on)).convert('RGB')
        img_off = Image.open(io.BytesIO(result_off)).convert('RGB')
        name_box = _scaled_bbox(template.name_bbox, template, img_on.width, img_on.height)
        img_on.paste((0, 0, 0), name_box)
        img_off.paste((0, 0, 0), name_box)
        assert img_on.tobytes() == img_off.tobytes(), (
            'name ink leaked outside the name bbox'
        )


class TestNoFormImport:
    def test_qr_service_does_not_import_forms(self):
        import esb.services.qr_service as svc
        source = inspect.getsource(svc)
        assert 'from esb.forms' not in source
        assert 'import esb.forms' not in source
