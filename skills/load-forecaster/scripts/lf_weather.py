"""Weather handling for load-forecaster: station ranking, unit check, gap fill, balance point,
and normal-weather daily temperatures. Pure pandas / numpy.

Weather input: ``station_id``, ``hour_start_utc`` (tz-aware UTC), ``temp`` (one unit for all).

    from lf_weather import rank_stations, fit_balance_points, normal_daily_temperature
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def infer_temperature_unit(temp: pd.Series) -> dict:
    """Heuristic only (the preview shows it; the user decides)."""
    clean = temp.dropna()
    p95 = float(clean.quantile(0.95)) if len(clean) else float("nan")
    guess = "C" if p95 < 45 else "F"
    return {"guess": guess, "p05": float(clean.quantile(0.05)) if len(clean) else None,
            "p95": p95, "note": "Summer p95 below ~45 suggests Celsius; confirm with the source."}


def fill_short_gaps(weather: pd.DataFrame, max_gap_hours: int) -> pd.DataFrame:
    """Reindex one station hourly and linearly fill gaps ≤ ``max_gap_hours``; flag the fills."""
    w = weather.sort_values("hour_start_utc").drop_duplicates("hour_start_utc")
    grid = pd.date_range(w["hour_start_utc"].min(), w["hour_start_utc"].max(), freq="h",
                         tz="UTC", name="hour_start_utc")
    s = w.set_index("hour_start_utc")["temp"].reindex(grid)
    missing = s.isna()
    run = missing.groupby((missing != missing.shift()).cumsum()).transform("sum")
    filled = s.interpolate(limit_area="inside").where(~missing | (run <= max_gap_hours))
    return pd.DataFrame({"hour_start_utc": grid, "temp": filled.to_numpy(),
                         "temp_filled": (missing & filled.notna()).to_numpy()})


def _daily(series: pd.Series, hour_start_utc: pd.Series, tz: str) -> pd.Series:
    d = hour_start_utc.dt.tz_convert(tz).dt.date
    return series.groupby(d.to_numpy()).mean()


def _haversine_km(lat1, lon1, lat2, lon2) -> float:
    r = 6371.0
    p1, p2 = np.radians(lat1), np.radians(lat2)
    a = np.sin((p2 - p1) / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(np.radians(lon2 - lon1) / 2) ** 2
    return float(2 * r * np.arcsin(np.sqrt(a)))


def rank_stations(load: pd.DataFrame, weather: pd.DataFrame, tz: str,
                  stations: pd.DataFrame | None = None,
                  load_centroid: tuple[float, float] | None = None) -> pd.DataFrame:
    """Rank candidate stations by coverage of the load period and fit to daily load.

    Fit is the R² of a quadratic in daily mean temperature (captures both heating and
    cooling) on weekday daily energy. Distance is reported when coordinates are given.
    """
    start, end = load["hour_start_utc"].min(), load["hour_start_utc"].max()
    hours = (end - start) / pd.Timedelta(hours=1) + 1
    daily_load = _daily(load["load_mw"], load["hour_start_utc"], tz)
    weekday = pd.Series(pd.to_datetime(daily_load.index).dayofweek < 5, index=daily_load.index)
    rows = []
    for sid, g in weather.groupby("station_id"):
        inside = g[(g["hour_start_utc"] >= start) & (g["hour_start_utc"] <= end)]
        coverage = inside["hour_start_utc"].nunique() / hours
        t = _daily(inside["temp"], inside["hour_start_utc"], tz)
        both = pd.concat([daily_load[weekday], t], axis=1, join="inner").dropna()
        r2 = _quadratic_r2(both.iloc[:, 1], both.iloc[:, 0]) if len(both) > 30 else np.nan
        rows.append({"station_id": sid, "coverage_pct": round(100 * coverage, 2),
                     "fit_r2_daily": round(r2, 4) if r2 == r2 else None,
                     "distance_km": _distance(stations, sid, load_centroid)})
    return pd.DataFrame(rows).sort_values(["coverage_pct", "fit_r2_daily"], ascending=False,
                                          na_position="last").reset_index(drop=True)


def _distance(stations, sid, centroid):
    if stations is None or centroid is None or sid not in set(stations["station_id"]):
        return None
    row = stations.set_index("station_id").loc[sid]
    return round(_haversine_km(centroid[0], centroid[1], row["lat"], row["lon"]), 1)


def _quadratic_r2(x: pd.Series, y: pd.Series) -> float:
    X = np.column_stack([np.ones(len(x)), x, x ** 2])
    coef, *_ = np.linalg.lstsq(X, y.to_numpy(), rcond=None)
    resid = y.to_numpy() - X @ coef
    return float(1 - resid.var() / y.to_numpy().var())


def fit_balance_points(daily_energy: pd.Series, daily_temp: pd.Series,
                       candidates: np.ndarray) -> pd.DataFrame:
    """Five-parameter change-point search: SSE for each (heating base, cooling base) pair.

    ``energy = a + b·max(Th − T, 0) + c·max(T − Tc, 0)``, Th ≤ Tc, both from ``candidates``.
    Returns all pairs sorted by SSE (best first) so the preview can show alternatives.
    """
    both = pd.concat([daily_energy.rename("e"), daily_temp.rename("t")], axis=1).dropna()
    t, e = both["t"].to_numpy(), both["e"].to_numpy()
    rows = []
    for th in candidates:
        for tc in candidates[candidates >= th]:
            X = np.column_stack([np.ones(len(t)), np.clip(th - t, 0, None), np.clip(t - tc, 0, None)])
            coef, *_ = np.linalg.lstsq(X, e, rcond=None)
            rows.append({"hdd_base": float(th), "cdd_base": float(tc),
                         "sse": float(((e - X @ coef) ** 2).sum()),
                         "heating_slope": float(coef[1]), "cooling_slope": float(coef[2])})
    return pd.DataFrame(rows).sort_values("sse").reset_index(drop=True)


def normal_daily_temperature(weather: pd.DataFrame, tz: str, years: tuple[int, int]) -> pd.Series:
    """Mean daily temperature by day-of-year (1..366) over ``years`` (inclusive).

    Feb 29 falls back to Feb 28's normal when a year in the period lacks it.
    """
    local = weather["hour_start_utc"].dt.tz_convert(tz)
    sel = local.dt.year.between(years[0], years[1])
    if not sel.any():
        raise ValueError(f"No weather data in normal_years {years}.")
    daily = weather[sel].groupby(local[sel].dt.date)["temp"].mean()
    idx = pd.to_datetime(daily.index)
    key = idx.strftime("%m-%d")
    normals = daily.groupby(key.to_numpy()).mean()
    if "02-29" not in normals.index and "02-28" in normals.index:
        normals = pd.concat([normals, pd.Series({"02-29": normals["02-28"]})])
    return normals.sort_index()


def years_available(weather: pd.DataFrame, tz: str) -> list[int]:
    return sorted(weather["hour_start_utc"].dt.tz_convert(tz).dt.year.unique().tolist())
