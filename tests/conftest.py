"""Test wiring.

Storage and database paths are redirected before backend.main is imported — the app mounts
its storage directory at import time, so patching later would be too late and tests would
scribble into the real ./storage.

Nothing here talks to OpenAI or loads an ONNX model. The billing tests in particular have to
be runnable on every commit, which means the paid call is always a fake.
"""

import shutil
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend import config  # noqa: E402

_TMP = Path(tempfile.mkdtemp(prefix="tree-decorator-tests-"))
config.DATA_DIR = _TMP / "data"
config.STORAGE_DIR = _TMP / "storage"
config.DB_PATH = config.DATA_DIR / "app.db"
config.DATA_DIR.mkdir(parents=True, exist_ok=True)
config.STORAGE_DIR.mkdir(parents=True, exist_ok=True)

from fastapi.testclient import TestClient  # noqa: E402

from backend import main  # noqa: E402
from backend.models import request_log  # noqa: E402
from backend.services import background_removal, credit, image_gen  # noqa: E402

from helpers import png_bytes, transparent_png_bytes  # noqa: E402


def pytest_sessionfinish(session, exitstatus):
    shutil.rmtree(_TMP, ignore_errors=True)


@pytest.fixture(autouse=True)
def fresh_db():
    """One empty database and one empty storage directory per test.

    Both, not just the database: leftover files from an earlier test look exactly like
    orphans to the housekeeping tests, and the app mounts the directory at import time so it
    has to be emptied rather than replaced.
    """
    for suffix in ("", "-wal", "-shm"):
        Path(str(config.DB_PATH) + suffix).unlink(missing_ok=True)
    for leftover in config.STORAGE_DIR.glob("*"):
        if leftover.is_file():
            leftover.unlink()
    conn = request_log.connect()
    yield conn
    conn.close()


@pytest.fixture
def conn(fresh_db):
    return fresh_db


@pytest.fixture
def client():
    with TestClient(main.app) as test_client:
        yield test_client


class Spy:
    """Records every call and does whatever it was told to do."""

    def __init__(self, result=None, error=None):
        self.calls = []
        self.result = result
        self.error = error
        self.delay = 0.0

    def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        if self.delay:
            import time

            time.sleep(self.delay)
        if self.error is not None:
            raise self.error
        return self.result

    @property
    def count(self):
        return len(self.calls)


FAKE_USAGE = {
    "input_tokens": 340,
    "output_tokens": 6208,
    "total_tokens": 6548,
    "input_tokens_details": {"text_tokens": 212, "image_tokens": 128},
}


@pytest.fixture
def fake_gen(monkeypatch):
    """Stands in for the one paid call in the app: (image bytes, token usage)."""
    spy = Spy(result=(png_bytes((32, 40)), FAKE_USAGE))
    monkeypatch.setattr(image_gen, "generate", spy)
    return spy


@pytest.fixture
def fake_rembg(monkeypatch):
    spy = Spy(result=transparent_png_bytes())
    monkeypatch.setattr(background_removal, "remove_background", spy)
    return spy


@pytest.fixture
def funded(conn):
    """A balance to spend, so a missing credit never masks a billing bug."""
    credit.topup(conn, 5)
    return 5
