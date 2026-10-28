# IBM Granite TinyTimeMixers (TTM r2)

## Identity

- Model family: IBM Granite TimeSeries TTM (MLP-mixer, ~1M+ parameters)
- HF repo: ibm-granite/granite-timeseries-ttm-r2
- HF revision: d6a79570cac0f33d526601cd3a0fc7c80a8f9a2f
- Code repo: https://github.com/ibm-granite/granite-tsfm
- Code revision: 9d0b839f997eb4918822a43036012ce8c277687c (latest release tag v0.3.11)
- Weights license: apache-2.0
- Code license: Apache-2.0
- Commercial use: yes
- Reviewed: 2026-10-28

## Energy use cases

- Very cheap point forecasts for **minutely to hourly** SCADA / AMI / plant telemetry at
  massive scale (thousands of tags on CPU).
- Few-shot fine-tuning with exogenous / control variables (r2 recipes), e.g. plant output
  with irradiance, on a small slice of history.
- Not for: probabilistic forecasts (point forecaster; the catalog exposes only the median),
  monthly data.

## Integration contract

- Each model is a **branch** named `<context>-<horizon>-<ft?>-<loss?>-<release>`. Verified
  branches include `512-96-r2`, `1024-96-r2`, `1536-96-r2`, `512-720-r2`, `1536-720-r2`, and
  r2.1 daily/weekly branches such as `90-30-ft-r2.1` and `52-16-ft-r2.1`.
- Context: 512 / 1024 / 1536 for r2 (fixed per branch; short histories must not be
  zero-padded — the card says it degrades performance).
- Horizon: 96 / 192 / 336 / 720 per branch; `get_model()` selects a branch.
- Frequencies: r2 minutely–hourly; r2.1 adds daily and weekly.
- Scaling: users must standard-scale each channel externally (`TimeSeriesPreprocessor`).

## Artifacts and runtime

- `granite-tsfm` (pin the exact version), `transformers` (pin). Record the **branch name and
  its commit** in the manifest, not just the repo.
- CPU-first; laptops and small CPU endpoints are enough.

## Wrapper boundary

Not shipped as an adapter in `tsfm_pyfunc.py` yet (point-only output and per-branch context
need their own contract). Package with the generic PyFunc pattern: load the pinned branch
with `get_model(model_path, context_length, prediction_length)`, apply the saved scaler, and
return the median column only.

## Deployment recommendation

Batch Job (spark_udf) over many tags; CPU serving for small online requests.

## Pitfalls

1. Forgetting external scaling: outputs look plausible but are biased.
2. Picking `main` instead of the branch that matches your context/horizon.
3. Treating the point forecast as P50 with uncertainty: there is no quantile fan.

## Validation

Backtest vs seasonal naive per branch; confirm the scaler is fit on the context only (no
leakage from the test window).
