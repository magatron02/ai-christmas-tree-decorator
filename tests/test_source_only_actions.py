"""Catalogue sync and supplier price-list import re-run project scripts as a subprocess of
sys.executable — which only works from a source checkout (issue #36). An installed (frozen)
copy must refuse them with a plain explanation, before doing anything, instead of failing
opaquely halfway through."""

import pytest

from backend import config
from backend.services import settings, vendor_admin
from backend.validation import ValidationError


@pytest.fixture
def local(monkeypatch):
    monkeypatch.setattr(settings, "is_local", lambda request: True)


@pytest.fixture
def frozen(monkeypatch):
    monkeypatch.setattr(config, "FROZEN", True)


@pytest.fixture
def no_subprocess(monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("a frozen copy must not shell out")

    # both callers use subprocess.run (main imports it inside the handler), so patch it at the source
    monkeypatch.setattr("subprocess.run", boom)


def test_a_frozen_copy_refuses_catalogue_sync_with_a_reason(client, local, frozen, no_subprocess):
    response = client.post("/api/catalog/sync")

    assert response.status_code == 409
    assert "ซอร์สโค้ด" in response.json()["error"]


def test_a_frozen_copy_refuses_price_list_import_before_touching_disk(
    frozen, no_subprocess, tmp_path, monkeypatch
):
    monkeypatch.setattr(config, "VENDOR_PRICELISTS_DIR", tmp_path)

    with pytest.raises(ValidationError, match="ซอร์สโค้ด"):
        vendor_admin.import_pricelist("bangkok-christmas", b"%PDF-1.4 fake", "new.pdf")

    assert list(tmp_path.iterdir()) == []  # nothing written, not even the source folder


def test_settings_says_whether_this_copy_can_run_the_scripts(client, monkeypatch):
    assert client.get("/api/settings").json()["frozen"] is False

    monkeypatch.setattr(config, "FROZEN", True)
    assert client.get("/api/settings").json()["frozen"] is True
