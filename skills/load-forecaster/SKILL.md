---
name: load-forecaster
description: >-
  Electric load forecasting and weather normalization on Unity Catalog: hourly system, zone,
  feeder or customer-class load (MW/kW) joined to station temperatures (NOAA ISD/ASOS) for
  day-ahead and week-ahead forecasts, leakage-safe rolling-origin backtests, and
  weather-normalized annual energy (MWh). Ranks candidate weather stations, checks
  temperature units, and fits heating/cooling balance points (change-point model) so the
  user chooses HDD/CDD bases. Uses holiday calendars (NERC, US federal), DST-safe
  hour-ending conversion, and load lags no shorter than the horizon. Always reports the
  seasonal-naive benchmark plus MAPE, WAPE, RMSE, bias, and daily peak magnitude/timing
  error. Run by calling the vetted entrypoints in scripts/lf_run.py; do not hand-write the
  split or the model. For cleaning raw smart-meter data first use ami-interval-analytics;
  for ISO market prices use iso-market-data.
category: "Power & Utilities"
summary: Day-ahead and week-ahead load forecasts with leakage-safe backtests, a naive benchmark, and weather-normalized energy.
version: 0.1.0
author: Sourabh Ghose
license: Databricks License
---

# Load Forecaster: Leakage-Safe Forecasts and Weather Normalization

## Overview

Load forecasts from a general coding agent tend to look better on paper than they turn out
in production. A random train/test split leaks neighbouring hours into training. Lag-1
features don't exist at a day-ahead horizon. Holiday load gets ignored. Celsius gets fed
into 65-degree bases. No one compares against a naive forecast. This skill runs a
rolling-origin backtest that is leakage-safe by construction, reports the model next to a
seasonal-naive benchmark, produces the next-horizon forecast, and computes weather-normalized
energy for the last 365 days. The weather decisions (station, unit, balance points, normal
period) are shown to the user and they decide.

Outputs: `<prefix>_backtest` (hourly actual, model, naive by origin), `<prefix>_forecast`,
`<prefix>_metrics` (JSON metrics and normalization), and `<prefix>_manifest`.

## When to Use

- "Build a day-ahead hourly load forecast for our service territory."
- "How accurate would a week-ahead forecast be? Backtest it properly."
- "What would last year's sales have been in normal weather?" (weather normalization)
- "Which weather station best explains our system load?"
- "Find our heating and cooling balance points."
- "Compare a gradient-boosting model against a degree-day regression and a naive benchmark."
- "Forecast EIA-930 balancing-authority demand for the next 24 hours."

## Prerequisites

- **Compute:** Python compute (serverless). `model_family='gbm'` needs scikit-learn (preinstalled
  on Databricks runtimes).
- **Load table:** a timestamp column and a demand column (hourly or sub-hourly average MW or kW).
  At least 13 months of history is needed for the default backtest.
- **Weather table:** `station_id`, UTC timestamp, temperature (one unit). Hours past the last
  load hour (forecast weather) let the skill produce the next-horizon forecast.
- **Optional:** a station table (`station_id, lat, lon`) and load centroid for distances.

## Quick Start

```python
import sys
sys.path.append('<this-skill-dir>/scripts')
from lf_run import preview_forecast_options, build_confirmed_forecast

# STEP 1: READ-ONLY. Station ranking, unit check, fitted balance points, decisions.
print(preview_forecast_options("main.grid.system_load", "main.grid.weather_hourly",
                               local_timezone="America/Chicago", load_ts_col="ts_utc",
                               load_value_col="load_mw"))

# STEP 2: ONLY after the user has answered every decision.
print(build_confirmed_forecast("main.grid.system_load", "main.grid.weather_hourly",
                               "main.grid.lf_system", local_timezone="America/Chicago",
                               load_timestamp_basis="utc", load_interval_convention="ending",
                               load_unit="MW", weather_station="KORD", temperature_unit="F",
                               hdd_base=60, cdd_base=68, holiday_calendar="nerc",
                               horizon_hours=24, model_family="gbm", normal_years=(1994, 2023),
                               load_ts_col="ts_utc", load_value_col="load_mw"))
```

## Workflow

**⛔ EXECUTE, DO NOT REIMPLEMENT.** Call `preview_forecast_options` and then
`build_confirmed_forecast`, and report their output. Do not write your own split, features
or model, and do not choose a station, unit, base, or normal period yourself.

### Step 1: Preview (read-only)

The preview ranks stations (coverage, then R² against daily load, then distance), reports
temperature percentiles with a unit guess, fits a five-parameter change-point model over a
grid of bases (top 5 pairs, and how much worse the 65/65 convention fits), lists the weather
years available for normals, and shows which load lags each horizon allows. **Show the
preview to the user and ask for every decision.**

### Step 2: Prepare hourly data

Load timestamps are converted to hour-beginning UTC (the fall-back hour is resolved by
order), sub-hourly data is averaged to hourly MW, and kW is converted to MW. The chosen
station is gridded hourly, with gaps of up to 3 hours filled linearly and flagged. Longer
gaps stay missing.

### Step 3: Features without leakage

Features are local hour, weekday, month, holiday and weekend-or-holiday flags (from the
chosen calendar), temperature, heating/cooling degrees, and load lags of at least the
horizon (24 → lags 24/168/336; 36 → 48/168/336). The code asserts no lag is shorter than the
horizon.

### Step 4: Rolling-origin backtest

The skill runs six weekly origins by default, each trained only on data before the origin
with at least 365 days of history. It reports the chosen model and the seasonal-naive
benchmark (same hour, one week earlier) with MAPE, WAPE, RMSE, bias, daily peak APE, peak
timing error, and skill vs naive. See `references/backtesting_and_metrics.md`.

### Step 5: Weather normalization and forecast

A daily degree-day model is re-predicted with normal degree days (the mean of each calendar
day's degree days over `normal_years`) to give weather-normalized MWh for the last 365 days.
The model is then refit on all history to forecast the next horizon wherever forecast
weather exists.

### Step 6: Write and report

The skill writes the tables and manifest. Report WAPE against naive, peak error, and the
normalization, and **state that backtest weather is actual (ex-post)**.

## Decision Points

| Decision | Options | Governing practice | What changes |
|----------|---------|--------------------|--------------|
| `local_timezone` | IANA zone | Load area | Calendar features, holidays |
| `load_timestamp_basis` / `load_interval_convention` | `utc`/`local_naive`; `ending`/`beginning` | Source system (EIA-930: UTC hour-ending) | One-hour shift of every value |
| `load_unit` | `MW`, `kW` | Source system | Energy totals (×1000) |
| `weather_station` | from the ranking | Coverage + fit + distance | Forecast and normalization accuracy |
| `temperature_unit` | `F`, `C` | Source data | Meaning of bases |
| `hdd_base`, `cdd_base` | 65 °F / 18 °C convention or fitted balance points | NOAA/EIA convention vs ASHRAE-style change-point fit | Degree days, normalization |
| `holiday_calendar` | `nerc`, `us_federal`, `none` | NERC off-peak days vs federal | Holiday load shape |
| `horizon_hours` | 24, 168, … | Use case (day-ahead ops, week-ahead planning) | Allowed lags, accuracy |
| `model_family` | `degree_day_regression`, `gbm` | Transparency vs accuracy | Model |
| `normal_years` | e.g. (1991, 2020) or trailing 10/20 years | NOAA normals vs utility rate-case practice | Normalized MWh |

## Key Parameters

| Parameter | Default | Effect |
|-----------|---------|--------|
| `backtest_folds` | `6` | Number of rolling origins |
| `backtest_step_hours` | `168` | Spacing between origins |
| `min_train_days` | `365` | History required before the first origin |
| `max_weather_gap_hours` | `3` | Longest temperature gap filled linearly |
| `assume_basis` / `assume_convention` (preview) | `utc` / `ending` | Placement for the profile only; printed as assumptions |

## Expected Outputs

- `<prefix>_backtest`: `hour_start_utc, local_date, load_mw, origin_utc, forecast_mw, naive_mw`
- `<prefix>_forecast`: `hour_start_utc, forecast_mw` for the next horizon (if forecast weather exists)
- `<prefix>_metrics`: model and naive metrics, skill score, normalization (actual vs
  normalized MWh, actual vs normal HDD/CDD, slopes, R², CV(RMSE)), data-quality report
- `<prefix>_manifest`: inputs, every decision, version

## Common Recipes

### Recipe: Balance points only

```python
from lf_weather import fit_balance_points
fit_balance_points(daily_mwh, daily_mean_temp, np.arange(45, 80, 1.0)).head()
```

### Recipe: Normalization only (no forecast)

```python
from lf_normalize import daily_frame, normal_degree_days, weather_normalized_energy
normals = normal_degree_days(station_wx, "America/Chicago", (1994, 2023), 60, 68)
weather_normalized_energy(daily_frame(hourly, "America/Chicago", hol), normals, 60, 68)
```

## Troubleshooting

| Problem | Cause | Solution |
|---------|-------|----------|
| `DecisionRequired` | A decision was not given | Ask the user |
| "Not enough history for the requested backtest" | < 13 months of load | Reduce folds or `min_train_days` after telling the user |
| Model doesn't beat naive | Wrong station, unit, or bases; structural change | Revisit the preview; check data quality |
| Normalization off by a few % between runs | Different `normal_years` | Pin the period in the manifest; report it |
| `gbm` ImportError | scikit-learn missing locally | Use Databricks runtime or `degree_day_regression` |
| Empty forecast table | No weather after the last load hour | Append forecast weather to the weather table |

## Guardrails

1. Never use a random split or a load lag shorter than the horizon.
2. Always report the naive benchmark next to the model.
3. Always state that backtest weather is actual (ex-post).
4. Never assume the temperature unit or bases; show the fit and ask.
5. Customer-level load is customer data: share aggregates or use grid-data-guard.
6. Retry at most 3 times; ask before backtesting more than ~50 series at once.

## Related Skills

- `ami-interval-analytics`: VEE on smart-meter data before aggregating to load
- `iso-market-data`: LMP and ISO load data (settlement intervals, nodes)
- `energy-foundation-models`: time-series foundation models (Chronos, TimesFM) as alternatives
- `energy-semantic-builder`: governed KPIs (peak demand, load factor)
- `grid-data-guard`: protect customer-level series before sharing
- `unit-guard`: MW/MWh/kW conversions

## Bundled Resources

- `scripts/lf_run.py`: entrypoints (`preview_forecast_options`, `build_confirmed_forecast`)
- `scripts/lf_pipeline.py`: preparation, preview profile, end-to-end run
- `scripts/lf_features.py`: DST-safe time, NERC/federal holidays, degree values, safe lags
- `scripts/lf_weather.py`: station ranking, unit check, gap fill, change-point fit, normals
- `scripts/lf_models.py`: naive, degree-day regression, GBM, rolling origin, metrics
- `scripts/lf_normalize.py`: weather normalization
- `scripts/lf_decisions.py`: decisions, `DecisionRequired`, config, manifest
- `references/backtesting_and_metrics.md`, `references/weather_and_degree_days.md`

## References

- [Forecasting: Principles and Practice, time-series cross-validation](https://otexts.com/fpp3/tscv.html)
- [Hong & Fan (2016), probabilistic load forecasting review](https://doi.org/10.1016/j.ijforecast.2015.11.011)
- [NOAA ISD](https://www.ncei.noaa.gov/products/land-based-station/integrated-surface-database) and [U.S. Climate Normals](https://www.ncei.noaa.gov/products/land-based-station/us-climate-normals)
- [EIA-930 Hourly Electric Grid Monitor](https://www.eia.gov/electricity/gridmonitor/)
- [ASHRAE Guideline 14](https://www.ashrae.org/) (inverse change-point models; paywalled)
