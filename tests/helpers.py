"""Test fixtures' raw material: real image bytes, so validation is exercised for real."""

import io

from PIL import Image


def png_bytes(size=(64, 80), color=(20, 60, 30, 255)):
    buf = io.BytesIO()
    Image.new("RGBA", size, color).save(buf, format="PNG")
    return buf.getvalue()


def transparent_png_bytes(size=(64, 64)):
    """What a good rembg cut looks like: RGBA with genuinely transparent pixels."""
    image = Image.new("RGBA", size, (0, 0, 0, 0))
    image.paste((200, 40, 40, 255), (16, 16, 48, 48))
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def jpeg_bytes(size=(64, 80), color=(20, 60, 30)):
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="JPEG")
    return buf.getvalue()


def gif_bytes(size=(8, 8)):
    buf = io.BytesIO()
    Image.new("P", size).save(buf, format="GIF")
    return buf.getvalue()


def webp_bytes(size=(8, 8)):
    buf = io.BytesIO()
    Image.new("RGB", size).save(buf, format="WEBP")
    return buf.getvalue()


def upload(data, filename="tree.png", mime="image/png"):
    """A single multipart part shaped the way the endpoints expect."""
    return ("files", (filename, io.BytesIO(data), mime))
