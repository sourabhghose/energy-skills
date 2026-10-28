"""Synthetic network + hazard layers for wildfire-asset-risk tests (offline, seeded)."""

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from h3grid import cell_for  # noqa: E402

RES = 9
LAT0, LON0 = 38.50, -122.50


def make_segments() -> pd.DataFrame:
    """Three circuits; circuit A runs through the hazardous, populated area."""
    rows = []
    for c, (dlat, tier) in enumerate([(0.0, "Tier 3"), (0.05, "Tier 2"), (0.10, None)]):
        for s in range(5):
            lon1 = LON0 + s * 0.01
            rows.append({"segment_id": f"{'ABC'[c]}{s}", "circuit_id": "ABC"[c],
                         "lat1": LAT0 + dlat, "lon1": lon1, "lat2": LAT0 + dlat,
                         "lon2": lon1 + 0.01, "hftd_tier": tier})
    return pd.DataFrame(rows)


def _cells_along(lat: float, lon_from: float, lon_to: float, n: int = 40) -> list[str]:
    return sorted({cell_for(lat, lon_from + (lon_to - lon_from) * i / n, RES) for i in range(n + 1)})


def make_layers() -> dict:
    a = _cells_along(LAT0, LON0, LON0 + 0.05)
    b = _cells_along(LAT0 + 0.05, LON0, LON0 + 0.05)
    c = _cells_along(LAT0 + 0.10, LON0, LON0 + 0.05)
    veg = [(x, 0.9) for x in a] + [(x, 0.4) for x in b] + [(x, 0.1) for x in c]
    fuel = [(x, "SH5") for x in a] + [(x, "GR2") for x in b] + [(x, "NB1") for x in c]
    slope = [(x, 30.0) for x in a] + [(x, 10.0) for x in b] + [(x, 2.0) for x in c]
    return {
        "vegetation": pd.DataFrame(veg, columns=["cell", "veg_strike_index"]),
        "fuel": pd.DataFrame(fuel, columns=["cell", "fbfm40"]),
        "slope": pd.DataFrame(slope, columns=["cell", "slope_deg"]),
        "ignitions": pd.DataFrame({"cell": [a[3], a[10]], "n_ignitions": [2, 1]}),
        "exposure": pd.DataFrame({"cell": a + c[:3],
                                  "structures": [40] * len(a) + [1] * len(c[:3]),
                                  "population": [100] * len(a) + [2] * len(c[:3])}),
    }


def make_forecast(gust: float = 55.0, rh: float = 12.0) -> pd.DataFrame:
    hours = pd.date_range("2025-10-01 00:00", periods=6, freq="h", tz="America/Los_Angeles")
    cells = _cells_along(LAT0, LON0, LON0 + 0.05) + _cells_along(LAT0 + 0.10, LON0, LON0 + 0.05)
    rows = [{"cell": x, "valid_ts": h, "wind_gust_mph": gust, "wind_sustained_mph": gust * 0.55,
             "rh_pct": rh, "temp_f": 85.0} for x in cells for h in hours]
    return pd.DataFrame(rows)


WEIGHTS = {"vegetation": 0.4, "fuel": 0.3, "slope": 0.1, "ignition_history": 0.2}


@pytest.fixture
def segments() -> pd.DataFrame:
    return make_segments()


@pytest.fixture
def layers() -> dict:
    return make_layers()


@pytest.fixture
def forecast() -> pd.DataFrame:
    return make_forecast()
