"""Databricks runner: Unity Catalog tables in, reliability tables + metric view out.

Purpose
    Thin adapter over reliability_api. Reads outage steps and customers served from UC,
    maps columns to the canonical names, calls the core, and (build only) writes:
        <target_prefix>_indices       headline / all-days / excl-MED rows
        <target_prefix>_daily_fact    complete date x circuit grid with MED flag
        <target_prefix>_causes        cause-code breakdown (non-MED days)
        <target_prefix>_manifest      run manifest (JSON string column)
        <target_prefix>_mv            metric view over the daily fact
    Requires Python compute with a Spark session (serverless or cluster).

Usage (Databricks notebook / Genie Code, serverless Python)
    import sys; sys.path.append("<skill-dir>/scripts")
    from reliability_run import preview_from_uc, build_confirmed_from_uc
    print(preview_from_uc("main.oms.restoration_steps", "main.cis.customers_served",
                          reporting_year=2024, tz="America/Chicago")["readout"])
"""

from __future__ import annotations

import json
import logging
import re

import pandas as pd

from metric_view import build_daily_fact, metric_view_sql
from reliability_api import SKILL_VERSION, build_confirmed_reliability, preview_reliability_options
from reliability_core import classify_steps, summarize_events

LOG = logging.getLogger(__name__)
IDENT = re.compile(r"^[A-Za-z0-9_]+(\.[A-Za-z0-9_]+){0,2}$")


def _spark():
    try:
        from pyspark.sql import SparkSession
    except ImportError as exc:
        raise RuntimeError("reliability_run needs a Spark session (Python compute).") from exc
    session = SparkSession.getActiveSession()
    if session is None:
        raise RuntimeError("No active Spark session; run on serverless or a cluster.")
    return session


def _check(name: str) -> str:
    if not IDENT.match(name):
        raise ValueError(f"Invalid Unity Catalog identifier: {name!r}")
    return ".".join(f"`{p}`" for p in name.split("."))


def _read(table: str, column_map: dict | None, tz: str | None) -> pd.DataFrame:
    """Read a UC table to pandas, renaming physical -> canonical columns."""
    pdf = _spark().table(_check(table)).toPandas()
    renamed = pdf.rename(columns={v: k for k, v in (column_map or {}).items()})
    if tz is None:
        return renamed
    converted = {c: _as_tz(renamed[c], tz) for c in ("outage_start", "restore_ts", "op_ts")
                 if c in renamed.columns}
    return renamed.assign(**converted)


def _as_tz(col: pd.Series, tz: str) -> pd.Series:
    """Spark returns session-local naive timestamps; localize as UTC then convert."""
    ts = pd.to_datetime(col)
    if ts.dt.tz is None:
        LOG.info("Localizing naive timestamps as UTC (Spark session timezone).")
        ts = ts.dt.tz_localize("UTC")
    return ts.dt.tz_convert(tz)


def preview_from_uc(steps_table: str, customers_table: str, reporting_year: int, tz: str,
                    steps_columns: dict | None = None,
                    customers_columns: dict | None = None) -> dict:
    """READ-ONLY preview over UC tables. Writes nothing."""
    steps = _read(steps_table, steps_columns, tz)
    customers = _read(customers_table, customers_columns, None)
    return preview_reliability_options(steps, customers, reporting_year, tz)


def build_confirmed_from_uc(steps_table: str, customers_table: str, reporting_year: int,
                            tz: str, target_prefix: str, *, sustained_threshold_min,
                            denominator_basis, planned_handling, med_method,
                            steps_columns: dict | None = None,
                            customers_columns: dict | None = None) -> dict:
    """Build + persist under confirmed decisions (all required, no defaults)."""
    _check(target_prefix)
    steps = _read(steps_table, steps_columns, tz)
    customers = _read(customers_table, customers_columns, None)
    result = build_confirmed_reliability(
        steps, customers, reporting_year, tz,
        sustained_threshold_min=sustained_threshold_min, denominator_basis=denominator_basis,
        planned_handling=planned_handling, med_method=med_method,
        source_tables={"steps_table": steps_table, "customers_table": customers_table},
    )
    events = summarize_events(classify_steps(steps, int(sustained_threshold_min)), tz)
    if planned_handling == "exclude_planned":
        events = events.loc[~events["is_planned"].astype(bool)]
    fact = build_daily_fact(events, customers, result["major_event_days"], reporting_year,
                            denominator_basis)
    _persist(result, fact, target_prefix)
    return result


def _persist(result: dict, fact: pd.DataFrame, prefix: str) -> None:
    spark = _spark()
    indices = pd.DataFrame([{"scope": k, **result[k]} for k in ("headline", "all_days",
                                                                 "excluding_med")])
    tables = {
        f"{prefix}_indices": indices,
        f"{prefix}_daily_fact": fact,
        f"{prefix}_causes": result["cause_breakdown"],
        f"{prefix}_manifest": pd.DataFrame([{"manifest_json": json.dumps(result["manifest"],
                                                                         default=str)}]),
    }
    for name, pdf in tables.items():
        spark.createDataFrame(pdf).write.mode("overwrite").option(
            "overwriteSchema", "true").saveAsTable(_check(name))
        comment = f"reliability-metrics v{SKILL_VERSION}; see {prefix}_manifest"
        spark.sql(f"COMMENT ON TABLE {_check(name)} IS {_sql_string(comment)}")
    spark.sql(metric_view_sql(f"{prefix}_mv", f"{prefix}_daily_fact"))


def _sql_string(value: str) -> str:
    """Escape a literal for COMMENT ON (DDL does not accept bound parameters)."""
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"
