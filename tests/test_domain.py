from domain.classes import (
    CLASS_COLORS,
    CLASS_IDS,
    CLASS_NAMES,
    FEEDBACK_CLASS_NAMES,
    UNKNOWN_CLASS,
    VALID_CLASSES,
    is_supported_class,
)
from domain.auth_policy import (
    ACCESS_TOKEN_EXPIRES_IN,
    FAILED_LOGIN_LIMIT,
    LOCKOUT_MINUTES,
    PASSWORD_MIN_LENGTH,
    USERNAME_PATTERN,
)


def test_class_names():
    assert CLASS_NAMES == ("Plastic", "Glass", "Metal", "Paper")


def test_class_ids_match_names():
    for idx, name in enumerate(CLASS_NAMES):
        assert CLASS_IDS[name] == idx


def test_all_classes_have_colors():
    for name in CLASS_NAMES:
        assert name in CLASS_COLORS


def test_feedback_includes_unknown():
    assert UNKNOWN_CLASS in FEEDBACK_CLASS_NAMES
    for name in CLASS_NAMES:
        assert name in FEEDBACK_CLASS_NAMES


def test_is_supported_class():
    assert is_supported_class("Plastic") is True
    assert is_supported_class("Unknown") is False
    assert is_supported_class("") is False


def test_valid_classes_set():
    assert VALID_CLASSES == {"Plastic", "Glass", "Metal", "Paper"}


def test_auth_policy_sane():
    assert PASSWORD_MIN_LENGTH >= 8
    assert FAILED_LOGIN_LIMIT >= 3
    assert LOCKOUT_MINUTES >= 1
    assert ACCESS_TOKEN_EXPIRES_IN > 0
    assert USERNAME_PATTERN
