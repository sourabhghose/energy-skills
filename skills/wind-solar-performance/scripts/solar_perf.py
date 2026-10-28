"""Vetted solar entrypoints: preview decisions (read-only), then build a confirmed PV performance report.

    from solar_perf import preview_solar, build_confirmed_solar
    print(preview_solar(df, dc_kwp=5000, ac_capacity_kw=4200, gamma_pmax_per_c=-0.0035)["readout"])
    out = build_confirmed_solar(df, dc_kwp=5000, ac_capacity_kw=4200, gamma_pmax_per_c=-0.0035,
                                timestamp_convention="interval_ending", pr_method="nrel_weather_corrected",
                                clipping_handling="exclude_intervals", availability_in_pr="include_downtime")

Curtailed intervals are always excluded from PR and reported as a separate loss.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from perf_common import TIMESTAMP_CONVENTIONS, require, with_interval_start
from solar_core import (cell_temperature, daily_normalized, flag_solar, inverter_availability, lost_energy,
                        performance_ratio, require_poa, soiling_screen, yoy_degradation)

SKILL, VERSION = "wind-solar-performance", "0.1.0"
PR_METHODS = ("iec_61724_uncorrected", "temperature_corrected_stc", "nrel_weather_corrected")
CLIPPING = ("exclude_intervals", "include")
AVAILABILITY_IN_PR = ("include_downtime", "exclude_downtime")


def _prepare(df: pd.DataFrame, convention: str, ac_capacity_kw: float, min_poa_wm2: float) -> pd.DataFrame:
    require_poa(df)
    group = "inverter_id" if "inverter_id" in df else None
    out = with_interval_start(df, convention, group_col=group)
    out = out.assign(t_cell=cell_temperature(out))
    return flag_solar(out, ac_capacity_kw, min_poa_wm2)


def _pr_mask(df: pd.DataFrame, clipping: str, availability_in_pr: str) -> pd.Series:
    mask = df["daylight"] & ~df["flag_curtailed"] & ~df["flag_missing"]
    if clipping == "exclude_intervals":
        mask &= ~df["flag_clipped"]
    if availability_in_pr == "exclude_downtime":
        mask &= ~df["flag_inverter_fault"]
    return mask


def _monthly_pr(df: pd.DataFrame, dc_kwp: float, method: str, gamma, t_ref) -> pd.DataFrame:
    month = df["interval_start"].dt.strftime("%Y-%m")
    rows = [{"month": m, "pr": performance_ratio(g, dc_kwp, method, gamma, t_ref)} for m, g in df.groupby(month)]
    return pd.DataFrame(rows)


def _long_term(df: pd.DataFrame, dc_kwp: float, gamma) -> dict:
    if gamma is None:
        return {"degradation": "skipped: needs gamma_pmax_per_c", "soiling": "skipped: needs gamma_pmax_per_c"}
    daily = daily_normalized(df, dc_kwp, gamma)
    try:
        degradation = yoy_degradation(daily)
    except ValueError as exc:
        degradation = f"skipped: {exc}"
    return {"degradation": degradation, "soiling": soiling_screen(daily)}


def build_confirmed_solar(df: pd.DataFrame, *, dc_kwp: float, ac_capacity_kw: float,
                          gamma_pmax_per_c: float | None = None, timestamp_convention=None, pr_method=None,
                          clipping_handling=None, availability_in_pr=None, min_poa_wm2: float = 50.0,
                          t_ref_c: float | None = None) -> dict:
    """Every decision explicit (no defaults)."""
    d = {
        "timestamp_convention": require("timestamp_convention", timestamp_convention, TIMESTAMP_CONVENTIONS),
        "pr_method": require("pr_method", pr_method, PR_METHODS),
        "clipping_handling": require("clipping_handling", clipping_handling, CLIPPING),
        "availability_in_pr": require("availability_in_pr", availability_in_pr, AVAILABILITY_IN_PR),
    }
    prepared = _prepare(df, d["timestamp_convention"], ac_capacity_kw, min_poa_wm2)
    included = prepared[_pr_mask(prepared, d["clipping_handling"], d["availability_in_pr"])]
    gamma = gamma_pmax_per_c
    pr = performance_ratio(included, dc_kwp, d["pr_method"], gamma, t_ref_c)
    flags = prepared.filter(like="flag_")[prepared["daylight"]].mean().to_dict()
    manifest = {"skill": SKILL, "skill_version": VERSION, "analysis": "solar",
                "built_utc": datetime.now(timezone.utc).isoformat(), "decisions": d,
                "inputs": {"rows": len(df), "dc_kwp": dc_kwp, "ac_capacity_kw": ac_capacity_kw,
                           "gamma_pmax_per_c": gamma, "min_poa_wm2": min_poa_wm2, "t_ref_c": t_ref_c,
                           "intervals_in_pr": int(len(included))}}
    return {
        "pr": pr, "monthly_pr": _monthly_pr(included, dc_kwp, d["pr_method"], gamma, t_ref_c),
        "inverter_availability": inverter_availability(prepared),
        "lost_energy": lost_energy(prepared, dc_kwp, pr, gamma if d["pr_method"] != "iec_61724_uncorrected" else None),
        "flag_shares_daylight": flags, **_long_term(prepared, dc_kwp, gamma), "manifest": manifest,
    }


def preview_solar(df: pd.DataFrame, *, dc_kwp: float, ac_capacity_kw: float,
                  gamma_pmax_per_c: float | None = None, min_poa_wm2: float = 50.0) -> dict:
    """READ-ONLY. PR under every method x clipping x availability choice on this data."""
    prepared = _prepare(df, "interval_beginning", ac_capacity_kw, min_poa_wm2)
    grid = {}
    for method in PR_METHODS:
        if method != "iec_61724_uncorrected" and gamma_pmax_per_c is None:
            grid[method] = "needs gamma_pmax_per_c"
            continue
        for clip in CLIPPING:
            for avail in AVAILABILITY_IN_PR:
                sub = prepared[_pr_mask(prepared, clip, avail)]
                grid[f"{method}|{clip}|{avail}"] = round(performance_ratio(sub, dc_kwp, method, gamma_pmax_per_c), 4)
    flags = prepared.filter(like="flag_")[prepared["daylight"]].mean().round(4).to_dict()
    readout = "\n".join([
        "## Solar performance preview (nothing built)",
        f"Rows: {len(df)}  Interval: {prepared['interval_h'].iloc[0] * 60:.0f} min  "
        f"Daylight intervals (POA >= {min_poa_wm2} W/m2): {int(prepared['daylight'].sum())}",
        "### Flag shares (daylight)", "\n".join(f"- {k}: {v:.2%}" for k, v in flags.items()),
        "### PR by method | clipping | availability", "\n".join(f"- {k}: {v}" for k, v in grid.items()),
        "### Decisions you must make: timestamp_convention, pr_method, clipping_handling, availability_in_pr",
        "Curtailed intervals are always excluded from PR and reported as lost_curtailment_kwh.",
    ])
    return {"pr_grid": grid, "flags": flags, "readout": readout}
