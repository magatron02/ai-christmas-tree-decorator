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
The last image is the exact setting the tree goes into — treat it exactly the way the tree's
own background would be treated with no reference photo at all: keep it exactly as it is, the
room, the floor, the furniture, the framing, the crop, and anything else already in that shot.
Do not repaint it, do not regenerate it, and do not treat it as a mood or a style to
reinterpret — composite the decorated tree into these actual pixels.

Relight only the tree to match this setting's real light: the same direction, colour, and
softness of shadow the setting already has, so the tree reads as if it were photographed in
that room. Do not relight, move, add to, or remove anything else in the reference photo."""


def describe_scene(has_reference):
    """What to do with the background, which is the opposite instruction in the two cases.

    Without a reference the background is sacred — the shop wants its own tree in its own
    shop. With one, replacing it is the entire point (Product.md 8.3), so the "keep the
    setting" line has to actually leave rather than sit there contradicting the new one.
    """
    return REFERENCE_SCENE if has_reference else NO_REFERENCE_SCENE


def load_prompt(scale, element_count=1, has_reference=False, density=None):
    """Read the template on every call and fill in what changes between runs.

    Prompt design is the highest-risk part of this project and gets tuned constantly
    (Spec.md 4), so editing the file takes effect on the next generation without a restart
    and without touching code.

    Four substitutions, all existing so whoever tunes the prompt controls where the text
    goes rather than the code appending it somewhere fixed: `{scene}` says what happens to
    the background, `{elements}` how many decorations there are, `{scale}` how big they
    really are, and `{density}` how many decorations to place. `density` is the sentence
    text (from config.DENSITY_PRESETS), not a bare key — the same shape as `scale`.
    """
    text = config.PROMPT_PATH.read_text(encoding="utf-8").strip()
    if not text:
        raise ImageGenError(f"ไฟล์ prompt template ที่ {config.PROMPT_PATH} ว่างเปล่า")
    for token in ("{scale}", "{elements}", "{scene}", "{density}"):
        if token not in text:
            raise ImageGenError(
                f"ไฟล์ prompt template ที่ {config.PROMPT_PATH} ไม่มี {token} แล้ว "
                "คำสั่งบางส่วนจะหายไปเงียบ ๆ"
            )
    return (
        text.replace("{scene}", describe_scene(has_reference))
        .replace("{elements}", describe_elements(element_count))
        .replace("{scale}", scale)
        .replace("{density}", density or config.DENSITY_PRESETS[config.DEFAULT_DENSITY])
    )


def describe_element_density(elements):
    """The `{density}` sentence, built from each accepted item's own density choice.

    `elements` is the list of per-item dicts read back from request_log's elements_json —
    each carries an optional "density" key (a DENSITY_PRESETS key; absent/None falls back to
    DEFAULT_DENSITY, same as before per-item density existed). When every item shares one
    density — including the common case of nobody touching the control at all — this returns
    config.DENSITY_PRESETS[key] verbatim: the exact sentence every generation already sent
    before this feature existed, so the default path never sees new prompt text. Only once
    items actually disagree does it build one line per item from ELEMENT_DENSITY_PHRASES,
    which is worded per-kind rather than as a whole-tree total.
    """
    keys = [element.get("density") or config.DEFAULT_DENSITY for element in elements]
    if len(set(keys)) <= 1:
        return config.DENSITY_PRESETS[keys[0] if keys else config.DEFAULT_DENSITY]

    lines = ["How densely each kind is used is not the same for every kind:"]
    for element, key in zip(elements, keys):
        label = element.get("code") or "this decoration"
        lines.append(f"- {label}: {config.ELEMENT_DENSITY_PHRASES[key]}.")
    return "\n".join(lines)


def _part(name, data):
    """Describe the upload honestly — the tree keeps whatever format it was shot in."""
    jpeg = data[:3] == b"\xff\xd8\xff"
    ext, mime = ("jpg", "image/jpeg") if jpeg else ("png", "image/png")
    return (f"{name}.{ext}", io.BytesIO(data), mime)


def generate(tree_image, element_pngs, width, height, scale, reference=None, density=None):
    """Composite the transparent decorations onto the bare tree.

    `element_pngs` is a list of one to MAX_ELEMENTS cut-outs. `scale` is the sentence saying
    how big each really is next to the tree, built from the catalogue when product codes were
    given (backend/services/catalog.py). `reference`, if given, is a photo whose setting and
    light the result should adopt — it goes last so "the last image" in the prompt is
    unambiguous however many decorations there are. `density` is the sentence saying how many
    decorations to place (backend/config.py's DENSITY_PRESETS); appended after `reference`
    rather than inserted earlier so existing positional callers/tests reading args[0..5]
    (tree, elements, width, height, scale, reference) are unaffected by this addition.

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
            prompt=load_prompt(scale, len(element_pngs), reference is not None, density),
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
