"""Ask of every catalogue crop: is this a product, or something else on the page?

    python scripts/audit_crops.py               # resumes; skips what is already judged
    python scripts/audit_crops.py --limit 20    # try it on a few first
    python scripts/audit_crops.py --retry-failed

One billed vision call per crop. Writes after every crop, so an interruption costs nothing
already paid for.

Why this exists as a separate pass from describe_catalog.py: that one was told "describe the
product shown", which presupposes there is one. Asked that way the model called a printed
page-number badge "an orange circular decoration with the number 44" — a confident description
of something that is not for sale, which is exactly how page numbers ended up in the picker.
The question has to be asked in a form where "there is no product here" is an easy answer.

Only crops that are actually reachable in the picker are audited: a crop already hidden for
being shared by several codes is hidden whatever it depicts, so paying to describe it buys
nothing. Output is catalog/crop_audit.json, read by catalog.crop_is_not_a_product().
"""

import argparse
import json
import sys
import time

from _bootstrap import ROOT

from backend.services import catalog, vision  # noqa: E402

IMAGES = ROOT / "catalog" / "images"
OUT = ROOT / "catalog" / "crop_audit.json"


def load_done():
    if OUT.is_file():
        return json.loads(OUT.read_text(encoding="utf-8"))
    return {}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, help="stop after this many new verdicts")
    parser.add_argument("--retry-failed", action="store_true")
    parser.add_argument(
        "--all", action="store_true",
        help="also audit crops already hidden for being shared (normally pointless)",
    )
    args = parser.parse_args()

    codes = [row["code"] for row in catalog._rows() if catalog.image_for(row["code"])]
    if not args.all:
        codes = [code for code in codes if not catalog.crop_is_ambiguous(code)]

    done = load_done()
    todo = []
    for code in codes:
        seen = done.get(code)
        if seen and not seen.get("error"):
            continue
        if seen and seen.get("error") and not args.retry_failed:
            continue
        todo.append(code)

    if args.limit:
        todo = todo[: args.limit]

    print(f"{len(done)} already judged, {len(todo)} to do")
    tokens = 0
    started = time.time()

    for n, code in enumerate(todo, 1):
        path = IMAGES / catalog.image_for(code)
        try:
            verdict, usage = vision.audit_crop(path.read_bytes())
            done[code] = {
                "code": code,
                "image": catalog.image_for(code),
                "is_product": verdict.is_product,
                "crop_kind": verdict.crop_kind,
                "why": verdict.why,
                "tokens": usage["total_tokens"],
            }
            tokens += usage["total_tokens"]
        except Exception as exc:
            done[code] = {"code": code, "error": f"{type(exc).__name__}: {exc}"}

        OUT.write_text(json.dumps(done, indent=1, ensure_ascii=False), encoding="utf-8")

        if n % 25 == 0 or n == len(todo):
            rate = n / max(time.time() - started, 1e-9)
            left = (len(todo) - n) / rate if rate else 0
            print(f"  {n}/{len(todo)}  {tokens:,} tokens  ~{left/60:.0f} min left")

    judged = [v for v in done.values() if "error" in v or "is_product" in v]
    rejected = [v for v in judged if not v.get("error") and not v["is_product"]]
    failed = [v for v in judged if v.get("error")]

    print(f"\n{len(judged)} judged -> {OUT}")
    print(f"  not a product : {len(rejected)}")
    print(f"  failed        : {len(failed)}")
    if rejected:
        from collections import Counter
        for kind, count in Counter(v["crop_kind"] for v in rejected).most_common():
            print(f"    {kind:14} {count}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
