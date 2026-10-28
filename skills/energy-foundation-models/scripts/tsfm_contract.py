"""Serving contract for energy time-series foundation models (TSFMs).

Pure pandas / numpy — no MLflow, Spark, or network. Used by the PyFunc wrapper
(`tsfm_pyfunc.py`), the validation harness (`tsfm_validation.py`), and the
Databricks runner (`tsfm_run.py`), and exercised offline by `tests/`.

Request (long format, one row per observation):
    series_id  str      meter, feeder, well, node, or plant identifier
    timestamp  str|ts   timezone-aware ISO 8601 (naive timestamps are rejected)
    target     float    observed value; NULL on future rows that only carry covariates
    <cov>      float    optional covariates declared in the manifest (e.g. temp_c)

Response (long format, one row per series x forecast step):
    series_id, timestamp (UTC ISO 8601), point, q<level>..., unit,
    model_name, model_revision

Usage:
    from tsfm_contract import ForecastSpec, normalize_request, build_response
    spec = ForecastSpec(horizon=48, quantiles=(0.1, 0.5, 0.9), freq="30min",
                        unit="mwh", non_negative=True, covariates=("temp_c",))
    batch = normalize_request(request_df, spec, max_context=8192)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

import numpy as np
import pandas as pd

REQUIRED_COLUMNS = ("series_id", "timestamp", "target")
MAX_SERIES_PER_REQUEST = 1000
# reject: fail on any missing interval; pass_nan: model handles NaN (Chronos family does);
# interpolate_linear: fill gaps up to MAX_INTERP_STEPS, fail on longer outages.
GAP_POLICIES = ("reject", "pass_nan", "interpolate_linear")
MAX_INTERP_STEPS = 4


class DecisionRequired(ValueError):
    """A decision that belongs to the user was not supplied."""

    def __init__(self, decision: str, options: Sequence[str] | str):
        opts = options if isinstance(options, str) else ", ".join(map(str, options))
        super().__init__(f"Decision required: '{decision}'. Options: {opts}")
        self.decision = decision


class ContractError(ValueError):
    """The request does not satisfy the declared serving contract."""


@dataclass(frozen=True)
class ForecastSpec:
    """Decisions fixed at registration time and stored in the manifest."""

    horizon: int
    quantiles: tuple[float, ...]
    freq: str
    unit: str
    non_negative: bool
    gap_policy: str
    covariates: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.horizon <= 0:
            raise ContractError(f"horizon must be positive, got {self.horizon}")
        if not self.quantiles:
            raise ContractError("at least one quantile level is required")
        if any(not 0.0 < q < 1.0 for q in self.quantiles):
            raise ContractError(f"quantile levels must be in (0, 1): {self.quantiles}")
        if list(self.quantiles) != sorted(set(self.quantiles)):
            raise ContractError("quantile levels must be unique and ascending")
        pd.tseries.frequencies.to_offset(self.freq)  # raises on an invalid alias
        if self.gap_policy not in GAP_POLICIES:
            raise DecisionRequired("gap_policy", GAP_POLICIES)

    @property
    def quantile_columns(self) -> list[str]:
        return [quantile_column(q) for q in self.quantiles]


@dataclass(frozen=True)
class SeriesBatch:
    """Normalized model input: one context array per series, aligned in UTC."""

    series_ids: tuple[str, ...]
    contexts: tuple[np.ndarray, ...]
    last_timestamps: tuple[pd.Timestamp, ...]
    future_covariates: tuple[np.ndarray | None, ...]
    past_covariates: tuple[np.ndarray | None, ...]
    truncated: tuple[str, ...]


def quantile_column(level: float) -> str:
    return f"q{level:g}"


def require_decision(value, decision: str, options: Sequence[str] | str):
    """Return value, or raise DecisionRequired when it is None."""
    if value is None:
        raise DecisionRequired(decision, options)
    return value


_OFFSET_SUFFIX = r"(?:Z|[+-]\d{2}:?\d{2})$"
_NAIVE_MSG = ("timestamps must be timezone-aware (e.g. 2026-03-08T02:00:00-06:00 or ...Z); "
              "naive local times are ambiguous across DST transitions")


def _to_utc(ts: pd.Series) -> pd.Series:
    """Convert to UTC; reject naive values. Mixed offsets (a DST transition) are expected."""
    if isinstance(ts.dtype, pd.DatetimeTZDtype):
        return ts.dt.tz_convert("UTC")
    if pd.api.types.is_datetime64_any_dtype(ts):
        raise ContractError(_NAIVE_MSG)
    text = ts.astype(str).str.strip()
    if not text.str.contains(_OFFSET_SUFFIX, regex=True).all():
        raise ContractError(_NAIVE_MSG)
    return pd.to_datetime(text, utc=True, errors="raise", format="ISO8601")


def _check_columns(df: pd.DataFrame, spec: ForecastSpec) -> None:
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ContractError(f"missing required columns: {missing}")
    extra = [c for c in df.columns if c not in REQUIRED_COLUMNS and c not in spec.covariates]
    if extra:
        raise ContractError(f"undeclared columns {extra}; declared covariates: {list(spec.covariates)}")
    absent = [c for c in spec.covariates if c not in df.columns]
    if absent:
        raise ContractError(f"declared covariates missing from request: {absent}")


def _regularize(group: pd.DataFrame, freq: str) -> pd.DataFrame:
    """Reindex one series onto a regular UTC grid; gaps become NaN, duplicates fail."""
    if group["timestamp"].duplicated().any():
        dupes = group.loc[group["timestamp"].duplicated(), "timestamp"].head(3).tolist()
        raise ContractError(f"duplicate timestamps for series {group['series_id'].iat[0]}: {dupes}")
    indexed = group.set_index("timestamp").sort_index()
    grid = pd.date_range(indexed.index.min(), indexed.index.max(), freq=freq, tz="UTC")
    off_grid = indexed.index.difference(grid)
    if len(off_grid):
        raise ContractError(
            f"series {group['series_id'].iat[0]} has timestamps off the {freq} grid "
            f"(first: {off_grid[0]}); check interval-ending vs interval-beginning alignment"
        )
    return indexed.reindex(grid)


def apply_gap_policy(values: np.ndarray, policy: str, series_id: str) -> np.ndarray:
    """Return a new array with gaps handled per the chosen policy."""
    gaps = int(np.isnan(values).sum())
    if gaps == 0 or policy == "pass_nan":
        return values
    if policy == "reject":
        raise ContractError(f"series {series_id} has {gaps} missing intervals and gap_policy='reject'")
    filled = pd.Series(values).interpolate(method="linear", limit=MAX_INTERP_STEPS, limit_area="inside")
    if filled.isna().any():
        raise ContractError(
            f"series {series_id} has a gap longer than {MAX_INTERP_STEPS} steps (or at the edge); "
            "an outage this long should not be interpolated"
        )
    return filled.to_numpy()


def _split_series(frame: pd.DataFrame, spec: ForecastSpec, max_context: int):
    observed = frame[frame["target"].notna()]
    if observed.empty:
        raise ContractError("series has no observed target values")
    last_obs = observed.index.max()
    history = frame.loc[:last_obs]
    future = frame.loc[frame.index > last_obs]
    sid = str(frame["series_id"].dropna().iat[0])
    context = apply_gap_policy(history["target"].to_numpy(dtype=float), spec.gap_policy, sid)
    truncated = len(context) > max_context
    context = context[-max_context:]
    future_cov = _future_covariates(future, spec, last_obs)
    past_cov = history[list(spec.covariates)].to_numpy(dtype=float)[-max_context:] if spec.covariates else None
    return context, last_obs, future_cov, past_cov, truncated


def _future_covariates(future: pd.DataFrame, spec: ForecastSpec, last_obs) -> np.ndarray | None:
    if not spec.covariates:
        return None
    expected = pd.date_range(last_obs, periods=spec.horizon + 1, freq=spec.freq, tz="UTC")[1:]
    if future.empty:
        return None
    if len(future) != spec.horizon or not future.index.equals(expected):
        raise ContractError(
            f"future covariate rows must cover exactly the {spec.horizon} steps after the last "
            f"observation ({expected[0]} .. {expected[-1]})"
        )
    values = future[list(spec.covariates)].to_numpy(dtype=float)
    if np.isnan(values).any():
        raise ContractError("future covariate rows contain NULLs")
    return values


def normalize_request(df: pd.DataFrame, spec: ForecastSpec, max_context: int) -> SeriesBatch:
    """Validate a long-format request and return per-series UTC-aligned arrays."""
    _check_columns(df, spec)
    frame = df.assign(timestamp=_to_utc(df["timestamp"]), series_id=df["series_id"].astype(str))
    n_series = frame["series_id"].nunique()
    if n_series > MAX_SERIES_PER_REQUEST:
        raise ContractError(f"{n_series} series exceeds the per-request limit {MAX_SERIES_PER_REQUEST}")
    parts = {"ids": [], "ctx": [], "last": [], "fut": [], "past": [], "trunc": []}
    for sid, group in frame.groupby("series_id", sort=True):
        regular = _regularize(group, spec.freq)
        context, last_obs, fut, past, truncated = _split_series(regular, spec, max_context)
        for key, value in zip(parts, (sid, context, last_obs, fut, past, truncated)):
            parts[key].append(value)
    return SeriesBatch(
        series_ids=tuple(parts["ids"]),
        contexts=tuple(parts["ctx"]),
        last_timestamps=tuple(parts["last"]),
        future_covariates=tuple(parts["fut"]),
        past_covariates=tuple(parts["past"]),
        truncated=tuple(s for s, t in zip(parts["ids"], parts["trunc"]) if t),
    )


def postprocess_quantiles(values: np.ndarray, non_negative: bool) -> np.ndarray:
    """Fix quantile crossing (sort along the quantile axis) and optionally clip at zero.

    values: array (horizon, n_quantiles). Clipping is a decision: load, generation, and
    production are physically non-negative; LMPs and spreads can go negative.
    """
    arr = np.sort(np.asarray(values, dtype=float), axis=1)
    if not np.isfinite(arr).all():
        raise ContractError("model returned non-finite forecast values")
    return np.clip(arr, 0.0, None) if non_negative else arr


def _point_from_quantiles(values: np.ndarray, quantiles: tuple[float, ...]) -> np.ndarray:
    if 0.5 in quantiles:
        return values[:, quantiles.index(0.5)]
    return np.array([np.interp(0.5, quantiles, row) for row in values])


def build_response(batch: SeriesBatch, forecasts: Sequence[np.ndarray], spec: ForecastSpec,
                   model_name: str, model_revision: str) -> pd.DataFrame:
    """Assemble the long-format response; one row per series x step."""
    if len(forecasts) != len(batch.series_ids):
        raise ContractError(f"expected {len(batch.series_ids)} forecasts, got {len(forecasts)}")
    frames = []
    for sid, last, raw in zip(batch.series_ids, batch.last_timestamps, forecasts):
        values = postprocess_quantiles(raw, spec.non_negative)
        if values.shape != (spec.horizon, len(spec.quantiles)):
            raise ContractError(f"forecast shape {values.shape} != {(spec.horizon, len(spec.quantiles))}")
        steps = pd.date_range(last, periods=spec.horizon + 1, freq=spec.freq, tz="UTC")[1:]
        cols = {quantile_column(q): values[:, i] for i, q in enumerate(spec.quantiles)}
        frames.append(pd.DataFrame({
            "series_id": sid,
            "timestamp": steps.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "point": _point_from_quantiles(values, spec.quantiles),
            **cols,
        }))
    out = pd.concat(frames, ignore_index=True)
    return out.assign(unit=spec.unit, model_name=model_name, model_revision=model_revision)
