# Validating a foundation model on energy data

Implemented in `scripts/tsfm_validation.py`. A green endpoint is technical validation only;
this protocol checks whether the model is *useful* on the user's own series.

## 1. Baseline: seasonal naive

Every energy series has a strong daily and weekly cycle. The bar is "same interval last
week" (or last day). Choose the cycle explicitly:

| data | frequency | season (`seasonal_period`) |
|---|---|---|
| feeder / system load | 15 min | weekly = 672 |
| AMI interval load (UK MHHS) | 30 min | weekly = 336 |
| ISO LMP, hourly | 1 h | daily = 24 or weekly = 168 |
| solar output | 1 h | daily = 24 (weather dominates; consider a clear-sky baseline too) |
| well production | 1 d | not seasonal: use naive (season=1) and decline-curve baselines from `decline-curve-analysis` |

## 2. Rolling-origin backtest

- Non-overlapping horizons, origins strictly in the past of their test windows: no leakage.
- At least 8 origins; include the DST-transition weeks and a peak week if the history has them.
- The model sees only the context up to each origin (truncated to its `max_context`).

## 3. Metrics

| metric | meaning | gate (default) |
|---|---|---|
| MASE ratio (model / seasonal naive) | < 1 beats the baseline | < 1.0 |
| pinball loss (scaled) | quality of the whole quantile fan | compare models |
| interval coverage | share of actuals inside [lowest, highest] declared quantile | near nominal (P10–P90 → ~0.8) |

The gate thresholds are the user's call. A trading desk may require MASE ratio < 0.9 and
calibrated P10/P90; a planning team may accept < 1.0.

## 4. Smoke tests on the endpoint

`smoke_test_response()` checks columns, one row per series × step, no quantile crossing,
UTC timestamps. Run it on: a single series, a 100-series batch, a series with a DST
transition inside the context, and a request with an undeclared column (must fail).

## 5. Negative tests (must fail cleanly)

- naive timestamps; duplicate timestamps; off-grid timestamps
- gap longer than the interpolation cap under `interpolate_linear`
- future covariate rows that do not cover exactly the horizon
- more than `MAX_SERIES_PER_REQUEST` series

## Sources

- Hyndman & Koehler (2006), "Another look at measures of forecast accuracy" (MASE):
  https://robjhyndman.com/papers/mase.pdf
- Chronos-2 technical report: https://arxiv.org/abs/2510.15821
- TimesFM paper: https://arxiv.org/abs/2310.10688
