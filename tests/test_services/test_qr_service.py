"""Tests for QR code generation service."""

import inspect
import io
import logging

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
    _fit_text,
    _px,
    render_qr_png,
)


BASE_URL = 'http://esb.test:5000'


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


class TestNoFormImport:
    def test_qr_service_does_not_import_forms(self):
        import esb.services.qr_service as svc
        source = inspect.getsource(svc)
        assert 'from esb.forms' not in source
        assert 'import esb.forms' not in source
