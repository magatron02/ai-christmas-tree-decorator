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
API_TIMEOUT_S = 300.0

DATA_DIR = ROOT / "data"
STORAGE_DIR = ROOT / "storage"
DB_PATH = DATA_DIR / "app.db"
PROMPT_PATH = BACKEND_DIR / "prompts" / "compositing_prompt.txt"
FRONTEND_DIR = ROOT / "frontend"

# Spec.md 3. gpt-image-2's own per-file ceiling is higher; this is ours.
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
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

MAX_DIMENSION = (3840, 2160)
DIMENSION_MULTIPLE = 16
MIN_RATIO = 1 / 3
MAX_RATIO = 3 / 1
