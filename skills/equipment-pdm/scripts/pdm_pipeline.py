"""End-to-end equipment-pdm pipeline on pandas frames (no Spark): profile, sweep, build.

Purpose: the offline core the runner wraps.
  * profile_inputs: tag grounding, sampling intervals, digital states, failure-mode counts,
    label counts per candidate horizon (read-only facts for the decision preview)
  * sweep(...): every decision except alert_threshold; returns the threshold trade-off measured
    on the TRAINING period (choosing a threshold on test data would leak)
  * build(...): every decision; returns features, scores, alert events, test evaluation

Usage:
    from pdm_pipeline import profile_inputs, sweep, build
"""

from __future__ import annotations

import pandas as pd

from features import add_features, operating_state
from modeling import (alert_events, evaluate_alerts, feature_columns, fit_baseline, label_failures,
                      qualifying_failures, score, split, threshold_sweep)
from pdm_taxonomy import VIBRATION_ZONES, require_decisions
from resample import resample_grid
from tags import ground_tags, normalize_samples

CANDIDATE_HORIZONS = (72, 168, 336)


def _intervals(samples: pd.DataFrame) -> pd.DataFrame:
    gaps = samples.groupby(["asset_id", "measurement"])["ts"].apply(
        lambda s: s.sort_values().diff().dt.total_seconds().div(60))
    return (gaps.groupby(level=["asset_id", "measurement"]).describe(percentiles=[0.5, 0.95])
            [["50%", "95%", "max"]].rename(columns={"50%": "median_gap_min", "95%": "p95_gap_min",
                                                    "max": "max_gap_min"}).reset_index())


def profile_inputs(historian: pd.DataFrame, tag_map: pd.DataFrame, work_orders: pd.DataFrame) -> dict:
    """Read-only facts for the preview."""
    grounding = ground_tags(historian, tag_map)
    samples, dropped = normalize_samples(historian, grounding.mapped)
    wo = work_orders.assign(failure_start=pd.to_datetime(work_orders["failure_start"]))
    return {
        "grounding": grounding, "dropped_samples": dropped,
        "sampling": _intervals(samples) if len(samples) else pd.DataFrame(),
        "has_run_status": bool((grounding.mapped["measurement"] == "run_status").any()),
        "failure_mode_counts": wo["failure_mode"].value_counts().to_dict(),
        "assets": sorted(grounding.mapped["asset_id"].unique()),
        "span": (samples["ts"].min(), samples["ts"].max()) if len(samples) else (None, None),
    }


def _zones(zone_class: str | None, site_limits: tuple | None):
    if site_limits:
        return tuple(float(x) for x in site_limits)
    return VIBRATION_ZONES[zone_class] if zone_class else None


def _prepare(historian, tag_map, work_orders, d: dict, p: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    grounding = ground_tags(historian, tag_map)
    samples, _ = normalize_samples(historian, grounding.mapped)
    wide = resample_grid(samples, p["freq"], d["analog_interpolation"], p["max_gap"])
    wide = operating_state(wide, d["running_definition"], d["transient_exclusion_minutes"], p.get("threshold"))
    feats = add_features(wide, p["window"], _zones(p.get("vibration_zone_class"), p.get("site_vibration_limits")))
    failures = qualifying_failures(work_orders, list(d["failure_modes"]))
    labelled = label_failures(feats, failures, d["label_horizon_hours"])
    return labelled.assign(split=split(labelled, d["split_strategy"], d["label_horizon_hours"],
                                       p.get("test_fraction", 0.3))), failures


def _scored(labelled: pd.DataFrame, d: dict) -> tuple[pd.DataFrame, dict]:
    cols = feature_columns(labelled)
    baseline = fit_baseline(labelled[labelled["split"] == "train"], d["anomaly_method"], cols)
    return labelled.assign(score=score(labelled, baseline)), baseline


DEFAULT_PARAMS = {"freq": "10min", "max_gap": "30min", "window": "2h", "test_fraction": 0.3}


def _decisions(**kw) -> dict:
    return require_decisions(**kw)


def sweep(historian, tag_map, work_orders, *, analog_interpolation, running_definition,
          transient_exclusion_minutes, failure_modes, label_horizon_hours, split_strategy,
          anomaly_method, params: dict | None = None) -> pd.DataFrame:
    """Threshold trade-off on the training period for the user to pick alert_threshold."""
    d = _decisions(analog_interpolation=analog_interpolation, running_definition=running_definition,
                   transient_exclusion_minutes=transient_exclusion_minutes, failure_modes=failure_modes,
                   label_horizon_hours=label_horizon_hours, split_strategy=split_strategy,
                   anomaly_method=anomaly_method)
    labelled, failures = _prepare(historian, tag_map, work_orders, d, {**DEFAULT_PARAMS, **(params or {})})
    scored, _ = _scored(labelled, d)
    return threshold_sweep(scored[scored["split"] == "train"], failures, d["label_horizon_hours"])


def build(historian, tag_map, work_orders, *, analog_interpolation, running_definition,
          transient_exclusion_minutes, failure_modes, label_horizon_hours, split_strategy,
          anomaly_method, alert_threshold, params: dict | None = None) -> dict:
    """Full pipeline; evaluation is on test rows only."""
    d = _decisions(analog_interpolation=analog_interpolation, running_definition=running_definition,
                   transient_exclusion_minutes=transient_exclusion_minutes, failure_modes=failure_modes,
                   label_horizon_hours=label_horizon_hours, split_strategy=split_strategy,
                   anomaly_method=anomaly_method, alert_threshold=alert_threshold)
    p = {**DEFAULT_PARAMS, **(params or {})}
    labelled, failures = _prepare(historian, tag_map, work_orders, d, p)
    scored, baseline = _scored(labelled, d)
    test = scored[scored["split"] == "test"]
    return {"decisions": d, "params": p, "features": scored, "failures": failures,
            "alerts": alert_events(test, alert_threshold, label_horizon_hours),
            "evaluation": evaluate_alerts(test, failures, alert_threshold, label_horizon_hours),
            "baseline_columns": baseline["columns"]}
