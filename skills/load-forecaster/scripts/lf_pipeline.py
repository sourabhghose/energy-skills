"""Load-forecaster pipeline: prepare hourly data, preview decisions, backtest, normalize, forecast.

Pure pandas / numpy (scikit-learn only for ``model_family='gbm'``). ``lf_run.py`` adapts it to
Unity Catalog.

    from lf_pipeline import prepare_hourly, preview_profile, run_forecast
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from lf_features import build_features, feature_columns, holidays, lag_hours, to_hour_start_utc
from lf_models import MODEL_FAMILIES, metrics, rolling_origin_backtest, skill_vs_naive
from lf_normalize import daily_frame, normal_degree_days, weather_normalized_energy
from lf_weather import (fill_short_gaps, fit_balance_points, infer_temperature_unit,
                        rank_stations, years_available)


def canonical_load(load_raw: pd.DataFrame, basis: str, convention: str, tz: str,
                   mw_factor: float) -> pd.DataFrame:
    """``load_raw``: ts, value → hourly ``hour_start_utc``, ``load_mw`` (sub-hourly averaged)."""
    start = to_hour_start_utc(load_raw["ts"], basis, convention, tz)
    frame = pd.DataFrame({"t": start, "load_mw": pd.to_numeric(load_raw["value"],
                                                                errors="coerce") * mw_factor})
    hourly = frame.dropna(subset=["t"]).assign(hour_start_utc=lambda d: d["t"].dt.floor("h"))
    return (hourly.groupby("hour_start_utc", as_index=False)["load_mw"].mean()
            .sort_values("hour_start_utc").reset_index(drop=True))


def canonical_weather(weather_raw: pd.DataFrame) -> pd.DataFrame:
    """``weather_raw``: station_id, ts (UTC), temp → tz-aware UTC hour starts."""
    ts = pd.to_datetime(weather_raw["ts"], utc=True)
    return pd.DataFrame({"station_id": weather_raw["station_id"].astype(str),
                         "hour_start_utc": ts.dt.floor("h"),
                         "temp": pd.to_numeric(weather_raw["temp"], errors="coerce")})


def prepare_hourly(load: pd.DataFrame, weather: pd.DataFrame, cfg) -> tuple[pd.DataFrame, dict]:
    """Join load with the chosen station on a full hourly grid (incl. future weather hours)."""
    station = weather[weather["station_id"] == cfg.weather_station]
    if station.empty:
        raise ValueError(f"weather_station {cfg.weather_station!r} not in weather data.")
    filled = fill_short_gaps(station, cfg.max_weather_gap_hours)
    grid = pd.date_range(load["hour_start_utc"].min(),
                         max(load["hour_start_utc"].max(), filled["hour_start_utc"].max()),
                         freq="h", tz="UTC", name="hour_start_utc")
    frame = (pd.DataFrame(index=grid).reset_index()
             .merge(load, on="hour_start_utc", how="left")
             .merge(filled, on="hour_start_utc", how="left"))
    in_load = frame["hour_start_utc"] <= load["hour_start_utc"].max()
    report = {"load_hours_missing": int(frame.loc[in_load, "load_mw"].isna().sum()),
              "weather_hours_filled": int(frame["temp_filled"].fillna(False).sum()),
              "weather_hours_missing": int(frame.loc[in_load, "temp"].isna().sum())}
    return frame, report


def _year_range(frame: pd.DataFrame) -> range:
    years = frame["hour_start_utc"].dt.year
    return range(int(years.min()) - 1, int(years.max()) + 2)


def preview_profile(load: pd.DataFrame, weather: pd.DataFrame, tz: str,
                    stations: pd.DataFrame | None = None,
                    load_centroid: tuple[float, float] | None = None) -> dict:
    """Read-only profile: station ranking, unit check, fitted balance points, years available."""
    ranking = rank_stations(load, weather, tz, stations, load_centroid)
    top = ranking["station_id"].iloc[0]
    station = weather[weather["station_id"] == top]
    unit = infer_temperature_unit(station["temp"])
    hourly = load.merge(station[["hour_start_utc", "temp"]], on="hour_start_utc", how="inner")
    daily = daily_frame(hourly, tz, set())
    weekday = daily[daily["dow"] < 5]
    lo, hi = (40, 80) if unit["guess"] == "F" else (5, 27)
    bp = fit_balance_points(weekday["energy_mwh"], weekday["temp"], np.arange(lo, hi + 1, 1.0))
    conv = (65.0, 65.0) if unit["guess"] == "F" else (18.0, 18.0)
    conv_row = bp[(bp["hdd_base"] == conv[0]) & (bp["cdd_base"] == conv[1])]
    return {"load_hours": int(len(load)),
            "load_start_utc": str(load["hour_start_utc"].min()),
            "load_end_utc": str(load["hour_start_utc"].max()),
            "station_ranking": ranking.head(10).to_dict("records"),
            "temperature_unit_check": unit,
            "fitted_balance_points_top5": bp.head(5).round(2).to_dict("records"),
            "convention_base_sse_ratio_vs_best": (
                float(conv_row["sse"].iloc[0] / bp["sse"].iloc[0]) if len(conv_row) else None),
            "weather_years_available": years_available(weather, tz),
            "allowed_lags_by_horizon": {h: lag_hours(h) for h in (24, 48, 168)}}


def _final_forecast(features: pd.DataFrame, cfg, cols: list[str],
                    last_load_hour: pd.Timestamp) -> pd.DataFrame:
    """Fit on all history and forecast hours after the last load hour that have weather."""
    history = features[features["hour_start_utc"] <= last_load_hour].dropna(subset=cols + ["load_mw"])
    future = features[(features["hour_start_utc"] > last_load_hour) &
                      (features["hour_start_utc"] <= last_load_hour +
                       pd.Timedelta(hours=cfg.horizon_hours))].dropna(subset=cols)
    if future.empty:
        return pd.DataFrame(columns=["hour_start_utc", "forecast_mw"])
    model = MODEL_FAMILIES[cfg.model_family].fit(history, cols)
    return future[["hour_start_utc"]].assign(forecast_mw=model.predict(future))


def run_forecast(load: pd.DataFrame, weather: pd.DataFrame, cfg) -> dict:
    """Backtest (model vs naive), weather normalization, and the next-horizon forecast."""
    frame, data_report = prepare_hourly(load, weather, cfg)
    hol = holidays(cfg.holiday_calendar, _year_range(frame))
    features = build_features(frame, cfg, hol)
    cols = feature_columns(cfg)
    last_load = load["hour_start_utc"].max()
    bt = rolling_origin_backtest(features[features["hour_start_utc"] <= last_load], cfg, cols)
    hours = bt["hour_start_utc"].dt.tz_convert(cfg.local_timezone).dt.hour
    m_model = metrics(bt["load_mw"], bt["forecast_mw"], bt["local_date"], hours)
    m_naive = metrics(bt["load_mw"], bt["naive_mw"], bt["local_date"], hours)
    normals = normal_degree_days(weather[weather["station_id"] == cfg.weather_station],
                                 cfg.local_timezone, cfg.normal_years, cfg.hdd_base, cfg.cdd_base)
    daily = daily_frame(frame[frame["hour_start_utc"] <= last_load], cfg.local_timezone, hol)
    last_year = daily[pd.to_datetime(daily.index) > pd.to_datetime(daily.index.max()) -
                      pd.Timedelta(days=365)]
    return {"data_report": data_report, "backtest": bt,
            "metrics_model": m_model, "metrics_naive": m_naive,
            "skill_vs_naive": skill_vs_naive(m_model, m_naive),
            "normalization_last_365_days": weather_normalized_energy(
                last_year, normals, cfg.hdd_base, cfg.cdd_base),
            "forecast": _final_forecast(features, cfg, cols, last_load)}
