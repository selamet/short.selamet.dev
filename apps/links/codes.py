"""Short code generation and validation.

Codes are global, not per workspace: two workspaces cannot both own /spring-drop.
"""

import re
import secrets

from django.conf import settings
from django.core.exceptions import ValidationError

from .reserved import RESERVED_CODES

# Lowercase letters and digits, minus the characters people mistype when reading a
# code aloud or off a screen (l, o, 0, 1). Codes are compared case-insensitively (see
# `normalize_code`), so the generator only ever emits lowercase.
ALPHABET = "abcdefghijkmnpqrstuvwxyz23456789"

CODE_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,38}[a-z0-9]$")


def generate_code(length=None):
    length = length or settings.LINK_CODE_LENGTH
    return "".join(secrets.choice(ALPHABET) for _ in range(length))


def normalize_code(code):
    return (code or "").strip().lower()


def validate_code(code):
    code = normalize_code(code)
    if not CODE_RE.match(code):
        raise ValidationError(
            "Use 3 to 40 letters, numbers, hyphens or underscores, starting and ending "
            "with a letter or number."
        )
    if code in RESERVED_CODES:
        raise ValidationError("Reserved word — pick another code.")
    return code
