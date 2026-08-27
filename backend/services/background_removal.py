"""rembg wrapper (Product.md 4 step 3, Spec.md 3).

Failure here must stop the run. It never continues into the paid step on its own — the API
call lives behind a separate endpoint and a confirm dialog, so "rembg failed" costs nothing
by construction rather than by remembering to check a flag (NonGoals.md #3, AC-4).
"""

import io
import threading

from PIL import Image

_session = None
# _session_once can now be reached from two threads at once — the desktop launcher warms the
# model in the background while the user is free to pick something immediately. Without the
# lock both threads see None and each builds its own onnx session, paying the load twice.
_session_lock = threading.Lock()


class BackgroundRemovalError(RuntimeError):
    """Message is user-facing: the user re-uploads or cuts the element by hand instead."""


def _session_once():
    # the u2net model is ~180 MB and downloads on first use; don't pay for it at import time
    global _session
    with _session_lock:
        if _session is None:
            from rembg import new_session

            _session = new_session()
    return _session


def warm():
    """Build the onnx session now, so the first cut-out does not have to.

    Loading the model is what made the first background removal take 10s on a dev box and 68s
    on a cold installed copy — long enough that picking a decoration from the catalogue read
    as the program hanging. Nothing here needs the result: the point is only that _session is
    populated by the time a user gets around to clicking. Failures are swallowed because this
    is speculative work — if the model is genuinely broken the real call will say so properly.
    """
    try:
        _session_once()
    except Exception:
        pass


def remove_background(data):
    """JPG/PNG bytes in, transparent RGBA PNG bytes out.

    AC-2 asks for a verified alpha channel, not just the absence of an exception, so the
    output is opened and checked. A fully opaque result means nothing was cut, which is a
    failure the user needs to see before it reaches the tree.
    """
    from rembg import remove

    try:
        cut = remove(data, session=_session_once(), force_return_bytes=True)
    except Exception as exc:  # rembg raises whatever onnxruntime/PIL raise underneath
        raise BackgroundRemovalError(f"ตัดพื้นหลังไม่สำเร็จ: {exc}") from exc

    try:
        image = Image.open(io.BytesIO(cut))
        image.load()
    except Exception as exc:
        raise BackgroundRemovalError(f"ตัดพื้นหลังแล้วได้ไฟล์ภาพที่เสีย อ่านไม่ได้: {exc}") from exc

    if image.mode != "RGBA":
        raise BackgroundRemovalError(
            "ตัดพื้นหลังแล้วไม่มี alpha channel — ใช้รูปที่ชัดกว่านี้ "
            "หรือตัดพื้นหลังเองแล้วอัปโหลด PNG แบบโปร่งใส"
        )
    if image.getchannel("A").getextrema()[0] == 255:
        raise BackgroundRemovalError(
            "ตัดพื้นหลังแล้วไม่มีอะไรถูกตัดออกเลย ทั้งภาพยังทึบอยู่ — "
            "ส่วนใหญ่เกิดจากของตกแต่งกับพื้นหลังสีใกล้กันเกินไป"
        )

    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()
