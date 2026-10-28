"""Databricks entrypoints for load-forecaster — EXECUTION model.

Genie Code CALLS these functions and reports their output. It does not hand-write the
forecast, the backtest split, or the normalization, and does not pick a decision value.

    import sys; sys.path.append('<this-skill-dir>/scripts')
    from lf_run import preview_forecast_options, build_confirmed_forecast

    print(preview_forecast_options("main.grid.system_load", "main.grid.weather_hourly",
                                   local_timezone="America/Chicago"))
    print(build_confirmed_forecast("main.grid.system_load", "main.grid.weather_hourly",
                                   "main.grid.lf_area1", local_timezone="America/Chicago",
                                   load_timestamp_basis="utc", load_interval_convention="ending",
                                   load_unit="MW", weather_station="KORD", temperature_unit="F",
                                   hdd_base=60, cdd_base=68, holiday_calendar="nerc",
                                   horizon_hours=24, model_family="gbm",
                                   normal_years=(1994, 2023)))

``preview_forecast_options`` is READ-ONLY. ``build_confirmed_forecast`` requires every decision.
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _uc import quote_identifier, read_query, validate_identifier, write_manifest, write_table  # noqa: E402
from lf_decisions import DECISIONS, SKILL_VERSION, build_manifest, make_config  # noqa: E402
from lf_pipeline import canonical_load, canonical_weather, preview_profile, run_forecast  # noqa: E402


def _select(table: str, cols: dict[str, str]) -> str:
    validate_identifier(table, fully_qualified=True)
    exprs = ", ".join(f"{quote_identifier(src)} AS {alias}" for alias, src in cols.items())
    return f"SELECT {exprs} FROM {quote_identifier(table)}"


def _read_inputs(load_table, weather_table, load_cols, weather_cols, warehouse_id, profile):
    load_raw = read_query(_select(load_table, load_cols), warehouse_id=warehouse_id, profile=profile)
    weather_raw = read_query(_select(weather_table, weather_cols), warehouse_id=warehouse_id,
                             profile=profile)
    return load_raw, canonical_weather(weather_raw)


def preview_forecast_options(load_table: str, weather_table: str, *, local_timezone: str,
                             load_ts_col: str = "ts", load_value_col: str = "load_mw",
                             station_col: str = "station_id", weather_ts_col: str = "ts",
                             temp_col: str = "temp", assume_basis: str = "utc",
                             assume_convention: str = "ending", assume_unit_factor: float = 1.0,
                             warehouse_id: str | None = None, profile: str | None = None) -> str:
    """READ-ONLY. Rank stations, check units, fit balance points, list every decision.

    ``assume_*`` only place timestamps for the profile; they are printed as assumptions and
    are not decisions.
    """
    load_raw, weather = _read_inputs(
        load_table, weather_table, {"ts": load_ts_col, "value": load_value_col},
        {"station_id": station_col, "ts": weather_ts_col, "temp": temp_col}, warehouse_id, profile)
    load = canonical_load(load_raw, assume_basis, assume_convention, local_timezone,
                          assume_unit_factor)
    prof = preview_profile(load, weather, local_timezone)
    lines = ["LOAD FORECAST PREVIEW (read-only — nothing was built)",
             f"  assumptions for this profile only: basis={assume_basis}, "
             f"convention={assume_convention}", ""]
    lines += [f"  {k}: {json.dumps(v, default=str)}" for k, v in prof.items()]
    lines += ["", "DECISIONS REQUIRED before build_confirmed_forecast (ask the user; do not pick):"]
    lines += [f"  - {n}: {s['options']}  — {s['why']}" for n, s in DECISIONS.items()]
    return "\n".join(lines)


def build_confirmed_forecast(load_table: str, weather_table: str, output_prefix: str, *,
                             local_timezone=None, load_timestamp_basis=None,
                             load_interval_convention=None, load_unit=None, weather_station=None,
                             temperature_unit=None, hdd_base=None, cdd_base=None,
                             holiday_calendar=None, horizon_hours=None, model_family=None,
                             normal_years=None, load_ts_col: str = "ts",
                             load_value_col: str = "load_mw", station_col: str = "station_id",
                             weather_ts_col: str = "ts", temp_col: str = "temp",
                             warehouse_id: str | None = None, profile: str | None = None) -> str:
    """Backtest, normalize, forecast; write ``<prefix>_backtest/_forecast/_metrics/_manifest``."""
    cfg = make_config(local_timezone=local_timezone, load_timestamp_basis=load_timestamp_basis,
                      load_interval_convention=load_interval_convention, load_unit=load_unit,
                      weather_station=weather_station, temperature_unit=temperature_unit,
                      hdd_base=hdd_base, cdd_base=cdd_base, holiday_calendar=holiday_calendar,
                      horizon_hours=horizon_hours, model_family=model_family,
                      normal_years=normal_years)
    validate_identifier(output_prefix, fully_qualified=True)
    load_raw, weather = _read_inputs(
        load_table, weather_table, {"ts": load_ts_col, "value": load_value_col},
        {"station_id": station_col, "ts": weather_ts_col, "temp": temp_col}, warehouse_id, profile)
    load = canonical_load(load_raw, cfg.load_timestamp_basis, cfg.load_interval_convention,
                          cfg.local_timezone, cfg.mw_factor)
    result = run_forecast(load, weather, cfg)
    return _write_outputs(result, cfg, load_table, weather_table, output_prefix, len(load))


def _write_outputs(result, cfg, load_table, weather_table, prefix, n_load) -> str:
    import pandas as pd

    tag = f"load-forecaster {SKILL_VERSION}"
    write_table(result["backtest"].assign(local_date=lambda d: d["local_date"].astype(str)),
                f"{prefix}_backtest", table_comment=f"Rolling-origin backtest, MW ({tag})")
    write_table(result["forecast"], f"{prefix}_forecast",
                table_comment=f"Next-horizon forecast, MW, hour-beginning UTC ({tag})")
    summary = {k: result[k] for k in ("metrics_model", "metrics_naive", "skill_vs_naive",
                                      "normalization_last_365_days", "data_report")}
    write_table(pd.DataFrame([{"metrics_json": json.dumps(summary)}]), f"{prefix}_metrics",
                table_comment=f"Backtest metrics and weather normalization ({tag})")
    manifest = build_manifest(cfg, {"load_table": load_table, "weather_table": weather_table,
                                    "load_hours": n_load},
                              {s: f"{prefix}_{s}" for s in ("backtest", "forecast", "metrics")})
    write_manifest(manifest, f"{prefix}_manifest")
    return format_build(summary, manifest)


def format_build(summary: dict, manifest: dict) -> str:
    m, n = summary["metrics_model"], summary["metrics_naive"]
    norm = summary["normalization_last_365_days"]
    return "\n".join([
        "LOAD FORECAST BUILD COMPLETE", f"  run_id: {manifest['run_id']}",
        f"  outputs: {manifest['outputs']}",
        f"  backtest WAPE model {m['wape_pct']:.2f}% vs naive {n['wape_pct']:.2f}% "
        f"(skill {summary['skill_vs_naive']:+.2f}); MAPE {m['mape_pct']:.2f}%; "
        f"daily peak APE {m['daily_peak_ape_pct']:.2f}%",
        "  backtest weather is ACTUAL (ex-post): live error will be higher by the weather "
        "forecast error.",
        f"  last 365 days: actual {norm['actual_mwh']:,.0f} MWh, weather-normalized "
        f"{norm['normalized_mwh']:,.0f} MWh (adjustment {norm['weather_adjustment_mwh']:+,.0f})",
        "  decisions:"] + [f"    {k} = {v}" for k, v in manifest["decisions"].items()])
