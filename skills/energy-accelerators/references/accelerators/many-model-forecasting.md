# Many Models Forecasting (MMF)

## Identity

- Name: Many Models Forecasting (MMF)
- Kind: accelerator
- URL: https://github.com/databricks-industry-solutions/many-model-forecasting
- Install doc: README (`pip install "mmf_sa @ git+https://github.com/databricks-industry-solutions/many-model-forecasting.git"`), `RUNME.py`
- Maintainers: see repo contributors
- Licence: Databricks License
- Last updated: 2026-10-26
- Maturity: maintained
- Reviewed: 2026-10-28 against commit a90eb50

## Use it for

- Forecasting thousands of series (meters, feeders, stores) with local statistical, global ML/DL, and foundation models in one configuration-driven framework
- Foundation models including Chronos-2 and TimesFM 2.5 (and, via foundationforecast, TimesFM 3.0 — check licences), hierarchical reconciliation, serverless execution
- An MMF Agent skill set (`skills/`) for Genie Code / Claude Code

## Do not use it for

- Licence-checked, single-model production endpoints with a seasonal-naive gate: use `energy-foundation-models`
- Energy-specific weather normalization and DST handling: use `load-forecaster` / `ami-interval-analytics` first

## Data

Your own series in a Delta table; examples use public datasets.

## Deploy signals

Not documented as named resources; look for `mmf_sa` installs and MMF experiment names.

## Smallest path

`pip install "mmf_sa[local] @ git+https://github.com/databricks-industry-solutions/many-model-forecasting.git"` on DBR 18 ML+, then an example notebook under `examples/`.

## Pitfalls

1. MMF exposes TimesFM 3.0 among foundation models; its weights are non-commercial. Do not use it for a utility's production forecasts.
2. Moirai is disabled in MMF (uni2ts needs torch<2.5).
3. Use DBR 18 ML or later for all model classes (README).

## Pair with Energy Skills

`energy-foundation-models`, `load-forecaster`, `ami-interval-analytics`
