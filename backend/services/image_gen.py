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


def describe_elements(count):
    """What to say about the decoration images, which is different for one and for several."""
    if count == 1:
        return (
            "The second image is the decoration to add. It is a cut-out on a transparent "
            "background and it is the only decoration that may appear."
        )
    return (
        f"The {count} images after the first are the decorations to add, in the order given. "
        f"They are cut-outs on transparent backgrounds and they are the only decorations "
        f"that may appear.\n"
        f"Use all {count} kinds. Mix them across the whole tree rather than grouping each "
        f"kind in its own area, and use roughly the same number of each unless one is much "
        f"larger than the others. Two of the same kind should not end up side by side."
    )


NO_REFERENCE_SCENE = """\
Keep the setting exactly as it is: the background, the floor, the framing, the crop, and
anything else in the shot. Only the decorations are new."""

REFERENCE_SCENE = """\
The last image is a reference for the setting, not for the tree and not for the decorations.
Take only its mood from it: the kind of place, the time of day, the colour of the light, how
warm or cool it is, how soft or hard the shadows are, the overall palette.

Place the decorated tree into a setting of that kind. Relight the tree to match — the light
has to fall on it from the same direction and in the same colour as the setting implies, or
it will look pasted in. Do not copy any object, furniture, decoration or person from the
reference image, and do not copy its composition."""


def describe_scene(has_reference):
    """What to do with the background, which is the opposite instruction in the two cases.

    Without a reference the background is sacred — the shop wants its own tree in its own
    shop. With one, replacing it is the entire point (Product.md 8.3), so the "keep the
    setting" line has to actually leave rather than sit there contradicting the new one.
    """
    return REFERENCE_SCENE if has_reference else NO_REFERENCE_SCENE


def load_prompt(scale, element_count=1, has_reference=False):
    """Read the template on every call and fill in what changes between runs.

    Prompt design is the highest-risk part of this project and gets tuned constantly
    (Spec.md 4), so editing the file takes effect on the next generation without a restart
    and without touching code.

    Three substitutions, all existing so whoever tunes the prompt controls where the text
    goes rather than the code appending it somewhere fixed: `{scene}` says what happens to
    the background, `{elements}` how many decorations there are, and `{scale}` how big they
    really are.
    """
    text = config.PROMPT_PATH.read_text(encoding="utf-8").strip()
    if not text:
        raise ImageGenError(f"ไฟล์ prompt template ที่ {config.PROMPT_PATH} ว่างเปล่า")
    for token in ("{scale}", "{elements}", "{scene}"):
        if token not in text:
            raise ImageGenError(
                f"ไฟล์ prompt template ที่ {config.PROMPT_PATH} ไม่มี {token} แล้ว "
                "คำสั่งบางส่วนจะหายไปเงียบ ๆ"
            )
    return (
        text.replace("{scene}", describe_scene(has_reference))
        .replace("{elements}", describe_elements(element_count))
        .replace("{scale}", scale)
    )


def _part(name, data):
    """Describe the upload honestly — the tree keeps whatever format it was shot in."""
    jpeg = data[:3] == b"\xff\xd8\xff"
    ext, mime = ("jpg", "image/jpeg") if jpeg else ("png", "image/png")
    return (f"{name}.{ext}", io.BytesIO(data), mime)


def generate(tree_image, element_pngs, width, height, scale, reference=None):
    """Composite the transparent decorations onto the bare tree.

    `element_pngs` is a list of one to five cut-outs. `scale` is the sentence saying how big
    each really is next to the tree, built from the catalogue when product codes were given
    (backend/services/catalog.py). `reference`, if given, is a photo whose setting and light
    the result should adopt — it goes last so "the last image" in the prompt is unambiguous
    however many decorations there are.

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
            image=(
                [_part("tree", tree_image)]
                + [_part(f"element{n}", data) for n, data in enumerate(element_pngs, 1)]
                + ([_part("reference", reference)] if reference else [])
            ),
            prompt=load_prompt(scale, len(element_pngs), reference is not None),
            size=f"{width}x{height}",
        )
    except Exception as exc:
        # OpenAI's own billing limit is what stops a run when the account is out of money;
        # there is no local balance to check first, so make that answer readable
        if "billing_hard_limit" in str(exc):
            raise ImageGenError(
                "OpenAI ปฏิเสธคำขอ: บัญชีชนขีดจำกัดวงเงินแล้ว "
                "ไปเติมเงินหรือปรับวงเงินที่ platform.openai.com — ยังไม่มีการสร้างภาพเกิดขึ้น"
            ) from exc
        raise ImageGenError(f"{type(exc).__name__}: {exc}") from exc

    if not response.data:
        raise ImageGenError("API ไม่ส่งภาพกลับมา")
    payload = getattr(response.data[0], "b64_json", None)
    if not payload:
        raise ImageGenError("คำตอบจาก API ไม่มีข้อมูลภาพอยู่ในนั้น")

    usage = getattr(response, "usage", None)
    return base64.b64decode(payload), (usage.model_dump() if usage else None)
