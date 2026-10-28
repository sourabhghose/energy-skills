"""Databricks entrypoints for grid-data-guard — EXECUTION model.

Genie Code CALLS these functions and reports their output. It does not hand-write masking or
aggregation SQL, and does not choose the audience, rule, grain, or geo precision.

    import sys; sys.path.append('<this-skill-dir>/scripts')
    from gdg_run import preview_guard_options, build_confirmed_guard

    print(preview_guard_options("main.ami.monthly_usage", customer_col="premise_id",
                                value_col="kwh", time_col="read_month",
                                lat_col="lat", lon_col="lon",
                                candidate_groupings=[["zip"], ["rate_class", "zip"], ["geo"]]))
    print(build_confirmed_guard("main.ami.monthly_usage", "main.share.usage_by_zip",
                                release_audience="public", aggregation_rule="15_15",
                                group_by=["zip"], time_grain="month",
                                customer_col="premise_id", value_col="kwh",
                                time_col="read_month"))

``preview_guard_options`` is READ-ONLY. ``build_confirmed_guard`` requires every decision.
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _uc import (execute_sql, quote_identifier, read_query, sql_string_literal,  # noqa: E402
                 validate_identifier, write_manifest, write_table)
from gdg_classify import apply_overrides, classify_columns  # noqa: E402
from gdg_core import (apply_rule, column_plan, complementary_suppression,  # noqa: E402
                      coordinate_uniqueness, risk_summary)
from gdg_decisions import DECISIONS, SKILL_VERSION, build_manifest, make_config  # noqa: E402
from gdg_sql import column_tag_sql, group_stats_sql, internal_view_sql  # noqa: E402

PREVIEW_GEO = [("h3", 7), ("h3", 8), ("round", 2)]
PUBLISHED = ["n_customers", "total"]


def _sample(table: str, n: int, warehouse_id, profile):
    validate_identifier(table, fully_qualified=True)
    return read_query(f"SELECT * FROM {quote_identifier(table)} LIMIT {int(n)}",
                      warehouse_id=warehouse_id, profile=profile)


def _stats(table, grouping, customer_col, value_col, time_col, grain, geo, wh, profile):
    sql = group_stats_sql(table, list(grouping), customer_col, value_col, time_col, grain, geo)
    stats = read_query(sql, warehouse_id=wh, profile=profile)
    for col in ("n_customers", "total", "max_customer_value"):
        stats[col] = stats[col].astype(float)
    share = stats["max_customer_value"] / stats["total"].where(stats["total"] != 0)
    return stats.assign(max_customer_share_pct=100 * share.fillna(1.0))


def preview_guard_options(table: str, *, customer_col: str, value_col: str,
                          time_col: str | None = None, lat_col: str | None = None,
                          lon_col: str | None = None, candidate_groupings: list | None = None,
                          time_grains: tuple[str, ...] = ("month",), sample_rows: int = 50_000,
                          warehouse_id: str | None = None, profile: str | None = None) -> str:
    """READ-ONLY. Classify columns and show how much each grouping would suppress under 15/15."""
    sample = _sample(table, sample_rows, warehouse_id, profile)
    classes = classify_columns(sample)
    lines = ["GRID DATA GUARD PREVIEW (read-only — nothing was built)", "", "Column classes:"]
    lines += [f"  {c}: {v['class']} ({v['evidence']})" for c, v in classes.items()]
    if lat_col and lon_col:
        lines.append(f"Precise coordinates: {coordinate_uniqueness(sample[lat_col], sample[lon_col])}")
    lines += ["", "Suppression under 15/15 (full table, aggregated read):"]
    for grouping in candidate_groupings or []:
        geos = PREVIEW_GEO if "geo" in grouping else [None]
        for geo in geos:
            for grain in time_grains if time_col else [None]:
                g = (lat_col, lon_col, *geo) if geo else None
                stats = apply_rule(_stats(table, grouping, customer_col, value_col, time_col,
                                          grain, g, warehouse_id, profile), "15_15", 15, 15.0)
                label = f"{grouping} geo={geo} grain={grain}"
                lines.append(f"  {label}: {json.dumps(risk_summary(stats), default=str)}")
    lines += ["", "DECISIONS REQUIRED (ask the user or their privacy officer; do not pick):"]
    lines += [f"  - {n}: {s['options']}  — {s['why']}" for n, s in DECISIONS.items()]
    return "\n".join(lines)


def build_confirmed_guard(table: str, output: str, *, release_audience=None,
                          privileged_group=None, tokenization_secret=None, aggregation_rule=None,
                          k_min=None, group_by=None, time_grain=None, geo_method=None,
                          geo_precision=None, customer_col: str | None = None,
                          value_col: str | None = None, time_col: str | None = None,
                          lat_col: str | None = None, lon_col: str | None = None,
                          class_overrides: dict | None = None, tag_source_columns: bool = False,
                          warehouse_id: str | None = None, profile: str | None = None) -> str:
    """Build the governed view (internal) or the rule-checked aggregate table (external)."""
    validate_identifier(output, fully_qualified=True)
    sample = _sample(table, 5_000, warehouse_id, profile)
    classes = apply_overrides(classify_columns(sample), class_overrides)
    has_ids = any(v["class"] == "PII_ID" for v in classes.values())
    cfg = make_config(has_id_columns=has_ids, release_audience=release_audience,
                      privileged_group=privileged_group, tokenization_secret=tokenization_secret,
                      aggregation_rule=aggregation_rule, k_min=k_min,
                      group_by=tuple(group_by) if group_by else None, time_grain=time_grain,
                      geo_method=geo_method, geo_precision=geo_precision)
    plan = column_plan(classes, cfg.release_audience, cfg.group_by)
    geo = (lat_col, lon_col, cfg.geo_method, cfg.geo_precision) if lat_col and cfg.geo_method \
        else None
    if cfg.aggregate_only:
        result = _build_aggregate(table, output, cfg, customer_col, value_col, time_col, geo,
                                  warehouse_id, profile)
    else:
        result = _build_internal(table, output, cfg, plan, geo, warehouse_id, profile)
    if tag_source_columns:
        for stmt in column_tag_sql(table, plan):
            execute_sql(stmt, warehouse_id=warehouse_id, profile=profile)
    manifest = build_manifest(cfg, {"table": table}, result, plan)
    write_manifest(manifest, f"{output}_manifest")
    return _format_build(cfg, plan, result, manifest)


def _build_internal(table, output, cfg, plan, geo, wh, profile) -> dict:
    sql = internal_view_sql(table, output, plan, cfg.privileged_group, cfg.tokenization_secret,
                            geo)
    execute_sql(sql, warehouse_id=wh, profile=profile)
    comment = (f"Governed view (grid-data-guard {SKILL_VERSION}); sensitive columns visible "
               f"only to {cfg.privileged_group}")
    execute_sql(f"COMMENT ON TABLE {quote_identifier(output)} IS {sql_string_literal(comment)}",
                warehouse_id=wh, profile=profile)
    return {"view": output, "masked": sorted(c for c, p in plan.items()
                                              if p["action"] == "mask_privileged"),
            "tokenized": sorted(c for c, p in plan.items() if p["action"] == "tokenize")}


def _build_aggregate(table, output, cfg, customer_col, value_col, time_col, geo, wh, profile):
    if not customer_col or not value_col:
        raise ValueError("Aggregate releases need customer_col and value_col.")
    stats = _stats(table, cfg.group_by, customer_col, value_col, time_col, cfg.time_grain, geo,
                   wh, profile)
    ruled = apply_rule(stats, cfg.aggregation_rule, cfg.k_min, cfg.max_share_pct)
    parents = ["period"] if time_col else []
    final = complementary_suppression(ruled, parents) if cfg.complementary_suppression else ruled
    dims = [c for c in final.columns if c not in
            ("n_customers", "total", "max_customer_value", "max_customer_share_pct",
             "passes_rule", "suppression_reason", "complementary")]
    released = final.loc[final["passes_rule"], dims + PUBLISHED].reset_index(drop=True)
    write_table(released.rename(columns={"total": f"total_{value_col}"}), output,
                table_comment=f"Aggregate release, {cfg.aggregation_rule} rule, "
                              f"{cfg.release_audience} (grid-data-guard {SKILL_VERSION}). "
                              "Suppressed cells are omitted.")
    summary = risk_summary(final)
    write_table(final.groupby("suppression_reason").size().rename("cells").reset_index(),
                f"{output}_suppression", table_comment="Suppressed-cell counts by reason")
    return {"table": output, "cells_released": int(len(released)), **summary}


def _format_build(cfg, plan, result, manifest) -> str:
    lines = ["GRID DATA GUARD BUILD COMPLETE", f"  run_id: {manifest['run_id']}",
             f"  audience: {cfg.release_audience}", f"  result: {json.dumps(result, default=str)}",
             "  column plan:"]
    lines += [f"    {c}: {p['class']} -> {p['action']}" for c, p in plan.items()]
    lines.append("  The largest-customer value and share are used for the rule but never published.")
    return "\n".join(lines)
