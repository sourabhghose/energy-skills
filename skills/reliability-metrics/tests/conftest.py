"""Shared synthetic fixtures for reliability-metrics tests (offline, seeded)."""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

TZ = "America/Chicago"
N_CUSTOMERS = 100_000


def make_history(seed: int = 7, years=range(2019, 2025), storm_day: str = "2024-07-15",
                 storm_cmi: float = 4_000_000.0) -> pd.DataFrame:
    """One unstepped outage per day with log-normal customer-minutes, plus a planted storm."""
    rng = np.random.default_rng(seed)
    rows = []
    for year in years:
        for day in pd.date_range(f"{year}-01-01", f"{year}-12-31", freq="D"):
            if rng.random() < 0.15:  # zero-SAIDI day
                continue
            cmi = float(np.exp(rng.normal(np.log(50_000), 0.8)))
            rows.append(_row(f"E{day:%Y%m%d}", day, cmi, planned=False))
    storm = pd.Timestamp(storm_day)
    rows.append(_row("STORM", storm, storm_cmi, planned=False))
    rows.append(_row("PLANNED1", pd.Timestamp("2024-03-05"), 30_000.0, planned=True))
    return pd.DataFrame(rows)


def _row(event_id: str, day: pd.Timestamp, cmi: float, planned: bool) -> dict:
    start = (day + pd.Timedelta(hours=12)).tz_localize(TZ)
    customers = 500
    minutes = cmi / customers
    return {"event_id": event_id, "outage_start": start,
            "restore_ts": start + pd.Timedelta(minutes=minutes),
            "customers_restored": customers, "cause_code": "VEG" if planned is False else "PLN",
            "is_planned": planned, "circuit_id": "C1"}


def make_customers(years=range(2019, 2025), growth: int = 1_000) -> pd.DataFrame:
    rows = []
    for i, year in enumerate(years):
        for month in range(1, 13):
            count = N_CUSTOMERS + i * 12 * growth + (month - 1) * growth
            rows.append({"period_start": pd.Timestamp(year, month, 1).date(),
                         "customers_served": count})
    return pd.DataFrame(rows)


@pytest.fixture
def history() -> pd.DataFrame:
    return make_history()


@pytest.fixture
def customers() -> pd.DataFrame:
    return make_customers()
