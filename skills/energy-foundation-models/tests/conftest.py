"""Shared fixtures: synthetic energy series and a fake forecaster (no downloads, no MLflow)."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

from tsfm_contract import ForecastSpec  # noqa: E402


class FakeForecaster:
    """Seasonal-naive point forecast with a fixed symmetric fan; records what it was given."""

    def __init__(self, season: int, spread: float = 5.0, bias: float = 0.0, max_context: int = 4096):
        self.season = season
        self.spread = spread
        self.bias = bias
        self.max_context = max_context
        self.calls: list[dict] = []

    def predict(self, contexts, horizon, quantiles, covariates=None):
        self.calls = [*self.calls, {"n": len(contexts), "lengths": [len(c) for c in contexts],
                                    "covariates": covariates}]
        out = []
        for ctx in contexts:
            ctx = np.nan_to_num(np.asarray(ctx, dtype=float), nan=float(np.nanmean(ctx)))
            base = np.tile(ctx[-self.season:], int(np.ceil(horizon / self.season)))[:horizon] + self.bias
            offsets = np.array([(q - 0.5) * 2 * self.spread for q in quantiles])
            out.append(base[:, None] + offsets[None, :])
        return out


def feeder_load(n_days: int = 21, freq: str = "30min", seed: int = 7) -> np.ndarray:
    """Synthetic feeder load in MWh per interval with daily + weekly shape and noise."""
    rng = np.random.default_rng(seed)
    per_day = int(pd.Timedelta("1D") / pd.Timedelta(freq))
    t = np.arange(n_days * per_day)
    daily = 10 * np.sin(2 * np.pi * t / per_day - np.pi / 2)
    weekly = 4 * (np.floor(t / per_day) % 7 >= 5)
    return 50 + daily - weekly + rng.normal(0, 1.0, t.size)


def request_frame(values: np.ndarray, start: str, freq: str, series_id: str = "feeder_001",
                  tz: str = "UTC") -> pd.DataFrame:
    idx = pd.date_range(start, periods=len(values), freq=freq, tz=tz)
    return pd.DataFrame({"series_id": series_id, "timestamp": idx.map(lambda ts: ts.isoformat()),
                         "target": values})


@pytest.fixture
def spec() -> ForecastSpec:
    return ForecastSpec(horizon=48, quantiles=(0.1, 0.5, 0.9), freq="30min", unit="mwh",
                        non_negative=True, gap_policy="reject")


@pytest.fixture
def fake() -> FakeForecaster:
    return FakeForecaster(season=48)
