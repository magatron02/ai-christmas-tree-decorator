"""Risk gate for per-item density: a per-kind density line has never been sent to the real
API before — every generation until now always sent DENSITY_PRESETS' single whole-tree
sentence. This calls the real image_gen.generate() (not a hand-rolled copy of the API call,
like scripts/check_scale_and_ratio.py does) with two accepted decorations set to opposite
densities, exactly the path /api/generate takes once main.py calls
image_gen.describe_element_density() on elements whose per-item density actually differs.

Same posture as scripts/check_edit_endpoint.py: one real, billed call, saved for inspection.
PASS/FAIL here only means "the API accepted the request and returned an image the right
size" — whether the two kinds actually read as different densities is a call a human makes
by looking at scripts/risk_gate_per_item_density.png.

    python scripts/check_per_item_density.py

Exit 0 = the call succeeded — look at the saved image before calling per-item density done.
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

    # two accepted decorations, deliberately opposite densities — this is exactly what
    # main.py hands to describe_element_density() once per-item densities actually differ
    elements = [
        {"code": "RISK-STAR-LIGHT", "density": "light"},
        {"code": "RISK-BALL-FULL", "density": "full"},
    ]
    density_sentence = image_gen.describe_element_density(elements)
    print("density sentence sent to the prompt:\n")
    print(density_sentence)
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
            density=density_sentence,
        )
    except Exception as exc:
        print(f"FAIL — {type(exc).__name__}: {exc}")
        return 1

    out = ROOT / "scripts" / "risk_gate_per_item_density.png"
    out.write_bytes(png_bytes)
    got = Image.open(io.BytesIO(png_bytes)).size
    print(f"OK — {len(png_bytes)} bytes, {got[0]}x{got[1]}, saved to {out}")
    if usage:
        print(f"usage — {usage}")

    print(
        "\nPASS (API accepted the request) — open the saved image and confirm by eye that "
        "the yellow star copies read as sparse/scattered and the red ball copies read as "
        "dense/packed, not the same everywhere."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
