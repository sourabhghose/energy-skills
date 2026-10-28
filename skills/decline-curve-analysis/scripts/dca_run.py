"""decline-curve-analysis runner: Unity Catalog in, governed DCA tables out.

Entrypoints (Databricks Python compute; Spark discovered at call time):

    from dca_run import preview_dca_options, build_confirmed_dca, build_confirmed_type_curve

    # 1. READ-ONLY profile + EUR sensitivity for a sample of wells. Builds nothing.
    print(preview_dca_options("main.upstream.monthly_prod", well_col="api14", date_col="prod_month",
                              volume_col="oil_bbl", volume_unit="bbl", period="monthly",
                              days_on_col="days_on"))

    # 2. Only after the user chose every decision. No decision has a default.
    print(build_confirmed_dca("main.upstream.monthly_prod", "main.upstream.dca_oil",
          well_col="api14", date_col="prod_month", volume_col="oil_bbl", volume_unit="bbl",
          period="monthly", days_on_col="days_on",
          rate_basis="producing_day", decline_start="peak", outlier_method="mad",
          b_bounds=(0.0, 1.5), terminal_decline_eff=0.08, econ_limit_rate=5.0, max_life_years=50))

Outputs: <prefix>_fits (one row per well), <prefix>_forecast (monthly), <prefix>_manifest.
"""

from __future__ import annotations

import json
import logging
import re

import pandas as pd

from dca_config import PERIODS, DcaDecisions, DecisionRequired, TypeCurveDecisions
from dca_preview import preview_wells
from dca_typecurve import build_type_curve, eur_percentiles
from dca_well import analyze_well, forecast_well
from uc_io import build_manifest, get_spark, validate_identifier, write_manifest, write_table

logger = logging.getLogger(__name__)

SKILL, VERSION = "decline-curve-analysis", "0.1.0"
COLUMN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
VOLUME_UNITS = ("bbl", "Mcf", "MMcf", "m3", "Sm3", "boe")
FIT_COLUMNS = [
    "well_id", "status", "volume_unit", "qi_per_day", "di_nominal_per_yr", "b", "di_secant_eff",
    "di_tangent_eff", "d_lim_nominal_per_yr", "r2_log", "n_points", "b_min", "b_max", "peak_rate_per_day",
    "cum_to_date", "remaining", "eur", "t_last_years", "t_end_years", "end_reason", "rate_at_last",
    "first_production", "decline_start", "exclusions_json", "flags",
]


def _check_columns(**cols: str | None) -> None:
    for role, name in cols.items():
        if name is not None and not COLUMN.match(name):
            raise ValueError(f"Invalid column name for {role}: {name!r}")


def _check_stream(volume_unit: str, period: str) -> None:
    if volume_unit not in VOLUME_UNITS:
        raise DecisionRequired("volume_unit", VOLUME_UNITS, "state the unit of the volume column (gas is not boe)")
    if period not in PERIODS:
        raise DecisionRequired("period", PERIODS, "volumes per calendar month or per day")


def _load_wells(spark, table: str, well_col: str, date_col: str, volume_col: str, days_on_col: str | None,
                wells: list[str] | None, max_wells: int | None) -> dict[str, pd.DataFrame]:
    from pyspark.sql import functions as F

    cols = [F.col(well_col).cast("string").alias("well_id"), F.col(date_col).alias("period_start"),
            F.col(volume_col).cast("double").alias("volume")]
    if days_on_col:
        cols.append(F.col(days_on_col).cast("double").alias("days_on"))
    sdf = spark.table(validate_identifier(table)).select(*cols)
    if wells:
        sdf = sdf.where(F.col("well_id").isin([str(w) for w in wells]))
    if max_wells:
        keep = [r["well_id"] for r in sdf.select("well_id").distinct().orderBy("well_id").limit(max_wells).collect()]
        sdf = sdf.where(F.col("well_id").isin(keep))
    pdf = sdf.toPandas()
    return {w: g.drop(columns="well_id").reset_index(drop=True) for w, g in pdf.groupby("well_id")}


def preview_dca_options(table: str, well_col: str, date_col: str, volume_col: str, volume_unit: str,
                        period: str, days_on_col: str | None = None, wells: list[str] | None = None,
                        max_wells: int = 10, profile: str | None = None) -> str:
    """READ-ONLY. Profile a sample of wells and show EUR sensitivity to each decision."""
    _check_columns(well_col=well_col, date_col=date_col, volume_col=volume_col, days_on_col=days_on_col)
    _check_stream(volume_unit, period)
    spark = get_spark(profile)
    loaded = _load_wells(spark, table, well_col, date_col, volume_col, days_on_col, wells, max_wells)
    if not loaded:
        return f"No rows found in {table} for the requested wells."
    return preview_wells(loaded, period, volume_unit)


def _row(well_id: str, result: dict, volume_unit: str) -> dict:
    row = {c: result.get(c) for c in FIT_COLUMNS}
    return {**row, "well_id": well_id, "volume_unit": volume_unit,
            "exclusions_json": json.dumps(result.get("exclusions", {}), sort_keys=True),
            "flags": ",".join(result.get("flags", []))}


def analyze_all(wells: dict[str, pd.DataFrame], period: str, decisions: DcaDecisions,
                volume_unit: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Pure-pandas batch: (fits, forecast) frames for many wells. Failed wells get status=error."""
    fits, forecasts = [], []
    for well_id, pdf in wells.items():
        try:
            result = analyze_well(pdf, period, decisions)
        except ValueError as exc:
            logger.warning("DCA failed for well %s: %s", well_id, exc)
            result = {"status": f"error: {exc}"}
        fits.append(_row(well_id, result, volume_unit))
        fc = forecast_well(result)
        if not fc.empty:
            forecasts.append(fc.assign(well_id=well_id, volume_unit=volume_unit))
    forecast = pd.concat(forecasts, ignore_index=True) if forecasts else pd.DataFrame(
        columns=["month_index", "t_start_years", "volume", "rate_per_day", "well_id", "volume_unit"])
    return pd.DataFrame(fits, columns=FIT_COLUMNS), forecast


FIT_COMMENTS = {
    "qi_per_day": "Fitted initial rate at decline start, volume_unit per day",
    "di_nominal_per_yr": "Initial nominal (instantaneous) decline, 1/year",
    "di_secant_eff": "Initial decline as secant effective annual fraction (SPEE convention)",
    "di_tangent_eff": "Initial decline as tangent effective annual fraction",
    "d_lim_nominal_per_yr": "Terminal exponential decline (nominal 1/yr); null = pure Arps",
    "b": "Arps b-factor (constrained to [b_min, b_max])",
    "eur": "Estimated ultimate recovery = cum_to_date + remaining, volume_unit",
    "flags": "Plausibility flags a reviewer must clear before booking",
}


def build_confirmed_dca(table: str, output_prefix: str, *, well_col: str, date_col: str, volume_col: str,
                        volume_unit: str, period: str, days_on_col: str | None, rate_basis: str,
                        decline_start: str, outlier_method: str, b_bounds: tuple[float, float],
                        terminal_decline_eff, econ_limit_rate: float, max_life_years: float,
                        wells: list[str] | None = None, profile: str | None = None) -> str:
    """Fit every well with the user's decisions; write fits, forecast, and manifest tables."""
    decisions = DcaDecisions.from_kwargs(
        rate_basis=rate_basis, decline_start=decline_start, outlier_method=outlier_method, b_bounds=b_bounds,
        terminal_decline_eff=terminal_decline_eff, econ_limit_rate=econ_limit_rate, max_life_years=max_life_years)
    _check_columns(well_col=well_col, date_col=date_col, volume_col=volume_col, days_on_col=days_on_col)
    _check_stream(volume_unit, period)
    validate_identifier(output_prefix)
    spark = get_spark(profile)
    loaded = _load_wells(spark, table, well_col, date_col, volume_col, days_on_col, wells, None)
    fits, forecast = analyze_all(loaded, period, decisions, volume_unit)
    write_table(spark, spark.createDataFrame(fits), f"{output_prefix}_fits",
                f"Per-well decline fits and EUR from {table} by {SKILL} {VERSION}", FIT_COMMENTS)
    write_table(spark, spark.createDataFrame(forecast), f"{output_prefix}_forecast",
                f"Monthly forecast to economic limit / max life by {SKILL} {VERSION}",
                {"volume": f"Forecast volume per month, {volume_unit}", "rate_per_day": f"{volume_unit}/d"})
    manifest = build_manifest(SKILL, VERSION, {"table": table, "wells": len(loaded), "volume_col": volume_col,
                                               "volume_unit": volume_unit, "period": period},
                              decisions.as_dict(), {"output_prefix": output_prefix})
    write_manifest(spark, output_prefix, manifest)
    return _summary(fits, volume_unit, output_prefix)


def _summary(fits: pd.DataFrame, volume_unit: str, output_prefix: str) -> str:
    ok = fits[fits["status"] == "ok"]
    flagged = ok[ok["flags"].astype(str) != ""]
    lines = [f"Fitted {len(ok)}/{len(fits)} wells -> {output_prefix}_fits, _forecast, _manifest.",
             f"Total EUR: {ok['eur'].sum():,.0f} {volume_unit} (remaining {ok['remaining'].sum():,.0f}).",
             f"Wells with plausibility flags: {len(flagged)}"]
    lines += [f"  {r.well_id}: {r.flags}" for r in flagged.head(20).itertuples()]
    failed = fits[fits["status"] != "ok"]
    lines += [f"  NOT FITTED {r.well_id}: {r.status}" for r in failed.head(20).itertuples()]
    return "\n".join(lines)


def build_confirmed_type_curve(table: str, output_prefix: str, *, well_col: str, date_col: str, volume_col: str,
                               volume_unit: str, days_on_col: str | None, lateral_col: str | None,
                               normalization: str, reference_lateral_ft: float | None, rate_basis: str,
                               decline_start: str, outlier_method: str, b_bounds: tuple[float, float],
                               terminal_decline_eff, econ_limit_rate: float, max_life_years: float,
                               min_wells: int = 5, wells: list[str] | None = None,
                               profile: str | None = None) -> str:
    """P10/P50/P90 (PRMS) monthly type curve + EUR distribution from monthly data."""
    decisions = DcaDecisions.from_kwargs(
        rate_basis=rate_basis, decline_start=decline_start, outlier_method=outlier_method, b_bounds=b_bounds,
        terminal_decline_eff=terminal_decline_eff, econ_limit_rate=econ_limit_rate, max_life_years=max_life_years)
    tcd = TypeCurveDecisions.from_kwargs(normalization, reference_lateral_ft)
    if tcd.normalization == "lateral_length" and not lateral_col:
        raise DecisionRequired("lateral_col", ("column with lateral length in ft",), "needed to normalize")
    _check_columns(well_col=well_col, date_col=date_col, volume_col=volume_col, days_on_col=days_on_col,
                   lateral_col=lateral_col)
    _check_stream(volume_unit, "monthly")
    validate_identifier(output_prefix)
    spark = get_spark(profile)
    loaded = _load_wells(spark, table, well_col, date_col, volume_col, days_on_col, wells, None)
    laterals = _laterals(spark, table, well_col, lateral_col) if lateral_col else {}
    tc = build_type_curve(loaded, laterals, decisions, tcd, min_wells=min_wells)
    fits, _ = analyze_all(loaded, "monthly", decisions, volume_unit)
    ok = fits[fits["status"] == "ok"]
    eur_dist = eur_percentiles(dict(zip(ok["well_id"], ok["eur"])), laterals, tcd)
    write_table(spark, spark.createDataFrame(tc.curve.assign(volume_unit=volume_unit)), f"{output_prefix}_type_curve",
                f"PRMS P10(high)/P50/P90(low) type curve by {SKILL} {VERSION}",
                {"p10_high_rate": "P10 = HIGH case (90th percentile), per day",
                 "p90_low_rate": "P90 = LOW case (10th percentile), per day"})
    manifest = build_manifest(SKILL, VERSION, {"table": table, "wells_used": len(tc.wells_used)},
                              {**decisions.as_dict(), "normalization": tcd.normalization,
                               "reference_lateral_ft": tcd.reference_lateral_ft},
                              {"min_wells": min_wells, "eur_percentiles": eur_dist,
                               "wells_excluded": tc.wells_excluded})
    write_manifest(spark, f"{output_prefix}_type_curve", manifest)
    return (f"Type curve from {len(tc.wells_used)} wells ({len(tc.wells_excluded)} excluded), "
            f"{len(tc.curve)} months with >= {min_wells} wells -> {output_prefix}_type_curve.\n"
            f"EUR ({volume_unit}{', per ' + str(int(tcd.reference_lateral_ft)) + ' ft' if tcd.reference_lateral_ft else ''}):"
            f" P90(low) {eur_dist['p90_low']:,.0f} | P50 {eur_dist['p50']:,.0f} | P10(high) {eur_dist['p10_high']:,.0f}")


def _laterals(spark, table: str, well_col: str, lateral_col: str) -> dict[str, float]:
    from pyspark.sql import functions as F

    rows = (spark.table(validate_identifier(table))
            .groupBy(F.col(well_col).cast("string").alias("well_id"))
            .agg(F.max(F.col(lateral_col).cast("double")).alias("lateral")).collect())
    return {r["well_id"]: r["lateral"] for r in rows}
