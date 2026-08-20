"""Extract the product catalogue: every code, its real size where one is printed, and where
it lives.

    python scripts/extract_catalog.py "ac5-source/CHRISTMAS BKK BOOK2024 .pdf (12).pdf"

The catalogue PDF carries real text, so codes and dimensions come out exactly rather than
through OCR. That matters: NonGoals.md 7 and 8 forbid guessing a product code or a size,
because a wrong code means the customer orders the wrong thing and the shop wears it.

Codes with no printed size are kept with `size: null`. Roughly a third of the catalogue is
like that, and a record saying "no size printed" is the honest answer — dropping those rows
would make the table look complete while quietly hiding the products it cannot size.

There is no per-code product name. An earlier version guessed one by picking the nearest
large text, which paired code 017-06 with "Dimension" — the caption of a size chart 364 pt
away — and, because product names and section headings are both set at 30 pt, swallowed
"Norwood Fir" into the heading instead. A guessed name in a data file is indistinguishable
from a known one, which is the thing NonGoals.md 7 is about. What is recorded instead is the
exact heading text printed on the page, which carries the same words without claiming which
code they belong to.

This is phase A of Product.md 8.1 — the code → size table, which is all 8.2 needs to put true
millimetres into the prompt. It deliberately does not decide which photo belongs to which
code: the bauble pages carry forty images each and the price ribbons are images too, so a
nearest-neighbour rule would be confidently wrong often. That association is phase B, needed
only for 8.3, and it has to be verified rather than guessed — the same reason there is no
per-code name here.
"""

import argparse
import json
import re
import sys
from collections import Counter

import fitz

from _bootstrap import ROOT  # noqa: E402

from backend.services.catalog import parse_size  # noqa: E402

# 71016-1/DG/66 and 74026-1/D are real codes; the suffix is part of the product identity.
# 26022-2FK is the same thing with no slash (a finish letter glued straight onto the number,
# 2026 book) — without the bare-letter branch this reads as plain 26022-2, which collided
# with an unrelated real 26022-2 elsewhere on the same page and lost "flocked" silently.
CODE = re.compile(r"\b(\d{3,5}-\d{1,3}(?:/[A-Za-z0-9]+)*(?:[A-Z]{1,3}\b)?)")
SIZE_AFTER_CODE = re.compile(
    r"\b\d{3,5}-\d{1,3}(?:/[A-Za-z0-9]+)*(?:[A-Z]{1,3}\b)?\s*\(([^)]{1,40})\)"
)


def spans(page):
    for block in page.get_text("dict")["blocks"]:
        if block["type"] != 0:
            continue
        for line in block["lines"]:
            for span in line["spans"]:
                text = span["text"].strip()
                if text:
                    yield text, span["size"], span["bbox"]


def extract(pdf_path, pages=None, book=None):
    """`pages`, if given, is a (start, end) 1-based inclusive pair restricting which pages of
    the PDF are scanned — for a source file that bundles several catalogue editions into one
    PDF, so only the pages belonging to the edition being ingested are read. `book` tags every
    row, so a catalogue merged in later can be told apart from the one already in
    catalog/products.json (which has no `book` field at all)."""
    doc = fitz.open(pdf_path)
    rows, unparsed = [], []
    seen = set()
    current_section = None

    page_range = range(doc.page_count)
    if pages:
        start, end = pages
        page_range = range(start - 1, min(end, doc.page_count))

    for index in page_range:
        page = doc[index]
        page_spans = list(spans(page))

        # Every large piece of text printed on this page, exactly as set. Product names and
        # section headings are both 30 pt here, so this deliberately does not try to tell
        # them apart — it is context to search on, not a claim about any one code.
        page_headings = [t for t, s, _ in page_spans if s >= 28]

        # a section heading is printed once, on its opening page, and the following pages
        # belong to it silently — carry it forward or four fifths of the table has no category
        if page_headings:
            current_section = " ".join(page_headings)
        section = current_section

        for text, size, bbox in page_spans:
            if size >= 28:
                continue
            sizes = SIZE_AFTER_CODE.findall(text)
            for position, match in enumerate(CODE.finditer(text)):
                code = match.group(1)
                raw = sizes[position] if position < len(sizes) else None
                parsed = parse_size(raw) if raw else None

                if raw and parsed is None:
                    unparsed.append((index + 1, code, raw))

                rows.append({
                    "code": code,
                    "size_raw": " ".join(raw.split()) if raw else None,
                    "size": parsed,
                    "section": section,
                    "page_headings": page_headings,
                    "pdf_page": index + 1,
                    "bbox": [round(v, 1) for v in bbox],
                    "duplicate": code in seen,
                    "book": book,
                })
                seen.add(code)

    return rows, unparsed


def main():
    parser = argparse.ArgumentParser(description="Extract product codes and sizes from the catalogue PDF.")
    parser.add_argument("pdf")
    parser.add_argument("--out", default="catalog/products.json")
    parser.add_argument("--pages", help="1-based inclusive range, e.g. 1:96")
    parser.add_argument("--book", help="tag every row with this edition label")
    args = parser.parse_args()

    pages = None
    if args.pages:
        start, end = args.pages.split(":")
        pages = (int(start), int(end))

    rows, unparsed = extract(args.pdf, pages=pages, book=args.book)

    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rows, indent=1, ensure_ascii=False), encoding="utf-8")

    codes = {r["code"] for r in rows}
    with_size = [r for r in rows if r["size"]]
    no_size_printed = [r for r in rows if r["size_raw"] is None]

    print(f"{len(rows)} labels, {len(codes)} distinct codes -> {out}")
    print(f"  size parsed        : {len(with_size)}")
    print(f"  no size printed    : {len(no_size_printed)}  (recorded as null, not dropped)")
    print(f"  size printed but unreadable: {len(unparsed)}")

    units = Counter(r["size"]["unit_printed"] for r in with_size)
    print(f"  units              : {dict(units.most_common())}")

    if unparsed:
        print("\nsizes that were printed but could not be read:")
        for page_no, code, raw in unparsed[:20]:
            print(f"  page {page_no}: {code} {raw!r}")
        if len(unparsed) > 20:
            print(f"  ... and {len(unparsed) - 20} more")

    return 0


if __name__ == "__main__":
    sys.exit(main())
