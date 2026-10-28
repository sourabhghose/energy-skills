"""Weather normalization of energy (what consumption would have been in normal weather).

Fits daily energy on heating/cooling degree days plus day-type, then re-predicts the period
with *normal* degree days and applies the difference to actual energy:

    normalized = actual + (model(normal weather) − model(actual weather))

Normal degree days are the mean of each calendar day's degree days across ``normal_years``,
not the degree days of a mean temperature (averaging temperature first understates them).

    from lf_normalize import daily_frame, normal_degree_days, weather_normalized_energy
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def daily_frame(hourly: pd.DataFrame, tz: str, holiday_dates: set) -> pd.DataFrame:
    """Daily MWh (sum of hourly MW) and mean temperature by local date (full days only)."""
    local = hourly["hour_start_utc"].dt.tz_convert(tz)
    g = hourly.assign(d=local.dt.date).groupby("d")
    daily = pd.DataFrame({"energy_mwh": g["load_mw"].sum(min_count=1), "temp": g["temp"].mean(),
                          "hours": g["load_mw"].count()})
    full = daily["hours"] >= 23  # 23-hour spring-forward days are complete
    idx = pd.to_datetime(daily.index)
    return daily[full].assign(dow=idx[full].dayofweek,
                              is_holiday=[d in holiday_dates for d in daily.index[full]],
                              mmdd=idx[full].strftime("%m-%d"))


def normal_degree_days(weather: pd.DataFrame, tz: str, years: tuple[int, int],
                       hdd_base: float, cdd_base: float) -> pd.DataFrame:
    """Normal HDD / CDD by ``mm-dd`` over ``years`` (inclusive), from daily mean temperatures."""
    local = weather["hour_start_utc"].dt.tz_convert(tz)
    sel = local.dt.year.between(years[0], years[1])
    if not sel.any():
        raise ValueError(f"No weather data in normal_years {years}.")
    daily = weather[sel].groupby(local[sel].dt.date)["temp"].mean()
    mmdd = pd.to_datetime(daily.index).strftime("%m-%d")
    dd = pd.DataFrame({"hdd": (hdd_base - daily).clip(lower=0).to_numpy(),
                       "cdd": (daily - cdd_base).clip(lower=0).to_numpy(), "mmdd": mmdd})
    normals = dd.groupby("mmdd")[["hdd", "cdd"]].mean()
    if "02-29" not in normals.index and "02-28" in normals.index:
        normals.loc["02-29"] = normals.loc["02-28"]
    return normals.assign(years_used=f"{years[0]}-{years[1]}")


def _design(hdd: np.ndarray, cdd: np.ndarray, dow: np.ndarray, hol: np.ndarray) -> np.ndarray:
    return np.column_stack([np.ones(len(hdd)), hdd, cdd, np.eye(7)[dow][:, 1:], hol.astype(float)])


def weather_normalized_energy(daily: pd.DataFrame, normals: pd.DataFrame, hdd_base: float,
                              cdd_base: float) -> dict:
    """Actual vs weather-normalized energy for the days in ``daily`` (see module docstring)."""
    hdd = (hdd_base - daily["temp"]).clip(lower=0).to_numpy()
    cdd = (daily["temp"] - cdd_base).clip(lower=0).to_numpy()
    dow, hol = daily["dow"].to_numpy(), daily["is_holiday"].to_numpy()
    X = _design(hdd, cdd, dow, hol)
    y = daily["energy_mwh"].to_numpy()
    coef, *_ = np.linalg.lstsq(X, y, rcond=None)
    missing = set(daily["mmdd"]) - set(normals.index)
    if missing:
        raise ValueError(f"Normals missing for {len(missing)} calendar days, e.g. {sorted(missing)[:3]}")
    n_hdd = normals.loc[daily["mmdd"], "hdd"].to_numpy()
    n_cdd = normals.loc[daily["mmdd"], "cdd"].to_numpy()
    pred_actual = X @ coef
    pred_normal = _design(n_hdd, n_cdd, dow, hol) @ coef
    resid = y - pred_actual
    actual = float(y.sum())
    return {
        "days": int(len(y)), "actual_mwh": actual,
        "normalized_mwh": float(actual + pred_normal.sum() - pred_actual.sum()),
        "weather_adjustment_mwh": float(pred_normal.sum() - pred_actual.sum()),
        "actual_hdd": float(hdd.sum()), "normal_hdd": float(n_hdd.sum()),
        "actual_cdd": float(cdd.sum()), "normal_cdd": float(n_cdd.sum()),
        "heating_mwh_per_hdd": float(coef[1]), "cooling_mwh_per_cdd": float(coef[2]),
        "fit_r2": float(1 - resid.var() / y.var()),
        "cv_rmse_pct": float(100 * np.sqrt(np.mean(resid ** 2)) / y.mean()),
    }
