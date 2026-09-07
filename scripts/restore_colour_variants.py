"""One-time restore of the colour-split mapping lost on 2026-08-19 (issue #13).

The re-import that day reduced catalog/variants.json from 264 codes to {}, orphaning 919
colour photographs that are still on disk. A backup of the catalogue from just before that
re-import — catalog-backup-2026-08-19-before-newbook-rebuild/variants.json — still has the
original 264-code mapping. This writes it into the shop overlay, code by code, the same way
scripts/split_colourways.py now does, so a future re-import cannot repeat the loss.

A restored code that no longer appears in the current book is not skipped: it is written the
same as any other, and shows up afterward as a kept, flagged orphan (issue #9) rather than
being silently dropped a second time.

    python scripts/restore_colour_variants.py             # write it
    python scripts/restore_colour_variants.py --dry-run    # report what would be written

Safe to re-run: writing the same mapping twice is a no-op the second time.
"""

import argparse
import json
import sys

from _bootstrap import ROOT

from backend.services import catalog  # noqa: E402

BACKUP = ROOT / "catalog-backup-2026-08-19-before-newbook-rebuild" / "variants.json"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not BACKUP.is_file():
        print(f"backup not found: {BACKUP}")
        return 1

    mapping = json.loads(BACKUP.read_text(encoding="utf-8"))
    known = set(catalog._by_code())
    already = catalog.split_codes()

    restored, unchanged, orphaned = 0, 0, 0
    for code, names in mapping.items():
        if already.get(code) == names:
            unchanged += 1
            continue
        if code not in known:
            orphaned += 1
        if not args.dry_run:
            catalog.set_colour_split(code, names)
        restored += 1

    if not args.dry_run:
        catalog.refresh()

    print(f"{len(mapping)} codes in the backup")
    print(f"{restored} written{' (dry run)' if args.dry_run else ''}, {unchanged} already matched")
    print(f"{orphaned} of those are not in the current book — kept as orphans (issue #9)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
