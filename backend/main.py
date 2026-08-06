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
import re
import uuid

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
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

app = FastAPI(title="AI Christmas Tree Decorator")
app.mount("/files", StaticFiles(directory=config.STORAGE_DIR), name="files")
app.mount("/static", StaticFiles(directory=config.FRONTEND_DIR), name="static")

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
        raise ValidationError(f"Unknown file '{name}'.")
    path = config.STORAGE_DIR / name
    if not path.is_file():
        raise ValidationError(f"File '{name}' is no longer on disk. Upload it again.")
    return path


def _url(name):
    return f"/files/{name}" if name else None


def _db():
    return request_log.connect()


def _row_json(row):
    elements = request_log.elements_of(row)
    return {
        "request_id": row["request_id"],
        "status": row["status"],
        "elements": [{"url": _url(e["path"]), "code": e.get("code")} for e in elements],
        "reference_url": _url(row["reference_path"]),
        # billed is derived, not stored: a row that carries usage is a row that cost money,
        # so there is no flag that can disagree with the record of what happened
        "billed": row["usage_json"] is not None,
        "size": row["size"],
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


# ---------------------------------------------------------------- api


@app.get("/api/config")
def api_config():
    """So the frontend never re-declares limits that live in config.py."""
    return {
        "sizes": [
            {"key": key, "width": w, "height": h} for key, (w, h) in config.SIZE_PRESETS.items()
        ],
        "default_size": config.DEFAULT_SIZE,
        "max_upload_mb": config.MAX_UPLOAD_BYTES // (1024 * 1024),
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


@app.post("/api/prepare")
def api_prepare(
    files: list[UploadFile] = File(...),
    element: list[str] = Form(...),
    size: str = Form(config.DEFAULT_SIZE),
    tree_code: str = Form(""),
    element_code: list[str] = Form(default=[]),
    reference: str = Form(""),
):
    """Input A + one to five accepted decorations -> a `pending` request. Still free; still
    no API call.

    Product codes are optional but all-or-nothing: with the tree and every decoration named,
    the prompt gets each one's real millimetres (Product.md 8.2). Codes are resolved here
    rather than at generation time so an unknown code costs nothing and is caught before the
    confirm dialog.
    """
    upload = validation.exactly_one(files, "Tree image")
    data = _read(upload, "Tree image")
    fmt, _dimensions = validation.check_image(data, upload.filename, upload.content_type, "Tree image")

    width, height = validation.resolve_size(size)
    names = validation.element_count([e.strip() for e in element if e.strip()])
    paths = [_stored_path(name) for name in names]

    tree_code = tree_code.strip()
    codes = [c.strip() for c in element_code][: len(paths)]
    codes += [""] * (len(paths) - len(codes))
    if any(codes) and not all(codes):
        raise ValidationError(
            "Some decorations have a product code and some do not. Give a code for every "
            "one, or for none — a partial set cannot produce real sizes."
        )

    scale = catalog.scale_sentence(tree_code, codes)
    reference = reference.strip()
    reference_name = _stored_path(reference).name if reference else None
    tree_name = _store(data, "tree", EXT_FOR_FORMAT[fmt])
    elements = [{"path": p.name, "code": c or None} for p, c in zip(paths, codes)]

    conn = _db()
    try:
        request_id = request_log.create(
            conn, tree_name, elements, size, tree_code or None, reference_name
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
        "exact_scale": bool(tree_code and all(codes)),
    }


@app.post("/api/generate/{request_id}")
def api_generate(request_id: str):
    """The paid step. Reached only after the confirm dialog (AC-4)."""
    conn = _db()
    try:
        row = request_log.get(conn, request_id)
        if row is None:
            raise HTTPException(404, "Unknown request.")

        # pending -> calling_api. Losing this race means the request is already running or
        # finished, which is what a double-click looks like from here.
        if not request_log.claim(conn, request_id):
            raise HTTPException(
                409,
                f"This request is already {row['status']}. It will not be generated twice.",
            )

        width, height = validation.resolve_size(row["size"])
        tree_path = _stored_path(row["tree_path"])
        elements = request_log.elements_of(row)
        element_paths = [_stored_path(e["path"]) for e in elements]
        scale = catalog.scale_sentence(row["tree_code"], [e.get("code") for e in elements])

        # Once the request is claimed it must reach a terminal state on every path, or it is
        # stranded at calling_api and can never be retried. So this catches everything, not
        # just ImageGenError — an unexpected failure is still a failure that produced no
        # image and should be runnable again.
        reference = row["reference_path"]
        reference_bytes = _stored_path(reference).read_bytes() if reference else None

        try:
            output, usage = image_gen.generate(
                tree_path.read_bytes(),
                [path.read_bytes() for path in element_paths],
                width, height, scale, reference_bytes,
            )
            name = _store(output, "output", "png")
        except Exception as exc:
            request_log.mark_failed(conn, request_id, exc)
            detail = exc if isinstance(exc, ImageGenError) else f"{type(exc).__name__}: {exc}"
            raise HTTPException(502, f"Generation failed. {detail}") from exc

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
            raise HTTPException(404, "Unknown request.")
        request_log.mark_delivered(conn, request_id)
        return _row_json(request_log.get(conn, request_id))
    finally:
        conn.close()


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
