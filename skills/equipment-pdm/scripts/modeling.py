"""Failure labels from work orders, leakage-safe splits, anomaly baselines, alert evaluation.

Purpose:
  * label_failures: rows within `label_horizon_hours` before a qualifying failure are positive;
    rows during the outage (failure start -> restored) are excluded, not labelled healthy
  * split: by time with an embargo equal to the label horizon (labels look forward, so
    test labels must not leak into training), by asset, or both
  * fit/score: robust z (median / MAD) or isolation forest, fitted on healthy training rows
  * evaluate_alerts: dedupe alerts with a cooldown; report failures caught, lead time, and
    false alarms per asset-month (the number maintenance planners actually care about)

Usage:
    from modeling import label_failures, split, fit_baseline, score, evaluate_alerts
"""

from __future__ import annotations

import hashlib

import numpy as np
import pandas as pd

from pdm_taxonomy import ANOMALY_METHODS, SPLIT_STRATEGIES

DAYS_PER_MONTH = 30.4375


def qualifying_failures(work_orders: pd.DataFrame, failure_modes: list[str]) -> pd.DataFrame:
    """Work orders whose failure_mode is in the chosen set, with tz-aware start / restore times."""
    missing = [c for c in ("asset_id", "failure_mode", "failure_start") if c not in work_orders]
    if missing:
        raise ValueError(f"work orders missing columns: {missing}")
    wo = work_orders[work_orders["failure_mode"].isin(failure_modes)]
    start = pd.to_datetime(wo["failure_start"])
    restored = pd.to_datetime(wo["restored"]) if "restored" in wo else start
    return wo.assign(failure_start=start, restored=restored.fillna(start)).sort_values("failure_start")


def label_failures(feats: pd.DataFrame, failures: pd.DataFrame, horizon_hours: int) -> pd.DataFrame:
    """Adds label (1 pre-failure, 0 healthy, NaN excluded/outage) and hours_to_failure."""
    horizon = pd.Timedelta(hours=int(horizon_hours))
    label = pd.Series(0.0, index=feats.index)
    to_fail = pd.Series(np.nan, index=feats.index)
    for f in failures.itertuples():
        same = feats["asset_id"] == f.asset_id
        pre = same & (feats["ts"] >= f.failure_start - horizon) & (feats["ts"] < f.failure_start)
        outage = same & (feats["ts"] >= f.failure_start) & (feats["ts"] <= f.restored)
        hours = (f.failure_start - feats["ts"]).dt.total_seconds() / 3600.0
        to_fail = to_fail.where(~pre | (to_fail <= hours), hours)
        label = label.mask(pre & label.notna(), 1.0).mask(outage, np.nan)
    return feats.assign(label=label, hours_to_failure=to_fail)


def _test_assets(assets: list[str], fraction: float) -> set[str]:
    """Deterministic asset hold-out by hash (stable across reruns)."""
    ranked = sorted(assets, key=lambda a: hashlib.sha256(str(a).encode()).hexdigest())
    return set(ranked[: max(1, round(len(ranked) * fraction))])


def split(feats: pd.DataFrame, strategy: str, horizon_hours: int, test_fraction: float = 0.3) -> pd.Series:
    """'train' / 'test' / 'embargo' per row."""
    if strategy not in SPLIT_STRATEGIES:
        raise ValueError(f"split_strategy must be one of {SPLIT_STRATEGIES}")
    cutoff = feats["ts"].quantile(1 - test_fraction)
    embargo_end = cutoff + pd.Timedelta(hours=int(horizon_hours))
    test_assets = _test_assets(sorted(feats["asset_id"].unique()), test_fraction)
    in_test_assets = feats["asset_id"].isin(test_assets)
    after, before = feats["ts"] >= embargo_end, feats["ts"] < cutoff
    if strategy == "asset":
        return pd.Series(np.where(in_test_assets, "test", "train"), index=feats.index)
    if strategy == "time":
        return pd.Series(np.select([before, after], ["train", "test"], "embargo"), index=feats.index)
    return pd.Series(np.select([~in_test_assets & before, in_test_assets & after], ["train", "test"], "embargo"),
                     index=feats.index)


def feature_columns(feats: pd.DataFrame) -> list[str]:
    skip = {"asset_id", "ts", "steady", "label", "hours_to_failure", "split", "vibration_zone", "score"}
    return [c for c in feats.columns if c not in skip and feats[c].dtype.kind in "fi"]


def fit_baseline(train: pd.DataFrame, method: str, columns: list[str]) -> dict:
    """Fit on healthy, steady training rows only."""
    if method not in ANOMALY_METHODS:
        raise ValueError(f"anomaly_method must be one of {ANOMALY_METHODS}")
    healthy = train[(train["label"] == 0) & train["steady"].astype(bool)][columns]
    if healthy.dropna(how="all").empty:
        raise ValueError("no healthy steady training rows to fit a baseline")
    median = healthy.median()
    if method == "robust_z":
        mad = (healthy - median).abs().median() * 1.4826
        return {"method": method, "columns": columns, "median": median, "scale": mad.where(mad > 0)}
    from sklearn.ensemble import IsolationForest

    model = IsolationForest(n_estimators=200, random_state=0).fit(healthy.fillna(median).to_numpy())
    return {"method": method, "columns": columns, "median": median, "model": model}


def score(feats: pd.DataFrame, baseline: dict) -> pd.Series:
    """Anomaly score per row (higher = more anomalous); NaN for non-steady rows."""
    x = feats[baseline["columns"]]
    if baseline["method"] == "robust_z":
        z = ((x - baseline["median"]) / baseline["scale"]).abs()
        raw = z.max(axis=1, skipna=True)
    else:
        raw = pd.Series(-baseline["model"].score_samples(x.fillna(baseline["median"]).to_numpy()), index=feats.index)
    return raw.where(feats["steady"].astype(bool))


def alert_events(scored: pd.DataFrame, threshold: float, cooldown_hours: int) -> pd.DataFrame:
    """First exceedance per asset, then silence for `cooldown_hours`."""
    hits = scored[scored["score"] > float(threshold)].sort_values(["asset_id", "ts"])
    events, cooldown = [], pd.Timedelta(hours=int(cooldown_hours))
    for asset, g in hits.groupby("asset_id"):
        last = None
        for ts, sc in zip(g["ts"], g["score"]):
            if last is None or ts >= last + cooldown:
                events.append({"asset_id": asset, "alert_ts": ts, "score": float(sc)})
                last = ts
    return pd.DataFrame(events, columns=["asset_id", "alert_ts", "score"])


def _asset_months(test: pd.DataFrame) -> float:
    span = test.groupby("asset_id")["ts"].agg(lambda s: (s.max() - s.min()).total_seconds() / 86400.0)
    return float(span.sum() / DAYS_PER_MONTH)


def _match(alerts: pd.DataFrame, failures: pd.DataFrame, horizon: pd.Timedelta) -> tuple[list, set]:
    lead_times, true_alerts = [], set()
    for f in failures.itertuples():
        window = alerts[(alerts["asset_id"] == f.asset_id) & (alerts["alert_ts"] >= f.failure_start - horizon)
                        & (alerts["alert_ts"] < f.failure_start)]
        true_alerts |= set(window.index)
        lead_times.append((f.failure_start - window["alert_ts"].min()).total_seconds() / 3600.0
                          if len(window) else None)
    return lead_times, true_alerts


def evaluate_alerts(scored_test: pd.DataFrame, failures: pd.DataFrame, threshold: float,
                    horizon_hours: int) -> dict:
    """Failures caught, median lead time, false alarms per asset-month on the test rows."""
    horizon = pd.Timedelta(hours=int(horizon_hours))
    alerts = alert_events(scored_test, threshold, horizon_hours)
    lo, hi = scored_test["ts"].min(), scored_test["ts"].max()
    in_test = failures[failures["asset_id"].isin(scored_test["asset_id"].unique())
                       & (failures["failure_start"] > lo) & (failures["failure_start"] <= hi + horizon)]
    lead, true_idx = _match(alerts, in_test, horizon)
    caught = [x for x in lead if x is not None]
    false_alarms = int(len(alerts) - len(true_idx))
    months = _asset_months(scored_test)
    return {"threshold": float(threshold), "failures": int(len(in_test)), "caught": len(caught),
            "recall": round(len(caught) / len(in_test), 3) if len(in_test) else None,
            "median_lead_time_h": float(np.median(caught)) if caught else None,
            "alerts": int(len(alerts)), "false_alarms": false_alarms,
            "false_alarms_per_asset_month": round(false_alarms / months, 3) if months else None,
            "precision": round(len(true_idx) / len(alerts), 3) if len(alerts) else None,
            "asset_months": round(months, 2)}


def threshold_sweep(scored_test: pd.DataFrame, failures: pd.DataFrame, horizon_hours: int,
                    quantiles=(0.95, 0.98, 0.99, 0.995, 0.999)) -> pd.DataFrame:
    """Trade-off table the user picks `alert_threshold` from (preview only)."""
    s = scored_test["score"].dropna()
    rows = [evaluate_alerts(scored_test, failures, float(s.quantile(q)), horizon_hours) | {"quantile": q}
            for q in quantiles] if len(s) else []
    return pd.DataFrame(rows)
