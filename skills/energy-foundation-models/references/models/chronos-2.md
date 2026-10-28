# Chronos-2

## Identity

- Model family: Amazon Chronos (encoder-only, group attention), 120M parameters
- HF repo: amazon/chronos-2
- HF revision: 29ec3766d36d6f73f0696f85560a422f50e8498c
- Code repo: https://github.com/amazon-science/chronos-forecasting
- Code revision: 1224fafa91e1ecd6674f5204066b159e40b5e4a1 (tag v2.3.2 is the latest release; pin the SHA)
- Weights license: apache-2.0
- Code license: Apache-2.0
- Commercial use: yes
- Reviewed: 2026-10-28

## Energy use cases

- Day-ahead and intraday **load** forecasting with **known-future weather covariates**
  (temperature, humidity, GHI) — the only catalog model with native future covariates in
  the same call.
- Price (LMP / day-ahead) forecasting with load and renewable forecasts as covariates; do
  **not** clip at zero.
- Many related series at once (feeders under one substation) with `cross_learning=True`,
  after testing — results become batch-size dependent.
- Not for: monthly production decline (use `decline-curve-analysis`), imagery.

## Integration contract

- Context: up to 8192 points (`config.json` `context_length`).
- Horizon: up to 1024 steps per the model card; longer horizons are unrolled autoregressively.
- Native quantiles (`config.json`): 0.01, 0.05, 0.1, 0.15, …, 0.95, 0.99 (21 levels). Other
  levels are interpolated by the pipeline; this skill restricts to native levels.
- Covariates: past-only and known-future, real or categorical, as dicts per series
  (`past_covariates`, `future_covariates`); future keys must be a subset of past keys.
- Missing values: NaN in the context is accepted (`gap_policy="pass_nan"` is viable).
- Transport: long-format frame per `references/integration-contract.md`.

## Artifacts and runtime

- `chronos-forecasting>=2.0` (pin the exact version from the repo's `pyproject.toml` at the
  pinned commit), `torch`, `pandas[pyarrow]`.
- Checkpoint: `model.safetensors` + `config.json`; stage with `huggingface_hub.snapshot_download(
  repo_id, revision=<sha>, local_dir=/Volumes/...)` and set `HF_HUB_OFFLINE=1` at serve time.
- CPU and GPU inference both supported (card: >300 forecasts/s on one A10G). CPU serving is
  usually enough for a few hundred feeders per request.

## Wrapper boundary

`Chronos2Pipeline.from_pretrained(local_dir, device_map=...)` in `load_context`;
`predict_quantiles(inputs, prediction_length, quantile_levels)` in `predict`, which returns
per-series tensors shaped `(n_variates, horizon, n_quantiles)`. See `Chronos2Adapter` in
`scripts/tsfm_pyfunc.py`.

## Deployment recommendation

Model Serving (CPU, scale-to-zero) for interactive and day-ahead requests; batch Job with
`mlflow.pyfunc.spark_udf` for nightly forecasts over all meters/feeders.

## Pitfalls

1. Feeding local-time timestamps: DST shifts the daily cycle. The contract converts to UTC.
2. Passing weather *actuals* as future covariates in the backtest: leaks information the
   production run will not have. Backtest with archived **forecasts** (or accept optimistic
   scores and say so).
3. `cross_learning=True` silently changes results with batch composition; keep it off unless
   a backtest shows a gain.

## Validation

- Contract tests (offline) with a fake adapter; backtest vs seasonal naive (weekly season
  for 15/30-min load); smoke test on a DST-transition week; negative test with an
  undeclared covariate.
