"""FastAPI app.

The pipeline is split across endpoints so that the expensive step is reachable only by a
deliberate act:

    /api/remove-bg   free   background removal, user sees the preview and can reject it
    /api/prepare     free   validates, writes a `pending` row, returns what the dialog shows
    /api/generate    PAID   claims the row, calls gpt-image-2, records what it cost
    /api/delivered   free   the browser confirms it actually rendered the result

Nothing chains automatically: a failed background removal cannot walk into a paid call,
because the paid call is a different request that only exists after the user confirms
(NonGoals.md #3, AC-4).

There is no local credit balance. The money lives in the OpenAI account, and OpenAI is the
only thing that can say whether any is left — it refuses the call with a billing error when
there is not. The integrity requirement that survives is narrower and sharper: one confirmed
request may produce at most one billable API call, and a request that fails must produce
none at all.

Endpoints are plain `def`, so FastAPI runs them in its threadpool — rembg and the image API
are blocking and slow, and a single-user internal tool has nothing to gain from async.
"""

import json
import random
import re
import uuid

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from PIL import Image
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from backend import config, validation
from backend.models import request_log
from backend.services import background_removal, catalog, image_gen
from backend.services.background_removal import BackgroundRemovalError
from backend.services.image_gen import ImageGenError
from backend.validation import ValidationError

load_dotenv(config.ROOT / ".env")

config.STORAGE_DIR.mkdir(parents=True, exist_ok=True)
config.DATA_DIR.mkdir(parents=True, exist_ok=True)
config.SHOP_PHOTOS_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="AI Christmas Tree Decorator")
app.mount("/files", StaticFiles(directory=config.STORAGE_DIR), name="files")
app.mount("/static", StaticFiles(directory=config.FRONTEND_DIR), name="static")
# The shop's own product photos (issue #12) — a separate mount from /catalog, because they
# live in data/ rather than catalog/ (ADR-0001: never where a re-import or reinstall can
# overwrite them).
app.mount("/shop-photos", StaticFiles(directory=config.SHOP_PHOTOS_DIR), name="shop-photos")


PAGE_PATHS = {"/", "/history", "/settings"}


@app.middleware("http")
async def no_cache_static(request: Request, call_next):
    """The CSS/JS under /static, and the pages that reference them with a ?v= cache-buster,
    change during a work session (this is a single-machine tool, not a CDN-fronted deploy) —
    without this, a browser's heuristic caching (no Cache-Control header is set by StaticFiles
    or FileResponse) can keep serving a page from before the last edit, complete with its old
    ?v= links, so even bumping the version does nothing until a hard refresh. Which reads as
    "the fix didn't work" when it actually did. ETag still makes a revalidated load cheap;
    this only forces the revalidation to happen every time."""
    response = await call_next(request)
    if request.url.path.startswith("/static/") or request.url.path in PAGE_PATHS:
        response.headers["Cache-Control"] = "no-cache"
    return response

# catalogue product crops, so a proposed code can be shown as a picture. Mounted only if the
# index has been built — the app works without it, minus the reference matching.
CATALOG_IMAGES = config.CATALOG_PATH.parent / "images"
# Cut-outs made ahead of time by scripts/precut_catalog.py. Optional: without them a pick
# still works, it just pays for rembg on the spot the way it always did.
CATALOG_CUTOUTS = config.CATALOG_PATH.parent / "cutouts"
if CATALOG_IMAGES.is_dir():
    app.mount("/catalog", StaticFiles(directory=CATALOG_IMAGES), name="catalog")

STORED_NAME = re.compile(r"^[0-9a-f]{32}_(tree|element|output|reference)\.(png|jpg)$")
EXT_FOR_FORMAT = {"PNG": "png", "JPEG": "jpg"}


# ---------------------------------------------------------------- error responses
# Every failure leaves as {"error": "..."} with a real status code. AC-1 asks for a readable
# message and no crash, and the frontend only ever has to look at one field.


@app.exception_handler(ValidationError)
def _validation_error(request: Request, exc: ValidationError):
    return JSONResponse({"error": str(exc)}, status_code=422)


@app.exception_handler(BackgroundRemovalError)
def _rembg_error(request: Request, exc: BackgroundRemovalError):
    return JSONResponse({"error": str(exc)}, status_code=422)


@app.exception_handler(HTTPException)
def _http_error(request: Request, exc: HTTPException):
    return JSONResponse({"error": exc.detail}, status_code=exc.status_code)


# ---------------------------------------------------------------- storage helpers


def _read(upload, field):
    """Read an upload, checking the length before pulling it into memory."""
    upload.file.seek(0, 2)
    size = upload.file.tell()
    upload.file.seek(0)
    validation.check_size(size, field)
    return upload.file.read()


def _store(data, kind, ext):
    name = f"{uuid.uuid4().hex}_{kind}.{ext}"
    (config.STORAGE_DIR / name).write_bytes(data)
    return name


def _stored_path(name):
    """Resolve a stored filename, rejecting anything that is not one we wrote."""
    if not name or not STORED_NAME.match(name):
        raise ValidationError(f"ไม่รู้จักไฟล์ '{name}'")
    path = config.STORAGE_DIR / name
    if not path.is_file():
        raise ValidationError(f"ไฟล์ '{name}' ไม่อยู่ในเครื่องแล้ว — อัปโหลดใหม่")
    return path


def _url(name):
    return f"/files/{name}" if name else None


# History shows one row per generation, up to 100 of them. A finished picture is ~3.3 MB, so
# putting the real file in each row would have the page pull hundreds of megabytes to draw
# postage stamps — the opposite of the point, which is seeing what a run produced without
# fetching it again.
THUMB_MAX_PX = 320


def _thumbnail_path(name):
    """A small copy of a stored image, made once and kept.

    Cheap enough to build on demand that there is no reason to make generating an image any
    slower for it, and old runs from before this existed get one the first time they are
    looked at.
    """
    source = _stored_path(name)
    thumb = config.THUMBS_DIR / f"{source.stem}.jpg"
    if thumb.is_file() and thumb.stat().st_mtime >= source.stat().st_mtime:
        return thumb

    config.THUMBS_DIR.mkdir(parents=True, exist_ok=True)
    with Image.open(source) as image:
        # JPEG has no alpha; a cut-out would otherwise come out with a black background
        image = image.convert("RGB")
        image.thumbnail((THUMB_MAX_PX, THUMB_MAX_PX))
        staged = thumb.with_name(f"{thumb.name}.{uuid.uuid4().hex}.part")
        image.save(staged, format="JPEG", quality=82)
    staged.replace(thumb)
    return thumb


def _db():
    return request_log.connect()


def _stock_for(tree_code, code):
    """What to pull off the shelf for one item of a finished run (issue #25): how many pieces
    that tree takes, and how many packs that is for a product sold by the pack.

    Recomputed from the row's own codes rather than stored with the request: both numbers are
    derived from catalogue facts the shop keeps correcting, and a pack size typed in today
    should show on a run generated last week rather than the blank it was made with.
    """
    if not tree_code or not code:
        return None, None
    from backend.services import matching

    try:
        quantity = matching.suggest_quantity(tree_code, code)
    except ValidationError:
        return None, None  # no catalogue size for one of them; nothing is invented (NonGoals 8)
    packs = catalog.packs_for(code, quantity["high"])
    if packs:
        packs = {"low": catalog.packs_for(code, quantity["low"])["packs"],
                 "high": packs["packs"], "pack_size": packs["pack_size"]}
    return quantity, packs


def _row_json(row):
    elements = request_log.elements_of(row)
    stock = [_stock_for(row["tree_code"], e.get("code")) for e in elements]
    return {
        "request_id": row["request_id"],
        "status": row["status"],
        "elements": [
            {
                "url": _url(e["path"]), "code": e.get("code"), "colour": e.get("colour"),
                "quantity": quantity, "packs": packs,
            }
            for e, (quantity, packs) in zip(elements, stock)
        ],
        "reference_url": _url(row["reference_path"]),
        # billed is derived, not stored: a row that carries usage is a row that cost money,
        # so there is no flag that can disagree with the record of what happened
        "billed": row["usage_json"] is not None,
        "size": row["size"],
        "density": row["density"],
        "tree_code": row["tree_code"],
        "element_code": row["element_code"],
        "error": row["error"],
        "usage": json.loads(row["usage_json"]) if row["usage_json"] else None,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "tree_url": _url(row["tree_path"]),
        "element_url": _url(row["element_path"]),
        "output_url": _url(row["output_path"]),
    }


# ---------------------------------------------------------------- pages


@app.get("/", include_in_schema=False)
def page_index():
    return FileResponse(config.FRONTEND_DIR / "index.html")


@app.get("/history", include_in_schema=False)
def page_history():
    return FileResponse(config.FRONTEND_DIR / "history.html")


@app.get("/identify", include_in_schema=False)
def page_identify():
    return FileResponse(config.FRONTEND_DIR / "identify.html")


@app.get("/pricing", include_in_schema=False)
def page_pricing():
    return FileResponse(config.FRONTEND_DIR / "pricing.html")


# ---------------------------------------------------------------- api


@app.get("/settings", include_in_schema=False)
def page_settings():
    return FileResponse(config.FRONTEND_DIR / "settings.html")


@app.get("/api/settings")
def api_settings():
    """Whether a key is configured — never the key itself (NonGoals.md 10)."""
    from backend.services import settings

    return {
        "api_key_set": settings.is_set(),
        "env_path": str(settings.ENV_PATH),
        "model": config.IMAGE_MODEL,
        "vision_model": config.VISION_MODEL,
        "catalog_products": config.CATALOG_PATH.is_file(),
        "catalog_searchable": (config.CATALOG_PATH.parent / "embeddings.npy").is_file(),
        "catalog_conflicts": len(catalog.conflicts()),
        "catalog_orphans": len(catalog.orphans()),
    }


@app.get("/api/catalog/conflicts")
def api_catalog_conflicts():
    """Codes the rebuild found meaning two different things on two different pages. Neither
    side is picked automatically (catalog.code_is_contested) — this is what Settings shows so
    someone who knows the product line can say which one is real."""
    return {"conflicts": catalog.conflicts()}


@app.get("/api/catalog/orphans")
def api_catalog_orphans():
    """Shop overlays a re-import's book no longer prints a code for — kept, never dropped
    (ADR-0001, issue #9). What Settings shows so the shop can see what it needs to act on."""
    return {"orphans": catalog.orphans()}


def _pricing_queue_item(row):
    return {
        "code": row["code"], "image": catalog.image_for(row["code"]),
        "size_raw": row.get("size_raw"), "section": row.get("section"), "book": row.get("book"),
    }


@app.get("/api/catalog/pricing-queue")
def api_pricing_queue():
    """The fast pricing entry screen's whole state: how many are left, and the one to show
    next. The queue itself decides "next" (printed order) — the page just re-fetches this
    after every price or skip rather than tracking a position of its own."""
    queue = catalog.pricing_queue()
    return {"remaining": len(queue), "next": _pricing_queue_item(queue[0]) if queue else None}


@app.post("/api/catalog/pricing-queue/{code}/price")
def api_pricing_queue_set_price(code: str, request: Request, price: str = Form("")):
    """The queue's one field. Localhost only, same reasoning as the other catalogue writes."""
    from backend.services import catalog_admin, settings

    if not settings.is_local(request):
        raise HTTPException(403, "The catalogue can only be edited from the machine running this.")
    return catalog_admin.queue_set_price(code, price)


@app.post("/api/catalog/pricing-queue/{code}/skip")
def api_pricing_queue_skip(code: str, request: Request):
    """Marks a product skipped for pricing — it leaves the queue for good."""
    from backend.services import catalog_admin, settings

    if not settings.is_local(request):
        raise HTTPException(403, "The catalogue can only be edited from the machine running this.")
    return catalog_admin.skip_pricing(code)


@app.post("/api/settings/api-key")
def api_set_key(request: Request, api_key: str = Form(...)):
    """Write a new key to .env. Localhost only: reachable from elsewhere this is a way to
    replace someone's credentials, and the auth for that does not exist."""
    from backend.services import settings

    if not settings.is_local(request):
        raise HTTPException(403, "The API key can only be set from the machine running this.")
    settings.set_key(api_key)
    return {"api_key_set": True}


def _orientation(width, height):
    if width == height:
        return "square"
    return "portrait" if width < height else "landscape"


@app.get("/api/config")
def api_config():
    """So the frontend never re-declares limits that live in config.py."""
    return {
        "sizes": [
            {"key": key, "width": w, "height": h, "orientation": _orientation(w, h)}
            for key, (w, h) in config.SIZE_PRESETS.items()
        ],
        "default_size": config.DEFAULT_SIZE,
        "densities": [
            {"key": key, "label": config.DENSITY_LABELS[key]} for key in config.DENSITY_PRESETS
        ],
        "default_density": config.DEFAULT_DENSITY,
        "max_upload_mb": config.MAX_UPLOAD_BYTES // (1024 * 1024),
        "max_elements": config.MAX_ELEMENTS,
        "prompt_mode_max_chars": config.PROMPT_MODE_MAX_CHARS,
        "model": config.IMAGE_MODEL,
    }


@app.get("/api/products")
def api_products(q: str = "", limit: int = 20):
    """Code picker lookup. Returns what the catalogue actually says, including `size: null`
    for the third of the catalogue that has no printed size (NonGoals.md 8)."""
    return {
        "results": [
            {
                "code": row["code"],
                "size_raw": row["size_raw"],
                "size_mm": catalog.longest_side_mm(row),
                "section": row["section"],
                "page": row["pdf_page"],
            }
            for row in catalog.search(q, limit)
        ]
    }


@app.get("/api/catalog/shops")
def api_catalog_shops():
    """Every brand/shop with a showable product, so the picker can offer "which shop" as its
    own filter — a hardcoded pair of options would already be wrong (Product.md: more shops
    are expected to join the catalogue over time)."""
    return {
        "shops": [{"key": book, "label": book, "count": count} for book, count in catalog.shops()]
    }


@app.get("/api/catalog/categories")
def api_catalog_categories(book: str = "", backdrop: str = ""):
    """The browsing categories and how many showable products each holds, so the picker can
    label its filters with real counts instead of offering an empty one.

    Scoped to one shop when `book` is given. Counting across every shop while a shop filter
    was active is what made the picker offer categories that shop does not stock: with MS
    Natural Design selected it still listed ribbons (43), bells (25) and toppers (15), all of
    which are Bangkok Christmas products, so choosing one produced an empty grid. A category
    with nothing behind it in the chosen shop is now simply not offered.
    """
    counts = {}
    for row in catalog.browse(10_000, 0, None, book or None, backdrop or None)[0]:
        key = catalog.category_of(row)
        counts[key] = counts.get(key, 0) + 1
    return {
        "categories": [
            {"key": key, "label": label, "count": counts.get(key, 0)}
            for key, label, _needles in catalog.CATEGORIES
            if counts.get(key, 0)
        ]
    }


@app.get("/api/catalog/search")
def api_catalog_search(q: str = "", category: str = "", book: str = "", limit: int = 60,
                       offset: int = 0, backdrop: str = ""):
    """Thumbnail picker for panel 2 — the catalogue photo alongside the code, so a decoration
    can be chosen without touching the filesystem.

    With no query it browses the whole catalogue in printed order, so the picker opens onto
    products rather than an empty box. `total` is the full match count, not the page's, which
    is what lets the browser say "showing 60 of 1252" and know whether to offer another page.
    Codes whose crop is shared by too many codes to identify any of them are left out of both
    paths — see catalog.crop_is_ambiguous.

    `backdrop` narrows the offer to what can actually go on it (issue #23): a wreath is not
    offered for a tree, an ornament is not offered for a wall. Empty means "no backdrop in
    mind" and browses everything, which is what the tree picker and every older caller do.
    """
    if q.strip():
        matched = [row for row in catalog.search(q, 10_000) if catalog.is_offered(row)]
        if category:
            matched = [row for row in matched if catalog.category_of(row) == category]
        if book:
            matched = [row for row in matched if row.get("book") == book]
        if backdrop:
            matched = [
                row for row in matched
                if catalog.suits_backdrop(catalog.category_of(row), backdrop)
            ]
        rows, total = matched[offset : offset + limit], len(matched)
    else:
        rows, total = catalog.browse(limit, offset, category or None, book or None, backdrop or None)

    # one card per colour, not per code: a product photographed across its colour range is one
    # code with several pictures, and picking "the whole photo" would hand the generator every
    # colour at once (catalog.variants_of)
    results = []
    for row in rows:
        images = catalog.variants_of(row["code"])
        for index, image in enumerate(images):
            results.append({
                "code": row["code"],
                "image": image,
                "colour": index + 1 if len(images) > 1 else None,
                "colours": len(images),
                # None until seeded/corrected (issue #14) — the picker falls back to
                # "colour"/"colours" above (a position label) rather than inventing a name
                "colour_name": catalog.colour_name(row["code"], image) if len(images) > 1 else None,
                # Visible when browsing, never pickable (issue #17) — the picker sends only
                # `image` (the main) through catalogPickerCallback; a supporting photo never
                # reaches /api/element/from-catalog from here.
                "supporting": catalog.supporting_photos(row["code"], image),
                "size_raw": row["size_raw"],
                "section": row["section"],
                "category": catalog.category_of(row),
                "book": row.get("book"),
            })

    # `codes` is how many products this page consumed, which is what the next offset must
    # advance by — `results` can be larger, since a colour range contributes several cards
    return {"total": total, "codes": len(rows), "results": results}


def _cutout_path(path):
    """Where this catalogue photo's cut-out lives, or None if it is not a catalogue photo."""
    try:
        return CATALOG_CUTOUTS / path.relative_to(CATALOG_IMAGES)
    except ValueError:  # not under images/ — nothing could have been pre-cut for it
        return None


def _precut(path):
    """The pre-made cut-out for a catalogue photo, or None if it was never made.

    A catalogue photo never changes, so neither does its cut-out — running rembg again per
    pick was recomputing a constant. Falling back rather than requiring the file keeps a
    catalogue that has not been pre-cut (a freshly added product, an install that skipped the
    step) working exactly as before, just slower.
    """
    candidate = _cutout_path(path)
    return candidate.read_bytes() if candidate and candidate.is_file() else None


def _keep_cutout(path, cut):
    """Remember a cut-out that had to be made live, so the next pick reads it instead.

    A product added from the settings page has no pre-cut file, and without this every pick of
    it would pay for rembg again — the same recomputation scripts/precut_catalog.py exists to
    avoid, just spread out one product at a time.

    Written to a temporary name and moved into place: a half-written PNG left by a crash or a
    full disk would be served as this product's cut-out from then on, and unlike the slow path
    that failure would be permanent. Any write problem is swallowed — the caller already has
    the cut-out it needs, and a read-only or full disk must not turn a working pick into an
    error.
    """
    target = _cutout_path(path)
    if target is None:
        return
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        staged = target.with_name(f"{target.name}.{uuid.uuid4().hex}.part")
        staged.write_bytes(cut)
        staged.replace(target)
    except OSError:
        pass


@app.post("/api/element/from-catalog")
def api_element_from_catalog(code: str = Form(...), image: str = Form("")):
    """Same as /api/remove-bg, except the source photo already lives in the catalogue instead
    of coming from the browser. Returns the identical shape so the frontend's existing
    preview/accept/reject flow needs no separate code path.

    `image` picks one colour of a product photographed as a colour range. It is checked
    against that code's own variant list rather than joined onto a path — the value arrives
    from the browser, and anything else would be a traversal into the filesystem.
    """
    code = code.strip()
    if image:
        if image not in catalog.variants_of(code):
            raise HTTPException(404, f"'{image}' ไม่ใช่รูปของ {code}")
        path = catalog.resolve_image_path(image)
    else:
        path = catalog.image_path(code)
    if not path or not path.is_file():
        raise HTTPException(404, f"ไม่มีรูป catalogue ของ '{code}'")

    cut = _precut(path)
    if cut is None:
        cut = background_removal.remove_background(path.read_bytes())
        _keep_cutout(path, cut)
    name = _store(cut, "element", "png")
    row = catalog.find(code)
    return {
        "element": name, "element_url": _url(name),
        "size_mm": catalog.longest_side_mm(row),
        # None means "the book never printed one" — the panel offers to fill it in on the spot
        # (issue #27), the way it already does for a missing size. Unlike a size, it never
        # blocks: a product with no price has always been fully usable for a picture.
        "price": row.get("price"),
    }


@app.post("/api/tree/from-catalog")
def api_tree_from_catalog(code: str = Form(...), image: str = Form("")):
    """Same as /api/element/from-catalog, but for the tree slot: no background removal — a
    tree is used with its own photographed background, never cut out."""
    code = code.strip()
    if image:
        if image not in catalog.variants_of(code):
            raise HTTPException(404, f"'{image}' ไม่ใช่รูปของ {code}")
        path = catalog.resolve_image_path(image)
    else:
        path = catalog.image_path(code)
    if not path or not path.is_file():
        raise HTTPException(404, f"ไม่มีรูป catalogue ของ '{code}'")

    name = _store(path.read_bytes(), "tree", "png")
    row = catalog.find(code)
    return {
        "tree": name, "tree_url": _url(name),
        "size_mm": catalog.longest_side_mm(row),
        "price": row.get("price"),  # same as the element slot's, issue #27
    }


@app.post("/api/catalog/products")
def api_catalog_add(
    request: Request,
    code: str = Form(...),
    size_raw: str = Form(""),
    section: str = Form(""),
    book: str = Form(""),
    price: str = Form(""),
    image: UploadFile = File(...),
):
    """Add one product by hand (settings page). Localhost only, same reasoning as the API-key
    write: this writes files to disk, and the auth to do that safely from elsewhere doesn't
    exist yet."""
    from backend.services import catalog_admin, settings

    if not settings.is_local(request):
        raise HTTPException(403, "The catalogue can only be edited from the machine running this.")

    data = _read(image, "Product photo")
    validation.check_image(data, image.filename, image.content_type, "Product photo")
    return catalog_admin.add_product(code, size_raw, section, book, data, price)


@app.post("/api/catalog/products/{code}")
def api_catalog_update(
    code: str,
    request: Request,
    size_raw: str = Form(""),
    section: str = Form(""),
    book: str = Form(""),
    price: str = Form(""),
):
    """Edit one existing product's fields (settings page). Same localhost-only gate as add —
    this writes to data/shop_overlay.json. The photo is a separate action now (issue #12):
    see /api/catalog/products/{code}/photo."""
    from backend.services import catalog_admin, settings

    if not settings.is_local(request):
        raise HTTPException(403, "The catalogue can only be edited from the machine running this.")

    return catalog_admin.update_product(code, size_raw, section, book, price)


@app.post("/api/catalog/products/{code}/pack-size")
def api_catalog_set_pack_size(code: str, request: Request, pack_size: str = Form("")):
    """How many pieces come in one pack of this product (issue #25). Its own endpoint rather
    than a field on update_product: that one diffs every field against the book and would read
    a form carrying only a pack size as "clear the size, section and book too", and a pack size
    has no book counterpart to diff against in the first place. Blank clears it."""
    from backend.services import catalog_admin, settings

    if not settings.is_local(request):
        raise HTTPException(403, "The catalogue can only be edited from the machine running this.")

    raw = (pack_size or "").strip()
    if raw and not raw.isdigit():
        raise ValidationError(f"จำนวนต่อแพ็ค '{raw}' ไม่ใช่จำนวนเต็ม")
    return catalog_admin.set_pack_size(code, int(raw) if raw else None)


@app.post("/api/catalog/products/{code}/photo")
def api_catalog_set_shop_photo(code: str, request: Request, image: UploadFile = File(...)):
    """Upload a shop photo for one product (issue #12) — it supersedes the book crop
    everywhere, un-hides a bad-crop code, and re-runs its search description/embedding.
    Localhost only, same reasoning as every other catalogue write."""
    from backend.services import catalog_admin, settings

    if not settings.is_local(request):
        raise HTTPException(403, "The catalogue can only be edited from the machine running this.")

    data = _read(image, "Product photo")
    fmt, _dimensions = validation.check_image(data, image.filename, image.content_type, "Product photo")
    catalog_admin.set_shop_photo(code, data, fmt)
    return catalog.product_detail(catalog.find(code))


@app.delete("/api/catalog/products/{code}/photo")
def api_catalog_remove_shop_photo(code: str, request: Request):
    """Falls back to the book photo (issue #12). Localhost only."""
    from backend.services import catalog_admin, settings

    if not settings.is_local(request):
        raise HTTPException(403, "The catalogue can only be edited from the machine running this.")

    catalog_admin.remove_shop_photo(code)
    return catalog.product_detail(catalog.find(code))


@app.get("/api/catalog/recent")
def api_catalog_recent(limit: int = 20):
    """Read-only list for the settings page, newest addition first."""
    return {"results": [catalog.product_detail(row) for row in catalog.recent(limit)]}


@app.get("/api/catalog/products/{code}")
def api_catalog_find(code: str):
    """Find one product by its code and show its merged record (issue #11) — the book-derived
    position fields (bbox, pdf_page) are never part of catalog.product_detail, so they never
    reach this response either."""
    return catalog.product_detail(catalog.find(code))


@app.get("/api/catalog/products/{code}/colours")
def api_catalog_colours(code: str):
    """Every colour of one product, image and name (issue #15) — what an accepted
    decoration's switcher offers. A single-colour product returns exactly one entry, which is
    the frontend's whole "offer no switcher" rule: nothing to switch to.

    `supporting` (issue #17) is every other photo kept for that same colour — for browsing and
    editing only. The switcher (issue #15) ignores the field entirely, since choosing a colour
    still only ever picks its main; nothing here changes what /api/element/from-catalog will
    accept.
    """
    row = catalog.find(code)
    return {
        "colours": [
            {
                "image": image, "name": catalog.colour_name(row["code"], image),
                "supporting": catalog.supporting_photos(row["code"], image),
            }
            for image in catalog.variants_of(row["code"])
        ]
    }


@app.post("/api/catalog/products/{code}/photos")
def api_add_supporting_photo(
    code: str, request: Request, main_image: str = Form(...), image: UploadFile = File(...)
):
    """Add another photo for one of a product's colours (issue #17) — the back, a detail
    shot, one that shows scale. Localhost only, same reasoning as every other catalogue
    write."""
    from backend.services import catalog_admin, settings

    if not settings.is_local(request):
        raise HTTPException(403, "The catalogue can only be edited from the machine running this.")
    data = _read(image, "Product photo")
    fmt, _dimensions = validation.check_image(data, image.filename, image.content_type, "Product photo")
    return catalog_admin.add_supporting_photo(code, main_image, data, fmt)


@app.delete("/api/catalog/products/{code}/photos")
def api_remove_photo(code: str, request: Request, image: str):
    """Remove one photo, main or supporting (issue #17) — removing a main promotes a
    supporting photo of the same colour to take its place. Localhost only."""
    from backend.services import catalog_admin, settings

    if not settings.is_local(request):
        raise HTTPException(403, "The catalogue can only be edited from the machine running this.")
    return catalog_admin.remove_photo(code, image)


@app.post("/api/catalog/products/{code}/main-photo")
def api_set_main_photo(code: str, request: Request, image: str = Form(...)):
    """Choose which of a colour's photos the generator gets, without removing anything (issue
    #17) — the old main becomes a supporting photo of the same colour. Localhost only."""
    from backend.services import catalog_admin, settings

    if not settings.is_local(request):
        raise HTTPException(403, "The catalogue can only be edited from the machine running this.")
    return catalog_admin.set_main_photo(code, image)


@app.post("/api/catalog/products/{code}/clear-override")
def api_catalog_clear_override(code: str, request: Request, field: str = Form(...)):
    """Returns one field to the book's value (issue #11). Same localhost-only gate as every
    other catalogue write — this changes what is on disk in data/shop_overlay.json."""
    from backend.services import catalog_admin, settings

    if not settings.is_local(request):
        raise HTTPException(403, "The catalogue can only be edited from the machine running this.")
    catalog_admin.clear_override(code, field)
    return catalog.product_detail(catalog.find(code))


@app.post("/api/catalog/products/{code}/colour-name")
def api_catalog_set_colour_name(
    code: str, request: Request, image: str = Form(...), name_th: str = Form(...)
):
    """Seed or correct one colour photo's Thai name (issue #14). Localhost only, same
    reasoning as every other catalogue write."""
    from backend.services import catalog_admin, settings

    if not settings.is_local(request):
        raise HTTPException(403, "The catalogue can only be edited from the machine running this.")
    return catalog_admin.set_colour_name(code, image, name_th)


@app.post("/api/catalog/sync")
def api_catalog_sync(request: Request):
    """Describe + embed whatever was added since the last sync, so newly-added products
    become findable through 'หาสินค้าใกล้เคียง'. Runs the same scripts a bulk catalogue
    import uses — describe_catalog.py already skips codes it has described before, so this
    is cheap to call after adding just one product."""
    import subprocess
    import sys

    from backend.services import settings

    if not settings.is_local(request):
        raise HTTPException(403, "Catalogue sync can only be run from the machine running this.")

    for script in ("scripts/describe_catalog.py", "scripts/embed_catalog.py"):
        result = subprocess.run(
            [sys.executable, str(config.ROOT / script)],
            capture_output=True, text=True, cwd=config.ROOT,
        )
        if result.returncode != 0:
            raise HTTPException(502, f"{script} ล้มเหลว:\n{result.stderr[-2000:]}")

    catalog.refresh()
    matching.refresh()
    return {"synced": True}


@app.get("/api/usage")
def api_usage():
    """What has been spent so far, summed from the log.

    Deliberately not a balance. OpenAI exposes no remaining-balance endpoint to an API key,
    so anything claiming to be one here would be a guess maintained by hand.
    """
    conn = _db()
    try:
        return request_log.usage_totals(conn)
    finally:
        conn.close()


@app.post("/api/remove-bg")
def api_remove_bg(files: list[UploadFile] = File(...)):
    """Input B -> transparent PNG. Free, and the user must look at the result before
    anything else happens (Spec.md 3, AC-2)."""
    upload = validation.exactly_one(files, "Element image")
    data = _read(upload, "Element image")
    validation.check_image(data, upload.filename, upload.content_type, "Element image")

    cut = background_removal.remove_background(data)
    name = _store(cut, "element", "png")
    return {"element": name, "element_url": _url(name)}


@app.post("/api/reference")
def api_reference(files: list[UploadFile] = File(...)):
    """An optional photo whose setting and light the result should adopt (Product.md 8.3).

    Stored as-is: unlike a decoration this one is not background-removed, because the
    background is the whole reason it is here.
    """
    upload = validation.exactly_one(files, "Reference image")
    data = _read(upload, "Reference image")
    fmt, _dimensions = validation.check_image(
        data, upload.filename, upload.content_type, "Reference image"
    )
    name = _store(data, "reference", EXT_FOR_FORMAT[fmt])
    return {"reference": name, "reference_url": _url(name)}


@app.post("/api/reference/{name}/analyse")
def api_analyse_reference(name: str, tree_code: str = ""):
    """Read the decorations in a reference photo and look for them in the catalogue.

    Product.md 8.3c. Every proposal comes as three candidates with their scores and their
    catalogue photo, and `refused` is set when nothing scored well enough — the shop orders
    from these, so a confident single answer is how the wrong box arrives (NonGoals.md 7).
    """
    from backend.services import matching, vision

    path = _stored_path(name)
    try:
        described, usage = vision.describe_reference(path.read_bytes())
    except Exception as exc:
        raise HTTPException(502, f"อ่านรูปอ้างอิงไม่ได้ ({type(exc).__name__}: {exc})")

    found = []
    for decoration in described.decorations:
        text = vision.as_text(decoration)
        matches, refused = matching.find(
            text, query_kind=decoration.kind, query_shape=decoration.shape,
            query_colour=decoration.primary_colour,
        )
        entry = {
            "seen": decoration.model_dump(),
            "text": text,
            "refused": refused,
            "candidates": matches,
            # a top candidate that disagrees on what the thing even is scores high anyway;
            # measured, a nutcracker matched a Santa at 0.820
            "same_kind": bool(matches) and matches[0]["kind_agrees"],
        }
        if tree_code.strip() and not refused:
            try:
                entry["quantity"] = matching.suggest_quantity(
                    tree_code.strip(), matches[0]["code"]
                )
            except ValidationError as exc:
                entry["quantity_note"] = str(exc)
        found.append(entry)

    return {
        "reference_url": _url(path.name),
        "decorations": found,
        "usage": usage,
        # NonGoals.md 7: this must never read as a confirmed identification, however short it
        # gets — "ใกล้เคียงที่สุด ไม่ใช่การยืนยัน" and "ดูรูปก่อน" are the load-bearing half.
        "note": (
            "ของที่ใกล้เคียงที่สุดในแคตตาล็อก ไม่ใช่การยืนยันว่าใช่ตัวนั้น "
            "ดูรูปให้แน่ใจก่อนแจ้งรหัสลูกค้า"
        ),
    }


@app.get("/api/auto/config")
def api_auto_config(backdrop: str = ""):
    """What auto pick offers: the tone presets, and the recipe it will fill (ADR-0003).

    No tree heights, no category picker, no budget: the shop is asked for a tone and nothing
    else, and the recipe is the same for every tone and every backdrop of a kind.

    `backdrop` (issue #24) chooses which recipe that is — the hung-and-grounded mix for a
    tree, the mounted one for a wall or door.

    On a wall or door, a tone with nothing behind it is not offered at all: that recipe is two
    categories wide and coming back empty is a routine outcome, so asking the shop to choose a
    tone that can only disappoint is worse than one fewer button. The tree's six-category
    recipe is not filtered — every tone it offers today it goes on offering, and a tone that
    fills some slots but not all is offered on either backdrop, the same as a tree tone with
    an unfillable bell slot always has been.
    """
    backdrop = validation.resolve_backdrop(backdrop)
    recipe = config.AUTO_RECIPES[backdrop]
    return {
        "tones": [
            {"key": key, "label": preset["label"]}
            for key, preset in config.TONE_PRESETS.items()
            if backdrop == "tree"
            or any(catalog.auto_pool(category, preset["colours"]) for category, _n in recipe)
        ],
        "recipe": [
            {"category": key, "label": catalog.label_for(key), "count": count}
            for key, count in recipe
        ],
    }


@app.post("/api/auto/pick")
def api_auto_pick(tone: str = Form(...), exclude: list[str] = Form(default=[]),
                  backdrop: str = Form("")):
    """Fill the recipe with products in one tone — the whole of auto pick.

    `backdrop` (issue #24) decides which recipe is filled: the hung-and-grounded mix for a
    tree, the mounted one for a wall or door. Everything below is the same machinery either
    way, which is the whole point of ADR-0004.

    Each recipe slot draws from its own category's pool. A category with nothing in this tone
    contributes nothing and is reported in `missing`; a category with less stock than the
    recipe asks for contributes what it has and is reported in `short`. Neither case is filled
    with an off-tone product: the tone is the only thing the shop asked for, so substituting
    against it destroys the one reason they chose it.

    Touches no storage and bills nothing — free to call again for "สุ่มใหม่", passing the codes
    already shown as `exclude` to avoid repeats where the pool allows it. `exclude` is a
    preference, never a filter: a slot takes unshown products first and then tops itself back
    up from the shown ones. Letting it truncate instead would shrink the proposal on every
    re-roll — the shop asked for a different set, not a smaller one.

    No tree is proposed. The tree is the shop's own — uploaded or picked from the catalogue,
    the same as in กำหนดเอง — and the size question that used to justify guessing one is gone.
    """
    if tone not in config.TONE_PRESETS:
        raise ValidationError(f"ไม่รู้จักโทน '{tone}'")
    backdrop = validation.resolve_backdrop(backdrop)
    recipe = config.AUTO_RECIPES[backdrop]

    tone_colours = config.TONE_PRESETS[tone]["colours"]
    excluded = set(exclude)
    decorations, missing, short = [], [], {}

    for category, wanted in recipe:
        pool = catalog.auto_pool(category, tone_colours)
        if not pool:
            missing.append(category)
            continue
        fresh = [row for row in pool if row["code"] not in excluded]
        shown = [row for row in pool if row["code"] in excluded]
        chosen = random.sample(fresh, k=min(wanted, len(fresh)))
        if len(chosen) < wanted and shown:
            chosen += random.sample(shown, k=min(wanted - len(chosen), len(shown)))
        if len(chosen) < wanted:
            short[category] = len(chosen)
        for row in chosen:
            decorations.append({
                "code": row["code"],
                "category": category,
                "price": row.get("price"),
                "image_url": f"/catalog/{catalog.image_for(row['code'])}",
            })

    return {
        "decorations": decorations,
        "requested": sum(count for _category, count in recipe),
        "missing": missing,
        "short": short,
    }


@app.post("/api/prepare")
def api_prepare(
    files: list[UploadFile] = File(...),
    element: list[str] = Form(...),
    size: str = Form(config.DEFAULT_SIZE),
    scene_ratio: str = Form(""),
    density: str = Form(config.DEFAULT_DENSITY),
    tree_code: str = Form(""),
    element_code: list[str] = Form(default=[]),
    element_image: list[str] = Form(default=[]),
    reference: str = Form(""),
    tree_manual_mm: str = Form(""),
    element_manual_mm: list[str] = Form(default=[]),
    element_density: list[str] = Form(default=[]),
    custom_prompt: str = Form(""),
    backdrop: str = Form(""),
):
    """Input A + one to MAX_ELEMENTS accepted decorations -> a `pending` request. Still free;
    still no API call.

    Product codes are optional, and every named item's code has to resolve to something in
    the catalogue or the whole request is refused (a typo is a wrong order). A code that
    resolves but whose row has no printed size is different: that one item just falls back to
    a believable, non-exact size (Product.md 8.2, NonGoals.md 8) and comes back in
    `missing_sizes` so the confirm dialog can say so, rather than refusing outright — unless
    the frontend's blocking manual-size gate already collected a real number for it, sent
    here as `tree_manual_mm`/`element_manual_mm` (positional, aligned with `element_code`,
    empty string meaning "no override"). Codes are resolved here rather than at generation
    time so a bad one costs nothing and is caught before the confirm dialog.

    `element_density` is a per-item DENSITY_PRESETS key, positional with `element_code` the
    same way; empty entries fall back to DEFAULT_DENSITY. `density` (the old, whole-request
    field) still selects the tree's overall feel when nobody has touched per-item density —
    image_gen.describe_element_density() is what actually decides which of the two the prompt
    sees, at generate time.

    `custom_prompt` (Prompt mode) wins outright over both `density` and `element_density` at
    generate time when non-empty — see /api/generate's own comment on this.

    `element_image` (issue #16) names which colour photo an item is, positional the same way,
    resolved here into a Thai colour name (catalog.colour_name) rather than storing the
    picker's raw filename — the history and the staff worksheet want the same word a shop
    assistant would say, not "4400-1--5.png". A code with no colour, or one that resolves to
    nothing, simply records no colour rather than guessing (NonGoals.md 8) — the
    count-what-is-in-the-picture feature (image_gen.count_decorations) reads a finished photo
    and has no catalogue element to attach this to either way, so it is untouched by this.

    `size == "auto"` means "match the scene reference photo's own ratio" — resolved here into
    a concrete WxH via fit_custom_size(scene_ratio) and stored as that literal string, so
    /api/generate later re-resolves it through the exact same resolve_size() path as any
    preset, with no memory of where the number came from.
    """
    upload = validation.exactly_one(files, "Tree image")
    data = _read(upload, "Tree image")
    fmt, _dimensions = validation.check_image(data, upload.filename, upload.content_type, "Tree image")

    if size == "auto":
        try:
            ratio = float(scene_ratio)
        except ValueError:
            raise ValidationError("ขอสัดส่วนรูปจริงไม่ได้ — ไม่มีข้อมูลอัตราส่วน")
        width, height = validation.fit_custom_size(ratio)
        size = f"{width}x{height}"
    else:
        width, height = validation.resolve_size(size)
    validation.resolve_density(density)  # fail fast; the sentence itself is re-resolved at generate time
    backdrop = validation.resolve_backdrop(backdrop)
    custom_prompt = validation.parse_custom_prompt(custom_prompt)
    names = validation.element_count([e.strip() for e in element if e.strip()])
    paths = [_stored_path(name) for name in names]

    # A wall or door is the shop's own photo, never a catalogue product, so it has no code to
    # carry (issue #23) — dropping one sent anyway keeps an unvalidated string out of the row.
    tree_code = tree_code.strip() if backdrop == "tree" else ""
    codes = [c.strip() for c in element_code][: len(paths)]
    codes += [""] * (len(paths) - len(codes))
    if any(codes) and not all(codes):
        raise ValidationError(
            "ของตกแต่งบางชิ้นใส่รหัส บางชิ้นไม่ใส่ — ใส่รหัสให้ครบทุกชิ้น หรือไม่ใส่เลยก็ได้ "
            "ใส่บางส่วนคำนวณขนาดจริงไม่ได้"
        )
    # Resolved from the catalogue, never trusted as freeform text (issue #16): a stale or
    # tampered image value just fails to name a colour rather than recording an invented one.
    images = [i.strip() for i in element_image][: len(paths)]
    images += [""] * (len(paths) - len(images))
    colours = [catalog.colour_name(c, i) if c and i else None for c, i in zip(codes, images)]

    tree_mm_override = validation.parse_manual_mm(tree_manual_mm, "ขนาดต้นไม้ (กรอกเอง)")
    manual_mm = [m.strip() for m in element_manual_mm][: len(paths)]
    manual_mm += [""] * (len(paths) - len(manual_mm))
    element_mm_overrides = [
        validation.parse_manual_mm(m, f"ขนาดของตกแต่งชิ้นที่ {i + 1} (กรอกเอง)")
        for i, m in enumerate(manual_mm)
    ]
    densities = [d.strip() for d in element_density][: len(paths)]
    densities += [""] * (len(paths) - len(densities))
    for d in densities:
        if d:
            validation.resolve_density(d)  # fail fast, per item

    # Every element has to belong on the backdrop it was picked for (issue #23) — checked
    # before the sizing below, since a wreath on a tree is wrong whatever its measurements say.
    chosen, other = ("ต้นคริสต์มาส", "ผนัง/ประตู") if backdrop == "tree" else ("ผนัง/ประตู", "ต้นคริสต์มาส")
    for code in codes:
        if code and not catalog.suits_backdrop(catalog.category_of(catalog.find(code)), backdrop):
            raise ValidationError(f"'{code}' เป็นของสำหรับ{other} ใส่กับ{chosen}ไม่ได้")

    if backdrop == "tree":
        scale, missing_sizes = catalog.scale_sentence(
            tree_code, codes, tree_mm_override, element_mm_overrides
        )
    else:
        # A wall or door is the shop's own photo, not a catalogue product, so there is no code
        # to measure it by — nothing here can be exact, and the tree's all-or-nothing code
        # rule has nothing to pair an element's code with (issue #23).
        scale, missing_sizes = catalog.scale_sentence("", [], backdrop=backdrop)
    # A garland wraps once around the trunk (issue #20) — a second one has nowhere to wrap
    # that the first doesn't already occupy, the same way a duplicate element file is refused.
    wrapped = [c for c in codes if catalog.placement_of_code(c) == "wrapped"]
    if len(wrapped) > 1:
        raise ValidationError(
            f"เลือกการ์แลนด์ได้ครั้งละ 1 เส้นเท่านั้น — ตอนนี้เลือกมา {len(wrapped)} เส้น"
        )
    # A grounded item (gift box, figure — issue #21) sits in its own cluster at the tree's
    # foot and never occupies a hung slot, so it is counted against its own ceiling here
    # rather than against MAX_ELEMENTS. `codes` already has one entry per element, empty
    # string for one with no code — those count as hung, same as before this ceiling split.
    grounded_count = sum(1 for c in codes if catalog.placement_of_code(c) == "grounded")
    hung_count = len(codes) - grounded_count
    if hung_count > config.MAX_ELEMENTS:
        raise ValidationError(
            f"ใส่ของแขวนต้นได้มากสุด {config.MAX_ELEMENTS} ชิ้น — ตอนนี้ใส่มา {hung_count} ชิ้น "
            "(ของตั้งพื้นอย่างกล่องของขวัญไม่นับรวมในนี้)"
        )
    if grounded_count > config.MAX_GROUNDED:
        raise ValidationError(
            f"ใส่ของตั้งพื้น (กล่องของขวัญ/ตุ๊กตา) ได้มากสุด {config.MAX_GROUNDED} ชิ้น — "
            f"ตอนนี้ใส่มา {grounded_count} ชิ้น"
        )
    quantities = None
    if tree_code and all(codes):
        from backend.services import matching

        # a code with no catalogue size already means scale_sentence() fell back to
        # "believable, not exact" for it — a quantity estimate needs the same real
        # millimetres and has no such fallback, so that one item's suggestion is just absent
        # rather than guessed (positional, so the frontend can still label the rest by index)
        quantities = []
        for code in codes:
            try:
                quantities.append(matching.suggest_quantity(tree_code, code))
            except ValidationError:
                quantities.append(None)
    reference = reference.strip()
    reference_name = _stored_path(reference).name if reference else None
    tree_name = _store(data, "tree", EXT_FOR_FORMAT[fmt])
    # a per-item density that was never touched falls back to the whole-request selector, not
    # straight to DEFAULT_DENSITY — that selector is still what "everyone gets the same feel"
    # means, per-item is only for a shop that actually wants some kinds sparser than others
    elements = [
        {
            "path": p.name,
            "code": c or None,
            "colour": colour,
            "manual_mm": mm,
            "density": d or density,
        }
        for p, c, colour, mm, d in zip(paths, codes, colours, element_mm_overrides, densities)
    ]

    conn = _db()
    try:
        request_id = request_log.create(
            conn, tree_name, elements, size, tree_code or None, reference_name, density,
            tree_mm_override, custom_prompt, backdrop,
        )
    finally:
        conn.close()

    return {
        "request_id": request_id,
        "size": size,
        "width": width,
        "height": height,
        "tree_url": _url(tree_name),
        "element_urls": [_url(e["path"]) for e in elements],
        "element_count": len(elements),
        "reference_url": _url(reference_name),
        "scale": scale,
        "exact_scale": bool(tree_code and all(codes) and not missing_sizes),
        "missing_sizes": missing_sizes,
        "quantities": quantities,
    }


@app.post("/api/generate/{request_id}")
def api_generate(request_id: str):
    """The paid step. Reached only after the confirm dialog (AC-4)."""
    conn = _db()
    try:
        row = request_log.get(conn, request_id)
        if row is None:
            raise HTTPException(404, "ไม่รู้จัก request นี้")

        # pending -> calling_api. Losing this race means the request is already running or
        # finished, which is what a double-click looks like from here.
        if not request_log.claim(conn, request_id):
            raise HTTPException(
                409,
                f"request นี้อยู่ในสถานะ {row['status']} แล้ว จะไม่สร้างซ้ำให้",
            )

        width, height = validation.resolve_size(row["size"])
        tree_path = _stored_path(row["tree_path"])
        elements = request_log.elements_of(row)
        element_paths = [_stored_path(e["path"]) for e in elements]
        # missing_sizes already surfaced as a warning at prepare time; only the prompt text
        # itself is needed again here. tree_manual_mm/each element's manual_mm are re-read
        # from storage rather than trusted from prepare time, same reasoning as re-resolving
        # size and density below — the row is the one source of truth once a request exists.
        tree_mm_override = float(row["tree_manual_mm"]) if row["tree_manual_mm"] not in (None, "") else None
        element_mm_overrides = [
            float(e["manual_mm"]) if e.get("manual_mm") not in (None, "") else None
            for e in elements
        ]
        # rows written before issue #22 have backdrop=NULL — they all decorated a tree
        backdrop = row["backdrop"] or "tree"
        if backdrop == "tree":
            scale, _missing_sizes = catalog.scale_sentence(
                row["tree_code"], [e.get("code") for e in elements],
                tree_mm_override, element_mm_overrides,
            )
        else:
            # no catalogue code measures a wall or door, same as at prepare time (issue #23)
            scale, _missing_sizes = catalog.scale_sentence("", [], backdrop=backdrop)

        # Once the request is claimed it must reach a terminal state on every path, or it is
        # stranded at calling_api and can never be retried. So this catches everything, not
        # just ImageGenError — an unexpected failure is still a failure that produced no
        # image and should be runnable again.
        reference = row["reference_path"]
        reference_bytes = _stored_path(reference).read_bytes() if reference else None
        # per-item density when accepted items actually disagree, else the same single
        # whole-tree sentence every generation sent before per-item density existed. Rows
        # written before per-item density existed have no per-element "density" at all, so
        # they fall back to the request-level column here rather than to DEFAULT_DENSITY —
        # otherwise an old row that explicitly chose "full" would silently regenerate as
        # "normal" the next time it was reused.
        fallback_density = row["density"] or config.DEFAULT_DENSITY
        elements_for_prompt = [
            {
                **e,
                "density": e.get("density") or fallback_density,
                "placement": catalog.placement_of_code(e.get("code")),
            }
            for e in elements
        ]
        # Prompt mode: a free-text description the shop typed instead of picking a density
        # wins outright, verbatim, over the whole density system above — it lands in exactly
        # the same {density} slot in the template (backend/services/image_gen.py:load_prompt),
        # which sits after the template's hard preservation rules, never before them.
        # Every DENSITY_PRESETS sentence counts decorations across a tree, so a wall/door gets
        # its own statement instead (issue #22). Prompt mode still wins over both.
        density_sentence = row["custom_prompt"] or (
            image_gen.describe_element_density(elements_for_prompt) if backdrop == "tree"
            else config.WALL_DENSITY
        )
        placement_notes = image_gen.describe_placement(elements_for_prompt, backdrop)

        try:
            output, usage = image_gen.generate(
                tree_path.read_bytes(),
                [path.read_bytes() for path in element_paths],
                width, height, scale, reference_bytes, density_sentence, placement_notes,
                backdrop,
            )
            name = _store(output, "output", "png")
        except Exception as exc:
            request_log.mark_failed(conn, request_id, exc)
            detail = exc if isinstance(exc, ImageGenError) else f"{type(exc).__name__}: {exc}"
            raise HTTPException(502, f"สร้างภาพไม่สำเร็จ: {detail}") from exc

        request_log.mark_success(conn, request_id, name, usage)

        return _row_json(request_log.get(conn, request_id)) | {
            "totals": request_log.usage_totals(conn)
        }
    finally:
        conn.close()


@app.post("/api/delivered/{request_id}")
def api_delivered(request_id: str):
    """The browser saying it rendered the result. Purely a reconciliation marker: a row left
    at api_success is one that was paid for but may never have been seen (Spec.md 7)."""
    conn = _db()
    try:
        if request_log.get(conn, request_id) is None:
            raise HTTPException(404, "ไม่รู้จัก request นี้")
        request_log.mark_delivered(conn, request_id)
        return _row_json(request_log.get(conn, request_id))
    finally:
        conn.close()


@app.post("/api/count/{request_id}")
def api_count_result(request_id: str):
    """Count the decorations in a finished picture.

    Separate from the size-based suggestion /api/prepare returns, and a different question.
    That one answers "how many of this product fit on a tree this size", from the catalogue
    millimetres; this one answers "how many are in the picture I am about to show a customer",
    which is what gets quoted. They disagree whenever gpt-image-2 renders the decorations off
    the instructed scale, which measured is most of the time (scripts/measure_scale.py).

    Its own endpoint, on a button, because it is a billed vision call — same rule as
    /api/reference/{name}/analyse: nothing bills without being asked (AC-4). The token cost is
    reported back but deliberately not written to the request's usage_json, which is the
    generation's own billing record and the basis of usage_totals' generation count.
    """
    from backend.services import vision

    conn = _db()
    try:
        row = request_log.get(conn, request_id)
    finally:
        conn.close()

    if row is None:
        raise HTTPException(404, "ไม่รู้จัก request นี้")
    if not row["output_path"]:
        raise ValidationError("request นี้ยังไม่มีภาพผลลัพธ์ให้นับ")

    path = _stored_path(row["output_path"])
    try:
        counted, usage = vision.count_decorations(path.read_bytes())
    except Exception as exc:
        raise HTTPException(502, f"นับของในรูปไม่สำเร็จ ({type(exc).__name__}: {exc})")

    return {
        "request_id": request_id,
        "kinds": [kind.model_dump() for kind in counted.kinds],
        "usage": usage,
        "note": "นับเฉพาะชิ้นที่เห็นในรูป ด้านหลังต้นกับที่บังกิ่งอยู่ไม่ได้นับ",
    }


@app.get("/api/thumbnail/{name}")
def api_thumbnail(name: str):
    """A small JPEG of a stored image, for the history table.

    Separate from /files/{name} rather than an option on it: the history page wants a preview
    it can afford to draw a hundred of, and the download button next to it wants the real
    file. Serving one URL for both would mean either a slow page or a downgraded download.
    """
    return FileResponse(_thumbnail_path(name), media_type="image/jpeg")


@app.get("/api/history")
def api_history(limit: int = 100):
    """Every request ever made, with its output. This is the reconciliation surface: if the
    browser dropped the response, the image is still here and the spend is still recorded."""
    conn = _db()
    try:
        return {
            "totals": request_log.usage_totals(conn),
            "requests": [_row_json(row) for row in request_log.recent(conn, limit)],
        }
    finally:
        conn.close()
