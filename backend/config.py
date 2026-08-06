"""Constants.

These are deliberately not environment variables. The image model in particular is a
Product.md decision-log entry — making it env-swappable would let the engine change
without going through the Architect (NonGoals.md #2). The only env var this project
reads is OPENAI_API_KEY, and the OpenAI SDK reads that itself.
"""

from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent
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
DB_PATH = DATA_DIR / "app.db"
PROMPT_PATH = BACKEND_DIR / "prompts" / "compositing_prompt.txt"
FRONTEND_DIR = ROOT / "frontend"
CATALOG_PATH = ROOT / "catalog" / "products.json"

# Spec.md 3. gpt-image-2's own per-file ceiling is higher; this is ours.
MAX_UPLOAD_BYTES = 10 * 1024 * 1024

# Decorations per image (Product.md 8.2). Five is the product's number, not a technical
# limit — each one is another reference image the model has to keep straight, and the
# quality of a five-way mix is what AC-7 has to establish.
MAX_ELEMENTS = 5
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
