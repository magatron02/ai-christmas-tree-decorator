"""Seed a Thai name for every colour photo, once (issue #14).

    python scripts/name_colours.py            # resumes; skips photos already named
    python scripts/name_colours.py --limit 20

One billed vision call per colour photo. Writes into the shop overlay after every photo (via
catalog_admin.set_colour_name, the same read-modify-write path a shop's own correction uses),
so an interruption costs nothing already paid for and a crash partway through only leaves the
remaining photos unnamed — which is a valid state (issue #14 AC: falls back to position).

The existing per-code descriptions (catalog/descriptions.json) cannot supply these names: they
describe a whole colour strip in one photo — one primary colour plus a list of others — so
they cannot say which colour photo is which, and only 118 of the 264 split codes have one at
all. This runs the cheap vision model once per PHOTO instead.
"""

import argparse
import sys
import time

from _bootstrap import ROOT

from backend.services import catalog, catalog_admin, vision  # noqa: E402

IMAGES = ROOT / "catalog" / "images"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, help="stop after this many new names")
    args = parser.parse_args()

    todo = []
    for code, filenames in catalog.split_codes().items():
        for filename in filenames:
            if catalog.colour_name(code, filename) is None:
                todo.append((code, filename))

    already = sum(len(v) for v in catalog.split_codes().values()) - len(todo)
    if args.limit:
        todo = todo[: args.limit]
    print(f"{already} already named, {len(todo)} to do")

    tokens, failed = 0, []
    started = time.time()
    for n, (code, filename) in enumerate(todo, 1):
        path = IMAGES / "variants" / filename
        if not path.is_file():
            failed.append((code, filename, "file not found"))
            continue
        try:
            parsed, usage = vision.name_colour(path.read_bytes())
            catalog_admin.set_colour_name(code, filename, parsed.name_th)
            tokens += usage["total_tokens"]
        except Exception as exc:
            failed.append((code, filename, f"{type(exc).__name__}: {exc}"))

        if n % 50 == 0 or n == len(todo):
            rate = n / max(time.time() - started, 1)
            left = (len(todo) - n) / max(rate, 0.001)
            print(f"  {n}/{len(todo)}  {tokens:,} tokens  ~{left / 60:.0f} min left")

    print(f"\n{len(todo) - len(failed)} named, {len(failed)} failed, {tokens:,} tokens")
    for code, filename, why in failed[:10]:
        print(f"  {code} {filename}: {why}")
    if len(failed) > 10:
        print(f"  … and {len(failed) - 10} more")
    print("\nrerun this script to retry whatever failed — it only ever names what is missing")
    return 0


if __name__ == "__main__":
    sys.exit(main())
