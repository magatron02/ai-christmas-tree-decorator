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
# The shop's own product photos (issue #12) — beside the overlay and the spend log, not
# inside catalog/, which a book re-import or a reinstall can overwrite wholesale (ADR-0001).
SHOP_PHOTOS_DIR = DATA_DIR / "shop_photos"
# Small JPEGs of stored images, for the history table. A subdirectory rather than a suffix in
# STORAGE_DIR so storage.orphans(), which globs that directory for loose files, never sees
# them as rubbish to delete — they are cleaned up alongside the image they are made from.
THUMBS_DIR = STORAGE_DIR / "thumbs"
DB_PATH = DATA_DIR / "app.db"
PROMPT_PATH = BACKEND_DIR / "prompts" / "compositing_prompt.txt"
# A wall or door is a valid backdrop alongside a tree (CONTEXT.md, ADR-0004, issue #22) — its
# own template, tuned independently, since its preservation rules have nothing to do with a
# tree's branch structure or fullness.
WALL_PROMPT_PATH = BACKEND_DIR / "prompts" / "wall_compositing_prompt.txt"
BACKDROPS = ("tree", "wall")
FRONTEND_DIR = ROOT / "frontend"
CATALOG_PATH = ROOT / "catalog" / "products.json"

# Spec.md 3. gpt-image-2's own per-file ceiling is higher; this is ours.
MAX_UPLOAD_BYTES = 10 * 1024 * 1024

# Decorations per image (Product.md 8.2). Not a technical limit — each one is another
# reference image the model has to keep straight. Raised from 5 to 10 after
# scripts/check_scale_and_ratio.py confirmed the real API accepts a 12-image request
# (tree + 10 elements + reference) at full quality.
MAX_ELEMENTS = 10

# A grounded element (gift box, figure — CONTEXT.md, issue #21) sits in its own cluster at the
# tree's foot, never on a branch, so it never competes with MAX_ELEMENTS for a hung slot. Kept
# deliberately small: a cluster reads as a cluster only while it stays a handful of pieces.
MAX_GROUNDED = 3

# The shop offers no tree at or under this (issue #26): below it the tree category is desk
# ornaments — it runs down to 9 inches — and a picture of one decorated is not what anybody is
# here for. Only trees; a 9-inch bauble is an ordinary product. A rule rather than a per-product
# flag, so it holds for trees no book has imported yet. The shop drew the line at "1.5 ft and
# under", which parses to 457mm rather than the round 450 it reads as.
MIN_TREE_MM = 460

ALLOWED_EXT = {".jpg", ".jpeg", ".png"}
ALLOWED_MIME = {"image/jpeg", "image/png"}
ALLOWED_FORMATS = {"JPEG", "PNG"}  # what Pillow reports after sniffing the actual bytes

# What validation.check_image()'s sniffed format actually is, in the two shapes the rest of
# the pipeline needs it in: a filename extension to save under, and the MIME string a vision
# call has to be told rather than assume — a JPEG shop photo sniffed as JPEG but described as
# "image/png" is a request the model is free to fail on.
FORMAT_EXT = {"PNG": "png", "JPEG": "jpg"}
FORMAT_MIME = {"PNG": "image/png", "JPEG": "image/jpeg"}

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

# The {density} slot for a wall/door backdrop (issue #22). Every DENSITY_PRESETS sentence
# above is about a tree — a count for "a full-height tree", gaps "of bare branch" — and a wall
# holds what the shop mounted on it and nothing else. There is no light/normal/full to choose
# between here, so this is a statement rather than a preset table.
WALL_DENSITY = (
    "Place exactly the decorations supplied, one copy of each, and nothing else. There is no "
    "surface to fill here: do not repeat a decoration to cover empty space."
)

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

# What auto pick hangs on every tree: the same mix of hung categories and counts for every
# tone and every tree size (ADR-0003). The tone decides which products fill these slots, never
# what the slots are, and the tree's size does not enter into it — density already governs how
# thickly the result reads, and an uploaded tree photo has no known size to reason from.
#
# Lights and figures are deliberately absent. A light string is not a single hangable object
# the compositor places well, and a figure is prominent enough to deserve being chosen on
# purpose rather than arriving in a mix. Grounded categories (gift boxes) are a separate pool,
# AUTO_GROUNDED below — not hung, so not part of this recipe (issue #21).
#
# Ordered, and kept under MAX_ELEMENTS: this is the whole hung proposal, and the order is the
# order the shop sees it in.
AUTO_RECIPE = (
    ("ornament", 3),
    ("ribbon", 1),
    ("topper", 1),
    ("flower", 1),
    ("bell", 1),
)

# The grounded half of auto pick's proposal (CONTEXT.md, issue #21) — its own pool, filled the
# same way as AUTO_RECIPE but counted against MAX_GROUNDED, never MAX_ELEMENTS. A gift box was
# in AUTO_RECIPE from the start; moving it here is a bug fix, not a change to what auto pick
# proposes by default.
AUTO_GROUNDED = (
    ("giftbox", 1),
)

# What auto pick mounts on a wall or door (issue #24) — the mounted categories, the only ones
# that can go there at all (catalog.suits_backdrop). A door usually takes one wreath, and a
# banner beside it is the pairing the domain modelling had in mind; a slot the shop cannot
# stock in the chosen tone simply places nothing, the same as an empty tree slot.
AUTO_WALL_RECIPE = (
    ("wreath", 1),
    ("banner", 1),
)

# The whole proposal per backdrop, which is all either auto pick endpoint needs to know about
# the difference between them — one engine, not one per backdrop (ADR-0004).
AUTO_RECIPES = {
    "tree": AUTO_RECIPE + AUTO_GROUNDED,
    "wall": AUTO_WALL_RECIPE,
}

# Auto pick's colour-tone presets, reviewed as the 5-tone mockup. Colours are
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
