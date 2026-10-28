"""Operating state, features, labels, splits, baselines, and alert evaluation."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from conftest import FAIL_AT, START
from features import add_features, operating_state
from modeling import (alert_events, evaluate_alerts, fit_baseline, label_failures, qualifying_failures, score,
                      split)
from pdm_taxonomy import VIBRATION_ZONES, vibration_zone


def _wide(n=48, stop_at=(20, 24)):
    ts = pd.date_range("2026-01-01", periods=n, freq="30min", tz="UTC")
    run = np.ones(n)
    run[stop_at[0]:stop_at[1]] = 0
    return pd.DataFrame({"asset_id": "A", "ts": ts, "run_status": run, "motor_current": np.linspace(40, 50, n)})


def test_transients_excluded_around_start_and_stop():
    w = operating_state(_wide(), "status_tag", 60)
    steady = w.set_index("ts")["steady"]
    stop = pd.Timestamp("2026-01-01 10:00", tz="UTC")
    restart = pd.Timestamp("2026-01-01 12:00", tz="UTC")
    assert not steady[stop - pd.Timedelta("30min")]
    assert not steady[restart] and not steady[restart + pd.Timedelta("30min")]
    assert steady[restart + pd.Timedelta("60min")]


def test_threshold_running_definition_requires_config():
    with pytest.raises(ValueError):
        operating_state(_wide(), "threshold", 30)
    w = operating_state(_wide(), "threshold", 0, threshold={"measurement": "motor_current", "min": 45})
    assert w["running"].sum() == (w["motor_current"] > 45).sum()


def test_features_slope_and_steady_only():
    w = operating_state(_wide(), "status_tag", 0)
    f = add_features(w, "3h", None)
    assert f["motor_current_slope_per_h"].dropna().gt(0).all()
    assert f.loc[~f["steady"].astype(bool), "motor_current_mean"].isna().all()


def test_vibration_zones():
    b = VIBRATION_ZONES["group2_rigid"]
    assert [vibration_zone(v, b) for v in (1.0, 2.0, 3.0, 5.0)] == ["A", "B", "C", "D"]


def _feats():
    ts = pd.date_range(START, START + pd.Timedelta(days=28), freq="1h", tz="UTC")
    return pd.DataFrame({"asset_id": "ESP-101", "ts": ts, "steady": True, "x": 0.0})


def test_labels_pre_failure_and_outage(fleet):
    _, _, wo = fleet
    lab = label_failures(_feats(), qualifying_failures(wo, ["ELF"]), 72).set_index("ts")
    assert lab.loc[FAIL_AT - pd.Timedelta(hours=1), "label"] == 1
    assert lab.loc[FAIL_AT - pd.Timedelta(hours=73), "label"] == 0
    assert np.isnan(lab.loc[FAIL_AT + pd.Timedelta(hours=1), "label"])
    assert lab.loc[FAIL_AT - pd.Timedelta(hours=10), "hours_to_failure"] == pytest.approx(10)


def test_failure_mode_filter(fleet):
    _, _, wo = fleet
    assert list(qualifying_failures(wo, ["ELF"])["wo_id"]) == ["WO-1"]


def test_time_split_has_embargo():
    f = _feats()
    s = split(f, "time", 72)
    train_max = f.loc[s == "train", "ts"].max()
    test_min = f.loc[s == "test", "ts"].min()
    assert (test_min - train_max) >= pd.Timedelta(hours=72)
    assert (s == "embargo").sum() > 0


def test_asset_split_deterministic():
    f = pd.concat([_feats().assign(asset_id=a) for a in ("A", "B", "C", "D")])
    s1, s2 = split(f, "asset", 72), split(f, "asset", 72)
    assert (s1 == s2).all() and f.loc[s1 == "test", "asset_id"].nunique() == 1


def test_robust_z_fit_on_healthy_train_only():
    train = pd.DataFrame({"x": [1.0, 1.1, 0.9, 1.0, 100.0], "label": [0, 0, 0, 0, 1], "steady": True})
    base = fit_baseline(train, "robust_z", ["x"])
    assert base["median"]["x"] == pytest.approx(1.0)
    sc = score(pd.DataFrame({"x": [1.0, 5.0], "steady": [True, False]}), base)
    assert sc.iloc[0] == pytest.approx(0.0) and np.isnan(sc.iloc[1])


def test_isolation_forest_optional():
    pytest.importorskip("sklearn")
    rng = np.random.default_rng(0)
    train = pd.DataFrame({"x": rng.normal(0, 1, 200), "label": 0, "steady": True})
    base = fit_baseline(train, "isolation_forest", ["x"])
    sc = score(pd.DataFrame({"x": [0.0, 8.0], "steady": [True, True]}), base)
    assert sc.iloc[1] > sc.iloc[0]


def test_alert_cooldown_and_evaluation(fleet):
    _, _, wo = fleet
    ts = pd.date_range(START, START + pd.Timedelta(days=28), freq="1h", tz="UTC")
    scored = pd.DataFrame({"asset_id": "ESP-101", "ts": ts, "score": 0.0})
    hot = (ts >= FAIL_AT - pd.Timedelta(hours=30)) & (ts < FAIL_AT)
    false_alarm = (ts >= START + pd.Timedelta(days=3)) & (ts < START + pd.Timedelta(days=3, hours=2))
    scored = scored.assign(score=np.where(hot | false_alarm, 10.0, 0.0))
    alerts = alert_events(scored, 5.0, 72)
    assert len(alerts) == 2
    ev = evaluate_alerts(scored, qualifying_failures(wo, ["ELF"]), 5.0, 72)
    assert ev["caught"] == 1 and ev["median_lead_time_h"] == pytest.approx(30)
    assert ev["false_alarms"] == 1 and ev["false_alarms_per_asset_month"] > 0
