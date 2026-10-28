"""Catalog of energy-relevant open-weight time-series foundation models.

Facts here are copied from the model cards in `references/models/` (reviewed 2026-10-28
against the Hugging Face API). `tests/test_model_cards.py` checks the two stay in sync.
Revisions are Hugging Face commit SHAs; re-pin them when you re-review a card.

`fit_report()` is what the runner's preview shows: which models can serve the requested
horizon, context, covariates, frequency, and licence posture, and why the others cannot.

Usage:
    from tsfm_catalog import CATALOG, fit_report
    rows = fit_report(horizon=48, context=4032, freq="30min", needs_future_covariates=True,
                      commercial_use=True)
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

DECILES = (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9)
# amazon/chronos-2 config.json "quantiles"
CHRONOS2_QUANTILES = (0.01, 0.05, 0.1, 0.15, 0.2, 0.25, 0.3, 0.35, 0.4, 0.45, 0.5,
                      0.55, 0.6, 0.65, 0.7, 0.75, 0.8, 0.85, 0.9, 0.95, 0.99)


@dataclass(frozen=True)
class ModelEntry:
    key: str
    hf_repo: str
    hf_revision: str
    package: str
    code_repo: str
    weights_license: str
    commercial_use: bool
    max_context: int
    max_horizon: int
    quantiles: tuple[float, ...]  # levels the checkpoint emits natively
    future_covariates: bool
    min_freq_minutes: float
    max_freq_minutes: float
    cpu_ok: bool
    card: str
    combined_budget: int | None = None  # context + horizon share one window (Moirai 2)


CATALOG: dict[str, ModelEntry] = {
    "chronos-2": ModelEntry(
        key="chronos-2", hf_repo="amazon/chronos-2",
        hf_revision="29ec3766d36d6f73f0696f85560a422f50e8498c",
        package="chronos-forecasting>=2.0", code_repo="https://github.com/amazon-science/chronos-forecasting",
        weights_license="apache-2.0", commercial_use=True, max_context=8192, max_horizon=1024,
        quantiles=CHRONOS2_QUANTILES, future_covariates=True, min_freq_minutes=1, max_freq_minutes=60 * 24 * 31,
        cpu_ok=True, card="references/models/chronos-2.md",
    ),
    "chronos-bolt-base": ModelEntry(
        key="chronos-bolt-base", hf_repo="amazon/chronos-bolt-base",
        hf_revision="5d9f166d69f47aef3401367a7b842e78fe97b121",
        package="chronos-forecasting", code_repo="https://github.com/amazon-science/chronos-forecasting",
        weights_license="apache-2.0", commercial_use=True, max_context=2048, max_horizon=64,
        quantiles=DECILES, future_covariates=False, min_freq_minutes=1, max_freq_minutes=60 * 24 * 31,
        cpu_ok=True, card="references/models/chronos-bolt.md",
    ),
    "timesfm-2.5-200m": ModelEntry(
        key="timesfm-2.5-200m", hf_repo="google/timesfm-2.5-200m-pytorch",
        hf_revision="1d952420fba87f3c6dee4f240de0f1a0fbc790e3",
        package="timesfm[torch] (git, pinned commit)", code_repo="https://github.com/google-research/timesfm",
        weights_license="apache-2.0", commercial_use=True, max_context=16384, max_horizon=1024,
        quantiles=DECILES, future_covariates=True, min_freq_minutes=1, max_freq_minutes=60 * 24 * 31,
        cpu_ok=True, card="references/models/timesfm.md",
    ),
    "granite-ttm-r2": ModelEntry(
        key="granite-ttm-r2", hf_repo="ibm-granite/granite-timeseries-ttm-r2",
        hf_revision="d6a79570cac0f33d526601cd3a0fc7c80a8f9a2f",
        package="granite-tsfm", code_repo="https://github.com/ibm-granite/granite-tsfm",
        weights_license="apache-2.0", commercial_use=True, max_context=1536, max_horizon=720,
        quantiles=(0.5,), future_covariates=False, min_freq_minutes=1, max_freq_minutes=60 * 24 * 7,
        cpu_ok=True, card="references/models/granite-ttm.md",
    ),
    "moirai-2.0-small": ModelEntry(
        key="moirai-2.0-small", hf_repo="Salesforce/moirai-2.0-R-small",
        hf_revision="30f43ff08c8494f4943ae1521e9d4e94a0fbb389",
        package="uni2ts (git)", code_repo="https://github.com/SalesforceAIResearch/uni2ts",
        weights_license="cc-by-nc-4.0", commercial_use=False, max_context=8192, max_horizon=8192,
        quantiles=DECILES, future_covariates=True, min_freq_minutes=1, max_freq_minutes=60 * 24 * 31,
        cpu_ok=True, card="references/models/moirai.md", combined_budget=8192,
    ),
}


def _freq_minutes(freq: str) -> float:
    return pd.Timedelta(pd.tseries.frequencies.to_offset(freq)).total_seconds() / 60.0


def _blockers(entry: ModelEntry, horizon: int, freq_min: float, needs_future_covariates: bool,
              commercial_use: bool, quantiles: tuple[float, ...] | None) -> list[str]:
    reasons = []
    if commercial_use and not entry.commercial_use:
        reasons.append(f"weights licence {entry.weights_license} is non-commercial")
    if horizon > entry.max_horizon:
        reasons.append(f"horizon {horizon} > max {entry.max_horizon} (would need rolling forecasts)")
    if entry.combined_budget and horizon >= entry.combined_budget:
        reasons.append(f"horizon {horizon} leaves no context in the {entry.combined_budget}-point window")
    if needs_future_covariates and not entry.future_covariates:
        reasons.append("no native known-future covariates (e.g. weather forecast)")
    if not entry.min_freq_minutes <= freq_min <= entry.max_freq_minutes:
        reasons.append(f"frequency {freq_min:g} min outside supported range")
    if quantiles and not set(quantiles) <= set(entry.quantiles):
        reasons.append(f"quantiles {quantiles} not in supported set {entry.quantiles}")
    return reasons


def fit_report(horizon: int, context: int, freq: str, needs_future_covariates: bool,
               commercial_use: bool, quantiles: tuple[float, ...] | None = None) -> list[dict]:
    """One row per catalog model: usable or not, and why. Read-only."""
    freq_min = _freq_minutes(freq)
    rows = []
    for entry in CATALOG.values():
        reasons = _blockers(entry, horizon, freq_min, needs_future_covariates, commercial_use, quantiles)
        notes = []
        if context > entry.max_context:
            notes.append(f"context {context} will be truncated to the last {entry.max_context} points")
        rows.append({
            "model": entry.key, "usable": not reasons, "blockers": reasons, "notes": notes,
            "weights_license": entry.weights_license, "max_context": entry.max_context,
            "max_horizon": entry.max_horizon, "cpu_ok": entry.cpu_ok,
        })
    return sorted(rows, key=lambda r: (not r["usable"], r["model"]))
