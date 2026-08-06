"""Describe every catalogue photo so pictures can be searched as text.

    python scripts/describe_catalog.py            # resumes; skips what is already described
    python scripts/describe_catalog.py --limit 20

One billed vision call per photo, about 550 tokens each. Writes after every photo, so an
interruption costs nothing already paid for — the same lesson the quality-run harness taught.

Output is catalog/descriptions.json: code -> attributes plus the text that gets embedded.
Failures are recorded with their error rather than dropped, so a rerun retries only those and
a photo nobody could describe stays visible instead of quietly missing from search.
"""

import argparse
import json
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from backend.services import vision  # noqa: E402

INDEX = ROOT / "catalog" / "product_images.json"
IMAGES = ROOT / "catalog" / "images"
OUT = ROOT / "catalog" / "descriptions.json"


def load_done():
    if OUT.is_file():
        return json.loads(OUT.read_text(encoding="utf-8"))
    return {}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, help="stop after this many new descriptions")
    parser.add_argument("--retry-failed", action="store_true")
    args = parser.parse_args()

    index = json.loads(INDEX.read_text(encoding="utf-8"))
    done = load_done()

    todo = []
    for row in index:
        if not row["image"]:
            continue
        existing = done.get(row["code"])
        if existing and not existing.get("error"):
            continue
        if existing and existing.get("error") and not args.retry_failed:
            continue
        todo.append(row)

    if args.limit:
        todo = todo[: args.limit]

    print(f"{len(done)} already described, {len(todo)} to do")
    tokens = 0
    started = time.time()

    for n, row in enumerate(todo, 1):
        path = IMAGES / row["image"]
        try:
            parsed, usage = vision.describe_catalogue_photo(path.read_bytes())
            decoration = parsed.decorations[0] if parsed.decorations else None
            if decoration is None:
                raise ValueError("the model described nothing in the photo")
            done[row["code"]] = {
                "code": row["code"],
                "pdf_page": row["pdf_page"],
                "image": row["image"],
                "match": row["match"],
                "attributes": decoration.model_dump(),
                "text": vision.as_text(decoration),
                "tokens": usage["total_tokens"],
            }
            tokens += usage["total_tokens"]
        except Exception as exc:
            done[row["code"]] = {
                "code": row["code"],
                "image": row["image"],
                "error": f"{type(exc).__name__}: {exc}",
            }

        OUT.write_text(json.dumps(done, indent=1, ensure_ascii=False), encoding="utf-8")

        if n % 25 == 0 or n == len(todo):
            rate = n / max(time.time() - started, 1)
            left = (len(todo) - n) / max(rate, 0.001)
            print(f"  {n}/{len(todo)}  {tokens:,} tokens  ~{left / 60:.0f} min left")

    failed = [row for row in done.values() if row.get("error")]
    print(f"\n{len(done) - len(failed)} described, {len(failed)} failed, {tokens:,} tokens")
    for row in failed[:10]:
        print(f"  {row['code']}: {row['error']}")
    print(f"-> {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
