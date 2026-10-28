"""Validation harness: does a foundation model beat a seasonal-naive baseline on *this* data?

Pure pandas / numpy. A zero-shot TSFM that loses to "same hour last week" on a utility's
own load is not worth an endpoint. This module runs a rolling-origin backtest for any
forecaster that matches the `Forecaster` protocol (a real adapter or a test fake), scores
it against seasonal naive, and returns a pass/fail verdict against an explicit gate.

Metrics:
    MASE      mean absolute scaled error (scale = in-sample seasonal-naive MAE)
    pinball   mean quantile (pinball) loss over the declared quantile levels
    coverage  share of actuals inside the outermost declared quantile interval

Usage:
    from tsfm_validation import ValidationGate, backtest, seasonal_period
    m = seasonal_period("1h", "weekly")            # 168
    report = backtest(series, forecaster, horizon=24, quantiles=(0.1, 0.5, 0.9),
                      season=m, n_origins=8, gate=ValidationGate())
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence

import numpy as np
import pandas as pd

class Forecaster(Protocol):
    """Anything that returns an array (horizon, n_quantiles) per context."""

    def predict(self, contexts: Sequence[np.ndarray], horizon: int,
                quantiles: Sequence[float]) -> list[np.ndarray]: ...


@dataclass(frozen=True)
class ValidationGate:
    """Ship gate. MASE ratio < 1 means the model beats seasonal naive on average."""

    max_mase_ratio: float = 1.0
    min_coverage: float = 0.0
    max_coverage: float = 1.0


@dataclass(frozen=True)
class BacktestReport:
    model_mase: float
    naive_mase: float
    mase_ratio: float
    model_pinball: float
    coverage: float
    nominal_coverage: float
    n_origins: int
    passed: bool
    reasons: tuple[str, ...]


def seasonal_period(freq: str, cycle: str) -> int:
    """Steps per daily or weekly cycle for a pandas frequency alias (e.g. '15min', '1h')."""
    offset = pd.tseries.frequencies.to_offset(freq)
    minutes = pd.Timedelta(offset).total_seconds() / 60.0
    if minutes <= 0 or (1440 % minutes and cycle == "daily"):
        raise ValueError(f"frequency {freq} does not divide a day")
    per_day = 1440.0 / minutes
    days = {"daily": 1, "weekly": 7}
    if cycle not in days:
        raise ValueError(f"cycle must be 'daily' or 'weekly', got {cycle!r}")
    return int(round(per_day * days[cycle]))


def seasonal_naive(context: np.ndarray, horizon: int, season: int) -> np.ndarray:
    """Repeat the last full season forward."""
    if len(context) < season:
        raise ValueError(f"context length {len(context)} < season {season}")
    last = context[-season:]
    reps = int(np.ceil(horizon / season))
    return np.tile(last, reps)[:horizon]


def mase_scale(context: np.ndarray, season: int) -> float:
    diffs = np.abs(context[season:] - context[:-season])
    diffs = diffs[np.isfinite(diffs)]
    scale = float(np.mean(diffs)) if diffs.size else float("nan")
    if not np.isfinite(scale) or scale == 0.0:
        raise ValueError("seasonal-naive scale is zero or undefined; series is flat or too short")
    return scale


def pinball_loss(actual: np.ndarray, qpred: np.ndarray, quantiles: Sequence[float]) -> float:
    """Mean pinball loss; qpred is (horizon, n_quantiles)."""
    losses = []
    for i, q in enumerate(quantiles):
        diff = actual - qpred[:, i]
        losses.append(np.mean(np.maximum(q * diff, (q - 1.0) * diff)))
    return float(np.mean(losses))


def interval_coverage(actual: np.ndarray, qpred: np.ndarray) -> float:
    lo, hi = qpred[:, 0], qpred[:, -1]
    return float(np.mean((actual >= lo) & (actual <= hi)))


def _origins(n: int, horizon: int, n_origins: int, min_context: int) -> list[int]:
    last = n - horizon
    first = max(min_context, last - (n_origins - 1) * horizon)
    if first > last:
        raise ValueError(
            f"series too short: need >= {min_context + horizon} points, have {n}"
        )
    return list(range(first, last + 1, horizon))[-n_origins:]


def _score_origin(series, cut, horizon, quantiles, season, forecaster):
    context, actual = series[:cut], series[cut:cut + horizon]
    scale = mase_scale(context, season)
    qpred = np.sort(np.asarray(forecaster.predict([context], horizon, quantiles)[0], float), axis=1)
    if qpred.shape != (horizon, len(quantiles)):
        raise ValueError(f"forecaster returned shape {qpred.shape}")
    point = qpred[:, list(quantiles).index(0.5)] if 0.5 in quantiles else qpred.mean(axis=1)
    naive = seasonal_naive(context, horizon, season)
    return (np.mean(np.abs(actual - point)) / scale,
            np.mean(np.abs(actual - naive)) / scale,
            pinball_loss(actual, qpred, quantiles) / scale,
            interval_coverage(actual, qpred))


def _verdict(ratio: float, coverage: float, gate: ValidationGate) -> tuple[bool, tuple[str, ...]]:
    reasons = []
    if not ratio < gate.max_mase_ratio:
        reasons.append(f"MASE ratio {ratio:.3f} >= gate {gate.max_mase_ratio}")
    if not gate.min_coverage <= coverage <= gate.max_coverage:
        reasons.append(f"coverage {coverage:.3f} outside [{gate.min_coverage}, {gate.max_coverage}]")
    return (not reasons, tuple(reasons))


def backtest(series: np.ndarray, forecaster: Forecaster, horizon: int,
             quantiles: Sequence[float], season: int, n_origins: int,
             gate: ValidationGate, min_context: int | None = None) -> BacktestReport:
    """Rolling-origin backtest (non-overlapping horizons, no future leakage)."""
    values = np.asarray(series, dtype=float)
    if np.isnan(values).any():
        raise ValueError("series contains NaN; impute or choose a gap policy before validating")
    cuts = _origins(len(values), horizon, n_origins, min_context or 2 * season)
    scores = np.array([_score_origin(values, c, horizon, quantiles, season, forecaster) for c in cuts])
    model_mase, naive_mase, pinball, coverage = scores.mean(axis=0)
    ratio = float(model_mase / naive_mase)
    passed, reasons = _verdict(ratio, float(coverage), gate)
    return BacktestReport(
        model_mase=float(model_mase), naive_mase=float(naive_mase), mase_ratio=ratio,
        model_pinball=float(pinball), coverage=float(coverage),
        nominal_coverage=float(quantiles[-1] - quantiles[0]), n_origins=len(cuts),
        passed=passed, reasons=reasons,
    )


def smoke_test_response(response: pd.DataFrame, expected_series: Sequence[str], horizon: int,
                        quantile_columns: Sequence[str]) -> list[str]:
    """Return a list of problems with an endpoint response (empty list == pass)."""
    problems = []
    needed = {"series_id", "timestamp", "point", "unit", "model_revision", *quantile_columns}
    missing = needed - set(response.columns)
    if missing:
        return [f"missing columns: {sorted(missing)}"]
    counts = response.groupby("series_id").size()
    for sid in expected_series:
        if counts.get(sid, 0) != horizon:
            problems.append(f"series {sid}: {counts.get(sid, 0)} rows, expected {horizon}")
    qvals = response[list(quantile_columns)].to_numpy(dtype=float)
    if (np.diff(qvals, axis=1) < 0).any():
        problems.append("quantile crossing in response")
    if not response["timestamp"].astype(str).str.endswith("Z").all():
        problems.append("response timestamps are not UTC (Z)")
    return problems
