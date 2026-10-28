# Energy TSFM integration contract

<!-- Adapted from databricks-industry-solutions/vital-skills (skills/open-weight-models/references/integration-contract.md); modified for the energy industry. -->

Implemented in `scripts/tsfm_contract.py`; this page explains the rules so a reviewer can
check them without reading code.

## Request: long format

| column | type | rule |
|---|---|---|
| `series_id` | string | meter, feeder, substation, well, pricing node, or plant ID; grounded in the source table |
| `timestamp` | ISO 8601 with offset | **timezone-aware only**; naive local time is rejected |
| `target` | float | observed value; `NULL` on future rows that only carry covariates |
| `<covariate>` | float | only covariates declared in the manifest (e.g. `temp_c`, `ghi_w_m2`) |

Why long format: one schema covers one meter or a thousand feeders, survives MLflow's
`dataframe_records` / `dataframe_split` serializers, and avoids untested `params=` paths.

## Time handling

- All timestamps are converted to **UTC** before the model sees them. A local-time grid has
  a 23-hour day in spring and a 25-hour day in autumn; a model fed local wall-clock
  positions misaligns every daily cycle after the transition.
- Each series is reindexed onto a regular grid at the manifest `freq`. Duplicate
  timestamps (the repeated 01:00 hour in local time, double-loaded files) **fail**.
- Timestamps that fall off the grid fail with a hint about interval-ending (AMI, ISO
  settlement) vs interval-beginning (SCADA, many historians) conventions. Shift explicitly
  upstream; never let the model guess.
- Responses return UTC (`...Z`). Convert back to market/local time in the consumer.

## Gaps (`gap_policy`, a decision)

| policy | when |
|---|---|
| `reject` | default stance for settlement-grade data: fix the VEE first (`ami-interval-analytics`) |
| `pass_nan` | models that accept NaN natively (Chronos family) and the gaps are real missing data |
| `interpolate_linear` | short telemetry dropouts; capped at 4 steps — a longer gap is an outage, not noise |

## Horizon and quantiles (decisions, fixed at registration)

- `horizon` and `quantiles` live in the manifest, not in the request. One registered version
  = one forecasting product (e.g. "day-ahead 30-min feeder load, P10/P50/P90").
- Quantiles must be ones the checkpoint emits natively (see `tsfm_catalog.py`). Chronos-Bolt
  and TimesFM 2.5 emit deciles; Chronos-2 emits 21 levels from 0.01 to 0.99; TTM is a point
  forecaster.
- Quantile crossing is fixed by sorting along the quantile axis.
- `non_negative` (decision): clip at zero for load, generation, production. **Never** for
  LMPs, spreads, or net load with behind-the-meter solar — those go negative.

## Response

`series_id, timestamp (UTC), point, q<level>..., unit, model_name, model_revision`.
`point` is the median (or interpolated median). `unit` comes from the manifest.

## Manifest (JSON, stored with the model version)

```json
{
  "model_key": "chronos-2",
  "hf_repo": "amazon/chronos-2",
  "hf_revision": "<40-char sha>",
  "code_repo": "https://github.com/amazon-science/chronos-forecasting",
  "weights_license": "apache-2.0",
  "commercial_use_permitted": true,
  "license_accepted_by": "<name, role, date>",
  "compute": "CPU",
  "max_context": 8192,
  "spec": {"horizon": 96, "quantiles": [0.1, 0.5, 0.9], "freq": "30min", "unit": "mwh",
           "non_negative": true, "gap_policy": "reject", "covariates": ["temp_c"]},
  "inputs": {"table": "main.grid.feeder_load_30min", "rows": 12000000},
  "validation": {"mase_ratio": 0.81, "coverage": 0.78, "n_origins": 8},
  "pip_requirements": ["chronos-forecasting==<pin>", "torch==<pin>"],
  "skill_version": "0.1.0",
  "created_at": "2026-10-28T12:00:00+00:00"
}
```

`load_context` refuses to load a manifest without `license_accepted_by` or with a
non-40-character `hf_revision`.

## Data minimization for inference tables

Interval load per meter is customer personal data in many jurisdictions; feeder and
substation load can be CEII. Before enabling AI Gateway inference tables, aggregate to
feeder/zone or hash `series_id`, set retention, and restrict access. Route meter-level
de-identification to `grid-data-guard`.
