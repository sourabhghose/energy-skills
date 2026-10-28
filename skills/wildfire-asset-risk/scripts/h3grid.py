"""Hexagonal grid indexing for wildfire-asset-risk: H3 when installed, square fallback otherwise.

Purpose
    One small interface the core uses for spatial joins:
        cell_for(lat, lon, res) -> str        point to cell id
        disk(cell, k) -> list[str]            cell plus k rings of neighbours
        parent(cell, res) -> str              coarser cell (for shareable outputs)
    With the `h3` package (v4 API) these are real H3 cells and match Databricks
    h3_longlatash3 / h3_kring / h3_toparent. Without it, a square lat/lon grid with
    H3-like spacing is used so the core and its tests still run; the fallback is NOT
    interchangeable with Databricks H3 ids and logs a warning once.

Pitfall
    Python h3 takes (lat, lng); Databricks h3_longlatash3 takes (longitude, latitude).

Usage
    from h3grid import cell_for, disk, BACKEND
"""

from __future__ import annotations

import logging
import math

LOG = logging.getLogger(__name__)

# Average H3 hexagon edge length in km by resolution (h3geo.org cell statistics).
EDGE_KM = {5: 8.544, 6: 3.229, 7: 1.220, 8: 0.461, 9: 0.174, 10: 0.066, 11: 0.025}
KM_PER_DEG_LAT = 110.574

try:
    import h3 as _h3

    BACKEND = "h3"
except ImportError:  # pragma: no cover - exercised when h3 is absent
    _h3 = None
    BACKEND = "square-fallback"
    LOG.warning("h3 not installed: using square-grid fallback (ids differ from Databricks H3).")


def _check(lat: float, lon: float, res: int) -> None:
    if not -90.0 <= lat <= 90.0:
        raise ValueError(f"latitude {lat} out of range; are lat/lon swapped?")
    if not -180.0 <= lon <= 180.0:
        raise ValueError(f"longitude {lon} out of range")
    if res not in EDGE_KM:
        raise ValueError(f"resolution {res} not supported; use one of {sorted(EDGE_KM)}")


def _spacing_deg(res: int) -> float:
    """Square cell side in degrees latitude with the same area as an H3 hexagon."""
    edge = EDGE_KM[res]
    hex_area = 1.5 * math.sqrt(3) * edge * edge
    return math.sqrt(hex_area) / KM_PER_DEG_LAT


def cell_for(lat: float, lon: float, res: int) -> str:
    _check(lat, lon, res)
    if _h3 is not None:
        return _h3.latlng_to_cell(lat, lon, res)
    step = _spacing_deg(res)
    lon_step = step / max(math.cos(math.radians(lat)), 1e-6)
    return f"{res}:{math.floor(lat / step)}:{math.floor(lon / lon_step)}:{lon_step:.9f}"


def disk(cell: str, k: int) -> list[str]:
    if k < 0:
        raise ValueError("k must be >= 0")
    if _h3 is not None:
        return list(_h3.grid_disk(cell, k))
    res, i, j, lon_step = cell.split(":")
    return [f"{res}:{int(i) + di}:{int(j) + dj}:{lon_step}"
            for di in range(-k, k + 1) for dj in range(-k, k + 1)]


def parent(cell: str, res: int) -> str:
    if _h3 is not None:
        return _h3.cell_to_parent(cell, res)
    own_res, i, j, _ = cell.split(":")
    if res > int(own_res):
        raise ValueError("parent resolution must be coarser")
    ratio = _spacing_deg(res) / _spacing_deg(int(own_res))
    return f"{res}:{math.floor(int(i) / ratio)}:{math.floor(int(j) / ratio)}"


def ring_radius_km(res: int, k: int) -> float:
    """Approximate distance covered by k rings (hex centre spacing = sqrt(3) * edge)."""
    return k * math.sqrt(3) * EDGE_KM[res]
