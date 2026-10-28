"""Databricks runner for equipment-pdm: preview -> threshold sweep -> confirmed build.

Purpose: Genie Code calls these entrypoints instead of writing PdM code by hand.
  * preview_pdm_options(...)    READ-ONLY: tag grounding, sampling, digital states, failure
                                modes, label counts per horizon, what each decision needs
  * sweep_alert_thresholds(...) READ-ONLY: threshold trade-off on the training period
  * build_confirmed_pdm(...)    every decision explicit; writes features, scores, alerts,
                                test evaluation and a run manifest to Unity Catalog

Usage (Python compute):
    import sys; sys.path.append("<skill-dir>/scripts")
    from pdm_run import preview_pdm_options, sweep_alert_thresholds, build_confirmed_pdm
    print(preview_pdm_options("ops.pi.samples", "ops.pi.tag_map", "ops.cmms.work_orders",
                              start="2026-01-01", end="2026-07-01"))
"""

from __future__ import annotations

import json
import logging

import pandas as pd

from modeling import label_failures, qualifying_failures
from pdm_pipeline import CANDIDATE_HORIZONS, build, profile_inputs, sweep
from uc_io import build_manifest, markdown, run_sql, validate_fqn, write_manifest, write_table

LOG = logging.getLogger(__name__)
SKILL, VERSION = "equipment-pdm", "0.1.0"


def _read_inputs(historian_table, tag_map_table, work_orders_table, start, end, warehouse_id, profile):
    kw = {"warehouse_id": warehouse_id, "profile": profile}
    tag_map = run_sql("SELECT * FROM {t}", tables={"t": validate_fqn(tag_map_table)}, **kw)
    tags = json.dumps(sorted(tag_map["tag"].astype(str).unique().tolist()))
    historian = run_sql(
        "SELECT * FROM {t} WHERE ts >= :start AND ts < :end "
        "AND array_contains(from_json(:tags, 'array<string>'), tag)",
        {"start": str(start), "end": str(end), "tags": tags}, tables={"t": validate_fqn(historian_table)}, **kw)
    work_orders = run_sql("SELECT * FROM {t}", tables={"t": validate_fqn(work_orders_table)}, **kw)
    return historian, tag_map, work_orders


def _label_counts(profile: dict, work_orders: pd.DataFrame) -> str:
    lo, hi = profile["span"]
    if lo is None:
        return "no samples"
    grid = pd.DataFrame([(a, t) for a in profile["assets"] for t in pd.date_range(lo, hi, freq="1h")],
                        columns=["asset_id", "ts"])
    failures = qualifying_failures(work_orders, list(profile["failure_mode_counts"]))
    lines = ["| horizon h | pre-failure asset-hours | share |", "|---|---|---|"]
    for h in CANDIDATE_HORIZONS:
        lab = label_failures(grid, failures, h)["label"]
        lines.append(f"| {h} | {int((lab == 1).sum())} | {100 * (lab == 1).mean():.2f} % |")
    return "\n".join(lines)


def preview_pdm_options(historian_table: str, tag_map_table: str, work_orders_table: str, *, start, end,
                        warehouse_id: str | None = None, profile: str | None = None) -> str:
    """READ-ONLY readout of facts behind each decision."""
    h, m, w = _read_inputs(historian_table, tag_map_table, work_orders_table, start, end, warehouse_id, profile)
    prof = profile_inputs(h, m, w)
    g = prof["grounding"]
    return "\n".join([
        f"# PdM preview ({start} → {end}, READ-ONLY, nothing written)",
        f"Assets: {len(prof['assets'])}  Mapped tags: {len(g.mapped)}",
        f"Historian tags not in tag map (excluded): {g.unmapped_tags or 'none'}",
        f"Tag-map tags with no samples: {g.missing_in_historian or 'none'}",
        "## Unit / measurement problems (excluded)", markdown(g.unit_problems) if len(g.unit_problems) else "none",
        "## Dropped samples (digital states / bad quality)",
        markdown(prof["dropped_samples"].head(20)) if len(prof["dropped_samples"]) else "none",
        "## Sampling intervals (choose max_gap and freq)", markdown(prof["sampling"]) if len(prof["sampling"]) else "none",
        f"\nrun_status tag available: {prof['has_run_status']} (decision running_definition)",
        f"Failure modes in work orders (decision failure_modes): {prof['failure_mode_counts']}",
        "## Pre-failure share by label horizon (all modes, decision label_horizon_hours)",
        _label_counts(prof, w),
        "\nNext: choose analog_interpolation, running_definition, transient_exclusion_minutes, failure_modes, "
        "label_horizon_hours, split_strategy, anomaly_method; then run sweep_alert_thresholds.",
    ])


def sweep_alert_thresholds(historian_table: str, tag_map_table: str, work_orders_table: str, *, start, end,
                           params: dict | None = None, warehouse_id: str | None = None,
                           profile: str | None = None, **decisions) -> str:
    """READ-ONLY threshold trade-off on the training period (all decisions but alert_threshold)."""
    h, m, w = _read_inputs(historian_table, tag_map_table, work_orders_table, start, end, warehouse_id, profile)
    table = sweep(h, m, w, params=params, **decisions)
    return "\n".join(["# Alert threshold trade-off (training period, READ-ONLY)", markdown(table),
                      "Choose alert_threshold for build_confirmed_pdm (false alarms per asset-month vs recall)."])


def _persist(res: dict, output_prefix: str, manifest: dict) -> list[str]:
    comment = f"{SKILL} v{VERSION}; decisions={json.dumps(res['decisions'], default=str)}"
    frames = {"features": res["features"], "alerts": res["alerts"],
              "evaluation": pd.DataFrame([res["evaluation"]])}
    written = [write_table(df.astype({c: "string" for c in df.columns if df[c].dtype == object}),
                           f"{output_prefix}_{name}", comment) for name, df in frames.items()]
    write_manifest(manifest, f"{output_prefix}_run_manifest")
    return written


def build_confirmed_pdm(historian_table: str, tag_map_table: str, work_orders_table: str, output_prefix: str, *,
                        start, end, analog_interpolation, running_definition, transient_exclusion_minutes,
                        failure_modes, label_horizon_hours, split_strategy, anomaly_method, alert_threshold,
                        params: dict | None = None, warehouse_id: str | None = None,
                        profile: str | None = None, write: bool = True) -> dict:
    """Build features, scores, alerts, evaluation. Every decision is keyword-only with no default."""
    validate_fqn(output_prefix)
    h, m, w = _read_inputs(historian_table, tag_map_table, work_orders_table, start, end, warehouse_id, profile)
    res = build(h, m, w, analog_interpolation=analog_interpolation, running_definition=running_definition,
                transient_exclusion_minutes=transient_exclusion_minutes, failure_modes=failure_modes,
                label_horizon_hours=label_horizon_hours, split_strategy=split_strategy,
                anomaly_method=anomaly_method, alert_threshold=alert_threshold, params=params)
    manifest = build_manifest(SKILL, VERSION, {"historian_table": historian_table, "tag_map_table": tag_map_table,
                                               "work_orders_table": work_orders_table, "start": str(start),
                                               "end": str(end), "samples": len(h)},
                              res["decisions"], {"params": res["params"], "evaluation": res["evaluation"],
                                                 "feature_columns": res["baseline_columns"]})
    if write:
        manifest = {**manifest, "tables": _persist(res, output_prefix, manifest)}
    return {"manifest": manifest, **res}


def format_result(res: dict) -> str:
    ev = res["evaluation"]
    return "\n".join([
        "# PdM result (test period only)", f"Decisions: {res['decisions']}",
        f"Failures in test: {ev['failures']}  Caught: {ev['caught']}  Recall: {ev['recall']}",
        f"Median lead time: {ev['median_lead_time_h']} h  Alerts: {ev['alerts']}  "
        f"False alarms / asset-month: {ev['false_alarms_per_asset_month']}  Precision: {ev['precision']}",
    ])
