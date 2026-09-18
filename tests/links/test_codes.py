import pytest
from django.core.exceptions import ValidationError

from apps.links import codes


def test_generated_codes_use_the_unambiguous_alphabet_and_default_length(settings):
    settings.LINK_CODE_LENGTH = 7
    generated = {codes.generate_code() for _ in range(200)}
    assert len(generated) == 200
    for code in generated:
        assert len(code) == 7
        assert set(code) <= set(codes.ALPHABET)
    for confusable in "O0Il1o":
        assert confusable not in codes.ALPHABET


def test_alphabet_has_no_uppercase():
    assert codes.ALPHABET == codes.ALPHABET.lower()


def test_normalize_code_strips_and_lowercases():
    assert codes.normalize_code("  Spring-Drop  ") == "spring-drop"


@pytest.mark.parametrize(
    "code", ["ab", "-abc", "abc-", "a b", "admin", "x" * 41, "spring/drop", ""]
)
def test_validate_code_rejects_bad_values(code):
    with pytest.raises(ValidationError):
        codes.validate_code(code)


@pytest.mark.parametrize("code", ["spring-drop", "k3f9xa", "nl_jul", "abc"])
def test_validate_code_accepts_good_values(code):
    assert codes.validate_code(code) == code


@pytest.mark.parametrize(
    "code",
    [
        "dashboard",
        "pricing",
        "blog",
        "docs",
        "app",
        "assets",
        "signin",
        "register",
        "account",
        "billing",
        "contact",
    ],
)
def test_validate_code_rejects_the_extended_reserved_words(code):
    with pytest.raises(ValidationError):
        codes.validate_code(code)
