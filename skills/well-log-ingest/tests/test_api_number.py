"""API / UWI validation."""

import pytest

from api_number import check_api


@pytest.mark.parametrize("raw,expected", [
    ("42-123-45678", "42123456780000"),
    ("4212345678", "42123456780000"),
    ("42-123-45678-01", "42123456780100"),
    ("42-123-45678-01-02", "42123456780102"),
])
def test_valid_us_api(raw, expected):
    res = check_api(raw)
    assert res.status == "ok" and res.normalized == expected


def test_leading_zero_lost_is_reported_not_fixed():
    res = check_api("512345678")                      # Colorado 05-123-45678 stored as int
    assert res.status == "leading_zero_lost" and res.normalized is None
    fixed = check_api("512345678", zero_pad="pad")
    assert fixed.status == "ok" and fixed.normalized == "05123456780000"
    assert check_api("512345678", zero_pad="reject").status == "leading_zero_lost"


def test_invalid_state_and_length():
    assert check_api("99-123-45678").status == "invalid_state"
    assert check_api("12345").status == "bad_length"
    assert check_api("").status == "empty"


def test_canadian_dls():
    assert check_api("100/06-12-034-05W5/00").status == "ca_dls"
