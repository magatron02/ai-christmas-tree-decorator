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


def load_prompt():
    """Read the template on every call.

    Prompt design is the highest-risk part of this project and gets tuned constantly
    (Spec.md 4), so editing the file takes effect on the next generation without a restart
    and without touching code.
    """
    text = config.PROMPT_PATH.read_text(encoding="utf-8").strip()
    if not text:
        raise ImageGenError(f"The prompt template at {config.PROMPT_PATH} is empty.")
    return text


def _part(name, data):
    """Describe the upload honestly — the tree keeps whatever format it was shot in."""
    jpeg = data[:3] == b"\xff\xd8\xff"
    ext, mime = ("jpg", "image/jpeg") if jpeg else ("png", "image/png")
    return (f"{name}.{ext}", io.BytesIO(data), mime)


def generate(tree_image, element_png, width, height):
    """Composite the transparent element onto the bare tree.

    Returns (png_bytes, usage). `usage` is whatever token accounting the API reported, kept
    because it is the only per-image record of what a generation actually cost — the credit
    unit is one generation regardless of output size, but the money is not, and Product.md
    still has to price a credit off real numbers rather than a dashboard average.
    """
    from openai import OpenAI

    try:
        # constructing the client can raise too — a missing key is a generation failure like
        # any other, not a crash, and the caller has a claimed request waiting on an answer
        client = OpenAI(timeout=config.API_TIMEOUT_S)
        response = client.images.edit(
            model=config.IMAGE_MODEL,
            image=[_part("tree", tree_image), _part("element", element_png)],
            prompt=load_prompt(),
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
