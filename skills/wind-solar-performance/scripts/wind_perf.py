"""Vetted wind entrypoints: preview decisions (read-only), then build a confirmed performance report.

    from wind_perf import preview_wind, build_confirmed_wind
    print(preview_wind(scada, rated_kw=2050, warranted_curve=wc)["readout"])
    out = build_confirmed_wind(scada, rated_kw=2050, warranted_curve=wc,
                               timestamp_convention="interval_beginning", reference_curve="warranted",
                               ref_density=1.225, turbine_control="pitch",
                               availability_basis="energy", external_downtime="exclude_from_availability")
"""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from perf_common import TIMESTAMP_CONVENTIONS, DecisionRequired, require, with_interval_start
from wind_core import (air_density, availability, binned_power_curve, curve_power, flag_scada, icing_suspect,
                       lost_production, normalize_density, rayleigh_aep_mwh, resolve_reference_density,
                       yaw_misalignment)

SKILL, VERSION = "wind-solar-performance", "0.1.0"
REFERENCE_CURVES = ("warranted", "site_baseline")
CONTROLS = ("pitch", "stall")
AVAILABILITY_BASIS = ("time", "energy")
EXTERNAL_DOWNTIME = ("exclude_from_availability", "count_as_unavailable")


def _check_ref_density(value):
    if value in ("site_mean", "iso_1.225"):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    raise DecisionRequired("ref_density", ["site_mean", "iso_1.225", "<warranted curve density kg/m3>"],
                           "Use the density the warranted power curve is stated at.")


def _reference(df: pd.DataFrame, reference_curve: str, warranted_curve, baseline_end) -> pd.DataFrame:
    if reference_curve == "warranted":
        if warranted_curve is None:
            raise ValueError("reference_curve='warranted' needs warranted_curve (ws_ms, power_kw)")
        return warranted_curve.rename(columns={"ws_ms": "ws_mean"})
    if baseline_end is None:
        raise DecisionRequired("baseline_end", ["<timestamp ending the baseline period>"],
                               "site_baseline compares later data to a measured baseline period.")
    base = df[df["interval_start"] < pd.Timestamp(baseline_end)]
    curve = binned_power_curve(base)
    return curve[curve["complete"]]


def _expected(df: pd.DataFrame, ref: pd.DataFrame, rated_kw: float, rho: pd.Series, rho_ref: float,
              control: str) -> pd.Series:
    if control == "pitch":
        return curve_power(ref, df["ws_norm"], rated_kw)
    return (curve_power(ref, df["wind_speed_ms"], rated_kw) * rho / rho_ref).clip(upper=rated_kw)


def _prepare(scada, rated_kw, convention, ref_density, control, site_elevation_m):
    df = flag_scada(with_interval_start(scada, convention, group_col="turbine_id"), rated_kw)
    rho = air_density(df, site_elevation_m)
    rho_ref = resolve_reference_density(rho, ref_density)
    return normalize_density(df, rho, rho_ref, control), rho, rho_ref


def _analyse(df, rho, rho_ref, rated_kw, d, warranted_curve, baseline_end, mean_ws):
    ref = _reference(df, d["reference_curve"], warranted_curve, baseline_end)
    expected = _expected(df, ref, rated_kw, rho, rho_ref, d["turbine_control"])
    icing = icing_suspect(df, expected)
    df = df.assign(flag_icing=icing, valid_for_curve=df["valid_for_curve"] & ~icing)
    measured = binned_power_curve(df)
    losses = lost_production(df, expected)
    avail = availability(df, losses, d["availability_basis"], d["external_downtime"])
    mean_ws = mean_ws or float(df.loc[df["valid_for_curve"], "ws_norm"].mean())
    aep = {"mean_ws_ms": mean_ws,
           "aep_measured_mwh": rayleigh_aep_mwh(measured[measured["complete"]], mean_ws, rated_kw),
           "aep_reference_mwh": rayleigh_aep_mwh(ref, mean_ws, rated_kw)}
    aep["aep_ratio"] = aep["aep_measured_mwh"] / aep["aep_reference_mwh"]
    return df, measured, losses, avail, aep


def _loss_summary(losses: pd.DataFrame) -> pd.DataFrame:
    cols = ["expected_kwh", "actual_kwh", "lost_availability_kwh", "lost_external_kwh",
            "lost_curtailment_kwh", "performance_gap_kwh"]
    return losses.groupby("turbine_id")[cols].sum().reset_index()


def build_confirmed_wind(scada: pd.DataFrame, *, rated_kw: float, timestamp_convention=None,
                         reference_curve=None, ref_density=None, turbine_control=None,
                         availability_basis=None, external_downtime=None, warranted_curve=None,
                         baseline_end=None, site_elevation_m=None, mean_ws_for_aep=None) -> dict:
    """Every decision explicit (no defaults). Curtailment is always separated from underperformance."""
    d = {
        "timestamp_convention": require("timestamp_convention", timestamp_convention, TIMESTAMP_CONVENTIONS),
        "reference_curve": require("reference_curve", reference_curve, REFERENCE_CURVES),
        "ref_density": _check_ref_density(ref_density),
        "turbine_control": require("turbine_control", turbine_control, CONTROLS),
        "availability_basis": require("availability_basis", availability_basis, AVAILABILITY_BASIS),
        "external_downtime": require("external_downtime", external_downtime, EXTERNAL_DOWNTIME),
    }
    df, rho, rho_ref = _prepare(scada, rated_kw, d["timestamp_convention"], d["ref_density"],
                                d["turbine_control"], site_elevation_m)
    df, measured, losses, avail, aep = _analyse(df, rho, rho_ref, rated_kw, d, warranted_curve,
                                                baseline_end, mean_ws_for_aep)
    flags = df.filter(like="flag_").mean().rename("share").reset_index().rename(columns={"index": "flag"})
    manifest = {"skill": SKILL, "skill_version": VERSION, "analysis": "wind",
                "built_utc": datetime.now(timezone.utc).isoformat(), "decisions": d,
                "inputs": {"rows": len(scada), "turbines": sorted(map(str, scada["turbine_id"].unique())),
                           "rated_kw": rated_kw, "rho_ref_kg_m3": rho_ref,
                           "baseline_end": str(baseline_end) if baseline_end else None},
                "aep": aep}
    return {"power_curve": measured, "losses": _loss_summary(losses), "availability": avail,
            "flags": flags, "yaw": yaw_misalignment(df), "aep": aep, "manifest": manifest}


def preview_wind(scada: pd.DataFrame, *, rated_kw: float, warranted_curve: pd.DataFrame | None = None,
                 site_elevation_m: float | None = None) -> dict:
    """READ-ONLY. Data profile + the effect of availability and density choices on this data."""
    probe = {"reference_curve": "warranted" if warranted_curve is not None else "site_baseline",
             "turbine_control": "pitch"}
    df, rho, _ = _prepare(scada, rated_kw, "interval_beginning", "site_mean", "pitch", site_elevation_m)
    flags = df.filter(like="flag_").mean().round(4).to_dict()
    consequences: dict = {"rho_kg_m3": {"min": round(rho.min(), 4), "mean": round(rho.mean(), 4),
                                        "max": round(rho.max(), 4)}}
    if warranted_curve is not None:
        for ref in ("site_mean", "iso_1.225"):
            dd, rr, r0 = _prepare(scada, rated_kw, "interval_beginning", ref, "pitch", site_elevation_m)
            *_, aep = _analyse(dd, rr, r0, rated_kw, {**probe, "availability_basis": "time",
                                                      "external_downtime": "exclude_from_availability"},
                               warranted_curve, None, None)
            consequences.setdefault("aep_ratio_by_ref_density", {})[ref] = round(aep["aep_ratio"], 4)
        for basis in AVAILABILITY_BASIS:
            for ext in EXTERNAL_DOWNTIME:
                *_, avail, _ = _analyse(df, rho, rho.mean(), rated_kw,
                                        {**probe, "availability_basis": basis, "external_downtime": ext},
                                        warranted_curve, None, None)
                consequences.setdefault("fleet_availability", {})[f"{basis}|{ext}"] = \
                    round(float(avail["availability"].mean()), 4)
    readout = "\n".join([
        "## Wind performance preview (nothing built)",
        f"Turbines: {scada['turbine_id'].nunique()}  Rows: {len(scada)}  "
        f"Interval: {df['interval_h'].iloc[0] * 60:.0f} min",
        "### Flag shares", "\n".join(f"- {k}: {v:.2%}" for k, v in flags.items()),
        "### Effect of each option on this data",
        "\n".join(f"- {k}: {v}" for k, v in consequences.items()),
        "### Decisions you must make: timestamp_convention, reference_curve, ref_density, "
        "turbine_control, availability_basis, external_downtime",
    ])
    return {"flags": flags, "consequences": consequences, "readout": readout}
