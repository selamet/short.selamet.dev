"""Guard rails for .env.example: it must document every env var settings read,
and it must never contain a value that overrides the settings module choice."""

import re
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
ENV_EXAMPLE_PATH = BASE_DIR / ".env.example"
SETTINGS_DIR = BASE_DIR / "config" / "settings"

# Matches env("KEY", ...), env.list("KEY", ...), env.db("KEY"), env.cache("KEY", ...),
# env.bool("KEY", ...).
ENV_CALL_PATTERN = re.compile(r'\benv(?:\.(?:list|db|cache|bool))?\(\s*["\'](\w+)["\']')


def _referenced_keys():
    keys = set()
    for path in SETTINGS_DIR.glob("*.py"):
        keys.update(ENV_CALL_PATTERN.findall(path.read_text()))
    return keys


def test_env_example_does_not_override_the_settings_module_choice():
    lines = ENV_EXAMPLE_PATH.read_text().splitlines()
    offending = [
        line
        for line in lines
        if line.strip().startswith("DJANGO_SETTINGS_MODULE=")
        or line.strip().startswith("TASKS_BACKEND=")
    ]
    assert offending == []


def test_env_example_documents_every_settings_key():
    content = ENV_EXAMPLE_PATH.read_text()
    missing = [
        key
        for key in _referenced_keys()
        if not re.search(rf"^#?\s*{re.escape(key)}=", content, re.MULTILINE)
    ]
    assert missing == []
