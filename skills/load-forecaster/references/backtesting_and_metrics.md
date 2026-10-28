# Leakage-safe backtesting and forecast metrics

## Why random splits are wrong for load

Hourly load is strongly autocorrelated. A random train/test split puts 14:00 in the test set
and 13:00 and 15:00 in training, so the model "interpolates" and reports errors several
times smaller than it will achieve live. Load forecasts must be evaluated **forward in
time**.

## Rolling-origin (expanding window) evaluation

For each origin `o` (default: the last 6 weekly origins):

1. Train only on hours `< o` (at least `min_train_days`, default 365, so every season is seen).
2. Forecast hours `o … o + horizon − 1`.
3. Score, then move `o` forward by `backtest_step_hours` (default 168).

Load lags are restricted to multiples of a day/week that are **≥ the horizon**: a day-ahead
model may use the same hour yesterday (lag 24) and last week (lag 168), but a 36-hour model
can't use lag 24. The code asserts this.

**Ex-post vs ex-ante weather.** The backtest uses *actual* temperatures for the forecast
hours. Live forecasts use *forecast* temperatures, so live error is higher by roughly the
weather-forecast error. Always state this when reporting backtest accuracy.

## Metrics reported

| Metric | Definition | Notes |
|--------|------------|-------|
| MAPE % | mean(\|f − a\| / a) | Hours with \|a\| < 1 % of mean are excluded (near-zero blow-up) |
| WAPE % | Σ\|f − a\| / Σ\|a\| | Preferred headline: robust to small loads |
| RMSE | √mean((f − a)²), MW | Penalises large misses |
| Bias % | Σ(f − a) / Σ\|a\| | Systematic over/under forecast |
| Daily peak APE % | mean over days of \|peak_f − peak_a\| / peak_a | Capacity and peak-pricing relevance |
| Peak timing MAE (h) | mean \|hour of actual peak − hour of forecast peak\| | Demand response dispatch relevance |
| Skill vs naive | 1 − WAPE_model / WAPE_naive | The naive benchmark is the same hour one week earlier |

A model that does not beat the seasonal naive benchmark should not be deployed. Report the
naive numbers next to the model's every time.

## Sources

- Hyndman, R.J. & Athanasopoulos, G., *Forecasting: Principles and Practice* (3rd ed.),
  §5.10 time-series cross-validation: https://otexts.com/fpp3/tscv.html
- Hong, T. & Fan, S. (2016), "Probabilistic electric load forecasting: A tutorial review",
  *International Journal of Forecasting* 32(3): https://doi.org/10.1016/j.ijforecast.2015.11.011
- GEFCom2012/2014 load-forecasting competitions (Hong et al.): https://doi.org/10.1016/j.ijforecast.2013.07.001
