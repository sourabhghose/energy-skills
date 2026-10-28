# Chronos-Bolt

## Identity

- Model family: Amazon Chronos-Bolt (T5 encoder-decoder, patch-based), tiny 9M / mini 21M / small 48M / base 205M
- HF repo: amazon/chronos-bolt-base
- HF revision: 5d9f166d69f47aef3401367a7b842e78fe97b121
- Code repo: https://github.com/amazon-science/chronos-forecasting
- Code revision: 1224fafa91e1ecd6674f5204066b159e40b5e4a1
- Weights license: apache-2.0
- Code license: Apache-2.0
- Commercial use: yes
- Reviewed: 2026-10-28

Other sizes: `amazon/chronos-bolt-small` (revision 772f3d25d38aec6d914c8949dab4462e2d46f5d8,
apache-2.0). The card marks `amazon/chronos-2` as the newer version.

## Energy use cases

- Fast univariate zero-shot baselines for thousands of AMI meters or SCADA tags on CPU.
- Short-horizon (≤ 64 steps) intraday load or renewable output where no covariates are needed.
- Not for: weather-driven day-ahead load (no native future covariates — use Chronos-2), or
  horizons > 64 steps without accepting autoregressive degradation.

## Integration contract

- Context: up to 2048 points (`config.json`).
- Horizon: 64 steps (`config.json` `prediction_length`); longer means rolling.
- Native quantiles: deciles 0.1 … 0.9 only.
- Covariates: none natively (AutoGluon can add an external covariate regressor; not wired here).
- Output of `pipeline.predict`: `[n_series, 9, horizon]`.

## Artifacts and runtime

- `chronos-forecasting` (exact pin from the pinned commit), `torch`.
- CPU-friendly; base fits comfortably on a CPU serving endpoint.

## Wrapper boundary

`BaseChronosPipeline.from_pretrained(local_dir, device_map=...)`;
`pipeline.predict(context=[tensors], prediction_length=h)`; transpose each `[9, h]` to `[h, 9]`
and select the manifest quantiles. See `ChronosBoltAdapter`.

## Deployment recommendation

CPU Model Serving or batch Job; the cheapest option in the catalog.

## Pitfalls

1. Asking for P5/P95: not emitted. The contract fails instead of extrapolating.
2. 30-min AMI data with a 48-hour horizon is 96 steps — over the 64-step limit.
3. Horizon past 64 via rolling compounds error; backtest at the real horizon.

## Validation

Backtest vs seasonal naive at the production horizon; negative test requesting a 0.05 quantile.
