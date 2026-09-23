"""Local, one-off review tool for the candidate photos scripts/stage_missing_photos.py staged.

    python scripts/review_missing_photos.py --staged <staging dir>

Opens a page at http://localhost:8010 — one code at a time, the candidate crop next to the
whole catalogue page with its box drawn in red, so a person can tell at a glance whether the
pairing grabbed the right product (see stage_missing_photos.py's docstring for why this can't
be trusted unattended: ~34% wrong even in the highest-confidence tier, measured 2026-09-23).

"รับ" copies the candidate crop straight into catalog/images/<code>.png — the exact path
catalog/product_images.json already points at, so nothing else needs to change for it to show
up in the picker. "ปฏิเสธ" just records the code as reviewed and skipped; nothing is written.
Decisions persist in <staging dir>/decisions.json, so closing this and coming back later
resumes where it left off rather than re-asking about codes already judged.

This is throwaway tooling for one catalogue-photo backfill, not part of the running app —
run it, use it, close it; it does not touch backend/main.py or any port the shop's app uses.
"""

import argparse
import io
import json
import shutil
import sys
from pathlib import Path

import fitz
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageDraw
import uvicorn

from _bootstrap import ROOT  # noqa: E402

sys.path.insert(0, str(ROOT / "scripts"))
import build_product_index as bpi  # noqa: E402

from backend.services import catalog  # noqa: E402

IMAGES_DIR = ROOT / "catalog" / "images"
CONTEXT_MAX_PX = 1400


def _images_on(page):
    """Like build_product_index.products_on(), minus its MAX_ASPECT cutoff — which exists
    there to drop wide flat price ribbons, but a garland is legitimately photographed as a
    tall narrow strip and gets dropped by that same cutoff for being "too elongated" the other
    way. On a garland page (2026-09-23: code 60901-3, "Christmas Garlands") that cutoff kept
    only 1 of 16 real product photos, so the candidate picker had nothing else to offer even
    though the pairing was wrong. Kept separate from products_on() itself (shared with the
    production import scripts) rather than loosening MAX_ASPECT there and risking price
    ribbons flooding back into every other page's candidates."""
    page_area = page.rect.width * page.rect.height
    out = []
    for info in page.get_image_info(xrefs=True):
        x0, y0, x1, y1 = info["bbox"]
        width, height = x1 - x0, y1 - y0
        if width * height > page_area * bpi.MAX_AREA_FRACTION:
            continue                                   # the page background
        if min(width, height) < bpi.MIN_SIDE_PT:
            continue                                   # icons, hairlines
        out.append(info)
    return out


def _ranked_candidates(label_bbox, products, limit=10):
    """Every product photo on the page, nearest label first — not just whichever one
    build_product_index.pair() would pick. pair() commits to a single rule (nearest "above"
    wins outright over everything else, no matter how much nearer a "beside" or second "above"
    candidate is), which is exactly the failure mode this review tool exists to catch: a small
    detail/texture swatch sitting above the label out-competes the real product photo, whether
    that real photo is beside the label (25022-5) or simply a second, farther "above" candidate
    (06072-3, 2026-09-23). Ranking every candidate by plain distance and letting a person pick
    covers both without hard-coding a rule per failure pattern discovered.

    Duplicated from pair()'s classification logic rather than editing pair() itself, since that
    function is shared with the production catalogue-import scripts and this is throwaway
    review tooling for one photo backfill."""
    lx = (label_bbox[0] + label_bbox[2]) / 2
    ly = (label_bbox[1] + label_bbox[3]) / 2
    ranked = []
    for info in products:
        x0, y0, x1, y1 = info["bbox"]
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        distance = ((cx - lx) ** 2 + (cy - ly) ** 2) ** 0.5
        if y1 <= ly:
            rule = "above"
        elif y0 - 40 <= ly <= y1 + 40:
            rule = "beside"
        else:
            rule = "other"
        ranked.append((distance, rule, info))
    ranked.sort(key=lambda t: t[0])
    return ranked[:limit]

PAGE = """<!doctype html>
<html lang="th"><head><meta charset="utf-8">
<title>ตรวจรูปสินค้าที่ดึงจาก PDF</title>
<style>
  body { font-family: system-ui, sans-serif; background: #faf3e8; margin: 0; padding: 24px; }
  .top { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 16px; }
  h1 { font-size: 1.1rem; margin: 0; }
  .stats { color: #555; font-size: 0.9rem; }
  .card { background: #fff; border-radius: 12px; padding: 20px; max-width: 1100px; }
  .row { display: flex; gap: 24px; flex-wrap: wrap; }
  .col { flex: 1; min-width: 320px; }
  .col h3 { margin: 0 0 8px; font-size: 0.85rem; color: #777; font-weight: 600; }
  img.crop { max-width: 100%; max-height: 320px; border: 1px solid #ddd; background: repeating-conic-gradient(#eee 0% 25%, #fff 0% 50%) 0 0/16px 16px; }
  .no-old { max-width: 100%; height: 160px; border: 1px dashed #ccc; border-radius: 6px; display: flex; align-items: center; justify-content: center; color: #999; font-size: 0.9rem; }
  img.context { max-width: 100%; border: 1px solid #ddd; }
  .meta { margin-top: 12px; font-size: 0.9rem; color: #333; line-height: 1.6; }
  .meta b { color: #000; }
  .tier { display: inline-block; padding: 2px 8px; border-radius: 6px; font-size: 0.8rem; }
  .tier.directly_above { background: #dcf5df; color: #1a6b2a; }
  .tier.above_far, .tier.beside { background: #fff3cd; color: #8a6400; }
  .tier.no_rule_fitted { background: #fde0e0; color: #a02020; }
  .btns { margin-top: 20px; display: flex; gap: 12px; }
  button { font-size: 1rem; padding: 10px 20px; border-radius: 8px; border: 1px solid #ccc; cursor: pointer; background: #f4f4f4; }
  button.accept { background: #1a6b2a; color: #fff; border: none; }
  button.reject { background: #a02020; color: #fff; border: none; }
  .source-note { margin-top: 8px; font-size: 0.85rem; color: #666; }
  .done { text-align: center; padding: 60px 20px; color: #555; }
  .candidates { margin-top: 16px; }
  .candidates h3 { margin: 0 0 8px; font-size: 0.85rem; color: #777; font-weight: 600; }
  .cand-strip { display: flex; gap: 10px; flex-wrap: wrap; }
  .cand-thumb { width: 76px; height: 76px; object-fit: contain; border: 2px solid #ddd; border-radius: 6px; cursor: pointer; background: repeating-conic-gradient(#eee 0% 25%, #fff 0% 50%) 0 0/12px 12px; }
  .cand-thumb.selected { border-color: #1a6b2a; box-shadow: 0 0 0 2px #dcf5df; }
  .cand-thumb.original { border-color: #88a; }
</style></head>
<body>
<div class="top">
  <h1>ตรวจรูปสินค้าที่ดึงจาก PDF ก่อนเข้า catalog จริง</h1>
  <div class="stats" id="stats"></div>
</div>
<div id="root"></div>
<script>
async function refreshStats() {
  const r = await fetch('/api/stats');
  const s = await r.json();
  document.getElementById('stats').textContent =
    `รับแล้ว ${s.accepted} · ปฏิเสธ ${s.rejected} · เหลือ ${s.remaining} จาก ${s.total}`;
}
async function loadNext() {
  await refreshStats();
  const r = await fetch('/api/next');
  const root = document.getElementById('root');
  if (r.status === 204) {
    root.innerHTML = '<div class="done">ตรวจครบทุกโค้ดแล้ว 🎄</div>';
    return;
  }
  const item = await r.json();
  const oldPhotoUrl = `/api/old-photo/${encodeURIComponent(item.code)}`;
  window._selectedIndex = -1;  // -1 = the original book pairing shown by default
  root.innerHTML = `
    <div class="card">
      <div class="row">
        <div class="col">
          <h3>รูปเดิม (ที่ระบบโชว์อยู่ตอนนี้)</h3>
          <img class="crop" id="old-img" src="${oldPhotoUrl}"
               onerror="this.replaceWith(Object.assign(document.createElement('div'),{className:'no-old', textContent:'ไม่พบรูปเดิม'}))">
        </div>
        <div class="col">
          <h3>รูปที่จะเอาเข้า (crop)</h3>
          <img class="crop" id="new-crop" src="/files/${item.crop}">
        </div>
        <div class="col">
          <h3>ตำแหน่งบนหน้า PDF จริง (กรอบแดง = ตัวที่จะเอาเข้า)</h3>
          <img class="context" id="new-context" src="/files/${item.context}">
        </div>
      </div>
      <div class="meta">
        <b>${item.code}</b> — ${item.label ?? ''}<br>
        หมวด: ${item.section ?? '-'} · หน้า PDF: ${item.pdf_page} ·
        กติกาจับคู่: <span class="tier ${item.match}">${item.match}</span> (${item.rule}, ${item.gap_pt ?? '-'} pt)
      </div>
      <div class="candidates">
        <h3>รูปอื่นบนหน้านี้ที่อยู่ใกล้ๆ (คลิกเพื่อลองแทนที่)</h3>
        <div class="cand-strip" id="cand-strip">กำลังโหลด...</div>
      </div>
      <div class="btns">
        <button class="accept" onclick="decide('${item.code}','accept')">✓ รับรูปนี้</button>
        <button class="reject" onclick="decide('${item.code}','reject')">✗ ไม่ใช่ ข้ามไป</button>
      </div>
      <div class="source-note" id="source-note"></div>
    </div>`;
  loadCandidates(item.code);
}
async function loadCandidates(code) {
  const strip = document.getElementById('cand-strip');
  const r = await fetch(`/api/candidates/${encodeURIComponent(code)}`);
  const cands = await r.json();
  if (!cands.length) {
    strip.textContent = 'ไม่มีรูปอื่นใกล้ๆ บนหน้านี้';
    return;
  }
  strip.innerHTML = cands.map(c => `
    <img class="cand-thumb" id="cand-${c.index}"
         src="/api/candidate-crop/${encodeURIComponent(code)}?index=${c.index}"
         title="${c.rule}, ${c.distance} pt"
         onclick="selectCandidate('${code}', ${c.index})">
  `).join('');
}
function selectCandidate(code, index) {
  document.getElementById('new-crop').src =
    `/api/candidate-crop/${encodeURIComponent(code)}?index=${index}&t=${Date.now()}`;
  document.getElementById('new-context').src =
    `/api/candidate-context/${encodeURIComponent(code)}?index=${index}&t=${Date.now()}`;
  window._selectedIndex = index;
  document.querySelectorAll('.cand-thumb').forEach(el => el.classList.remove('selected'));
  document.getElementById(`cand-${index}`).classList.add('selected');
  document.getElementById('source-note').textContent =
    'กำลังดูตัวเลือกที่เลือกไว้ — กด "รับรูปนี้" จะเอาตัวนี้เข้าแทน';
}
async function decide(code, decision) {
  const index = window._selectedIndex ?? -1;
  await fetch(`/api/decide/${encodeURIComponent(code)}?decision=${decision}&index=${index}`, { method: 'POST' });
  loadNext();
}
loadNext();
</script>
</body></html>
"""


def build_app(staged: Path, pdf_path: str):
    manifest = json.loads((staged / "manifest.json").read_text(encoding="utf-8"))
    by_code = {m["code"]: m for m in manifest}
    decisions_path = staged / "decisions.json"
    decisions = json.loads(decisions_path.read_text(encoding="utf-8")) if decisions_path.is_file() else {}
    doc = fitz.open(pdf_path)

    _candidate_cache = {}  # code -> (page_png, scale, ranked list) — rendering a page is the slow part

    def _candidates_for(code):
        if code in _candidate_cache:
            return _candidate_cache[code]
        item = by_code.get(code)
        if item is None:
            return None
        page = doc[item["pdf_page"] - 1]
        pix = page.get_pixmap(dpi=200)
        page_png = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        scale = pix.width / page.rect.width
        products = _images_on(page)
        label_bbox = next((bbox for c, bbox in bpi.labels_on(page) if c == code), None)
        if label_bbox is None:
            return None
        ranked = _ranked_candidates(label_bbox, products)
        result = (page_png, scale, ranked, label_bbox)
        _candidate_cache[code] = result
        return result

    def _render_candidate(code, index):
        """(crop, page-with-box) for the Nth-nearest candidate to code's label, or (None, None)."""
        found = _candidates_for(code)
        if found is None or not (0 <= index < len(found[2])):
            return None, None
        page_png, scale, ranked, label_bbox = found
        _distance, _rule, info = ranked[index]

        crop = bpi.crop(page_png, info["bbox"], scale)

        context = page_png.copy()
        context.thumbnail((CONTEXT_MAX_PX, CONTEXT_MAX_PX))
        ctx_scale = context.width / page_png.width
        draw = ImageDraw.Draw(context)
        x0, y0, x1, y1 = (v * scale * ctx_scale for v in info["bbox"])
        draw.rectangle([x0, y0, x1, y1], outline=(220, 30, 30), width=4)
        lx0, ly0, lx1, ly1 = (v * scale * ctx_scale for v in label_bbox)
        draw.rectangle([lx0, ly0, lx1, ly1], outline=(30, 90, 220), width=4)

        return crop, context.convert("RGB")

    def save_decisions():
        decisions_path.write_text(json.dumps(decisions, indent=1, ensure_ascii=False), encoding="utf-8")

    app = FastAPI()
    app.mount("/files", StaticFiles(directory=staged), name="files")

    @app.get("/", response_class=HTMLResponse)
    def index():
        return PAGE

    @app.get("/api/stats")
    def stats():
        accepted = sum(1 for d in decisions.values() if d == "accept")
        rejected = sum(1 for d in decisions.values() if d == "reject")
        return {
            "total": len(manifest), "accepted": accepted, "rejected": rejected,
            "remaining": len(manifest) - len(decisions),
        }

    @app.get("/api/next")
    def next_item():
        for m in manifest:
            if m["code"] not in decisions:
                return m
        return JSONResponse(status_code=204, content=None)

    @app.get("/api/old-photo/{code:path}")
    def old_photo(code: str):
        """Whatever the live app would currently show for this code — a shop-photographed
        override (data/shop_photos/), since a book crop can't exist here (this code is only in
        the review queue because catalog/images/<image> is missing on disk). Lets a reviewer
        see that the shop already deliberately set something before a book crop replaces it."""
        path = catalog.image_path(code)
        if path is None or not path.is_file():
            raise HTTPException(404, "ไม่มีรูปเดิม")
        return FileResponse(path)

    @app.get("/api/candidates/{code:path}")
    def candidates(code: str):
        found = _candidates_for(code)
        if found is None:
            return []
        _page_png, _scale, ranked, _label_bbox = found
        return [
            {"index": i, "rule": rule, "distance": round(distance, 1)}
            for i, (distance, rule, _info) in enumerate(ranked)
        ]

    @app.get("/api/candidate-crop/{code:path}")
    def candidate_crop(code: str, index: int):
        crop, _context = _render_candidate(code, index)
        if crop is None:
            raise HTTPException(404, "ไม่มีตัวเลือกนี้")
        buf = io.BytesIO()
        crop.save(buf, format="PNG")
        return Response(content=buf.getvalue(), media_type="image/png")

    @app.get("/api/candidate-context/{code:path}")
    def candidate_context(code: str, index: int):
        _crop, context = _render_candidate(code, index)
        if context is None:
            raise HTTPException(404, "ไม่มีตัวเลือกนี้")
        buf = io.BytesIO()
        context.save(buf, format="JPEG", quality=85)
        return Response(content=buf.getvalue(), media_type="image/jpeg")

    @app.post("/api/decide/{code:path}")
    def decide(code: str, decision: str, index: int = -1):
        """`index` -1 (default) means the original book pairing staged by
        stage_missing_photos.py; 0+ means the reviewer picked that ranked candidate instead
        (see _ranked_candidates) — accepting always saves whichever one is on screen."""
        if decision not in ("accept", "reject"):
            raise HTTPException(400, "decision ต้องเป็น accept หรือ reject")
        item = by_code.get(code)
        if item is None:
            raise HTTPException(404, f"ไม่รู้จักโค้ด {code}")

        if decision == "accept":
            dest = IMAGES_DIR / item["image"]
            if dest.is_file():
                # someone else already filled this in since staging — don't clobber it blind
                raise HTTPException(409, f"{item['image']} มีไฟล์อยู่แล้ว ไม่เขียนทับ")
            IMAGES_DIR.mkdir(parents=True, exist_ok=True)
            if index >= 0:
                crop, _context = _render_candidate(code, index)
                if crop is None:
                    raise HTTPException(404, "ตัวเลือกนี้หายไปแล้ว")
                crop.save(dest)
            else:
                shutil.copyfile(staged / item["crop"], dest)

        decisions[code] = decision
        save_decisions()
        return {"code": code, "decision": decision}

    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--staged", required=True)
    parser.add_argument("--pdf", required=True, help="the same catalogue PDF stage_missing_photos.py used")
    parser.add_argument("--port", type=int, default=8010)
    args = parser.parse_args()

    staged = Path(args.staged)
    if not (staged / "manifest.json").is_file():
        print(f"no manifest.json in {staged} — run stage_missing_photos.py first")
        return 1

    app = build_app(staged, args.pdf)
    print(f"http://localhost:{args.port}")
    uvicorn.run(app, host="127.0.0.1", port=args.port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
