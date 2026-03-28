import pytest
from fastapi import HTTPException

from validators import (
    EMAIL_MAX,
    PASSWORD_MAX,
    TOKEN_MAX,
    USERNAME_MAX,
    UUID_MAX,
    parse_uuid,
)


def test_parse_uuid_valid():
    result = parse_uuid("550e8400-e29b-41d4-a716-446655440000")
    assert result == "550e8400-e29b-41d4-a716-446655440000"


def test_parse_uuid_invalid():
    with pytest.raises(HTTPException) as exc_info:
        parse_uuid("not-a-uuid")
    assert exc_info.value.status_code == 422


def test_parse_uuid_rejects_empty():
    with pytest.raises(HTTPException):
        parse_uuid("")


def test_field_limits_defined():
    assert PASSWORD_MAX == 128
    assert EMAIL_MAX == 254
    assert USERNAME_MAX == 20
    assert TOKEN_MAX == 2048
    assert UUID_MAX == 36
