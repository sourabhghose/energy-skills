"""Serving contract: UTC, DST, grid alignment, gaps, covariates, quantiles."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from conftest import feeder_load, request_frame

from tsfm_contract import (
    ContractError,
    DecisionRequired,
    ForecastSpec,
    apply_gap_policy,
    build_response,
    normalize_request,
    postprocess_quantiles,
)


def test_naive_timestamps_rejected(spec):
    df = request_frame(feeder_load(3), "2026-01-01", "30min").assign(
        timestamp=lambda d: pd.to_datetime(d["timestamp"]).dt.tz_localize(None).astype(str))
    with pytest.raises(ContractError, match="timezone-aware"):
        normalize_request(df, spec, max_context=1000)


def test_dst_fall_back_local_time_is_regular_in_utc(spec):
    # US Central fall-back day: 50 half-hours locally; regular 30-min grid in UTC.
    idx = pd.date_range("2026-11-01T00:00", "2026-11-01T23:30", freq="30min", tz="America/Chicago")
    assert len(idx) == 50
    df = pd.DataFrame({"series_id": "f1", "timestamp": [t.isoformat() for t in idx],
                       "target": np.linspace(10, 20, len(idx))})
    batch = normalize_request(df, spec, max_context=1000)
    assert len(batch.contexts[0]) == 50
    assert not np.isnan(batch.contexts[0]).any()


def test_duplicate_timestamps_fail(spec):
    df = request_frame(feeder_load(2), "2026-01-01", "30min")
    df = pd.concat([df, df.iloc[[5]]], ignore_index=True)
    with pytest.raises(ContractError, match="duplicate"):
        normalize_request(df, spec, max_context=1000)


def test_off_grid_timestamp_fails(spec):
    df = request_frame(feeder_load(2), "2026-01-01T00:15", "30min")
    df = pd.concat([request_frame(feeder_load(1), "2026-01-05", "30min"), df], ignore_index=True)
    with pytest.raises(ContractError, match="off the 30min grid"):
        normalize_request(df, spec, max_context=1000)


def test_undeclared_column_fails(spec):
    df = request_frame(feeder_load(2), "2026-01-01", "30min").assign(temp_c=5.0)
    with pytest.raises(ContractError, match="undeclared"):
        normalize_request(df, spec, max_context=1000)


def test_gap_policy_reject_and_interpolate():
    values = np.array([1.0, 2.0, np.nan, 4.0])
    with pytest.raises(ContractError, match="reject"):
        apply_gap_policy(values, "reject", "m1")
    filled = apply_gap_policy(values, "interpolate_linear", "m1")
    assert filled.tolist() == [1.0, 2.0, 3.0, 4.0]
    assert np.isnan(values[2]), "input must not be mutated"
    long_gap = np.array([1.0] + [np.nan] * 6 + [8.0])
    with pytest.raises(ContractError, match="longer than"):
        apply_gap_policy(long_gap, "interpolate_linear", "m1")


def test_missing_gap_policy_is_a_decision():
    with pytest.raises(DecisionRequired, match="gap_policy"):
        ForecastSpec(horizon=4, quantiles=(0.5,), freq="1h", unit="mwh", non_negative=True,
                     gap_policy=None)


def test_context_truncated_to_model_limit(spec):
    df = request_frame(feeder_load(10), "2026-01-01", "30min")
    batch = normalize_request(df, spec, max_context=100)
    assert len(batch.contexts[0]) == 100
    assert batch.truncated == ("feeder_001",)


def test_future_covariates_must_cover_horizon():
    spec = ForecastSpec(horizon=4, quantiles=(0.5,), freq="1h", unit="mwh", non_negative=True,
                        gap_policy="reject", covariates=("temp_c",))
    hist = request_frame(np.arange(48.0), "2026-01-01", "1h").assign(temp_c=1.0)
    fut = request_frame(np.full(4, np.nan), "2026-01-03", "1h").assign(temp_c=2.0)
    batch = normalize_request(pd.concat([hist, fut], ignore_index=True), spec, max_context=1000)
    assert batch.future_covariates[0].shape == (4, 1)
    with pytest.raises(ContractError, match="exactly the 4 steps"):
        normalize_request(pd.concat([hist, fut.iloc[:3]], ignore_index=True), spec, max_context=1000)


def test_postprocess_sorts_crossing_and_clips_only_when_asked():
    raw = np.array([[-2.0, -5.0, 1.0]])
    assert postprocess_quantiles(raw, non_negative=True).tolist() == [[0.0, 0.0, 1.0]]
    assert postprocess_quantiles(raw, non_negative=False).tolist() == [[-5.0, -2.0, 1.0]]


def test_build_response_shape_units_and_utc(spec, fake):
    df = request_frame(feeder_load(7), "2026-01-01", "30min")
    batch = normalize_request(df, spec, max_context=1000)
    raw = fake.predict(list(batch.contexts), spec.horizon, spec.quantiles)
    out = build_response(batch, raw, spec, model_name="fake", model_revision="0" * 40)
    assert len(out) == spec.horizon
    assert {"q0.1", "q0.5", "q0.9", "point", "unit"} <= set(out.columns)
    assert (out["unit"] == "mwh").all()
    assert out["timestamp"].str.endswith("Z").all()
    assert out["timestamp"].iat[0] == "2026-01-08T00:00:00Z"
    assert np.allclose(out["point"], out["q0.5"])
