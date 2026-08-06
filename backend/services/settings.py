"""The one setting that lives on the server: the OpenAI API key.

Product.md 8.4, under the constraints NonGoals.md 10 fixed before this was built:

  * write-only. The value never travels back to the browser, in any response, ever. The only
    thing readable is whether one is set.
  * .env and nowhere else. Not SQLite — that database is a spend record that gets copied and
    backed up, and a key inside it travels with those copies.
  * never in a log or an error. A failure says a key is missing, not what it was.
  * localhost only. Enforced by the caller; binding wider turns this into a way to read and
    replace someone's credentials, and the auth for that has to exist first.

Theme is not here. It is a browser preference and lives in localStorage, so nothing about
how the page looks needs a server round trip or a second place to go stale.
"""

import re

from backend import config
from backend.validation import ValidationError

ENV_PATH = config.ROOT / ".env"
KEY_NAME = "OPENAI_API_KEY"

# loose on purpose: OpenAI has changed the prefix and the length more than once, and a
# validator that is stricter than reality rejects working keys
KEY_SHAPE = re.compile(r"^sk-[A-Za-z0-9._\-]{16,}$")


def is_set():
    """True when a key is configured, from the environment or the file. Never says which."""
    import os

    if os.environ.get(KEY_NAME, "").strip():
        return True
    return bool(_read_env().get(KEY_NAME, "").strip())


def _read_env():
    if not ENV_PATH.is_file():
        return {}
    values = {}
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        values[name.strip()] = value.strip().strip('"').strip("'")
    return values


def set_key(value):
    """Write the key to .env, leaving every other line as it was.

    Raises ValidationError with a message that never contains the value — an error string
    is the easiest place for a credential to end up in a log.
    """
    value = (value or "").strip()
    if not value:
        raise ValidationError("Paste an API key first.")
    if not KEY_SHAPE.match(value):
        raise ValidationError(
            "That does not look like an OpenAI API key. It should start with 'sk-'. "
            "Create one at platform.openai.com/api-keys."
        )

    lines = ENV_PATH.read_text(encoding="utf-8").splitlines() if ENV_PATH.is_file() else []
    replaced = False
    for index, line in enumerate(lines):
        if line.strip().startswith(f"{KEY_NAME}="):
            lines[index] = f"{KEY_NAME}={value}"
            replaced = True
            break
    if not replaced:
        lines.append(f"{KEY_NAME}={value}")

    ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # so the running process picks it up without a restart
    import os

    os.environ[KEY_NAME] = value


def is_local(request):
    """Whether this request came from the machine the app is running on."""
    host = (request.client.host if request.client else "") or ""
    return host in {"127.0.0.1", "::1", "localhost"}
