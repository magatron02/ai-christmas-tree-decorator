"""Risk gate for Spec.md open item #5.

There is a reported OpenAI SDK bug (Apr 2026) that `images.edit` rejects GPT Image models
with "Invalid value: 'gpt-image-2'". Everything in this project sits on top of that one
call, so it gets verified before any of it is trusted.

One paid call verifies three things at once:
  1. the edit endpoint accepts model=gpt-image-2
  2. it accepts a *list* of images (tree + transparent element)
  3. it accepts the custom size 1536x1920 (Product.md's 4:5 default)

    python scripts/check_edit_endpoint.py

Exit 0 = the engine works as specified. Exit 1 = it does not; report the printed error
back to the Architect. Do NOT edit this script to try gpt-image-1.5 instead — swapping
engines is a Product.md decision, not a Builder one (NonGoals.md #2).
"""

import io
import sys
from pathlib import Path

from dotenv import load_dotenv
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

MODEL = "gpt-image-2"
SIZE = "1536x1920"


def png(color, size=(256, 320)):
    buf = io.BytesIO()
    Image.new("RGBA", size, color).save(buf, format="PNG")
    return buf.getvalue()


def describe(exc):
    """Print everything the SDK gives us — the exact wording is what decides the outcome."""
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


def main():
    load_dotenv(ROOT / ".env")

    import openai
    from openai import OpenAI

    print(f"openai SDK : {openai.__version__}")

    try:
        client = OpenAI()
    except Exception as exc:
        print("FAIL: could not construct the client (OPENAI_API_KEY missing?)")
        describe(exc)
        return 1

    # free lookup first, so "the account cannot see this model" is distinguishable from
    # "the edit endpoint rejects this model" — they need different answers.
    print(f"\n[1/2] models.retrieve({MODEL!r}) ...")
    try:
        model = client.models.retrieve(MODEL)
        print(f"      OK — id={model.id} owned_by={getattr(model, 'owned_by', '?')}")
    except Exception as exc:
        print("      FAIL — the model is not reachable from this account/key.")
        describe(exc)
        return 1

    print(f"\n[2/2] images.edit(model={MODEL!r}, image=[2 files], size={SIZE!r}) ...")
    print("      this is a real, billed generation.")
    try:
        result = client.images.edit(
            model=MODEL,
            image=[
                ("tree.png", io.BytesIO(png((20, 60, 30, 255))), "image/png"),
                ("element.png", io.BytesIO(png((200, 40, 40, 255), (128, 128))), "image/png"),
            ],
            prompt="Place the decoration from the second image onto the tree in the first image.",
            size=SIZE,
        )
    except Exception as exc:
        print("      FAIL — the edit endpoint rejected the request.")
        describe(exc)
        print(
            "\nSTOP. Report this verbatim to the Architect before writing engine code.\n"
            "Do not silently fall back to another model (NonGoals.md #2)."
        )
        return 1

    item = result.data[0]
    payload = getattr(item, "b64_json", None)
    if not payload:
        print(f"      FAIL — response carried no b64_json. url={getattr(item, 'url', None)}")
        return 1

    import base64

    raw = base64.b64decode(payload)
    got = Image.open(io.BytesIO(raw)).size
    out = ROOT / "scripts" / "risk_gate_output.png"
    out.write_bytes(raw)

    print(f"      OK — {len(raw)} bytes, {got[0]}x{got[1]}, saved to {out}")
    usage = getattr(result, "usage", None)
    if usage is not None:
        print(f"      usage — {usage.model_dump()}")
        print("      (this is what one 4:5 generation costs; price a credit off it)")
    if f"{got[0]}x{got[1]}" != SIZE:
        print(f"      WARN — asked for {SIZE}, got {got[0]}x{got[1]}. Raise this before building on it.")
        return 1

    print("\nPASS: gpt-image-2 + images.edit + multi-image + 1536x1920 all work.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
