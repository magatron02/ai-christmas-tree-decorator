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


def load_prompt(scale, element_count=1, has_reference=False, density=None, placement=None):
    """Read the template on every call and fill in what changes between runs.

    Prompt design is the highest-risk part of this project and gets tuned constantly
    (Spec.md 4), so editing the file takes effect on the next generation without a restart
    and without touching code.

    Five substitutions, all existing so whoever tunes the prompt controls where the text
    goes rather than the code appending it somewhere fixed: `{scene}` says what happens to
    the background, `{elements}` how many decorations there are, `{scale}` how big they
    really are, `{density}` how many decorations to place, and `{placement_notes}` exempts
    any element that does not hang from a branch (issue #20) from the template's default
    Placement rules. `density` is the sentence text (from config.DENSITY_PRESETS), not a bare
    key — the same shape as `scale`. `placement_notes` is empty for an all-hung generation,
    leaving the template's rendered text byte-identical to before this existed.
    """
    text = config.PROMPT_PATH.read_text(encoding="utf-8").strip()
    if not text:
        raise ImageGenError(f"ไฟล์ prompt template ที่ {config.PROMPT_PATH} ว่างเปล่า")
    for token in ("{scale}", "{elements}", "{scene}", "{density}", "{placement_notes}"):
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
        .replace("{placement_notes}", placement or "")
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

    A wrapped element (a garland, issue #20) has no density — it is not "how many", it is one
    piece wrapped once — so it never enters this decision, even to break a tie between the
    hung items around it.
    """
    hung = [element for element in elements if element.get("placement") != "wrapped"]
    keys = [element.get("density") or config.DEFAULT_DENSITY for element in hung]
    if len(set(keys)) <= 1:
        return config.DENSITY_PRESETS[keys[0] if keys else config.DEFAULT_DENSITY]

    lines = [
        "Each kind below has its own separate density — these are hard limits, not "
        "suggestions or a starting point. Do not average them together or use the same "
        "amount for every kind; count only copies of that one kind toward its own limit. "
        "Before you finish, count how many of each kind you actually placed and check it "
        "against its limit below — remove copies of a kind that went over, add copies of a "
        "kind that fell short of its minimum:"
    ]
    for element, key in zip(hung, keys):
        label = element.get("code") or "this decoration"
        lines.append(f"- {label}: {config.ELEMENT_DENSITY_PHRASES[key]}")
    if "light" in keys:
        lines.append(
            "Whichever kind above has a strict maximum must end up visibly sparser than the "
            "others in the finished picture — if you are unsure how many to place, place "
            "fewer of it, never more."
        )
    return "\n".join(lines)


def describe_placement(elements):
    """The `{placement_notes}` addendum, exempting any element that does not hang from a
    branch from the template's default Placement rules (issue #20's wrapped garland; more
    placements join this as later sub-issues of the backdrops-and-placement epic land).

    `elements` carries an optional "placement" key per item, the same shape
    describe_element_density() reads "density" from. Empty for an all-hung generation, so the
    template's rendered Placement section stays byte-identical to before this existed.
    """
    # Image 1 is always the tree (describe_elements() calls the first decoration "the second
    # image"), so decoration n in this list is image n + 1 — start the count there, not at 1.
    lines = [
        f"- The copy from image {n} is a garland: ignore the rules above for it. Wrap it "
        "once around the tree's visible trunk, following the trunk's own taper, rather than "
        "hanging it from a branch or scattering several copies."
        for n, element in enumerate(elements, 2)
        if element.get("placement") == "wrapped"
    ]
    return "\n\n" + "\n".join(lines) if lines else ""


def _part(name, data):
    """Describe the upload honestly — the tree keeps whatever format it was shot in."""
    jpeg = data[:3] == b"\xff\xd8\xff"
    ext, mime = ("jpg", "image/jpeg") if jpeg else ("png", "image/png")
    return (f"{name}.{ext}", io.BytesIO(data), mime)


def generate(tree_image, element_pngs, width, height, scale, reference=None, density=None, placement=None):
    """Composite the transparent decorations onto the bare tree.

    `element_pngs` is a list of one to MAX_ELEMENTS cut-outs. `scale` is the sentence saying
    how big each really is next to the tree, built from the catalogue when product codes were
    given (backend/services/catalog.py). `reference`, if given, is a photo whose setting and
    light the result should adopt — it goes last so "the last image" in the prompt is
    unambiguous however many decorations there are. `density` is the sentence saying how many
    decorations to place (backend/config.py's DENSITY_PRESETS); `placement` is the
    describe_placement() addendum exempting any non-hung element (issue #20). Both are
    appended after `reference` rather than inserted earlier so existing positional
    callers/tests reading args[0..5] (tree, elements, width, height, scale, reference) are
    unaffected by either addition.

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
            prompt=load_prompt(scale, len(element_pngs), reference is not None, density, placement),
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
