"""Synthetic AMI fixtures with planted truth (offline, seeded)."""

from __future__ import annotations

import numpy as np
import pandas as pd

TZ = "America/Chicago"


def true_profile(start_utc: str, end_utc: str, interval_minutes: int = 15,
                 seed: int = 7) -> pd.DataFrame:
    """Ground-truth interval kWh on a UTC grid with a residential daily shape."""
    rng = np.random.default_rng(seed)
    grid = pd.date_range(start_utc, end_utc, freq=f"{interval_minutes}min", tz="UTC",
                         inclusive="left")
    hour = grid.tz_convert(TZ).hour + grid.tz_convert(TZ).minute / 60
    shape = 0.25 + 0.35 * np.exp(-((hour - 19) ** 2) / 6) + 0.15 * np.exp(-((hour - 7) ** 2) / 3)
    kwh = shape * interval_minutes / 15 * (1 + 0.05 * rng.standard_normal(len(grid)))
    return pd.DataFrame({"interval_start_utc": grid, "kwh": np.round(np.clip(kwh, 0.01, None), 4)})


def to_ending_local_labels(truth: pd.DataFrame, interval_minutes: int = 15) -> pd.Series:
    """Interval-ending wall-clock labels without offset, as many head-ends export them."""
    end = truth["interval_start_utc"] + pd.Timedelta(minutes=interval_minutes)
    return end.dt.tz_convert(TZ).dt.tz_localize(None)


def raw_meter(meter_id: str = "M1", start: str = "2024-10-20 05:00", end: str = "2024-11-20 06:00",
              seed: int = 7) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(raw export, truth) for one clean meter."""
    truth = true_profile(start, end, seed=seed)
    raw = pd.DataFrame({"meter_id": meter_id, "read_ts": to_ending_local_labels(truth),
                        "value": truth["kwh"], "quality": "A"})
    return raw, truth.assign(meter_id=meter_id)


def to_register(truth: pd.DataFrame, start_reading: float, rollover: float) -> pd.DataFrame:
    """Cumulative register reads at interval ends (wrapping at ``rollover``)."""
    cum = (start_reading + truth["kwh"].cumsum()) % rollover
    end = truth["interval_start_utc"] + pd.Timedelta(minutes=15)
    first = pd.DataFrame({"read_ts": [truth["interval_start_utc"].iloc[0]],
                          "value": [start_reading]})
    reads = pd.DataFrame({"read_ts": end, "value": cum})
    out = pd.concat([first, reads], ignore_index=True)
    return out.assign(read_ts=out["read_ts"].dt.tz_convert("UTC").dt.tz_localize(None),
                      meter_id="R1")
