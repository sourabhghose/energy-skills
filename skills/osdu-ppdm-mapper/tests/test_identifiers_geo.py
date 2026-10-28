"""API normalization / levels / padding and CRS checks."""

from __future__ import annotations

import pandas as pd
import pytest

from geo import coordinate_issues, resolve_crs, transform_coordinates
from identifiers import api_quality, apply_api_level, detect_api_level, find_collisions, ground_ids, normalize_api


@pytest.mark.parametrize("raw,expected", [
    ("42-301-12345", "4230112345"),
    ("42-301-12345-00-01", "42301123450001"),
    (4230112345.0, "4230112345"),
    ("512345678", "0512345678"),       # Colorado (05) stored as a number loses its zero
    ("12345", None),
    ("42-301-1234", None),             # formatted but short: malformed, never padded
    (None, None),
])
def test_normalize_api(raw, expected):
    assert normalize_api(raw) == expected


def test_api_quality_reasons():
    q = api_quality(pd.Series(["42-301-12345", "512345678", "123", None]))
    assert list(q["reason"]) == ["ok", "leading_zero_restored", "bad_length", "null"]


def test_detect_level_mixed_and_single():
    mixed = detect_api_level(pd.Series(["4230112345", "42301123450001"]))
    assert mixed["mixed_lengths"] and mixed["implied_level"] is None
    single = detect_api_level(pd.Series(["42301123450001", "42301123450100"]))
    assert single["implied_level"] == "completion" and single["distinct_by_level"]["wellbore"] == 2


def test_apply_level_truncates_and_never_pads_silently():
    s = pd.Series(["42301123450001", "4230112345"])
    left = apply_api_level(s, "wellbore", "leave_null")
    assert left.iloc[0] == "423011234500" and pd.isna(left.iloc[1])
    assert list(apply_api_level(s, "wellbore", "pad_zeros")) == ["423011234500", "423011234500"]
    with pytest.raises(ValueError):
        apply_api_level(s, "wellbore", "guess")


def test_collisions_and_grounding():
    df = pd.DataFrame({"id": ["A", "A", "B"], "name": ["X", "Y", "Z"]})
    col = find_collisions(df, "id", ["name"])
    assert list(col["id"]) == ["A"]
    assert ground_ids(["A", "Q"], df["id"]) == (["A"], ["Q"])


def test_resolve_crs():
    assert resolve_crs("NAD27") == "EPSG:4267"
    assert resolve_crs("epsg:32614") == "EPSG:32614"
    with pytest.raises(ValueError):
        resolve_crs("state plane")


def test_coordinate_issues_detects_common_errors():
    lat = pd.Series([31.9, -103.4, 650000.0, 0.0, 31.0])
    lon = pd.Series([-103.4, 31.9, 3200000.0, 0.0, 103.0])
    issues = coordinate_issues(lat, lon, "EPSG:4267", expected_lon_sign=-1).set_index("issue")["count"].to_dict()
    assert issues["possibly_swapped"] == 1
    assert issues["looks_projected"] == 1
    assert issues["zero_zero"] == 1
    assert issues["unexpected_lon_sign"] == 3


def test_transform_same_crs_is_identity():
    lat, lon = transform_coordinates(pd.Series([31.9]), pd.Series([-103.4]), "EPSG:4269", "EPSG:4269")
    assert lat.iloc[0] == 31.9 and lon.iloc[0] == -103.4


def test_transform_without_pyproj_raises():
    try:
        import pyproj  # noqa: F401
    except ImportError:
        with pytest.raises(RuntimeError, match="pyproj"):
            transform_coordinates(pd.Series([31.9]), pd.Series([-103.4]), "EPSG:4267", "EPSG:4269")
    else:
        lat, _ = transform_coordinates(pd.Series([31.9]), pd.Series([-103.4]), "EPSG:4267", "EPSG:4269")
        assert lat.iloc[0] != 31.9  # NAD27 -> NAD83 shifts the point
