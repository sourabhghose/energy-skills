---
name: energy-foundation-models
description: >-
  Time-series and geospatial foundation models for energy on Databricks - Chronos-2,
  Chronos-Bolt, TimesFM 2.5, Granite TTM, Moirai, Prithvi-EO-2.0. Packages an open-weight
  checkpoint as a file-based MLflow PyFunc with a UTC long-format serving contract, pins
  Hugging Face and code commits, records and enforces weights licences (flags Moirai
  CC-BY-NC and TimesFM 3.0 non-commercial weights), backtests against a seasonal-naive
  baseline before registration to Unity Catalog, and deploys to Model Serving with AI
  Gateway inference tables or to a batch Job. Covers load, price, renewable and production
  forecasting plus satellite chips for wildfire burn scars and flood extent. Surfaces model
  choice, compute, licence acceptance, horizon, quantiles, non-negativity and gap policy as
  user decisions. For classical load forecasting with weather normalization use
  load-forecaster; for finding an existing accelerator use energy-accelerators.
category: Others
summary: Package, validate against seasonal naive, register & deploy open-weight energy forecasting and satellite models — Chronos-2, TimesFM 2.5, Prithvi-EO-2.0.
version: 0.1.0
author: Sourabh Ghose
license: Databricks License
---

# Energy Foundation Models

<!-- Adapted from databricks-industry-solutions/vital-skills (skills/open-weight-models/SKILL.md); modified for the energy industry. -->

## Overview

Energy teams increasingly want to try zero-shot **time-series foundation models (TSFMs)**
on load, price, renewable output and telemetry, and **geospatial foundation models** on
satellite imagery for wildfire and flood exposure. A general coding agent will pip-install
the latest package, download `main` weights at request time, feed local timestamps, ignore
the weights licence, and ship an endpoint without checking that the model beats "same hour
last week". This skill supplies the energy-specific layer: a tested serving contract
(`scripts/tsfm_contract.py`), a verified model catalog with licences and limits
(`scripts/tsfm_catalog.py`, `references/models/`), a seasonal-naive validation gate
(`scripts/tsfm_validation.py`), and a preview → confirmed-build runner (`scripts/tsfm_run.py`).

For generic MLflow / Model Serving mechanics, rely on the Databricks model-serving skills;
this guide adds only what energy data and open weights require.

## When to Use

- "Can Chronos / TimesFM forecast our feeder load (or LMPs, or wind output) zero-shot? Deploy it."
- "Put a day-ahead load forecasting model behind an endpoint our trading app can call, with P10/P50/P90."
- "Which open forecasting models can we use commercially, and which need covariates support for weather?"
- "Score 50,000 smart meters nightly with a foundation model" (batch Job instead of an endpoint).
- "Run Prithvi on HLS imagery to map burn scars / flood extent near our assets."
- "Is the foundation model actually better than our naive baseline on our data?"
- A request to register an open-weight model from Hugging Face to Unity Catalog where the
  data is energy time series or multispectral imagery.

For weather-normalized regression / gradient-boosted load forecasts, use `load-forecaster`.

## Key Concepts

### Licence is a gate, not a footnote
Code and weights have separate licences. Moirai's code is Apache-2.0 but its weights are
CC-BY-NC-4.0; TimesFM 3.0 weights are non-commercial while 2.5 is Apache-2.0. Forecasting a
utility's own load for operations is commercial use. `build_manifest` refuses to proceed
without `license_accepted_by`, and `preview` marks non-commercial models unusable when
`commercial_use=True`.

### UTC long-format contract
Requests are rows of `series_id, timestamp (tz-aware), target, [declared covariates]`.
The contract converts to UTC, reindexes onto the declared grid, fails on duplicates and
off-grid stamps (interval-ending vs interval-beginning mistakes), and applies the chosen
gap policy. See `references/integration-contract.md`.

### One registered version = one forecasting product
Horizon, quantiles, frequency, unit, non-negativity and gap policy are fixed in the manifest
at registration, not passed per request. "Day-ahead 30-min feeder load, P10/P50/P90, MWh" is
a product; changing the horizon is a new version.

### Beat seasonal naive or do not ship
`backtest()` runs a rolling-origin evaluation and compares MASE against seasonal naive.
`build_confirmed_deployment` refuses to register without a passing report.

### Pins and offline startup
Weights are staged to a UC Volume at a 40-character HF commit SHA; serving sets
`HF_HUB_OFFLINE=1` and `HF_HUB_DISABLE_XET=1`; pip requirements must be exact pins.

## Decision Framework

```
What is the input?
├── Time series (load, price, renewable output, telemetry, production)
│   ├── Needs known-future covariates (weather forecast, calendar flags)?
│   │   └── Chronos-2 (native)            [TimesFM 2.5 XReg: possible, not wired here]
│   ├── Univariate, short horizon (≤ 64 steps), many series, CPU budget → Chronos-Bolt
│   ├── Very long context (> 8k points) or horizon up to 1k → TimesFM 2.5
│   ├── Point forecasts for huge tag counts, minutely–hourly → Granite TTM r2 (generic PyFunc)
│   ├── Monthly well production / decline → not a TSFM problem: decline-curve-analysis
│   └── Commercial use and Moirai / TimesFM 3.0 requested → stop: non-commercial weights
└── Multispectral satellite imagery (HLS, Sentinel-2, Landsat)
    ├── Burn scars / flood extent → Prithvi-EO-2.0 fine-tuned heads, GPU batch Job
    └── Methane plumes → no verified commercial open model; custom training project
```

| Scenario | Recommended | Rationale |
|---|---|---|
| Interactive day-ahead requests for ≤ a few hundred series | Model Serving, CPU, scale-to-zero | bounded request; CPU is enough for Chronos/TimesFM at this size |
| Nightly scoring of all meters / feeders | Batch Job with `mlflow.pyfunc.spark_udf` | throughput over latency; no endpoint cost |
| Large batches, long context, tight latency | Model Serving GPU_SMALL | TSFM attention cost grows with context |
| Satellite chips | GPU batch Job (`compute="BATCH_JOB_ONLY"`) | rasters in, rasters out; not an HTTP payload |

## Decision Points

| Decision | Options | Governing reference | What changes |
|---|---|---|---|
| `model_key` | chronos-2, chronos-bolt-base, timesfm-2.5-200m, granite-ttm-r2, moirai-2.0-small | `references/models/*.md` | context, horizon, covariates, licence |
| `license_accepted_by` | name / role / date | model card licence | blocks build if missing |
| `compute` | CPU, GPU_SMALL, GPU_MEDIUM, GPU_LARGE, BATCH_JOB_ONLY | Decision Framework | cost, latency; Azure has no GPU_MEDIUM |
| `horizon`, `freq` | steps, pandas alias | product definition | which models fit; rolling vs native |
| `quantiles` | native levels only | `tsfm_catalog.py` | P10/P90 fan; Bolt/TimesFM deciles, Chronos-2 21 levels |
| `non_negative` | True / False | physics of the series | clip at 0 for load/output; never for LMPs |
| `gap_policy` | reject, pass_nan, interpolate_linear (≤ 4 steps) | `integration-contract.md` | how outages and missing reads are treated |
| `unit` | e.g. mwh, mw, usd_per_mwh, bbl_per_day | source table | carried on every response row |
| validation gate | MASE ratio threshold, coverage band | `energy-validation.md` | whether the model ships |
| `pip_requirements` | exact pins from the model's pyproject at the pinned commit | model repo | reproducible serving container |

## Workflow

**⛔ EXECUTE, DO NOT REIMPLEMENT.** Call the entrypoints in `scripts/` and report their
output. Do not hand-write the contract, the backtest, or the manifest, and do not pick a
decision-point value yourself.

### Step 1: Preview (read-only)

```python
import sys; sys.path.append("<this-skill-dir>/scripts")
from tsfm_run import preview_deployment_options
print(preview_deployment_options("main.grid.feeder_load_30min", horizon=96,
                                 needs_future_covariates=True, commercial_use=True))
```

Show the profile (frequency, gaps, negatives, timezone awareness) and the model fit table.
Ask the user for every decision in the table above.

### Step 2: Stage weights at a pinned revision (CPU, run once)

```python
import os; os.environ["HF_HUB_DISABLE_XET"] = "1"   # before importing huggingface_hub
from huggingface_hub import snapshot_download
from tsfm_catalog import CATALOG
e = CATALOG["chronos-2"]
snapshot_download(e.hf_repo, revision=e.hf_revision, local_dir="/Volumes/main/models/tsfm/chronos-2")
```

### Step 3: Backtest against seasonal naive

```python
from tsfm_pyfunc import Chronos2Adapter
from tsfm_validation import ValidationGate, backtest, seasonal_period
adapter = Chronos2Adapter("/Volumes/main/models/tsfm/chronos-2", device="cpu")
report = backtest(series_values, adapter, horizon=96, quantiles=(0.1, 0.5, 0.9),
                  season=seasonal_period("30min", "weekly"), n_origins=8,
                  gate=ValidationGate(max_mase_ratio=1.0, min_coverage=0.7, max_coverage=0.9))
```

Report MASE ratio, coverage and pass/fail. If it fails, stop and say so.

### Step 4: Register (and optionally deploy) with confirmed decisions

```python
from tsfm_run import build_confirmed_deployment
out = build_confirmed_deployment(
    "main.grid.feeder_load_30min", "main.models.feeder_load_dayahead",
    "/Volumes/main/models/tsfm/chronos-2",
    model_key="chronos-2", compute="CPU", license_accepted_by="J. Doe, Forecasting lead, 2026-10-28",
    horizon=96, quantiles=(0.1, 0.5, 0.9), non_negative=True, gap_policy="reject",
    unit="mwh", freq="30min", pip_requirements=[...exact pins...],
    validation_report=report, endpoint="feeder-load-dayahead")
```

### Step 5: Smoke test the endpoint

Query with a real `series_id` from the table and run `smoke_test_response()`; include a
week that crosses a DST transition.

### Step 6 (imagery): validate chips, then a GPU Job

```python
from geo_contract import validate_chip_manifest
problems = validate_chip_manifest(chips_pdf, variant="300M-TL")
```

Fix every problem before launching the Job described in `references/models/prithvi-eo-2.md`.

## Best Practices

1. **Preview before packaging.** Profile frequency, gaps and timezone on the real table.
2. **Pin everything.** 40-char HF revision, code commit, exact pip pins; record in the manifest.
3. **Separate the download notebook (CPU) from the backtest/register notebook.**
4. **File-based PyFunc logging** (`python_model="scripts/tsfm_pyfunc.py"` + `code_paths`) so the
   serving container imports the wrapper after code paths are on `sys.path`.
5. **Backtest with what production will have.** Archived weather *forecasts*, not actuals, as
   future covariates — or label the scores optimistic.
6. **Minimize inference-table payloads.** Meter-level load is personal data; feeder load can be
   CEII. Aggregate or hash `series_id` before enabling capture (see `grid-data-guard`).
7. **Use SDK enums** (`ServingModelWorkloadType`) and set `workload_size` with `workload_type`.

## Troubleshooting

| Problem | Cause | Solution |
|---|---|---|
| `timestamps must be timezone-aware` | naive local time from a historian export | localize with the source's tz (`tz_localize(..., ambiguous=..., nonexistent=...)`) upstream, then send with offset |
| `duplicate timestamps` | repeated 01:00 hour at DST end, or double-loaded files | convert to UTC upstream; deduplicate with VEE (`ami-interval-analytics`) |
| `off the 30min grid` | interval-beginning vs interval-ending mismatch | shift timestamps explicitly by one interval upstream |
| `quantiles ... not emitted natively` | asked for P5/P95 from Bolt/TimesFM | choose native levels or Chronos-2 |
| Forecast never negative for prices | `non_negative=True` or TimesFM `infer_is_positive` | set `non_negative=False`; do not enable positive-forcing |
| "A library raised an error during model load" | unpinned `transformers` / `torch` resolved to a breaking major | exact pins from the model's pyproject; check **service** logs |
| `CAS service error ... Illegal seek` on download | HF Xet backend on serverless | `HF_HUB_DISABLE_XET=1` before importing `huggingface_hub`; restart kernel |
| Inference table name conflict | prefix reused after a failed deploy | timestamped `table_name_prefix` (done in `_endpoint_config`) |
| Moirai import fails on current DBR | uni2ts pins `torch<2.5` | research-only anyway; use a custom env or another model |

## Guardrails

1. Never register or serve weights whose licence forbids the user's use; non-commercial
   weights (Moirai, TimesFM 3.0) do not go to production endpoints.
2. Never download weights at request time; serve from a pinned, staged copy.
3. Never register a model whose backtest does not beat the agreed seasonal-naive gate;
   report the failure instead.
4. Never choose horizon, quantiles, non-negativity, gap policy, compute or licence
   acceptance for the user.
5. Never log raw meter-level payloads to inference tables without a data-minimization review.
6. A green endpoint is technical validation only; it is not an operational or
   regulatory sign-off for dispatch, settlement, or rate cases.
7. Avoid retrying a failing deployment more than 3 times; collect service logs and stop.

## Protocol Guidelines

Every new model card includes: identity with HF and code SHAs and both licences; energy use
cases and non-uses; context/horizon/quantile/covariate/frequency limits; artifacts and
runtime; wrapper boundary; deployment recommendation; pitfalls; validation. Add a catalog
entry and an index row, and keep `tests/test_model_cards.py` green.

## Related Skills

- `load-forecaster` — weather-normalized, backtested load forecasts without foundation models
- `ami-interval-analytics` — VEE, DST and gap handling before any forecasting
- `iso-market-data` — LMP and settlement-interval conventions for price forecasting
- `wind-solar-performance` — renewable output data quality before forecasting
- `wildfire-asset-risk` — consumes Prithvi burn-scar / vegetation outputs per asset
- `grid-data-guard` — de-identify meter data before inference tables
- `energy-accelerators` — Many Models Forecasting and other existing accelerators
- `skill-eval` — with/without-skill benchmark for this skill

## References

- [Chronos-2 model card](https://huggingface.co/amazon/chronos-2) and [technical report](https://arxiv.org/abs/2510.15821)
- [Chronos-Bolt model card](https://huggingface.co/amazon/chronos-bolt-base)
- [chronos-forecasting repo](https://github.com/amazon-science/chronos-forecasting)
- [TimesFM repo (licence note for 3.0)](https://github.com/google-research/timesfm) and [2.5 checkpoint](https://huggingface.co/google/timesfm-2.5-200m-pytorch)
- [Granite TTM r2](https://huggingface.co/ibm-granite/granite-timeseries-ttm-r2) and [granite-tsfm](https://github.com/ibm-granite/granite-tsfm)
- [Moirai 2.0 (CC-BY-NC-4.0)](https://huggingface.co/Salesforce/moirai-2.0-R-small) and [uni2ts](https://github.com/SalesforceAIResearch/uni2ts)
- [Prithvi-EO-2.0](https://huggingface.co/ibm-nasa-geospatial/Prithvi-EO-2.0-300M-TL), [NASA-IMPACT examples](https://github.com/NASA-IMPACT/Prithvi-EO-2.0), [TerraTorch](https://github.com/torchgeo/terratorch)
- [Databricks Model Serving](https://docs.databricks.com/aws/en/machine-learning/model-serving/)
- [MLflow custom Python models](https://mlflow.org/docs/latest/ml/model/python_model/)
- [Many Models Forecasting accelerator](https://github.com/databricks-industry-solutions/many-model-forecasting)
- [Vital Skills open-weight-models](https://github.com/databricks-industry-solutions/vital-skills/tree/main/skills/open-weight-models) — the HLS skill this adapts
