"""Databricks runner for wind and solar performance: read UC tables, call the core, write outputs.

    import sys; sys.path.append("<skill-dir>/scripts")
    from perf_run import preview_wind_table, build_wind_table, preview_solar_table, build_solar_table
    print(preview_wind_table("main.ops.scada_10min", rated_kw=2050,
                             warranted_curve_table="main.ops.warranted_curve_mm92"))
    build_wind_table("main.ops.scada_10min", "main.ops.wtg_perf_2025", rated_kw=2050,
                     warranted_curve_table="main.ops.warranted_curve_mm92",
                     timestamp_convention="interval_beginning", reference_curve="warranted",
                     ref_density=1.225, turbine_control="pitch", availability_basis="energy",
                     external_downtime="exclude_from_availability")

`where` filters use named parameters, e.g. where="timestamp >= :start", args={"start": "2025-01-01"}.
"""

from __future__ import annotations

import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from solar_perf import SKILL, VERSION, build_confirmed_solar, preview_solar  # noqa: E402
from uc_io import read_table, validate_identifier, write_manifest, write_table  # noqa: E402
from wind_perf import build_confirmed_wind, preview_wind  # noqa: E402

TAG = f"{SKILL} {VERSION}"


def _curve(table: str | None) -> pd.DataFrame | None:
    return read_table(table)[["ws_ms", "power_kw"]] if table else None


def preview_wind_table(scada_table: str, *, rated_kw: float, warranted_curve_table: str | None = None,
                       where: str | None = None, args: dict | None = None, **kw) -> str:
    """READ-ONLY."""
    scada = read_table(scada_table, where, args)
    return preview_wind(scada, rated_kw=rated_kw, warranted_curve=_curve(warranted_curve_table), **kw)["readout"]


def build_wind_table(scada_table: str, output_prefix: str, *, rated_kw: float,
                     warranted_curve_table: str | None = None, where: str | None = None,
                     args: dict | None = None, **decisions) -> dict:
    validate_identifier(output_prefix)
    scada = read_table(scada_table, where, args)
    out = build_confirmed_wind(scada, rated_kw=rated_kw, warranted_curve=_curve(warranted_curve_table),
                               **decisions)
    manifest = {**out["manifest"], "source_table": scada_table, "where": where, "args": args}
    for name in ("power_curve", "losses", "availability", "yaw"):
        if not out[name].empty:
            write_table(out[name], f"{output_prefix}_{name}", f"Wind {name} ({TAG})")
    write_manifest(manifest, f"{output_prefix}_manifest", SKILL, VERSION)
    return {**out, "manifest": manifest}


def preview_solar_table(table: str, *, dc_kwp: float, ac_capacity_kw: float, where: str | None = None,
                        args: dict | None = None, **kw) -> str:
    """READ-ONLY."""
    return preview_solar(read_table(table, where, args), dc_kwp=dc_kwp, ac_capacity_kw=ac_capacity_kw,
                         **kw)["readout"]


def build_solar_table(table: str, output_prefix: str, *, dc_kwp: float, ac_capacity_kw: float,
                      where: str | None = None, args: dict | None = None, **decisions) -> dict:
    validate_identifier(output_prefix)
    out = build_confirmed_solar(read_table(table, where, args), dc_kwp=dc_kwp,
                                ac_capacity_kw=ac_capacity_kw, **decisions)
    manifest = {**out["manifest"], "source_table": table, "where": where, "args": args}
    write_table(out["monthly_pr"], f"{output_prefix}_monthly_pr", f"Monthly PR ({TAG})")
    write_table(out["inverter_availability"], f"{output_prefix}_inverter_availability",
                f"Inverter availability ({TAG})")
    summary = pd.DataFrame([{"pr": out["pr"], **out["lost_energy"]}])
    write_table(summary, f"{output_prefix}_summary", f"PV performance summary ({TAG})")
    write_manifest(manifest, f"{output_prefix}_manifest", SKILL, VERSION)
    return {**out, "manifest": manifest}
