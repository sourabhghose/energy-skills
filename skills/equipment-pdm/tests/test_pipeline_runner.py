"""End-to-end pipeline and runner contract."""

from __future__ import annotations

import pytest

import pdm_run
from conftest import DECISIONS
from pdm_pipeline import build, profile_inputs, sweep
from pdm_taxonomy import DecisionRequired

PARAMS = {"freq": "30min", "max_gap": "30min", "window": "6h"}


def test_profile(fleet):
    prof = profile_inputs(*fleet)
    assert prof["has_run_status"] and prof["failure_mode_counts"] == {"ELF": 1, "OTH": 1}
    assert len(prof["sampling"]) == 12


def test_build_catches_planted_failure(fleet):
    res = build(*fleet, alert_threshold=6.0, params=PARAMS, **DECISIONS)
    ev = res["evaluation"]
    assert ev["failures"] == 1 and ev["caught"] == 1
    assert ev["median_lead_time_h"] > 6
    assert res["decisions"]["label_horizon_hours"] == 72


def test_sweep_uses_training_period(fleet):
    table = sweep(*fleet, params=PARAMS, **DECISIONS)
    assert {"threshold", "recall", "false_alarms_per_asset_month", "quantile"} <= set(table.columns)


@pytest.mark.parametrize("missing", [*DECISIONS, "alert_threshold"])
def test_missing_decision_raises(fleet, missing):
    args = {**DECISIONS, "alert_threshold": 6.0, missing: None}
    with pytest.raises(DecisionRequired, match=missing):
        build(*fleet, params=PARAMS, **args)


def test_invalid_failure_modes(fleet):
    with pytest.raises(DecisionRequired):
        build(*fleet, params=PARAMS, alert_threshold=6.0, **{**DECISIONS, "failure_modes": ["XYZ"]})


@pytest.fixture
def patched(monkeypatch, fleet):
    monkeypatch.setattr(pdm_run, "_read_inputs", lambda *a, **k: fleet)
    monkeypatch.setattr(pdm_run, "write_table", lambda *a, **k: pytest.fail("unexpected write"))


def test_runner_preview_read_only(patched):
    text = pdm_run.preview_pdm_options("a.b.h", "a.b.m", "a.b.w", start="2026-03-01", end="2026-04-01")
    assert "READ-ONLY" in text and "ESP-101.SPARE1" in text and "| 72 |" in text


def test_runner_build_and_format(patched):
    res = pdm_run.build_confirmed_pdm("a.b.h", "a.b.m", "a.b.w", "a.b.out", start="2026-03-01", end="2026-04-01",
                                      alert_threshold=6.0, params=PARAMS, write=False, **DECISIONS)
    assert res["manifest"]["decisions"]["split_strategy"] == "time"
    assert "False alarms" in pdm_run.format_result(res)


def test_runner_sweep(patched):
    text = pdm_run.sweep_alert_thresholds("a.b.h", "a.b.m", "a.b.w", start="s", end="e", params=PARAMS, **DECISIONS)
    assert "training period" in text
