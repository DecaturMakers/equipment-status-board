"""QR code generation service for equipment pages.

Renders QR codes as in-memory PNG bytes with optional equipment-name text
above and URL text below. No disk caching — generated on demand per request.
"""

import io
import os
from dataclasses import dataclass
from functools import lru_cache

import qrcode
from flask import current_app
from PIL import Image, ImageDraw, ImageFont

_DPI = 300
_MIN_FONT_PT = 8


@lru_cache(maxsize=64)
def _load_font(font_path: str, size_px: int) -> ImageFont.FreeTypeFont:
    """Cache truetype font loads — preview hot path hits this per render."""
    return ImageFont.truetype(font_path, size_px)


@dataclass(frozen=True)
class QRSizePreset:
    key: str
    label: str
    width_in: float
    height_in: float


QR_SIZE_PRESETS: tuple[QRSizePreset, ...] = (
    QRSizePreset('sticker_1', '1"×1" sticker', 1.0, 1.0),
    QRSizePreset('sticker_1_5', '1.5"×1.5" sticker', 1.5, 1.5),
    QRSizePreset('sticker_2', '2"×2" sticker', 2.0, 2.0),
    QRSizePreset('sticker_3', '3"×3" sticker', 3.0, 3.0),
    QRSizePreset('sticker_4', '4"×4" sticker', 4.0, 4.0),
    QRSizePreset('avery_5160', 'Avery 5160 label (2.625"×1")', 2.625, 1.0),
    QRSizePreset('avery_5163', 'Avery 5163 label (4"×2")', 4.0, 2.0),
    QRSizePreset('letter', 'US Letter page (8.5"×11")', 8.5, 11.0),
)

QR_PRESETS_BY_KEY: dict[str, QRSizePreset] = {p.key: p for p in QR_SIZE_PRESETS}


def _px(inches: float) -> int:
    return int(inches * _DPI + 0.5)


def _pt_to_px(pt: int) -> int:
    return int(pt * _DPI / 72 + 0.5)


def render_qr_png(
    equipment,
    preset: QRSizePreset,
    *,
    include_name: bool = False,
    include_url: bool = False,
    base_url: str,
    wifi_info: str = 'none',
    wifi_ssid: str = '',
    wifi_password: str = '',
) -> bytes:
    """Render a QR code PNG for an equipment item and return the bytes.

    The service trusts `base_url` — it must be validated upstream via
    `esb.utils.text.get_normalized_base_url`.
    """
    canvas_w_px = _px(preset.width_in)
    canvas_h_px = _px(preset.height_in)

    wifi_rows = _wifi_row_texts(wifi_info, wifi_ssid, wifi_password)
    num_wifi_rows = len(wifi_rows)

    reserved_top = int(canvas_h_px * 0.15) if include_name else 0
    reserved_bottom = int(canvas_h_px * 0.15) if include_url else 0

    if num_wifi_rows > 0:
        min_row_px = _pt_to_px(_MIN_FONT_PT) + 4
        wifi_budget = int(canvas_h_px * 0.30)
        max_text_px = int(canvas_h_px * 0.55)
        effective_wifi_rows = num_wifi_rows

        while effective_wifi_rows > 0:
            wifi_row_height = max(wifi_budget // effective_wifi_rows, min_row_px)
            if reserved_top + reserved_bottom + effective_wifi_rows * wifi_row_height <= max_text_px:
                break
            current_app.logger.warning(
                'QR WiFi: dropping row %d for preset %s (insufficient space)',
                effective_wifi_rows, preset.key,
            )
            effective_wifi_rows -= 1

        if effective_wifi_rows > 0:
            wifi_rows = wifi_rows[:effective_wifi_rows]
            reserved_wifi = effective_wifi_rows * wifi_row_height
        else:
            wifi_rows = []
            wifi_row_height = 0
            reserved_wifi = 0
    else:
        reserved_wifi = 0
        wifi_row_height = 0

    margin = max(4, int(canvas_w_px * 0.02))
    avail = min(canvas_w_px, canvas_h_px - reserved_wifi - reserved_top - reserved_bottom) - margin

    qr_url = f'{base_url}/public/equipment/{equipment.id}'
    qr = qrcode.QRCode(
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=1,
        border=4,
    )
    qr.add_data(qr_url)
    qr.make(fit=True)
    native = len(qr.get_matrix())
    if avail < native:
        raise ValueError(
            f'URL is too long for preset {preset.label!r} — '
            'choose a larger preset or shorten ESB_BASE_URL.'
        )
    module_px = avail // native
    qr_px = module_px * native

    if module_px < 5:
        current_app.logger.warning(
            'QR for equipment %s at preset %s has %d px modules (<5); '
            'scannability may be marginal',
            equipment.id, preset.key, module_px,
        )

    qr_img = (
        qr.make_image(fill_color='black', back_color='white')
        .convert('RGB')
        .resize((qr_px, qr_px), Image.NEAREST)
    )

    canvas = Image.new('RGB', (canvas_w_px, canvas_h_px), 'white')
    paste_x = (canvas_w_px - qr_px) // 2
    paste_y = (
        reserved_wifi + reserved_top
        + ((canvas_h_px - reserved_wifi - reserved_top - reserved_bottom) - qr_px) // 2
    )
    canvas.paste(qr_img, (paste_x, paste_y))

    drawable_w = canvas_w_px - 2 * margin
    max_text_width = min(int(qr_px * 1.2), drawable_w)
    wifi_max_text_width = min(max(int(qr_px * 1.2), int(canvas_w_px * 0.90)), drawable_w)

    for i, row_info in enumerate(wifi_rows):
        row_top = i * wifi_row_height
        if row_info['type'] == 'header':
            _draw_wifi_header_row(
                canvas, row_top=row_top, row_height=wifi_row_height,
                max_width_px=wifi_max_text_width,
            )
        else:
            _draw_text_row(
                canvas, row_info['text'],
                row_top=row_top, row_height=wifi_row_height,
                max_width_px=wifi_max_text_width,
            )

    if include_name:
        _draw_text_row(
            canvas, equipment.name,
            row_top=reserved_wifi, row_height=reserved_top, max_width_px=max_text_width,
        )
    if include_url:
        _draw_text_row(
            canvas, qr_url,
            row_top=canvas_h_px - reserved_bottom,
            row_height=reserved_bottom,
            max_width_px=max_text_width,
        )

    buf = io.BytesIO()
    canvas.save(buf, format='PNG')
    return buf.getvalue()


def _wifi_row_texts(wifi_info, wifi_ssid, wifi_password):
    """Return list of row dicts for the WiFi info section.

    Defensive: only renders known wifi_info values ('header', 'ssid', 'password').
    Any other value (including 'none', None, or garbage) renders nothing.
    Also requires non-empty SSID for 'ssid'/'password' and non-empty password
    for 'password'; degrades silently if requirements unmet.
    """
    if wifi_info not in ('header', 'ssid', 'password'):
        return []
    rows = [{'type': 'header'}]
    if wifi_info in ('ssid', 'password') and wifi_ssid:
        rows.append({'type': 'text', 'text': f'Network: {wifi_ssid}'})
    if wifi_info == 'password' and wifi_ssid and wifi_password:
        rows.append({'type': 'text', 'text': f'Password: {wifi_password}'})
    return rows


def _draw_wifi_header_row(canvas, *, row_top, row_height, max_width_px):
    """Draw the WiFi emoji + 'Must be on WiFi' text centered in a row."""
    text_font_path = os.path.join(current_app.static_folder, 'fonts', 'DejaVuSans-Bold.ttf')  # noqa: PTH118
    emoji_font_path = os.path.join(current_app.static_folder, 'fonts', 'NotoEmoji-Bold.ttf')  # noqa: PTH118
    label = 'Must be on WiFi'
    if not os.path.isfile(emoji_font_path):
        current_app.logger.warning(
            'QR WiFi emoji font missing at %s — falling back to text-only header.',
            emoji_font_path,
        )
        _draw_text_row(canvas, label, row_top=row_top, row_height=row_height, max_width_px=max_width_px)
        return
    gap = max(4, row_height // 10)

    text_font, rendered = _fit_text(
        label, max_width_px=int(max_width_px * 0.75),
        max_height_px=row_height, font_path=text_font_path,
    )
    if rendered == '':
        return

    emoji_size_px = text_font.size
    emoji_font = _load_font(emoji_font_path, emoji_size_px)
    draw = ImageDraw.Draw(canvas)

    emoji_char = '\U0001f6dc'
    e_left, e_top, e_right, e_bottom = draw.textbbox((0, 0), emoji_char, font=emoji_font)
    emoji_w = e_right - e_left
    emoji_h = e_bottom - e_top

    t_left, t_top, t_right, t_bottom = draw.textbbox((0, 0), rendered, font=text_font)
    text_w = t_right - t_left
    text_h = t_bottom - t_top

    if emoji_w + gap >= max_width_px:
        _draw_text_row(canvas, label, row_top=row_top, row_height=row_height, max_width_px=max_width_px)
        return

    total_w = emoji_w + gap + text_w
    if total_w > max_width_px:
        text_font, rendered = _fit_text(
            label, max_width_px=max_width_px - emoji_w - gap,
            max_height_px=row_height, font_path=text_font_path,
        )
        if rendered == '':
            _draw_text_row(canvas, label, row_top=row_top, row_height=row_height, max_width_px=max_width_px)
            return
        t_left, t_top, t_right, t_bottom = draw.textbbox((0, 0), rendered, font=text_font)
        text_w = t_right - t_left
        text_h = t_bottom - t_top
        total_w = emoji_w + gap + text_w

    group_x = (canvas.width - total_w) // 2
    emoji_y = row_top + (row_height - emoji_h) // 2 - e_top
    text_y = row_top + (row_height - text_h) // 2 - t_top

    draw.text((group_x - e_left, emoji_y), emoji_char, fill='black', font=emoji_font)
    draw.text((group_x + emoji_w + gap - t_left, text_y), rendered, fill='black', font=text_font)


def _draw_text_row(canvas, text, *, row_top, row_height, max_width_px):
    """Draw centered text in a horizontal row region of the canvas."""
    font_path = os.path.join(current_app.static_folder, 'fonts', 'DejaVuSans-Bold.ttf')  # noqa: PTH118
    if not os.path.isfile(font_path):
        raise RuntimeError(
            f'QR label font missing at {font_path}. '
            'Ensure DejaVuSans-Bold.ttf is vendored in esb/static/fonts/.'
        )
    font, rendered = _fit_text(
        text,
        max_width_px=max_width_px,
        max_height_px=row_height,
        font_path=font_path,
    )
    if rendered == '':
        return
    draw = ImageDraw.Draw(canvas)
    (left, top, right, bottom) = draw.textbbox((0, 0), rendered, font=font)
    width = right - left
    height = bottom - top
    x = (canvas.width - width) // 2 - left
    y = row_top + (row_height - height) // 2 - top
    draw.text((x, y), rendered, fill='black', font=font)


def _fit_text(text, *, max_width_px, max_height_px, font_path):
    """Return (font, rendered_text) fitting within max_width_px at ≤ max_height_px.

    Shrinks font toward the 8 pt floor; if still too wide at the floor,
    truncates with an ellipsis (binary-search); if even ellipsis alone
    doesn't fit, returns the min-size font and an empty string.
    """
    min_px = _pt_to_px(_MIN_FONT_PT)
    size_px = max_height_px
    step = max(1, int(max_height_px * 0.05))
    scratch = ImageDraw.Draw(Image.new('RGB', (1, 1)))

    def width_at(t, font):
        left, _, right, _ = scratch.textbbox((0, 0), t, font=font)
        return right - left

    while size_px >= min_px:
        font = _load_font(font_path, size_px)
        if width_at(text, font) <= max_width_px:
            return font, text
        size_px -= step

    font = _load_font(font_path, min_px)
    if width_at(text, font) <= max_width_px:
        return font, text
    if width_at('…', font) > max_width_px:
        return font, ''

    # Binary search: find the largest prefix length whose candidate fits.
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if width_at(text[:mid] + '…', font) <= max_width_px:
            lo = mid
        else:
            hi = mid - 1
    return font, text[:lo] + '…' if lo > 0 else '…'
