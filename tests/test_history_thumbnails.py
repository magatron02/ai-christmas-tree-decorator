"""The history table's picture column and the thumbnail behind it.

A finished picture is several megabytes. The point of showing one per row is to answer "was
this the good one?" without fetching the file again, so the preview has to be a genuinely
small image — serving the original and letting CSS shrink it would cost more than the
download it saves.
"""

import pytest
from PIL import Image

from backend import config, main
from helpers import png_bytes


@pytest.fixture
def thumbs(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "THUMBS_DIR", tmp_path / "thumbs")
    return tmp_path / "thumbs"


@pytest.fixture
def stored_output():
    """A stored image the size a real generation produces."""
    return main._store(png_bytes((1536, 1920)), "output", "png")


def test_the_thumbnail_is_small_enough_to_draw_a_hundred_of(client, thumbs, stored_output):
    """History lists up to 100 runs. What matters is the absolute weight of one preview, not
    its ratio to the original — a ratio would pass on this synthetic flat-colour PNG no matter
    what the endpoint did, because a solid image already compresses to almost nothing."""
    response = client.get(f"/api/thumbnail/{stored_output}")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    assert len(response.content) < 100_000, (
        f"{len(response.content)} bytes x 100 rows is more than the page can afford"
    )


def test_the_thumbnail_fits_the_declared_bound(client, thumbs, stored_output):
    client.get(f"/api/thumbnail/{stored_output}")

    made = list(thumbs.glob("*.jpg"))
    assert len(made) == 1
    with Image.open(made[0]) as image:
        assert max(image.size) <= main.THUMB_MAX_PX


def test_a_thumbnail_is_built_once_and_reused(client, thumbs, stored_output):
    client.get(f"/api/thumbnail/{stored_output}")
    made = next(thumbs.glob("*.jpg"))
    first = made.stat().st_mtime_ns

    client.get(f"/api/thumbnail/{stored_output}")

    assert made.stat().st_mtime_ns == first, "the second request should not rebuild it"


def test_no_staging_file_survives(client, thumbs, stored_output):
    """Written to a temporary name and moved into place, so a crash mid-write cannot leave a
    truncated JPEG that is then served as this row's preview forever."""
    client.get(f"/api/thumbnail/{stored_output}")

    assert not list(thumbs.glob("*.part"))


def test_a_filename_we_did_not_write_is_refused(client, thumbs):
    """Same guard as every other stored-file path: the name arrives from the browser."""
    response = client.get("/api/thumbnail/..%2F..%2Fetc%2Fpasswd")

    assert response.status_code in (404, 422)


def test_pruning_an_image_takes_its_thumbnail_with_it(client, thumbs, stored_output, conn):
    """orphans() only globs loose files in storage/, so nothing else would ever collect a
    thumbnail once the image it was made from is gone."""
    from backend.services import storage

    client.get(f"/api/thumbnail/{stored_output}")
    thumb = next(thumbs.glob("*.jpg"))
    assert thumb.is_file()

    storage.prune(conn, older_than_hours=-1)

    assert not (config.STORAGE_DIR / stored_output).exists(), "expected the image to be pruned"
    assert not thumb.exists(), "the thumbnail outlived the image it previews"
