"""gpt-image-2 call (Product.md 6, Spec.md 2).

One function, one API call, one model. There is no fallback to another engine here on
purpose: if gpt-image-2 stops working, that is an Architect decision, not a runtime branch
(NonGoals.md #2). scripts/check_edit_endpoint.py is what proves this path works.
"""

import base64
import io

from backend import config


class ImageGenError(RuntimeError):
    """Any reason the API did not hand back an image. Never charge on this."""


def load_prompt(scale):
    """Read the template on every call and drop the scale instruction into it.

    Prompt design is the highest-risk part of this project and gets tuned constantly
    (Spec.md 4), so editing the file takes effect on the next generation without a restart
    and without touching code.

    `{scale}` is the one substitution. It exists so whoever tunes the prompt controls where
    the measurement goes, rather than the code appending it somewhere fixed. The caller
    always supplies text — a real measurement when product codes were given, a generic
    instruction when they were not (backend/services/catalog.py).
    """
    text = config.PROMPT_PATH.read_text(encoding="utf-8").strip()
    if not text:
        raise ImageGenError(f"The prompt template at {config.PROMPT_PATH} is empty.")
    if "{scale}" not in text:
        raise ImageGenError(
            f"The prompt template at {config.PROMPT_PATH} no longer contains {{scale}}, so "
            "the real product size would be silently dropped."
        )
    return text.replace("{scale}", scale)


def _part(name, data):
    """Describe the upload honestly — the tree keeps whatever format it was shot in."""
    jpeg = data[:3] == b"\xff\xd8\xff"
    ext, mime = ("jpg", "image/jpeg") if jpeg else ("png", "image/png")
    return (f"{name}.{ext}", io.BytesIO(data), mime)


def generate(tree_image, element_png, width, height, scale):
    """Composite the transparent element onto the bare tree.

    `scale` is the sentence saying how big the decoration really is next to the tree, built
    from the catalogue when product codes were given (backend/services/catalog.py).

    Returns (png_bytes, usage). `usage` is whatever token accounting the API reported, kept
    because it is the only per-image record of what a generation actually cost.
    """
    from openai import OpenAI

    try:
        # constructing the client can raise too — a missing key is a generation failure like
        # any other, not a crash, and the caller has a claimed request waiting on an answer
        client = OpenAI(timeout=config.API_TIMEOUT_S)
        response = client.images.edit(
            model=config.IMAGE_MODEL,
            image=[_part("tree", tree_image), _part("element", element_png)],
            prompt=load_prompt(scale),
            size=f"{width}x{height}",
        )
    except Exception as exc:
        # OpenAI's own billing limit is what stops a run when the account is out of money;
        # there is no local balance to check first, so make that answer readable
        if "billing_hard_limit" in str(exc):
            raise ImageGenError(
                "OpenAI stopped the request: the account has hit its billing limit. "
                "Top up or raise the limit at platform.openai.com. Nothing was generated."
            ) from exc
        raise ImageGenError(f"{type(exc).__name__}: {exc}") from exc

    if not response.data:
        raise ImageGenError("The API returned no image.")
    payload = getattr(response.data[0], "b64_json", None)
    if not payload:
        raise ImageGenError("The API response carried no image data.")

    usage = getattr(response, "usage", None)
    return base64.b64decode(payload), (usage.model_dump() if usage else None)
