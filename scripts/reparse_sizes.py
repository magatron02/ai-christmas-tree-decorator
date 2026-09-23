"""Re-derive every product's parsed `size` from the `size_raw` the book already printed.

The parsed size is derived data: extract_catalog.py runs catalog.parse_size() over the book's
own text once, at import, and stores the result. So a fix to the parser only reaches products
that are imported after it — every row already in products.json keeps the shape the old parser
gave it, however wrong.

That is what this script is for. It invents nothing and reads nothing new: `size_raw` is the
book's own words, already in the base, and this re-runs the same parser extract_catalog.py
would run over it today. Rows whose parse is unchanged are left exactly as they are.

    python scripts/reparse_sizes.py            # show what would change
    python scripts/reparse_sizes.py --write    # write it
"""

import argparse
import json

from _bootstrap import ROOT  # noqa: F401  (sys.path + .env, before backend imports)

from backend import config
from backend.services import catalog


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="write the changes to disk")
    args = parser.parse_args()

    path = config.CATALOG_PATH
    rows = json.loads(path.read_text(encoding="utf-8"))

    changed = []
    for row in rows:
        fresh = catalog.parse_size(row.get("size_raw") or "")
        if fresh != row.get("size"):
            changed.append((row["code"], row.get("size_raw"), row.get("size"), fresh))
            if args.write:
                row["size"] = fresh

    for code, raw, before, after in changed:
        print(f"{code:14} {raw!r}\n    was {before}\n    now {after}")
    print(f"\n{len(changed)} of {len(rows)} rows differ")

    if not changed:
        return 0
    if not args.write:
        print("dry run — pass --write to apply")
        return 0

    # indent=1, exactly as extract_catalog.py writes it — a different indent would rewrite all
    # 829 rows and bury five real changes in a fifteen-thousand-line diff
    path.write_text(json.dumps(rows, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"written to {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
