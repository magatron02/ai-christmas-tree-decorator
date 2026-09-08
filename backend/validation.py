"""Input validation (Spec.md 3, AC-1).

Pure functions — no FastAPI, no database, no disk. That is the point: tests/test_input_validation.py
drives these directly, so validation stays provable independently of the pipeline around it.

Every ValidationError message is shown to the user verbatim, so write them readable.
"""

import io
from pathlib import PurePosixPath

from PIL import Image, UnidentifiedImageError

from backend import config


class ValidationError(ValueError):
    """Rejected input. The message is user-facing (AC-1: readable error, never a crash)."""


def exactly_one(files, field):
    """One file per upload. The tree is one image, and elements are background-removed one
    at a time even when several go into the same picture — each needs its own preview and
    its own accept or reject (AC-2).

    More than one is rejected outright rather than silently using the first: AC-1 requires
    the behaviour to be a choice, and a rejection is the one the user can actually see.
    """
    if not files:
        raise ValidationError(f"{field}: ยังไม่ได้เลือกไฟล์")
    if len(files) > 1:
        raise ValidationError(
            f"{field}: อัปโหลดมา {len(files)} ไฟล์ แต่รับได้ทีละ 1 ไฟล์เท่านั้น "
            "ใส่ของตกแต่งทีละชิ้น จะได้ตรวจการตัดพื้นหลังทีละอัน"
        )
    return files[0]


def element_count(elements):
    """1 to MAX_ELEMENTS + MAX_GROUNDED decorations per picture (Product.md 8.2).

    This is a structural ceiling only, checked before any code is known — a hung item and a
    grounded item (issue #21) draw from separate pools with their own, tighter limits, checked
    once their codes (and therefore placements) are known (backend/main.py's api_prepare).
    """
    if not elements:
        raise ValidationError("ใส่ของตกแต่งอย่างน้อย 1 ชิ้นก่อนสร้างภาพ")
    ceiling = config.MAX_ELEMENTS + config.MAX_GROUNDED
    if len(elements) > ceiling:
        raise ValidationError(
            f"เลือกของตกแต่งมา {len(elements)} ชิ้น แต่ใส่ในภาพเดียวได้มากสุด {ceiling} ชิ้น"
        )
    if len(set(elements)) != len(elements):
        raise ValidationError("ใส่ของตกแต่งชิ้นเดิมซ้ำ แต่ละชิ้นใส่ได้ครั้งเดียว")
    return elements


def parse_manual_mm(raw, field):
    """A person-typed real size (mm) for a code the catalogue has none for — the blocking
    manual-size gate's own input. Empty string means "no override" and returns None; anything
    else must be a plain positive number, since this value stands in for a catalogue lookup
    and a bad one would be a wrong scale in the finished picture."""
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        value = float(raw)
    except ValueError:
        raise ValidationError(f"{field}: '{raw}' ไม่ใช่ตัวเลข")
    if value <= 0:
        raise ValidationError(f"{field}: ขนาดต้องมากกว่า 0")
    return value


def parse_custom_prompt(raw):
    """Prompt mode's free-text description — replaces the density system outright for a
    request that has one (image_gen.py substitutes it straight into {density}). Empty means
    "not used, fall back to the usual density text"; anything longer than the configured
    ceiling is refused rather than silently truncated, since a cut-off instruction could read
    as something the shop never asked for."""
    raw = (raw or "").strip()
    if len(raw) > config.PROMPT_MODE_MAX_CHARS:
        raise ValidationError(
            f"ข้อความยาวเกิน {config.PROMPT_MODE_MAX_CHARS} ตัวอักษร "
            f"(ตอนนี้ {len(raw)} ตัวอักษร)"
        )
    return raw


def resolve_density(key):
    """Density key -> the prompt sentence. Same shape as resolve_size: users pick a level,
    never the sentence itself."""
    if key not in config.DENSITY_PRESETS:
        allowed = ", ".join(config.DENSITY_PRESETS)
        raise ValidationError(f"ไม่รู้จักความหนาแน่น '{key}' · เลือกจาก: {allowed}")
    return config.DENSITY_PRESETS[key]


def resolve_backdrop(value):
    """Backdrop kind, defaulted and validated (issue #22). Empty means "tree" — every request
    before this existed decorated a tree, so that stays the default rather than a forced
    choice on old callers/tests."""
    value = (value or "tree").strip()
    if value not in config.BACKDROPS:
        allowed = ", ".join(config.BACKDROPS)
        raise ValidationError(f"ไม่รู้จัก backdrop '{value}' · เลือกจาก: {allowed}")
    return value


def check_size(nbytes, field):
    if nbytes <= 0:
        raise ValidationError(f"{field}: ไฟล์ว่างเปล่า")
    if nbytes > config.MAX_UPLOAD_BYTES:
        limit = config.MAX_UPLOAD_BYTES // (1024 * 1024)
        raise ValidationError(
            f"{field}: ไฟล์ขนาด {nbytes / 1024 / 1024:.1f} MB เกินขีดจำกัด {limit} MB"
        )


def check_image(data, filename, content_type, field):
    """Extension, declared MIME, and — the one that matters — the actual bytes.

    Returns (format, (width, height)). A .pdf renamed to .png fails here, not three steps later.
    """
    ext = PurePosixPath(filename or "").suffix.lower()
    if ext not in config.ALLOWED_EXT:
        allowed = ", ".join(sorted(config.ALLOWED_EXT))
        raise ValidationError(
            f"{field}: '{filename}' เป็นชนิดไฟล์ที่ไม่รองรับ · รับเฉพาะ {allowed}"
        )
    if content_type and content_type.split(";")[0].strip().lower() not in config.ALLOWED_MIME:
        raise ValidationError(f"{field}: '{content_type}' เป็นชนิดไฟล์ที่ไม่รองรับ · ใช้ JPG หรือ PNG")

    try:
        probe = Image.open(io.BytesIO(data))
        fmt, size = probe.format, probe.size
        probe.verify()
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ValidationError(f"{field}: ไฟล์นี้อ่านเป็นรูปภาพไม่ได้ ({exc})") from exc

    if fmt not in config.ALLOWED_FORMATS:
        raise ValidationError(
            f"{field}: เนื้อไฟล์จริงเป็น {fmt} ไม่ใช่ JPG หรือ PNG ไม่ว่านามสกุลจะเขียนว่าอะไร"
        )
    return fmt, size


def validate_upload(data, filename, content_type, field):
    check_size(len(data), field)
    return check_image(data, filename, content_type, field)


def validate_dimensions(width, height):
    """gpt-image-2 output constraints (Spec.md 5)."""
    m = config.DIMENSION_MULTIPLE
    if width % m or height % m:
        raise ValidationError(f"ขนาดภาพ {width}x{height}: ทั้งสองด้านต้องหารด้วย {m} ลงตัว")
    max_w, max_h = config.MAX_DIMENSION
    if width > max_w or height > max_h:
        raise ValidationError(f"ขนาดภาพ {width}x{height} เกินขีดจำกัด {max_w}x{max_h}")
    ratio = width / height
    if not (config.MIN_RATIO <= ratio <= config.MAX_RATIO):
        raise ValidationError(f"ขนาดภาพ {width}x{height}: สัดส่วนต้องอยู่ระหว่าง 1:3 ถึง 3:1")
    return width, height


def resolve_size(key):
    """Preset key, or a literal 'WxH' computed by fit_custom_size(), -> (width, height).

    The literal-size path exists for "match the scene photo's own ratio": /api/prepare
    resolves that ratio into a concrete size once (via fit_custom_size) and stores the
    literal string, so /api/generate re-resolving the same row later doesn't need to know
    where the size came from — it is just another size key by the time it is stored.
    """
    if key in config.SIZE_PRESETS:
        return validate_dimensions(*config.SIZE_PRESETS[key])
    if "x" in key:
        try:
            width, height = (int(part) for part in key.split("x", 1))
        except ValueError:
            raise ValidationError(f"ไม่รู้จักขนาด '{key}'")
        return validate_dimensions(width, height)
    allowed = ", ".join(config.SIZE_PRESETS)
    raise ValidationError(f"ไม่รู้จักขนาด '{key}' · เลือกจาก: {allowed}")


def fit_custom_size(ratio):
    """The closest valid width x height to a real photo's aspect ratio — for "match the scene
    photo's own ratio", not one of the five fixed presets.

    Anchored to DEFAULT_SIZE's pixel count rather than maxed out to MAX_DIMENSION: gpt-image-2
    bills by canvas size, and a shop opting into "match my photo" should not silently pay for
    up to 3x the pixels of a normal run just because their room photo happens to be wide.
    Same divisible-by-16 / ratio / max-dimension rules as every preset, via validate_dimensions.
    """
    ratio = min(max(ratio, config.MIN_RATIO), config.MAX_RATIO)
    m = config.DIMENSION_MULTIPLE
    max_w, max_h = config.MAX_DIMENSION
    anchor_w, anchor_h = config.SIZE_PRESETS[config.DEFAULT_SIZE]
    area = anchor_w * anchor_h

    height = (area / ratio) ** 0.5
    width = height * ratio
    width = max(m, round(width / m) * m)
    height = max(m, round(height / m) * m)

    if width > max_w:
        width = max_w - (max_w % m)
        height = max(m, round(width / ratio / m) * m)
    if height > max_h:
        height = max_h - (max_h % m)
        width = max(m, round(height * ratio / m) * m)

    return validate_dimensions(width, height)
