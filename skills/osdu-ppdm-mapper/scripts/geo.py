"""Coordinate reference system (CRS) checks for well locations.

Purpose: never mix datums silently. NAD27 and NAD83 latitude/longitude for the same well can
differ by tens of metres (up to ~100 m in parts of North America), and nothing in the numbers
says which datum they are on. The source CRS is therefore a user decision. This module
validates coordinates against the declared CRS, spots typical ingestion errors (swapped
lat/lon, missing minus sign, projected values in a geographic column), and transforms
coordinates only when pyproj is installed and the user asked for a target CRS.

Usage:
    from geo import resolve_crs, coordinate_issues, transform_coordinates
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

LOG = logging.getLogger(__name__)

KNOWN_CRS: dict[str, dict] = {
    "EPSG:4267": {"name": "NAD27 (geographic)", "geographic": True},
    "EPSG:4269": {"name": "NAD83 (geographic)", "geographic": True},
    "EPSG:4326": {"name": "WGS 84 (geographic)", "geographic": True},
    "EPSG:6318": {"name": "NAD83(2011) (geographic)", "geographic": True},
    "EPSG:4230": {"name": "ED50 (geographic)", "geographic": True},
    "EPSG:4258": {"name": "ETRS89 (geographic)", "geographic": True},
}
ALIASES = {"NAD27": "EPSG:4267", "NAD83": "EPSG:4269", "WGS84": "EPSG:4326", "WGS 84": "EPSG:4326",
           "NAD83(2011)": "EPSG:6318", "ED50": "EPSG:4230", "ETRS89": "EPSG:4258"}


def resolve_crs(value: str) -> str:
    """Return an 'EPSG:<code>' string for an alias or explicit EPSG code."""
    text = str(value).strip().upper().replace(" ", "") if value else ""
    for alias, code in ALIASES.items():
        if text == alias.upper().replace(" ", ""):
            return code
    if text.startswith("EPSG:") and text[5:].isdigit():
        return text
    raise ValueError(f"Unrecognized CRS {value!r}; pass an EPSG code such as 'EPSG:4267'")


def is_geographic(crs: str) -> bool | None:
    """True/False for known CRS; None when unknown (assume projected and require pyproj)."""
    info = KNOWN_CRS.get(crs)
    return info["geographic"] if info else None


def coordinate_issues(lat: pd.Series, lon: pd.Series, crs: str,
                      expected_lon_sign: int | None = None) -> pd.DataFrame:
    """Row-level coordinate problems for a declared geographic CRS.

    `expected_lon_sign=-1` (e.g. North America) flags positive longitudes as a likely missing
    minus sign. Returns columns: issue, count, example_index.
    """
    if is_geographic(crs) is False:
        return pd.DataFrame([{"issue": "projected_crs_declared", "count": int(lat.notna().sum()),
                              "example_index": None}])
    la = pd.to_numeric(lat, errors="coerce")
    lo = pd.to_numeric(lon, errors="coerce")
    checks = {
        "non_numeric": (lat.notna() & la.isna()) | (lon.notna() & lo.isna()),
        "missing": la.isna() & lo.isna(),
        "looks_projected": (la.abs() > 90) & (lo.abs() > 180),
        "lat_out_of_range": (la.abs() > 90) & ~((la.abs() > 90) & (lo.abs() > 180)),
        "lon_out_of_range": (lo.abs() > 180) & ~((la.abs() > 90) & (lo.abs() > 180)),
        "possibly_swapped": (la.abs() > 90) & (lo.abs() <= 90),
        "zero_zero": (la == 0) & (lo == 0),
    }
    if expected_lon_sign in (-1, 1):
        checks["unexpected_lon_sign"] = np.sign(lo) == -expected_lon_sign
    rows = [{"issue": k, "count": int(m.fillna(False).sum()),
             "example_index": (m.fillna(False)[m.fillna(False)].index[0] if m.fillna(False).any() else None)}
            for k, m in checks.items()]
    return pd.DataFrame(rows).query("count > 0").reset_index(drop=True)


def transform_coordinates(lat: pd.Series, lon: pd.Series, source_crs: str,
                          target_crs: str) -> tuple[pd.Series, pd.Series]:
    """Datum/CRS transform with pyproj (always_xy). Raises if pyproj is unavailable."""
    if source_crs == target_crs:
        return lat.astype(float), lon.astype(float)
    try:
        from pyproj import Transformer
    except ImportError as exc:
        raise RuntimeError(
            f"Transforming {source_crs} -> {target_crs} needs pyproj; install it or keep "
            "coordinates as ingested (target_crs=None)") from exc
    transformer = Transformer.from_crs(source_crs, target_crs, always_xy=True)
    x, y = transformer.transform(lon.astype(float).to_numpy(), lat.astype(float).to_numpy())
    LOG.info("transformed %d coordinates %s -> %s", len(x), source_crs, target_crs)
    return pd.Series(y, index=lat.index), pd.Series(x, index=lon.index)
