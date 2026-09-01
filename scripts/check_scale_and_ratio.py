"""Risk gate for two changes that have never been sent to the real API before:

  1. MAX_ELEMENTS raised 5 -> 10 — a request with 12 input images (tree + 10 elements +
     reference) has never been tried against gpt-image-2's edit endpoint in this codebase.
  2. "Match the scene photo's own ratio" — a WxH the API has never been asked for before,
     computed by validation.fit_custom_size() rather than one of the five fixed presets.

Same pattern as scripts/check_edit_endpoint.py: real, billed calls, PASS/FAIL printed
plainly, non-zero exit on anything that isn't a clean success.

    python scripts/check_scale_and_ratio.py

Exit 0 = both checks pass — MAX_ELEMENTS=10 and the "auto" size path are safe to ship.
Exit 1 = report the printed error before shipping either; do not silently narrow the
request (fewer images, round to a preset) to make it pass (NonGoals.md #2 territory —
this is the Architect's call, not a runtime workaround).
"""

import base64
import io

from PIL import Image

from _bootstrap import ROOT

MODEL = "gpt-image-2"


def png(color, size=(512, 512)):
    buf = io.BytesIO()
    Image.new("RGBA", size, color).save(buf, format="PNG")
    return buf.getvalue()


def describe(exc):
    print(f"\n  type    : {type(exc).__module__}.{type(exc).__name__}")
    print(f"  message : {exc}")
    for attr in ("status_code", "code", "param", "type"):
        if getattr(exc, attr, None) is not None:
            print(f"  {attr:<8}: {getattr(exc, attr)}")
    body = getattr(exc, "body", None)
    if body is not None:
        print(f"  body    : {body}")
    resp = getattr(exc, "response", None)
    if resp is not None:
        text = getattr(resp, "text", None)
        if text:
            print(f"  raw     : {text[:2000]}")


def run_edit(client, label, image_parts, prompt, size, save_as):
    print(f"\n[{label}] images.edit(image=[{len(image_parts)} files], size={size!r}) ...")
    print("      this is a real, billed generation.")
    try:
        result = client.images.edit(model=MODEL, image=image_parts, prompt=prompt, size=size)
    except Exception as exc:
        print("      FAIL — the edit endpoint rejected the request.")
        describe(exc)
        return None

    item = result.data[0]
    payload = getattr(item, "b64_json", None)
    if not payload:
        print(f"      FAIL — response carried no b64_json. url={getattr(item, 'url', None)}")
        return None

    raw = base64.b64decode(payload)
    got = Image.open(io.BytesIO(raw)).size
    out = ROOT / "scripts" / save_as
    out.write_bytes(raw)
    print(f"      OK — {len(raw)} bytes, {got[0]}x{got[1]}, saved to {out}")

    usage = getattr(result, "usage", None)
    if usage is not None:
        print(f"      usage — {usage.model_dump()}")

    if f"{got[0]}x{got[1]}" != size:
        print(f"      WARN — asked for {size}, got {got[0]}x{got[1]}.")
        return None
    return got


def main():
    from openai import OpenAI

    from backend import config, validation

    try:
        client = OpenAI()
    except Exception as exc:
        print("FAIL: could not construct the client (OPENAI_API_KEY missing?)")
        describe(exc)
        return 1

    ok = True

    # ---- check 1: 12 input images (tree + 10 elements + reference) ----------------------
    width, height = config.SIZE_PRESETS[config.DEFAULT_SIZE]
    tree = ("tree.png", io.BytesIO(png((20, 60, 30, 255))), "image/png")
    elements = [
        (f"element{n}.png", io.BytesIO(png((200, 40 + n * 10, 40, 255), (128, 128))), "image/png")
        for n in range(1, 11)
    ]
    reference = ("reference.png", io.BytesIO(png((230, 220, 200, 255))), "image/png")
    prompt_10 = (
        "The 10 images after the first are the decorations to add, in the order given. "
        "They are cut-outs on transparent backgrounds and they are the only decorations "
        "that may appear. Mix them across the whole tree. The last image is the setting."
    )
    result = run_edit(
        client, "1/2 — 12 images", [tree] + elements + [reference],
        prompt_10, f"{width}x{height}", "risk_gate_12_images.png",
    )
    ok = ok and result is not None

    # ---- check 2: a custom, non-preset size --------------------------------------------
    # a deliberately awkward ratio (a wide room photo) that is not equal to any SIZE_PRESETS
    # value, run through the exact function /api/prepare uses for "auto"
    custom_w, custom_h = validation.fit_custom_size(1.6)
    is_a_preset = (custom_w, custom_h) in config.SIZE_PRESETS.values()
    print(f"\nfit_custom_size(1.6) -> {custom_w}x{custom_h}  (matches a fixed preset: {is_a_preset})")
    if is_a_preset:
        print("WARN — test setup produced a preset-equal size; this check would prove nothing "
              "about custom sizes specifically. Adjust the ratio above and re-run.")
        return 1

    result = run_edit(
        client, "2/2 — custom size", [tree, elements[0], reference],
        "Place the decoration from the second image onto the tree in the first image, "
        "in the setting shown in the last image.",
        f"{custom_w}x{custom_h}", "risk_gate_custom_size.png",
    )
    ok = ok and result is not None

    if not ok:
        print(
            "\nSTOP. At least one check failed — report this verbatim to the Architect. "
            "Do not ship MAX_ELEMENTS=10 or the auto-size feature until both pass."
        )
        return 1

    print("\nPASS: 12 input images and a custom non-preset size both work.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
