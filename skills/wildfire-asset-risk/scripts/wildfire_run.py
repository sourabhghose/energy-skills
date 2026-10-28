"""Databricks runner: index assets with Databricks H3 SQL, score with the core, write to UC.

Purpose
    1. segment_cells_sql   h3_coverash3 over each span (LINESTRING lon lat ...) at `res`,
                           returned as H3 strings (h3_h3tostring) so they match python h3.
    2. point_cells_sql     h3_longlatash3string(lon, lat, res) for point layers
                           (ignitions, structures, weather grid points).
    3. preview_from_uc / build_confirmed_from_uc  read the tables, call wildfire_api, and
                           (build only) write <prefix>_segment_risk, _circuit_risk,
                           _psps_candidates, _mitigation_plan, _shareable_cells, _manifest.
    Requires Python compute with a Spark session and the `h3` package (%pip install h3)
    so k-ring buffers in the core use the same cell ids as Databricks.

Pitfall
    Databricks H3 functions take (longitude, latitude); python h3 takes (lat, lng).

Usage
    from wildfire_run import preview_from_uc, build_confirmed_from_uc
"""

from __future__ import annotations

import json
import logging
import re

import pandas as pd

from h3grid import BACKEND
from wildfire_api import SKILL_VERSION, build_confirmed_wildfire_risk, preview_wildfire_risk

LOG = logging.getLogger(__name__)
IDENT = re.compile(r"^[A-Za-z0-9_]+(\.[A-Za-z0-9_]+){0,2}$")
LAYER_KEYS = ("vegetation", "fuel", "slope", "ignitions", "exposure")


def _q(name: str) -> str:
    if not IDENT.match(name):
        raise ValueError(f"Invalid Unity Catalog identifier: {name!r}")
    return ".".join(f"`{p}`" for p in name.split("."))


def _spark():
    try:
        from pyspark.sql import SparkSession
    except ImportError as exc:
        raise RuntimeError("wildfire_run needs a Spark session (Python compute).") from exc
    session = SparkSession.getActiveSession()
    if session is None:
        raise RuntimeError("No active Spark session; run on serverless or a cluster.")
    return session


def segment_cells_sql(segments_table: str) -> str:
    """Cells covering each span. `:res` is bound as a parameter."""
    return f"""
SELECT segment_id, h3_h3tostring(cell) AS cell
FROM (
  SELECT segment_id,
         explode(h3_coverash3(
           concat('LINESTRING(', lon1, ' ', lat1, ', ', lon2, ' ', lat2, ')'), :res)) AS cell
  FROM {_q(segments_table)}
)"""


def point_cells_sql(points_table: str, value_cols: list[str]) -> str:
    """Aggregate a point layer (lat, lon, values) to H3 strings at `:res`."""
    cols = ", ".join(f"SUM({_col(c)}) AS {_col(c)}" for c in value_cols)
    return f"""
SELECT h3_longlatash3string(lon, lat, :res) AS cell, {cols}
FROM {_q(points_table)}
GROUP BY 1"""


def _col(name: str) -> str:
    if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", name):
        raise ValueError(f"Invalid column name: {name!r}")
    return f"`{name}`"


def _load(segments_table: str, layer_tables: dict, res: int) -> tuple:
    if BACKEND != "h3":
        raise RuntimeError("Install python h3 (%pip install h3) so buffers match Databricks H3.")
    missing = set(LAYER_KEYS) - set(layer_tables)
    if missing:
        raise ValueError(f"layer_tables is missing {sorted(missing)}")
    spark = _spark()
    segments = spark.table(_q(segments_table)).toPandas()
    cells = spark.sql(segment_cells_sql(segments_table), args={"res": res}).toPandas()
    layers = {k: spark.table(_q(v)).toPandas() for k, v in layer_tables.items()}
    return segments, cells, layers


def preview_from_uc(segments_table: str, layer_tables: dict, res: int, buffer_k: int,
                    forecast_table: str | None = None) -> dict:
    """READ-ONLY preview over UC tables (layers already keyed by H3 string `cell`)."""
    segments, cells, layers = _load(segments_table, layer_tables, res)
    forecast = _spark().table(_q(forecast_table)).toPandas() if forecast_table else None
    return preview_wildfire_risk(segments, layers, res, buffer_k, forecast, cells=cells)


def build_confirmed_from_uc(segments_table: str, layer_tables: dict, res: int, buffer_k: int,
                            target_prefix: str, *, likelihood_weights, consequence_basis,
                            psps_thresholds=None, forecast_table: str | None = None,
                            mitigation_assumptions: pd.DataFrame | None = None,
                            budget_usd: float | None = None) -> dict:
    """Build and persist under confirmed decisions (weights and basis have no defaults)."""
    _q(target_prefix)
    segments, cells, layers = _load(segments_table, layer_tables, res)
    forecast = _spark().table(_q(forecast_table)).toPandas() if forecast_table else None
    result = build_confirmed_wildfire_risk(
        segments, layers, res, buffer_k, likelihood_weights=likelihood_weights,
        consequence_basis=consequence_basis, psps_thresholds=psps_thresholds,
        forecast=forecast, mitigation_assumptions=mitigation_assumptions,
        budget_usd=budget_usd, cells=cells,
        source_tables={"segments": segments_table, **layer_tables, "forecast": forecast_table})
    _persist(result, target_prefix)
    return result


def _persist(result: dict, prefix: str) -> None:
    spark = _spark()
    outputs = {"segment_risk": result["segment_risk"], "circuit_risk": result["circuit_risk"],
               "psps_candidates": result["psps_candidates"],
               "mitigation_plan": result["mitigation_plan"],
               "shareable_cells": result["shareable_cells"],
               "manifest": pd.DataFrame([{"manifest_json": json.dumps(result["manifest"],
                                                                      default=str)}])}
    for suffix, pdf in outputs.items():
        if pdf is None or pdf.empty:
            LOG.info("skipping empty output %s", suffix)
            continue
        name = _q(f"{prefix}_{suffix}")
        spark.createDataFrame(pdf).write.mode("overwrite").option(
            "overwriteSchema", "true").saveAsTable(name)
        note = f"wildfire-asset-risk v{SKILL_VERSION}; CEII-sensitive unless shareable_cells"
        spark.sql(f"COMMENT ON TABLE {name} IS '{note}'")
