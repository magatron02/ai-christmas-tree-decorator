"""Input validation — AC-1, Spec.md 3.

Half of these drive backend.validation directly, because it is a pure layer and should stay
provable without a server. The other half go through the endpoints, because AC-1 is about
what the user sees: a readable message and a live app, never a stack trace.
"""

import pytest

from backend import config, validation
from backend.validation import ValidationError

from helpers import gif_bytes, jpeg_bytes, png_bytes, upload, webp_bytes


# ---- file type -------------------------------------------------------------------------


@pytest.mark.parametrize(
    "data, filename, mime",
    [
        (gif_bytes(), "ornament.gif", "image/gif"),
        (webp_bytes(), "ornament.webp", "image/webp"),
        (b"%PDF-1.4 not an image at all", "ornament.pdf", "application/pdf"),
    ],
    ids=["gif", "webp", "pdf"],
)
def test_unsupported_types_are_rejected(data, filename, mime):
    with pytest.raises(ValidationError) as caught:
        validation.check_image(data, filename, mime, "Element image")
    assert "ไม่รองรับ" in str(caught.value)


def test_jpg_and_png_are_accepted():
    assert validation.check_image(png_bytes(), "tree.png", "image/png", "Tree image")[0] == "PNG"
    assert validation.check_image(jpeg_bytes(), "tree.jpg", "image/jpeg", "Tree image")[0] == "JPEG"


def test_a_renamed_file_is_caught_by_its_contents():
    """The extension and the MIME type both say PNG. The bytes do not."""
    with pytest.raises(ValidationError) as caught:
        validation.check_image(b"%PDF-1.4 still not an image", "sneaky.png", "image/png", "Tree image")
    assert "อ่านเป็นรูปภาพไม่ได้" in str(caught.value)


def test_a_real_gif_renamed_to_png_is_caught_by_its_format():
    with pytest.raises(ValidationError) as caught:
        validation.check_image(gif_bytes(), "sneaky.png", "image/png", "Tree image")
    assert "เนื้อไฟล์จริงเป็น GIF" in str(caught.value)


# ---- file size -------------------------------------------------------------------------


def test_oversized_file_is_rejected():
    with pytest.raises(ValidationError) as caught:
        validation.check_size(config.MAX_UPLOAD_BYTES + 1, "Tree image")
    assert "เกินขีดจำกัด 10 MB" in str(caught.value)


def test_empty_file_is_rejected():
    with pytest.raises(ValidationError):
        validation.check_size(0, "Tree image")


def test_size_at_the_limit_is_accepted():
    validation.check_size(config.MAX_UPLOAD_BYTES, "Tree image")


# ---- file count ------------------------------------------------------------------------


def test_more_than_one_element_is_rejected_not_silently_truncated():
    """AC-1 wants a defined behaviour. This is it: two files is an error the user sees."""
    with pytest.raises(ValidationError) as caught:
        validation.exactly_one(["a", "b"], "Element image")
    assert "รับได้ทีละ 1 ไฟล์" in str(caught.value)


def test_zero_files_is_rejected():
    with pytest.raises(ValidationError):
        validation.exactly_one([], "Tree image")


# ---- output size -----------------------------------------------------------------------


def test_the_default_is_the_ratio_product_asked_for():
    assert config.SIZE_PRESETS[config.DEFAULT_SIZE] == (1536, 1920)
    assert validation.resolve_size("4:5") == (1536, 1920)


def test_every_preset_satisfies_the_gpt_image_2_constraints():
    for key in config.SIZE_PRESETS:
        validation.resolve_size(key)


@pytest.mark.parametrize(
    "width, height",
    [(1000, 1920), (1536, 1900), (1536, 5000), (4096, 1024), (256, 1024)],
    ids=["width_not_multiple_of_16", "height_not_multiple_of_16", "too_tall", "too_wide", "ratio_out_of_range"],
)
def test_invalid_dimensions_are_rejected(width, height):
    with pytest.raises(ValidationError):
        validation.validate_dimensions(width, height)


def test_unknown_size_key_is_rejected():
    with pytest.raises(ValidationError) as caught:
        validation.resolve_size("7:3")
    assert "ไม่รู้จักขนาด" in str(caught.value)


# ---- "match the scene photo's own ratio" -----------------------------------------------


def test_resolve_size_accepts_a_literal_wxh_string():
    assert validation.resolve_size("1536x1920") == (1536, 1920)


def test_resolve_size_still_rejects_garbage_containing_an_x():
    with pytest.raises(ValidationError):
        validation.resolve_size("abcxdef")


@pytest.mark.parametrize(
    "ratio", [0.1, 0.333, 0.8, 1.0, 1.5, 1.778, 2.5, 3.0, 10.0],
)
def test_fit_custom_size_always_produces_a_valid_size(ratio):
    width, height = validation.fit_custom_size(ratio)
    # must not raise — validate_dimensions is the same gate every preset goes through
    assert validation.validate_dimensions(width, height) == (width, height)


def test_fit_custom_size_stays_close_to_the_requested_ratio_when_unclamped():
    # 4:5 (0.8) is well inside the allowed range and doesn't hit the max-dimension clamp,
    # so the result should land close to the ratio actually asked for
    width, height = validation.fit_custom_size(0.8)
    assert abs(width / height - 0.8) < 0.02


def test_fit_custom_size_clamps_extreme_ratios_into_the_allowed_range():
    width, height = validation.fit_custom_size(100.0)
    assert config.MIN_RATIO <= width / height <= config.MAX_RATIO

    width, height = validation.fit_custom_size(0.001)
    assert config.MIN_RATIO <= width / height <= config.MAX_RATIO


def test_fit_custom_size_does_not_wildly_inflate_the_pixel_budget():
    """Anchored to DEFAULT_SIZE's pixel count rather than maxed out to MAX_DIMENSION — a shop
    opting into "match my photo" should not silently pay for several times the normal canvas
    just because their room photo is wide."""
    anchor_w, anchor_h = config.SIZE_PRESETS[config.DEFAULT_SIZE]
    anchor_area = anchor_w * anchor_h

    width, height = validation.fit_custom_size(1.0)  # square: no clamp kicks in

    assert width * height < anchor_area * 1.5


# ---- through the API -------------------------------------------------------------------


def test_endpoint_rejects_a_bad_type_with_a_readable_message(client, fake_rembg):
    response = client.post("/api/remove-bg", files=[upload(gif_bytes(), "e.gif", "image/gif")])

    assert response.status_code == 422
    assert "ไม่รองรับ" in response.json()["error"]
    assert fake_rembg.count == 0


def test_endpoint_rejects_two_element_files(client, fake_rembg):
    response = client.post(
        "/api/remove-bg",
        files=[upload(png_bytes(), "one.png"), upload(png_bytes(), "two.png")],
    )

    assert response.status_code == 422
    assert "รับได้ทีละ 1 ไฟล์" in response.json()["error"]
    assert fake_rembg.count == 0


def test_endpoint_rejects_an_oversized_file(client, fake_rembg, monkeypatch):
    monkeypatch.setattr(config, "MAX_UPLOAD_BYTES", 128)

    response = client.post("/api/remove-bg", files=[upload(png_bytes(), "big.png")])

    assert response.status_code == 422
    assert "เกินขีดจำกัด" in response.json()["error"]
    assert fake_rembg.count == 0


def test_prepare_rejects_an_unknown_size(client, fake_rembg):
    cut = client.post("/api/remove-bg", files=[upload(png_bytes(), "element.png")])
    response = client.post(
        "/api/prepare",
        files=[upload(png_bytes(), "tree.png")],
        data={"element": cut.json()["element"], "size": "9:1"},
    )

    assert response.status_code == 422
    assert "ไม่รู้จักขนาด" in response.json()["error"]


def test_prepare_rejects_a_forged_element_path(client, fake_rembg):
    """The element name comes back from the client, so it is re-checked, not trusted."""
    response = client.post(
        "/api/prepare",
        files=[upload(png_bytes(), "tree.png")],
        data={"element": "../../../etc/passwd", "size": "4:5"},
    )

    assert response.status_code == 422
    assert "ไม่รู้จักไฟล์" in response.json()["error"]
