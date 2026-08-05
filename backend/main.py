"""FastAPI app.

The pipeline is split across endpoints so that the expensive step is reachable only by a
deliberate act:

    /api/remove-bg   free   background removal, user sees the preview and can reject it
    /api/prepare     free   validates, writes a `pending` row, returns what the dialog shows
    /api/generate    PAID   claims the row, calls gpt-image-2, charges on success only
    /api/delivered   free   the browser confirms it actually rendered the result

Nothing chains automatically: a failed background removal cannot walk into a paid call,
because the paid call is a different request that only exists after the user confirms
(NonGoals.md #3 and #4, AC-4).

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
from backend.services import background_removal, credit, image_gen
from backend.services.background_removal import BackgroundRemovalError
from backend.services.image_gen import ImageGenError
from backend.validation import ValidationError

load_dotenv(config.ROOT / ".env")

config.STORAGE_DIR.mkdir(parents=True, exist_ok=True)
config.DATA_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="AI Christmas Tree Decorator")
app.mount("/files", StaticFiles(directory=config.STORAGE_DIR), name="files")
app.mount("/static", StaticFiles(directory=config.FRONTEND_DIR), name="static")

STORED_NAME = re.compile(r"^[0-9a-f]{32}_(tree|element|output)\.(png|jpg)$")
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
    return {
        "request_id": row["request_id"],
        "status": row["status"],
        "charged": bool(row["charged"]),
        "size": row["size"],
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


@app.get("/api/balance")
def api_balance():
    conn = _db()
    try:
        return {"credits": credit.balance(conn)}
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


@app.post("/api/prepare")
def api_prepare(
    files: list[UploadFile] = File(...),
    element: str = Form(...),
    size: str = Form(config.DEFAULT_SIZE),
):
    """Input A + an accepted element -> a `pending` request. Still free; still no API call."""
    upload = validation.exactly_one(files, "Tree image")
    data = _read(upload, "Tree image")
    fmt, _dimensions = validation.check_image(data, upload.filename, upload.content_type, "Tree image")

    width, height = validation.resolve_size(size)
    element_path = _stored_path(element)
    tree_name = _store(data, "tree", EXT_FOR_FORMAT[fmt])

    conn = _db()
    try:
        request_id = request_log.create(conn, tree_name, element_path.name, size)
        credits = credit.balance(conn)
    finally:
        conn.close()

    return {
        "request_id": request_id,
        "size": size,
        "width": width,
        "height": height,
        "tree_url": _url(tree_name),
        "element_url": _url(element_path.name),
        "credits": credits,
        "cost": 1,
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

        if not credit.has_credit(conn):
            request_log.mark_failed(conn, request_id, "not enough credit")
            raise HTTPException(402, "Not enough credit. Top up before generating.")

        width, height = validation.resolve_size(row["size"])
        tree_path = _stored_path(row["tree_path"])
        element_path = _stored_path(row["element_path"])

        # Once the request is claimed it must reach a terminal state on every path, or it is
        # stranded at calling_api and can never be retried. So this catches everything, not
        # just ImageGenError — an unexpected failure is still a failure the user paid nothing
        # for and should be able to run again.
        try:
            output, usage = image_gen.generate(
                tree_path.read_bytes(), element_path.read_bytes(), width, height
            )
            name = _store(output, "output", "png")
        except Exception as exc:
            request_log.mark_failed(conn, request_id, exc)
            detail = exc if isinstance(exc, ImageGenError) else f"{type(exc).__name__}: {exc}"
            raise HTTPException(502, f"Generation failed, no credit was used. {detail}") from exc

        request_log.mark_success(conn, request_id, name, usage)
        credit.charge_for(conn, request_id)  # the only charge site in the app

        return _row_json(request_log.get(conn, request_id)) | {"credits": credit.balance(conn)}
    finally:
        conn.close()


@app.post("/api/delivered/{request_id}")
def api_delivered(request_id: str):
    """The browser saying it rendered the result. Purely a reconciliation marker: a row left
    at api_success is one the user paid for but may never have seen (Spec.md 7)."""
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
    browser dropped the response, the image is still here and the credit is accounted for."""
    conn = _db()
    try:
        return {
            "credits": credit.balance(conn),
            "requests": [_row_json(row) for row in request_log.recent(conn, limit)],
        }
    finally:
        conn.close()
