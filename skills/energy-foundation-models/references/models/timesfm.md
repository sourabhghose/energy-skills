# TimesFM 2.5 (200M)

## Identity

- Model family: Google Research TimesFM (decoder-only)
- HF repo: google/timesfm-2.5-200m-pytorch
- HF revision: 1d952420fba87f3c6dee4f240de0f1a0fbc790e3
- Code repo: https://github.com/google-research/timesfm
- Code revision: e51928e27119cb17bebc005be2696b75e0a9e688 (2.5 code lives under `src/timesfm`)
- Weights license: apache-2.0
- Code license: Apache-2.0
- Commercial use: yes
- Reviewed: 2026-10-28

**Licence trap:** TimesFM **3.0** weights (`google/timesfm-3.0-pytorch`, HF licence tag
`other`) are distributed under `timesfm-non-commercial-license-v1.0`: non-commercial,
non-production only, per the repo README. Weights up to 2.5 remain Apache-2.0. A utility or
trading desk must not serve 3.0 in production; this skill catalogs 2.5 only.

## Energy use cases

- Long-context load and price forecasting (up to 16k points ≈ 166 days of 15-min data).
- Long horizons with a continuous quantile head (up to 1k steps).
- Covariates via XReg (added back for 2.5 in Oct 2025) — not wired in this skill's adapter;
  use Chronos-2 when weather covariates are required, or extend the adapter and test it.

## Integration contract

- Context: up to 16384 points (README: "supports up to 16k context length").
- Horizon: up to 1024 with the optional quantile head.
- Output of `model.forecast`: point `(n, h)` and quantiles `(n, h, 10)` = mean, then 0.1…0.9.
- `ForecastConfig(max_context, max_horizon, normalize_inputs=True, use_continuous_quantile_head=True,
  fix_quantile_crossing=True, ...)` must be compiled before forecasting.
- `infer_is_positive=True` in the card example forces non-negative output — **do not** set it
  for prices; the contract's `non_negative` decision handles clipping explicitly.

## Artifacts and runtime

- Install from the git repo at the pinned commit (`pip install "timesfm[torch] @ git+https://github.com/google-research/timesfm@<sha>"`).
- PyTorch checkpoint; CPU inference works, GPU recommended for large batches.

## Wrapper boundary

`timesfm.TimesFM_2p5_200M_torch.from_pretrained(local_dir)` + `compile(ForecastConfig(...))`
in `load_context`; `forecast(horizon, inputs=[np arrays])` in `predict`; drop the mean
column (index 0) and select deciles. See `TimesFM25Adapter`.

## Deployment recommendation

Model Serving (CPU for modest batches, GPU_SMALL for large ones) or batch Job.

## Pitfalls

1. Pulling `main` of the GitHub repo gets the 3.0 code path and invites the 3.0 checkpoint.
   Pin the commit and the 2.5 HF repo.
2. `torch_compile=True` in the card example adds minutes to cold start; disable it on
   scale-to-zero endpoints.
3. The card example `max_context=1024` is not the model limit; set it from your data.

## Validation

Backtest vs seasonal naive; check that negative LMPs survive (no positive-forcing); smoke
test with mixed context lengths in one batch.
