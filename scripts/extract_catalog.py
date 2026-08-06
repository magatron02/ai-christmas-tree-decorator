"""Extract the product catalogue: every code, its real size where one is printed, and where
it lives.

    python scripts/extract_catalog.py "ac5-source/CHRISTMAS BKK BOOK2024 .pdf (12).pdf"

The catalogue PDF carries real text, so codes and dimensions come out exactly rather than
through OCR. That matters: NonGoals.md 7 and 8 forbid guessing a product code or a size,
because a wrong code means the customer orders the wrong thing and the shop wears it.

Codes with no printed size are kept with `size: null`. Roughly a third of the catalogue is
like that, and a record saying "no size printed" is the honest answer — dropping those rows
would make the table look complete while quietly hiding the products it cannot size.

This is phase A of Product.md 8.1 — the code → size table, which is all 8.2 needs to put true
millimetres into the prompt. It deliberately does not decide which photo belongs to which
code: the bauble pages carry forty images each and the price ribbons are images too, so a
nearest-neighbour rule would be confidently wrong often. That association is phase B, needed
only for 8.3, and it has to be verified rather than guessed.
"""

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

import fitz

ROOT = Path(__file__).resolve().parent.parent

# 71016-1/DG/66 and 74026-1/D are real codes; the suffix is part of the product identity
CODE = re.compile(r"\b(\d{3,5}-\d{1,3}(?:/[A-Za-z0-9]+)*)")
SIZE_AFTER_CODE = re.compile(
    r"\b\d{3,5}-\d{1,3}(?:/[A-Za-z0-9]+)*\s*\(([^)]{1,40})\)"
)

FEET = re.compile(r"([\d.]+)\s*Ft", re.I)
INCHES = re.compile(r"([\d.]+)\s*in(?:c|ch|ches)?\b", re.I)
SERIES = re.compile(r"([\d.]+(?:\s*[x×]\s*[\d.]+)+)\s*(cm|mm|in(?:c|ch)?)", re.I)
CM = re.compile(r"([\d.]+)\s*cm", re.I)
MM = re.compile(r"([\d.]+)\s*mm", re.I)
METRES = re.compile(r"([\d.]+)\s*m\.", re.I)

MM_PER_FOOT = 304.8
MM_PER_INCH = 25.4


def parse_size(raw):
    """'5 Ft.' -> height 1524 mm · '80 mm.' -> diameter 80 · '12 inc.' -> 305 mm ·
    '29 x 150 cm.' -> 290 x 1500 mm. Anything unrecognised returns None rather than a guess."""
    text = " ".join(raw.split())

    if match := SERIES.search(text):
        parts = [float(p) for p in re.split(r"[x×]", match.group(1))]
        unit = match.group(2).lower()
        unit = "inch" if unit.startswith("in") else unit
        factor = 10 if unit == "cm" else MM_PER_INCH if unit == "inch" else 1
        return {"dimensions_mm": [round(p * factor) for p in parts], "unit_printed": unit}

    if match := FEET.search(text):
        feet = float(match.group(1))
        return {"feet": feet, "height_mm": round(feet * MM_PER_FOOT), "unit_printed": "ft"}

    if match := INCHES.search(text):
        inches = float(match.group(1))
        return {"inches": inches, "size_mm": round(inches * MM_PER_INCH), "unit_printed": "inch"}

    if match := MM.search(text):
        return {"diameter_mm": float(match.group(1)), "unit_printed": "mm"}

    if match := CM.search(text):
        return {"diameter_mm": round(float(match.group(1)) * 10), "unit_printed": "cm"}

    if match := METRES.search(text):
        return {"size_mm": round(float(match.group(1)) * 1000), "unit_printed": "m"}

    return None


def spans(page):
    for block in page.get_text("dict")["blocks"]:
        if block["type"] != 0:
            continue
        for line in block["lines"]:
            for span in line["spans"]:
                text = span["text"].strip()
                if text:
                    yield text, span["size"], span["bbox"]


def centre(bbox):
    return ((bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2)


def gap(a, b):
    (ax, ay), (bx, by) = centre(a), centre(b)
    return ((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5


def extract(pdf_path):
    doc = fitz.open(pdf_path)
    rows, unparsed = [], []
    seen = set()
    current_section = None

    for index in range(doc.page_count):
        page = doc[index]
        page_spans = list(spans(page))

        # a section heading is printed once, on its opening page, and the following pages
        # belong to it silently — carry it forward or four fifths of the table has no category
        heading = " ".join(t for t, s, _ in page_spans if s >= 28) or None
        if heading:
            current_section = heading
        section = current_section
        # product names are set larger than the code labels but smaller than section headings
        names = [(t, b) for t, s, b in page_spans if 17 <= s < 28 and not CODE.search(t)]

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

                name, name_gap = None, None
                if names:
                    name, name_bbox = min(names, key=lambda n: gap(bbox, n[1]))
                    name_gap = round(gap(bbox, name_bbox), 1)

                rows.append({
                    "code": code,
                    "size_raw": " ".join(raw.split()) if raw else None,
                    "size": parsed,
                    "name": name,
                    # how far the guessed name sat from the code, so phase B can tell a
                    # confident pairing from a coincidence instead of trusting all of them
                    "name_gap_pt": name_gap,
                    "section": section,
                    "pdf_page": index + 1,
                    "bbox": [round(v, 1) for v in bbox],
                    "duplicate": code in seen,
                })
                seen.add(code)

    return rows, unparsed


def main():
    parser = argparse.ArgumentParser(description="Extract product codes and sizes from the catalogue PDF.")
    parser.add_argument("pdf")
    parser.add_argument("--out", default="catalog/products.json")
    args = parser.parse_args()

    rows, unparsed = extract(args.pdf)

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
