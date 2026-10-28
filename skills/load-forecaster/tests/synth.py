"""Synthetic hourly load + multi-station weather with planted balance points (seeded)."""

from __future__ import annotations

import numpy as np
import pandas as pd

TZ = "America/Chicago"
HEAT_BASE_F, COOL_BASE_F = 60.0, 70.0


def weather(start="2020-01-01", end="2024-01-03", seed=3) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    hours = pd.date_range(start, end, freq="h", tz="UTC", inclusive="left")
    doy = hours.dayofyear.to_numpy()
    local_hour = hours.tz_convert(TZ).hour.to_numpy()
    noise = np.cumsum(rng.normal(0, 0.6, len(hours)))
    noise = noise - pd.Series(noise).rolling(240, min_periods=1).mean().to_numpy()
    temp = 55 - 25 * np.cos(2 * np.pi * (doy - 15) / 365.25) \
        + 8 * np.sin(2 * np.pi * (local_hour - 9) / 24) + noise
    good = pd.DataFrame({"station_id": "KGOOD", "hour_start_utc": hours, "temp": temp})
    far = good.assign(station_id="KFAR", temp=temp + rng.normal(0, 6, len(hours)))
    gappy = good.assign(station_id="KGAPPY").sample(frac=0.7, random_state=1).sort_index()
    return pd.concat([good, far, gappy], ignore_index=True)


def load(wx: pd.DataFrame, start="2021-01-01", end="2024-01-01", seed=4) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    good = wx[wx["station_id"] == "KGOOD"].set_index("hour_start_utc")["temp"]
    hours = pd.date_range(start, end, freq="h", tz="UTC", inclusive="left")
    local = hours.tz_convert(TZ)
    tday = good.groupby(good.index.tz_convert(TZ).date).transform("mean").reindex(hours).to_numpy()
    shape = 0.8 + 0.25 * np.exp(-((local.hour - 18) ** 2) / 10) + 0.1 * np.exp(-((local.hour - 8) ** 2) / 4)
    weekend = np.where(local.dayofweek >= 5, 0.88, 1.0)
    daily = 1000 + 12 * np.clip(HEAT_BASE_F - tday, 0, None) + 30 * np.clip(tday - COOL_BASE_F, 0, None)
    mw = shape * weekend * daily * (1 + 0.015 * rng.standard_normal(len(hours)))
    return pd.DataFrame({"hour_start_utc": hours, "load_mw": mw})
