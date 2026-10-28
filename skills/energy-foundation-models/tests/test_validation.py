"""Seasonal-naive validation gate and endpoint smoke checks."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from conftest import FakeForecaster, feeder_load

from tsfm_validation import (
    ValidationGate,
    backtest,
    interval_coverage,
    pinball_loss,
    seasonal_naive,
    seasonal_period,
    smoke_test_response,
)


@pytest.mark.parametrize("freq,cycle,expected", [
    ("15min", "weekly", 672), ("30min", "weekly", 336), ("1h", "daily", 24), ("1h", "weekly", 168),
])
def test_seasonal_period(freq, cycle, expected):
    assert seasonal_period(freq, cycle) == expected


def test_seasonal_naive_repeats_last_season():
    assert seasonal_naive(np.arange(6.0), 5, 3).tolist() == [3.0, 4.0, 5.0, 3.0, 4.0]


def test_pinball_is_zero_for_perfect_forecast():
    actual = np.array([1.0, 2.0])
    q = np.column_stack([actual, actual, actual])
    assert pinball_loss(actual, q, (0.1, 0.5, 0.9)) == 0.0
    assert interval_coverage(actual, q) == 1.0


def test_weekly_naive_model_beats_daily_naive_gate():
    series = feeder_load(n_days=42)
    good = FakeForecaster(season=336)  # weekly naive captures the weekend dip
    report = backtest(series, good, horizon=48, quantiles=(0.1, 0.5, 0.9),
                      season=seasonal_period("30min", "daily"), n_origins=8, gate=ValidationGate(),
                      min_context=336)
    assert report.n_origins == 8
    assert report.mase_ratio < 1.0
    assert report.passed


def test_biased_model_fails_gate_with_reason():
    series = feeder_load(n_days=42)
    bad = FakeForecaster(season=48, bias=15.0)
    report = backtest(series, bad, horizon=48, quantiles=(0.1, 0.5, 0.9), season=48,
                      n_origins=6, gate=ValidationGate())
    assert not report.passed
    assert any("MASE ratio" in r for r in report.reasons)


def test_backtest_origins_do_not_leak_future():
    series = feeder_load(n_days=21)
    spy = FakeForecaster(season=48)
    backtest(series, spy, horizon=48, quantiles=(0.5,), season=48, n_origins=3, gate=ValidationGate())
    assert spy.calls[-1]["lengths"][0] == len(series) - 48


def test_backtest_rejects_nan():
    series = feeder_load(n_days=21)
    series = np.where(np.arange(series.size) == 100, np.nan, series)
    with pytest.raises(ValueError, match="NaN"):
        backtest(series, FakeForecaster(48), 48, (0.5,), 48, 3, ValidationGate())


def test_smoke_test_flags_crossing_and_non_utc():
    resp = pd.DataFrame({"series_id": ["a", "a"], "timestamp": ["2026-01-01T00:00:00Z", "2026-01-01T00:30:00"],
                         "point": [1.0, 1.0], "q0.1": [2.0, 0.5], "q0.9": [1.0, 1.5],
                         "unit": "mwh", "model_revision": "x"})
    problems = smoke_test_response(resp, ["a"], horizon=2, quantile_columns=["q0.1", "q0.9"])
    assert "quantile crossing in response" in problems
    assert "response timestamps are not UTC (Z)" in problems
