"""Pre-cut catalogue photos (scripts/precut_catalog.py) and the endpoint that prefers them.

A catalogue photo never changes, so its cut-out never changes either — running rembg on every
pick was recomputing a constant, and that recomputation is what made choosing a decoration
feel like the program had frozen. These pin the two halves that matter: a pre-cut file is used
instead of rembg, and a missing one still falls back to cutting live rather than failing.
"""

import pytest

from backend import main
from helpers import transparent_png_bytes


@pytest.fixture
def cutouts(tmp_path, monkeypatch):
    """Point the app at an empty cut-out directory alongside the real catalogue images."""
    monkeypatch.setattr(main, "CATALOG_CUTOUTS", tmp_path)
    return tmp_path


def _a_pickable_image():
    """A catalogue image the picker can actually offer, as (code, image name)."""
    from backend.services import catalog

    rows, _total = catalog.browse(50, 0)
    for row in rows:
        name = catalog.image_for(row["code"])
        if name and (main.CATALOG_IMAGES / name).is_file():
            return row["code"], name
    pytest.skip("no showable catalogue image with a file on disk")


def test_a_precut_file_is_used_instead_of_running_rembg(client, cutouts, fake_rembg):
    code, name = _a_pickable_image()
    target = cutouts / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(transparent_png_bytes())

    response = client.post("/api/element/from-catalog", data={"code": code})

    assert response.status_code == 200
    assert fake_rembg.count == 0, "a pre-cut photo must not be cut again"


def test_without_a_precut_file_it_still_cuts_live(client, cutouts, fake_rembg):
    """The cut-outs are an optimisation, not a requirement — a product added after the last
    pre-cut run has to keep working, just slower."""
    code, _name = _a_pickable_image()

    response = client.post("/api/element/from-catalog", data={"code": code})

    assert response.status_code == 200
    assert fake_rembg.count == 1


def test_precut_only_covers_images_the_picker_can_reach(cutouts):
    """Of the PNGs on disk only a fraction are offerable — the rest belong to codes that are
    contested, share a crop with too many others, or are page furniture. Cutting those would
    be minutes and megabytes spent on pictures nobody can pick."""
    from scripts.precut_catalog import reachable_images
    from backend.services import catalog

    reachable = reachable_images()
    assert reachable, "expected the catalogue to offer something"

    on_disk = {p.relative_to(main.CATALOG_IMAGES).as_posix()
               for p in main.CATALOG_IMAGES.rglob("*.png")}
    assert set(reachable) <= on_disk
    assert len(reachable) < len(on_disk), "expected some images to be unreachable"

    showable = {row["code"] for row in catalog.browse(10_000, 0)[0]}
    assert all(catalog.crop_is_showable(code) for code in showable)
