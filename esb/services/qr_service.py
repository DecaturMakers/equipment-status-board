"""QR code generation service for equipment pages.

Renders QR codes as in-memory PNG bytes — either the plain layout (QR with
optional equipment-name text above and URL text below on a white canvas) or,
when a QR_TEMPLATE_CONFIG_PATH template is configured, composited into branded
template artwork. No disk caching — generated on demand per request.
"""

import io
import json
import os
from dataclasses import dataclass
from functools import lru_cache

import qrcode
from flask import current_app
from PIL import Image, ImageDraw, ImageFont

_MIN_FONT_PT = 8

# Absolute floor for template text shrinking (px). The bbox ink-height loop may
# shrink below the 8 pt dpi-scaled _fit_text floor; below this, render nothing.
_HARD_MIN_TEXT_PX = 4


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

# High DPI × large physical size can produce enormous canvases (US Letter @ 1200 dpi
# ≈ 134 MP). Cap total pixels to avoid OOM; this is a deliberate, adjustable default.
MAX_CANVAS_PX = 50_000_000


@dataclass(frozen=True)
class QRTemplate:
    """Validated QR sticker template config (parsed once at app startup).

    Paths are absolute; bboxes are (x0, y0, x1, y1) pixel tuples in
    template-native coordinates using the exclusive PIL box convention.
    """

    image_path: str
    font_path: str
    qr_bbox: tuple[int, int, int, int]
    name_bbox: tuple[int, int, int, int]
    url_bbox: tuple[int, int, int, int] | None
    image_w: int
    image_h: int


def _validate_bbox(value, key, image_w, image_h, json_path):
    """Validate a bbox from the template JSON; return it as a tuple of 4 ints."""
    if (
        not isinstance(value, (list, tuple))
        or len(value) != 4
        # bool is an int subclass — JSON true/false must not pass as coordinates.
        or any(type(v) is not int for v in value)
    ):
        raise ValueError(
            f'QR template config {json_path}: {key} must be a list of exactly '
            f'4 integers [x0, y0, x1, y1], got {value!r}.'
        )
    x0, y0, x1, y1 = value
    if x1 <= x0 or y1 <= y0:
        raise ValueError(
            f'QR template config {json_path}: {key} {value!r} is degenerate — '
            'x1 must be > x0 and y1 must be > y0.'
        )
    # Exclusive convention: x1 == image_w / y1 == image_h are legal (full bleed).
    if x0 < 0 or y0 < 0 or x1 > image_w or y1 > image_h:
        raise ValueError(
            f'QR template config {json_path}: {key} {value!r} extends outside '
            f'the template image bounds ({image_w}×{image_h}).'
        )
    return (x0, y0, x1, y1)


def load_template_config(json_path: str) -> QRTemplate:
    """Parse and validate a QR template config JSON file.

    Pure function — no app context required (called from create_app before the
    app is fully built, and directly from tests). Raises ValueError with a
    specific message for every failure mode so startup fails fast and loud.
    """
    try:
        with open(json_path, encoding='utf-8') as f:  # noqa: PTH123
            data = json.load(f)
    except OSError as exc:
        raise ValueError(f'QR template config {json_path} is unreadable: {exc}') from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f'QR template config {json_path} is not valid JSON: {exc}') from exc
    if not isinstance(data, dict):
        raise ValueError(f'QR template config {json_path} must be a JSON object.')

    for key in ('image', 'qr_bbox', 'name_bbox'):
        if key not in data:
            raise ValueError(f'QR template config {json_path} is missing required key {key!r}.')

    if not isinstance(data['image'], str) or not data['image']:
        raise ValueError(
            f'QR template config {json_path}: image must be a non-empty string path, '
            f'got {data["image"]!r}.'
        )
    font_value = data.get('font')
    if font_value is not None and (not isinstance(font_value, str) or not font_value):
        raise ValueError(
            f'QR template config {json_path}: font must be a non-empty string path, '
            f'got {font_value!r}.'
        )

    base_dir = os.path.dirname(os.path.abspath(json_path))  # noqa: PTH100, PTH120
    image_path = os.path.join(base_dir, data['image'])  # noqa: PTH118
    try:
        with Image.open(image_path) as img:
            # Force a full decode — Image.open parses only the header, which
            # would let truncated/corrupt image data pass startup validation
            # and fail on every render instead.
            img.load()
            image_w, image_h = img.size
    except (OSError, Image.DecompressionBombError) as exc:
        # DecompressionBombError subclasses Exception, not OSError.
        raise ValueError(
            f'QR template config {json_path}: cannot open template image {image_path}: {exc}'
        ) from exc

    # Cap the input like MAX_CANVAS_PX caps the output: the template is fully
    # decoded and resized per render, and PIL's own bomb check only rejects
    # above 2× MAX_IMAGE_PIXELS (~179 MP) — far past sane template sizes.
    if image_w * image_h > MAX_CANVAS_PX:
        raise ValueError(
            f'QR template config {json_path}: template image {image_path} is '
            f'{image_w}×{image_h} ({image_w * image_h:,} px), exceeding the '
            f'{MAX_CANVAS_PX:,} px limit — supply a smaller template image.'
        )

    if font_value is not None:
        font_path = os.path.join(base_dir, font_value)  # noqa: PTH118
    else:
        # Vendored fallback, resolved package-relative — deliberately NOT via
        # current_app.static_folder so the loader needs no app context.
        import esb
        font_path = os.path.join(  # noqa: PTH118
            os.path.dirname(esb.__file__), 'static', 'fonts', 'DejaVuSans-Bold.ttf'  # noqa: PTH120
        )
    try:
        ImageFont.truetype(font_path, 12)
    except OSError as exc:
        raise ValueError(
            f'QR template config {json_path}: cannot load font {font_path}: {exc}'
        ) from exc

    qr_bbox = _validate_bbox(data['qr_bbox'], 'qr_bbox', image_w, image_h, json_path)
    name_bbox = _validate_bbox(data['name_bbox'], 'name_bbox', image_w, image_h, json_path)
    url_bbox = None
    if data.get('url_bbox') is not None:
        url_bbox = _validate_bbox(data['url_bbox'], 'url_bbox', image_w, image_h, json_path)

    # Overlapping bboxes are a silent disaster at render time: elements are
    # drawn in order (QR, name, URL) and each enabled element white-fills its
    # bbox first, so a later fill would erase part of an earlier element —
    # including the QR code itself. Fail fast instead.
    named_bboxes = [('qr_bbox', qr_bbox), ('name_bbox', name_bbox)]
    if url_bbox is not None:
        named_bboxes.append(('url_bbox', url_bbox))
    for i, (key_a, box_a) in enumerate(named_bboxes):
        for key_b, box_b in named_bboxes[i + 1:]:
            if (box_a[0] < box_b[2] and box_b[0] < box_a[2]
                    and box_a[1] < box_b[3] and box_b[1] < box_a[3]):
                raise ValueError(
                    f'QR template config {json_path}: {key_a} {box_a!r} and {key_b} '
                    f'{box_b!r} overlap — white-filling one would erase part of the other.'
                )

    return QRTemplate(
        image_path=image_path,
        font_path=font_path,
        qr_bbox=qr_bbox,
        name_bbox=name_bbox,
        url_bbox=url_bbox,
        image_w=image_w,
        image_h=image_h,
    )


def _px(inches: float, dpi: int) -> int:
    return int(inches * dpi + 0.5)


def _build_qr(qr_url: str):
    """Build the QR object at 1 px/module; return (qr, native_size_with_border)."""
    qr = qrcode.QRCode(
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=1,
        border=4,
    )
    qr.add_data(qr_url)
    qr.make(fit=True)
    return qr, len(qr.get_matrix())


def _qr_to_image(qr, qr_px: int) -> Image.Image:
    """Render the QR to an RGB image at qr_px via NEAREST — modules stay pure B/W."""
    return (
        qr.make_image(fill_color='black', back_color='white')
        .convert('RGB')
        .resize((qr_px, qr_px), Image.NEAREST)
    )


def _warn_if_marginal(equipment, preset, module_px: int) -> None:
    if module_px < 5:
        current_app.logger.warning(
            'QR for equipment %s at preset %s has %d px modules (<5); '
            'scannability may be marginal',
            equipment.id, preset.key, module_px,
        )


def _pt_to_px(pt: int, dpi: int) -> int:
    return int(pt * dpi / 72 + 0.5)


def render_qr_png(
    equipment,
    preset: QRSizePreset,
    *,
    dpi: int = 300,
    include_name: bool = False,
    include_url: bool = False,
    base_url: str,
    wifi_info: str = 'none',
    wifi_ssid: str = '',
    wifi_password: str = '',
    template: QRTemplate | None = None,
) -> bytes:
    """Render a QR code PNG for an equipment item and return the bytes.

    The service trusts `base_url` — it must be validated upstream via
    `esb.utils.text.get_normalized_base_url`.

    When `template` is given, the QR and text are composited into the template
    artwork and all `wifi_*` args are ignored (WiFi info is unsupported with
    templates — bake it into the artwork).
    """
    if dpi <= 0:
        raise ValueError(f'dpi must be positive, got {dpi}.')
    canvas_w_px = _px(preset.width_in, dpi)
    canvas_h_px = _px(preset.height_in, dpi)

    if canvas_w_px * canvas_h_px > MAX_CANVAS_PX:
        raise ValueError(
            f'{preset.label} at {dpi} dpi is too large to render — '
            'choose a lower-resolution printer or a smaller size.'
        )

    if template is not None:
        return _render_template_png(
            equipment, preset,
            dpi=dpi,
            include_name=include_name,
            include_url=include_url,
            base_url=base_url,
            template=template,
            canvas_w_px=canvas_w_px,
            canvas_h_px=canvas_h_px,
        )

    wifi_rows = _wifi_row_texts(wifi_info, wifi_ssid, wifi_password)
    num_wifi_rows = len(wifi_rows)

    reserved_top = int(canvas_h_px * 0.15) if include_name else 0
    reserved_bottom = int(canvas_h_px * 0.15) if include_url else 0

    if num_wifi_rows > 0:
        min_row_px = _pt_to_px(_MIN_FONT_PT, dpi) + 4
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
    qr, native = _build_qr(qr_url)
    if avail < native:
        raise ValueError(
            f'URL is too long for preset {preset.label!r} — '
            'choose a larger preset or shorten ESB_BASE_URL.'
        )
    module_px = avail // native
    qr_px = module_px * native

    _warn_if_marginal(equipment, preset, module_px)

    qr_img = _qr_to_image(qr, qr_px)

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
                max_width_px=wifi_max_text_width, dpi=dpi,
            )
        else:
            _draw_text_row(
                canvas, row_info['text'],
                row_top=row_top, row_height=wifi_row_height,
                max_width_px=wifi_max_text_width, dpi=dpi,
            )

    if include_name:
        _draw_text_row(
            canvas, equipment.name,
            row_top=reserved_wifi, row_height=reserved_top, max_width_px=max_text_width, dpi=dpi,
        )
    if include_url:
        _draw_text_row(
            canvas, qr_url,
            row_top=canvas_h_px - reserved_bottom,
            row_height=reserved_bottom,
            max_width_px=max_text_width, dpi=dpi,
        )

    buf = io.BytesIO()
    canvas.save(buf, format='PNG', dpi=(dpi, dpi))
    return buf.getvalue()


def _open_template_rgb(image_path: str) -> Image.Image:
    """Open a template image normalized to RGB, flattening alpha onto white.

    Design exports are frequently RGBA; Image.paste without a mask renders
    transparent regions as raw (often black) RGB, so composite onto white first.
    """
    try:
        with Image.open(image_path) as img:
            if img.mode == 'P':
                img = img.convert('RGBA') if 'transparency' in img.info else img.convert('RGB')
            if img.mode in ('RGBA', 'LA'):
                background = Image.new('RGB', img.size, 'white')
                background.paste(img, mask=img.getchannel('A'))
                return background
            return img.convert('RGB')
    except Image.DecompressionBombError as exc:
        # Subclasses Exception, not OSError — re-raise as RuntimeError so the
        # views' existing (OSError, RuntimeError) handlers produce a clean 500
        # if the on-disk image was swapped for an oversized one after startup.
        raise RuntimeError(
            f'QR template image {image_path} is too large to process: {exc}'
        ) from exc


def _render_template_png(
    equipment, preset, *, dpi, include_name, include_url, base_url, template,
    canvas_w_px, canvas_h_px,
) -> bytes:
    """Render the QR (and optional name/URL text) into a branded template.

    Render order keeps the QR crisp: scale the template to the output size
    FIRST (LANCZOS), map bboxes by the same factor, white-fill enabled bboxes
    (replacing any mock-up placeholder artwork), then draw the QR at integer
    module size with NEAREST and fit text into the scaled bboxes. The QR is
    never resampled after drawing — modules stay pure black/white.
    """
    tpl = _open_template_rgb(template.image_path)
    if tpl.size != (template.image_w, template.image_h):
        # The bboxes were validated against the startup dimensions; resizing a
        # dimension-changed replacement to the stale targets would silently
        # distort the artwork and land the bboxes on the wrong content.
        raise RuntimeError(
            f'QR template image {template.image_path} changed size on disk '
            f'({tpl.size[0]}×{tpl.size[1]} vs validated '
            f'{template.image_w}×{template.image_h}) — restart the app.'
        )
    s = min(canvas_w_px / template.image_w, canvas_h_px / template.image_h)
    scaled_w = max(1, round(template.image_w * s))
    scaled_h = max(1, round(template.image_h * s))
    tpl = tpl.resize((scaled_w, scaled_h), Image.LANCZOS)

    canvas = Image.new('RGB', (canvas_w_px, canvas_h_px), 'white')
    off_x = (canvas_w_px - scaled_w) // 2
    off_y = (canvas_h_px - scaled_h) // 2
    canvas.paste(tpl, (off_x, off_y))

    def scale_bbox(bbox):
        x0, y0, x1, y1 = bbox
        return (
            off_x + round(x0 * s), off_y + round(y0 * s),
            off_x + round(x1 * s), off_y + round(y1 * s),
        )

    # White-fill via paste — its box is exclusive like the bbox convention
    # (ImageDraw.rectangle endpoints are inclusive and would fill one extra
    # row/column). The fill replaces any placeholder artwork and guarantees
    # QR contrast and a clean margin regardless of the artwork.
    qr_box = scale_bbox(template.qr_bbox)
    canvas.paste((255, 255, 255), qr_box)

    qr_url = f'{base_url}/public/equipment/{equipment.id}'
    qr, native = _build_qr(qr_url)
    qr_box_w = qr_box[2] - qr_box[0]
    qr_box_h = qr_box[3] - qr_box[1]
    module_px = min(qr_box_w, qr_box_h) // native
    if module_px < 1:
        raise ValueError(
            'QR template box is too small at this size/resolution — '
            'choose a larger size or higher-resolution printer.'
        )
    _warn_if_marginal(equipment, preset, module_px)
    qr_px = module_px * native
    qr_img = _qr_to_image(qr, qr_px)
    canvas.paste(qr_img, (
        qr_box[0] + (qr_box_w - qr_px) // 2,
        qr_box[1] + (qr_box_h - qr_px) // 2,
    ))

    if include_name:
        name_box = scale_bbox(template.name_bbox)
        canvas.paste((255, 255, 255), name_box)
        _draw_text_in_bbox(canvas, equipment.name, name_box, template.font_path, dpi=dpi)
    if include_url and template.url_bbox is not None:
        url_box = scale_bbox(template.url_bbox)
        canvas.paste((255, 255, 255), url_box)
        _draw_text_in_bbox(canvas, qr_url, url_box, template.font_path, dpi=dpi)

    buf = io.BytesIO()
    canvas.save(buf, format='PNG', dpi=(dpi, dpi))
    return buf.getvalue()


def _draw_text_in_bbox(canvas, text, bbox, font_path, *, dpi: int = 300):
    """Draw single-line text centered within a bbox, never spilling outside it.

    Unlike _draw_text_row this takes the (startup-validated) template font path
    directly. Sizing starts from _fit_text's width-aware pick but may continue
    shrinking BELOW its 8 pt dpi-scaled floor — small scaled bboxes make that
    floor unachievable for width or for ink height (ascenders/diacritics +
    descenders can exceed the em size) — re-ellipsizing at each candidate size
    until both fit. If nothing fits at the hard minimum, render nothing (the
    bbox stays white-filled and blank).
    """
    x0, y0, x1, y1 = bbox
    box_w = x1 - x0
    box_h = y1 - y0
    if box_w <= 0 or box_h <= 0:
        return
    scratch = ImageDraw.Draw(Image.new('RGB', (1, 1)))

    def width_at(t, f):
        left, _, right, _ = scratch.textbbox((0, 0), t, font=f)
        return right - left

    # Starting size only — even when _fit_text gives up ('' at its floor),
    # the loop below keeps shrinking beneath that floor.
    font, _ = _fit_text(
        text, max_width_px=box_w, max_height_px=box_h, font_path=font_path, dpi=dpi,
    )
    size_px = font.size
    fits = False
    rendered = ''
    while size_px >= _HARD_MIN_TEXT_PX:
        font = _load_font(font_path, size_px)
        # Re-ellipsize at every size — a smaller font fits more characters
        # than the prefix chosen at a larger one.
        rendered = _ellipsize(text, font, box_w, width_at)
        if rendered == '':
            # Even the ellipsis is too wide — shrink proportionally to the
            # ellipsis overshoot (guaranteed to decrease).
            ellipsis_w = width_at('…', font)
            size_px = min(size_px - 1, int(size_px * box_w / ellipsis_w))
            continue
        left, top, right, bottom = scratch.textbbox((0, 0), rendered, font=font)
        ink_h = bottom - top
        if ink_h <= box_h:
            fits = True
            break
        # Proportional shrink (guaranteed to decrease) — ink overshoot is
        # typically small (~1.26× worst observed), so this converges fast.
        size_px = min(size_px - 1, int(size_px * box_h / ink_h))
    if not fits:
        current_app.logger.warning(
            'QR template: text %r does not fit bbox %s even at the %d px hard '
            'minimum; leaving the box blank', text, bbox, _HARD_MIN_TEXT_PX,
        )
        return

    draw = ImageDraw.Draw(canvas)
    left, top, right, bottom = draw.textbbox((0, 0), rendered, font=font)
    width = right - left
    height = bottom - top
    x = x0 + (box_w - width) // 2 - left
    y = y0 + (box_h - height) // 2 - top
    draw.text((x, y), rendered, fill='black', font=font)


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


def _draw_wifi_header_row(canvas, *, row_top, row_height, max_width_px, dpi: int = 300):
    """Draw the WiFi emoji + 'Must be on WiFi' text centered in a row."""
    text_font_path = os.path.join(current_app.static_folder, 'fonts', 'DejaVuSans-Bold.ttf')  # noqa: PTH118
    emoji_font_path = os.path.join(current_app.static_folder, 'fonts', 'NotoEmoji-Bold.ttf')  # noqa: PTH118
    label = 'Must be on WiFi'
    if not os.path.isfile(emoji_font_path):
        current_app.logger.warning(
            'QR WiFi emoji font missing at %s — falling back to text-only header.',
            emoji_font_path,
        )
        _draw_text_row(canvas, label, row_top=row_top, row_height=row_height, max_width_px=max_width_px, dpi=dpi)
        return
    gap = max(4, row_height // 10)

    text_font, rendered = _fit_text(
        label, max_width_px=int(max_width_px * 0.75),
        max_height_px=row_height, font_path=text_font_path, dpi=dpi,
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
        _draw_text_row(canvas, label, row_top=row_top, row_height=row_height, max_width_px=max_width_px, dpi=dpi)
        return

    total_w = emoji_w + gap + text_w
    if total_w > max_width_px:
        text_font, rendered = _fit_text(
            label, max_width_px=max_width_px - emoji_w - gap,
            max_height_px=row_height, font_path=text_font_path, dpi=dpi,
        )
        if rendered == '':
            _draw_text_row(canvas, label, row_top=row_top, row_height=row_height, max_width_px=max_width_px, dpi=dpi)
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


def _draw_text_row(canvas, text, *, row_top, row_height, max_width_px, dpi: int = 300):
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
        dpi=dpi,
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


def _fit_text(text, *, max_width_px, max_height_px, font_path, dpi: int = 300):
    """Return (font, rendered_text) fitting within max_width_px at ≤ max_height_px.

    Shrinks font toward the 8 pt floor; if still too wide at the floor,
    truncates with an ellipsis (binary-search); if even ellipsis alone
    doesn't fit, returns the min-size font and an empty string.
    """
    min_px = _pt_to_px(_MIN_FONT_PT, dpi)
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
    return font, _ellipsize(text, font, max_width_px, width_at)


def _ellipsize(text, font, max_width_px, width_at):
    """Return text fitted to max_width_px at this font.

    Unchanged if it fits; otherwise the largest '…'-suffixed prefix
    (binary search); '' if even the ellipsis alone is too wide.
    """
    if width_at(text, font) <= max_width_px:
        return text
    if width_at('…', font) > max_width_px:
        return ''
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if width_at(text[:mid] + '…', font) <= max_width_px:
            lo = mid
        else:
            hi = mid - 1
    return text[:lo] + '…' if lo > 0 else '…'
