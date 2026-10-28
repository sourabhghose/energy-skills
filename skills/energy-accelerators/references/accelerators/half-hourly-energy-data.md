# UK Energy Trading (half-hourly smart meter data)

## Identity

- Name: UK Energy Trading (half-hourly smart meter data)
- Kind: accelerator
- URL: https://github.com/databricks-industry-solutions/half-hourly-energy-data
- Install doc: README + `databricks.yml` (bundle `energy-forecasting-sa`)
- Maintainers: see repo contributors
- Licence: Databricks License
- Last updated: 2025-06-03
- Maturity: maintained
- Reviewed: 2026-10-28 against commit 4681c40

## Use it for

- UK Market-Wide Half-Hourly Settlement (MHHS): ingest ~12 GB of half-hourly smart-meter data and ERA5 / IFS weather
- Geospatial alignment of meters to weather and administrative boundaries
- Feature engineering and forecasts with Prophet and `ai_forecast()`, plus forecast evaluation

## Do not use it for

- Non-UK settlement conventions (ISO/RTO 5-min or 15-min intervals): see `iso-market-data`
- Weather-normalized production load forecasts with a backtest gate: use `load-forecaster`

## Data

Public UK smart-meter and weather data downloaded by the notebooks (several GB; real compute cost).

## Deploy signals

Bundle `energy-forecasting-sa`; notebooks `src/00_project_setup.ipynb` … `05_forecast_evaluation.ipynb`.

## Smallest path

Run `src/00_project_setup.ipynb`, then the ingest notebooks `01a`–`01c`; treat the rest as reference.

## Pitfalls

1. Data volume: ~12 GB meter data + several GB weather; budget compute before Run All.
2. README badge says DBR 15.4 LTS ML; newer runtimes may need dependency updates.

## Pair with Energy Skills

`ami-interval-analytics`, `load-forecaster`, `energy-foundation-models`
