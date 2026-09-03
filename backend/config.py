"""Constants.

These are deliberately not environment variables. The image model in particular is a
Product.md decision-log entry — making it env-swappable would let the engine change
without going through the Architect (NonGoals.md #2). The only env var this project
reads is OPENAI_API_KEY, and the OpenAI SDK reads that itself.
"""

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent

# Everything the app writes — .env, data/app.db, storage/, and the catalogue the settings page
# edits — is ROOT-relative. Running from source that is the repo. Frozen by PyInstaller the
# code lives inside _internal/, which is the wrong place for any of it: the installed copy has
# to keep its data beside the exe, where the installer put the shipped catalogue and where a
# per-user install can actually write.
if getattr(sys, "frozen", False):
    ROOT = Path(sys.executable).resolve().parent
else:
    ROOT = BACKEND_DIR.parent

IMAGE_MODEL = "gpt-image-2"

# Reading what a decoration is, for the reference-photo matching in Product.md 8.3c. A
# separate, much cheaper model than the image one: this only has to name a colour, a finish
# and a shape, and it runs 1,053 times to index the catalogue.
VISION_MODEL = "gpt-5.4-mini"
EMBEDDING_MODEL = "text-embedding-3-small"

API_TIMEOUT_S = 300.0

DATA_DIR = ROOT / "data"
STORAGE_DIR = ROOT / "storage"
# Small JPEGs of stored images, for the history table. A subdirectory rather than a suffix in
# STORAGE_DIR so storage.orphans(), which globs that directory for loose files, never sees
# them as rubbish to delete — they are cleaned up alongside the image they are made from.
THUMBS_DIR = STORAGE_DIR / "thumbs"
DB_PATH = DATA_DIR / "app.db"
PROMPT_PATH = BACKEND_DIR / "prompts" / "compositing_prompt.txt"
FRONTEND_DIR = ROOT / "frontend"
CATALOG_PATH = ROOT / "catalog" / "products.json"

# Spec.md 3. gpt-image-2's own per-file ceiling is higher; this is ours.
MAX_UPLOAD_BYTES = 10 * 1024 * 1024

# Decorations per image (Product.md 8.2). Not a technical limit — each one is another
# reference image the model has to keep straight. Raised from 5 to 10 after
# scripts/check_scale_and_ratio.py confirmed the real API accepts a 12-image request
# (tree + 10 elements + reference) at full quality.
MAX_ELEMENTS = 10
ALLOWED_EXT = {".jpg", ".jpeg", ".png"}
ALLOWED_MIME = {"image/jpeg", "image/png"}
ALLOWED_FORMATS = {"JPEG", "PNG"}  # what Pillow reports after sniffing the actual bytes

# gpt-image-2 constraints (Spec.md 5): both sides divisible by 16, ratio inside 1:3..3:1,
# no larger than 3840x2160. Every preset below is checked against that by validate_dimensions.
SIZE_PRESETS = {
    "4:5": (1536, 1920),  # Product.md default
    "1:1": (1024, 1024),
    "3:4": (1536, 2048),
    "2:3": (1024, 1536),
    "16:9": (2048, 1152),  # not 1920x1080 — 1080 is not divisible by 16
}
DEFAULT_SIZE = "4:5"

# How tightly the tree gets decorated. "normal" is worded identically to what the prompt
# always said, so the default behaviour is unchanged — this only exists so a shop that wants
# a sparser or fuller look has a control for it, without hand-editing the prompt file.
DENSITY_PRESETS = {
    "light": (
        "A lightly decorated tree: roughly 8 to 12 decorations in total for a full-height "
        "tree, counting every kind together, fewer if they are large. Leave generous gaps of "
        "bare branch between them."
    ),
    "normal": (
        "A naturally decorated tree, not a covered one: roughly 12 to 20 decorations in "
        "total for a full-height tree, counting every kind together, fewer if they are "
        "large. Leave visible gaps of bare branch between them."
    ),
    "full": (
        "A fully decorated tree: roughly 20 to 30 decorations in total for a full-height "
        "tree, counting every kind together, fewer if they are large. Leave only small gaps "
        "of bare branch between them."
    ),
}
DENSITY_LABELS = {"light": "โปร่ง", "normal": "ปกติ", "full": "แน่น"}
DEFAULT_DENSITY = "normal"

# Per-item density phrasing (workstream C) — same 3 levels/labels as DENSITY_PRESETS above,
# different vocabulary: DENSITY_PRESETS states a total count for the whole tree, which reads
# fine as one sentence but makes no sense repeated once per decoration kind when kinds differ.
# image_gen.describe_element_density() reaches for DENSITY_PRESETS verbatim (unchanged prompt)
# whenever every accepted item shares one density, and only builds a per-item list from this
# dict when they actually differ — so the common case never sees new prompt text.
# A real billed check (scripts/check_per_item_density.py, 2026-09-02) went through two rounds:
#   1. qualitative words alone ("sparingly" vs "generously") -> 25 vs 18 copies, no real
#      contrast at all.
#   2. a number range per kind (4-6 vs 18-24, the same trick DENSITY_PRESETS already uses for
#      the whole tree) -> "full" landed in range (~30) but "light" still overshot to ~17 —
#      the model has a strong prior toward "a normally decorated tree" that a soft range
#      doesn't override on the sparse side.
# Round 3: "light" states a hard ceiling ("never more than N") rather than a range, since the
# failure mode is specifically overshooting upward, never undershooting.
ELEMENT_DENSITY_PHRASES = {
    "light": (
        "a strict maximum of 6 copies of this kind — never more than 6, even if that leaves "
        "large bare patches of branch where this kind could have gone. Fewer than 6 is fine; "
        "more than 6 is wrong."
    ),
    "normal": (
        "roughly 8 to 12 copies of this kind, spread out with visible gaps of bare branch "
        "between them."
    ),
    "full": (
        "at least 18 copies of this kind, up to about 24 — noticeably more than a normal "
        "amount. Place them closely together, filling most of the space this kind would cover."
    ),
}

# The wizard's "ไซส์ต้น" step (wayfinder map #1) offers a real tree height in feet, resolved
# to the catalogue's closest actual sized tree by catalog.nearest_tree() — never a guessed
# product, just the nearest real one to what was asked for.
WIZARD_TREE_HEIGHTS_FT = [4, 5, 6, 7, 8]

# The wizard's "แนว" step: catalog.CATEGORIES minus the ones nobody adds *onto* a tree —
# wreath, banner, and the tree itself (wayfinder ticket #3's Q8 decision).
WIZARD_CATEGORIES = ["ornament", "flower", "bell", "topper", "giftbox", "light", "figure", "ribbon"]

# Auto-mode's colour-tone presets, reviewed as the 5-tone mockup this session. Colours are
# free strings matched through matching._normalize()/COLOUR_BUCKETS, so no separate bucket
# table lives here — catalog.auto_pool() does the matching.
TONE_PRESETS = {
    "redgold": {"label": "แดง-ทอง คลาสสิก", "colours": ["red", "gold"]},
    "whitesilver": {"label": "ขาว-เงิน มินิมอล", "colours": ["white", "silver"]},
    "natural": {"label": "ธรรมชาติ ใบไม้", "colours": ["green", "brown"]},
    "pastel": {"label": "พาสเทลหวาน", "colours": ["pink", "blue"]},
    "luxe": {"label": "น้ำเงิน-เงิน หรู", "colours": ["blue", "silver"]},
}

# Prompt mode: a free-text description the shop types instead of picking a density — see
# validation.parse_custom_prompt() and image_gen's {density} substitution. A ceiling, not a
# quota — this is a paid prompt, and an unbounded paste is a real cost/abuse surface even for
# an internal tool.
PROMPT_MODE_MAX_CHARS = 500

# There is deliberately no scale-correction constant here. gpt-image-2 renders decorations
# at roughly 0.55-0.70 of the fraction it is told, so correcting for it looks obvious: ask
# for 1/11 to get a true 1/19. Measured, that produced 0.55x — smaller than the uncorrected
# 0.70x, not larger. The instructed fraction does not control the rendered size linearly, so
# a correction factor would be a knob that implies control it does not have.
# scripts/measure_scale.py is the check if this is ever worth revisiting.

MAX_DIMENSION = (3840, 2160)
DIMENSION_MULTIPLE = 16
MIN_RATIO = 1 / 3
MAX_RATIO = 3 / 1
