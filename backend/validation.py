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
    """Input A = 1 file, Input B = 1 file (Product.md: one element per run).

    More than one is rejected outright rather than silently using the first — AC-1 requires
    the behaviour to be a choice, and a rejection is the one the user can actually see.
    """
    if not files:
        raise ValidationError(f"{field}: no file was uploaded.")
    if len(files) > 1:
        raise ValidationError(
            f"{field}: {len(files)} files uploaded, but exactly 1 is allowed. "
            "This tool composites one element per run."
        )
    return files[0]


def check_size(nbytes, field):
    if nbytes <= 0:
        raise ValidationError(f"{field}: the file is empty.")
    if nbytes > config.MAX_UPLOAD_BYTES:
        limit = config.MAX_UPLOAD_BYTES // (1024 * 1024)
        raise ValidationError(
            f"{field}: file is {nbytes / 1024 / 1024:.1f} MB, the limit is {limit} MB."
        )


def check_image(data, filename, content_type, field):
    """Extension, declared MIME, and — the one that matters — the actual bytes.

    Returns (format, (width, height)). A .pdf renamed to .png fails here, not three steps later.
    """
    ext = PurePosixPath(filename or "").suffix.lower()
    if ext not in config.ALLOWED_EXT:
        allowed = ", ".join(sorted(config.ALLOWED_EXT))
        raise ValidationError(
            f"{field}: '{filename}' is not a supported file type. Allowed: {allowed}."
        )
    if content_type and content_type.split(";")[0].strip().lower() not in config.ALLOWED_MIME:
        raise ValidationError(f"{field}: '{content_type}' is not a supported file type. Use JPG or PNG.")

    try:
        probe = Image.open(io.BytesIO(data))
        fmt, size = probe.format, probe.size
        probe.verify()
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ValidationError(f"{field}: the file is not a readable image ({exc}).") from exc

    if fmt not in config.ALLOWED_FORMATS:
        raise ValidationError(
            f"{field}: the file contents are {fmt}, not JPG or PNG, whatever the extension says."
        )
    return fmt, size


def validate_upload(data, filename, content_type, field):
    check_size(len(data), field)
    return check_image(data, filename, content_type, field)


def validate_dimensions(width, height):
    """gpt-image-2 output constraints (Spec.md 5)."""
    m = config.DIMENSION_MULTIPLE
    if width % m or height % m:
        raise ValidationError(f"Output size {width}x{height}: both sides must be divisible by {m}.")
    max_w, max_h = config.MAX_DIMENSION
    if width > max_w or height > max_h:
        raise ValidationError(f"Output size {width}x{height} exceeds the {max_w}x{max_h} maximum.")
    ratio = width / height
    if not (config.MIN_RATIO <= ratio <= config.MAX_RATIO):
        raise ValidationError(f"Output size {width}x{height}: aspect ratio must be between 1:3 and 3:1.")
    return width, height


def resolve_size(key):
    """Preset key -> (width, height). Users pick a ratio, never raw pixels."""
    if key not in config.SIZE_PRESETS:
        allowed = ", ".join(config.SIZE_PRESETS)
        raise ValidationError(f"Unknown output size '{key}'. Choose one of: {allowed}.")
    return validate_dimensions(*config.SIZE_PRESETS[key])
