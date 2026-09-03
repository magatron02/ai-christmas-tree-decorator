"""Risk gate for Prompt mode: a free-text description has never been sent to the real API in
the {density} slot before — every generation until now sent a DENSITY_PRESETS/per-item
sentence built from a picked density, never arbitrary shop-typed text. This calls the real
image_gen.generate() with a real styling prompt exactly where main.py's /api/generate puts
row["custom_prompt"] once one is set (backend/main.py: `density_sentence = row["custom_prompt"]
or image_gen.describe_element_density(...)`), so the risk under test is "does gpt-image-2
actually follow free text landing after the template's hard preservation rules, without those
rules breaking."

Same posture as scripts/check_per_item_density.py: one real, billed call, saved for inspection.
PASS/FAIL here only means "the API accepted the request and returned an image the right
size" — whether the styling actually shows up, and the tree/background still reads as
unmodified, is a call a human makes by looking at scripts/risk_gate_prompt_mode.png.

    python scripts/check_prompt_mode.py

Exit 0 = the call succeeded — look at the saved image before calling Prompt mode done.
Exit 1 = report the printed error before shipping.
"""

import io

from PIL import Image

from _bootstrap import ROOT


def solid_png(color, size=(256, 256)):
    buf = io.BytesIO()
    Image.new("RGBA", size, color).save(buf, format="PNG")
    return buf.getvalue()


def main():
    from backend import config
    from backend.services import image_gen

    # exactly what /api/generate sends when a request has a custom_prompt: the shop's own
    # words, verbatim, in the slot describe_element_density() would otherwise fill
    custom_prompt = (
        "จัดวางแบบหรูหรา โทนทอง เว้นระยะห่างพอสมควรไม่แน่นจนเกินไป "
        "เหมือนต้นในโรงแรมห้าดาว"
    )
    print("custom_prompt sent to the prompt (as {density}):\n")
    print(custom_prompt)
    print()

    tree = solid_png((30, 70, 40, 255), (768, 1024))
    star = solid_png((230, 200, 40, 255))
    ball = solid_png((200, 40, 40, 255))
    width, height = config.SIZE_PRESETS[config.DEFAULT_SIZE]

    print(f"image_gen.generate(...) size={width}x{height} — this is a real, billed generation.")
    try:
        png_bytes, usage = image_gen.generate(
            tree, [star, ball], width, height,
            "Keep every copy in proportion to the tree, as if it were the real object hanging there.",
            density=custom_prompt,
        )
    except Exception as exc:
        print(f"FAIL — {type(exc).__name__}: {exc}")
        return 1

    out = ROOT / "scripts" / "risk_gate_prompt_mode.png"
    out.write_bytes(png_bytes)
    got = Image.open(io.BytesIO(png_bytes)).size
    print(f"OK — {len(png_bytes)} bytes, {got[0]}x{got[1]}, saved to {out}")
    if usage:
        print(f"usage — {usage}")

    print(
        "\nPASS (API accepted the request) — open the saved image and confirm by eye that "
        "the result reads as gold/luxury-toned with generous spacing (what the typed prompt "
        "asked for), and that the tree shape/background still look like an edit of the "
        "original rather than something the free text overrode."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
