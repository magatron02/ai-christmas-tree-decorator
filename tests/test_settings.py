"""Settings — Product.md 8.4 under the constraints of NonGoals.md 10.

The API key is the only thing here worth testing hard, and what is being tested is that it
cannot leak: not through a response, not through an error, not into the database, and not
from another machine. Those were written down before the feature was built precisely because
they are the kind of mistake that is invisible until it matters.
"""

import pytest

from backend.services import settings
from backend.validation import ValidationError

FAKE_KEY = "sk-test-0123456789abcdefghijklmnop"


@pytest.fixture
def env(monkeypatch, tmp_path):
    path = tmp_path / ".env"
    path.write_text("OPENAI_API_KEY=sk-existing-0123456789abcdef\nOTHER=keep-me\n", encoding="utf-8")
    monkeypatch.setattr(settings, "ENV_PATH", path)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    return path


def test_the_key_is_never_in_a_response(client, env):
    body = client.get("/api/settings").json()

    assert "sk-" not in str(body)
    assert body["api_key_set"] is True


def test_the_response_says_only_whether_one_is_set(client, env):
    env.write_text("OTHER=keep-me\n", encoding="utf-8")
    assert client.get("/api/settings").json()["api_key_set"] is False


def test_saving_writes_to_env_and_leaves_other_lines_alone(env, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "")
    settings.set_key(FAKE_KEY)

    text = env.read_text(encoding="utf-8")
    assert f"OPENAI_API_KEY={FAKE_KEY}" in text
    assert "OTHER=keep-me" in text
    assert "sk-existing" not in text


def test_the_key_never_goes_into_the_database(client, conn, env, fake_gen, fake_rembg):
    """The log is a spend record that gets copied and backed up. A key inside it travels
    with those copies (NonGoals.md 10)."""
    settings.set_key(FAKE_KEY)

    dump = "".join(line for line in conn.iterdump())
    assert "sk-" not in dump


def test_a_rejected_key_error_does_not_repeat_the_value(env):
    with pytest.raises(ValidationError) as caught:
        settings.set_key("not-a-key-but-secret-looking")

    assert "not-a-key-but-secret-looking" not in str(caught.value)


def test_an_empty_key_is_refused(env):
    with pytest.raises(ValidationError):
        settings.set_key("   ")


def test_setting_a_key_is_localhost_only(client, env, monkeypatch):
    """Reachable from elsewhere, this endpoint replaces someone's credentials. The auth for
    that does not exist, so the door stays shut rather than guarded."""
    monkeypatch.setattr(settings, "is_local", lambda request: False)

    response = client.post("/api/settings/api-key", data={"api_key": FAKE_KEY})

    assert response.status_code == 403
    assert "sk-" not in response.text


def test_a_local_request_is_accepted(client, env, monkeypatch):
    monkeypatch.setattr(settings, "is_local", lambda request: True)
    monkeypatch.setattr(settings, "set_key", lambda value: None)

    response = client.post("/api/settings/api-key", data={"api_key": FAKE_KEY})

    assert response.status_code == 200
    assert "sk-" not in response.text


def test_the_settings_page_never_reads_a_key_back():
    """A password field the browser can repopulate is a key on a shared screen."""
    from backend import config

    script = (config.FRONTEND_DIR / "settings.js").read_text(encoding="utf-8")
    assert "api_key_set" in script
    assert 'input.value = ""' in script, "the field must be cleared after sending"
