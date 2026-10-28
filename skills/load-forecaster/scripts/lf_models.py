"""Forecast models and leakage-safe rolling-origin backtesting. numpy / pandas core.

Models share ``fit(train: DataFrame, cols) -> model`` and ``model.predict(df) -> ndarray``:

- ``NaiveSeasonal``: same hour one week earlier (or the smallest weekly multiple ≥ horizon).
  Always reported as the benchmark.
- ``DegreeDayRegression``: ridge least squares on hour×day-type dummies, month dummies,
  heating/cooling degrees (and squares), and allowed load lags.
- ``GradientBoosting``: scikit-learn ``HistGradientBoostingRegressor`` (lazy import).

    from lf_models import rolling_origin_backtest, metrics
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class NaiveSeasonal:
    lag: int

    def predict(self, df: pd.DataFrame) -> np.ndarray:
        return df[f"load_lag_{self.lag}"].to_numpy()


def naive_lag(horizon_hours: int) -> int:
    return int(np.ceil(horizon_hours / 168) * 168)


def _design(df: pd.DataFrame, lag_cols: list[str]) -> np.ndarray:
    hour_type = df["hour"].to_numpy() + 24 * df["is_weekend_or_holiday"].to_numpy()
    ht = np.eye(48)[hour_type.astype(int)]
    month = np.eye(12)[df["month"].to_numpy().astype(int) - 1][:, 1:]
    hd, cd = df["hd"].to_numpy(), df["cd"].to_numpy()
    lags = df[lag_cols].to_numpy() if lag_cols else np.empty((len(df), 0))
    return np.column_stack([ht, month, hd, cd, hd ** 2, cd ** 2, lags])


@dataclass(frozen=True)
class DegreeDayRegression:
    coef: np.ndarray
    lag_cols: tuple[str, ...]

    @classmethod
    def fit(cls, train: pd.DataFrame, cols: list[str], alpha: float = 1e-3):
        lag_cols = [c for c in cols if c.startswith("load_lag_")]
        X, y = _design(train, lag_cols), train["load_mw"].to_numpy()
        reg = alpha * np.eye(X.shape[1])
        coef = np.linalg.solve(X.T @ X + reg, X.T @ y)
        return cls(coef=coef, lag_cols=tuple(lag_cols))

    def predict(self, df: pd.DataFrame) -> np.ndarray:
        return _design(df, list(self.lag_cols)) @ self.coef


@dataclass(frozen=True)
class GradientBoosting:
    model: object
    cols: tuple[str, ...]

    @classmethod
    def fit(cls, train: pd.DataFrame, cols: list[str], seed: int = 0):
        try:
            from sklearn.ensemble import HistGradientBoostingRegressor
        except ImportError as exc:
            raise ImportError("model_family='gbm' needs scikit-learn; use "
                              "'degree_day_regression' or install scikit-learn.") from exc
        model = HistGradientBoostingRegressor(max_iter=300, learning_rate=0.05,
                                              random_state=seed)
        model.fit(train[cols], train["load_mw"])
        return cls(model=model, cols=tuple(cols))

    def predict(self, df: pd.DataFrame) -> np.ndarray:
        return self.model.predict(df[list(self.cols)])


MODEL_FAMILIES = {"degree_day_regression": DegreeDayRegression, "gbm": GradientBoosting}


def origins(hours: pd.Series, horizon: int, folds: int, step: int, min_train_hours: int) -> list:
    """Forecast origins (hour starts), latest last; each test window fits inside the data."""
    last_start = hours.max() - pd.Timedelta(hours=horizon - 1)
    out = [last_start - pd.Timedelta(hours=step * k) for k in range(folds)]
    earliest = hours.min() + pd.Timedelta(hours=min_train_hours)
    kept = sorted(o for o in out if o >= earliest)
    if not kept:
        raise ValueError("Not enough history for the requested backtest; reduce folds or "
                         "min_train_days.")
    return kept


def rolling_origin_backtest(features: pd.DataFrame, cfg, cols: list[str]) -> pd.DataFrame:
    """Expanding-window backtest. Train strictly before each origin; test the next horizon."""
    data = features.dropna(subset=cols + ["load_mw"]).reset_index(drop=True)
    family = MODEL_FAMILIES[cfg.model_family]
    naive = NaiveSeasonal(naive_lag(cfg.horizon_hours))
    parts = []
    for o in origins(data["hour_start_utc"], cfg.horizon_hours, cfg.backtest_folds,
                     cfg.backtest_step_hours, cfg.min_train_days * 24):
        train = data[data["hour_start_utc"] < o]
        test = data[(data["hour_start_utc"] >= o) &
                    (data["hour_start_utc"] < o + pd.Timedelta(hours=cfg.horizon_hours))]
        assert train["hour_start_utc"].max() < test["hour_start_utc"].min()
        model = family.fit(train, cols)
        parts.append(test[["hour_start_utc", "local_date", "load_mw"]].assign(
            origin_utc=o, forecast_mw=model.predict(test), naive_mw=naive.predict(test)))
    return pd.concat(parts, ignore_index=True)


def metrics(actual: pd.Series, forecast: pd.Series, local_date: pd.Series,
            hour: pd.Series | None = None) -> dict:
    """MAPE (near-zero actuals excluded), WAPE, RMSE, bias, daily-peak magnitude and timing."""
    a, f = actual.to_numpy(float), forecast.to_numpy(float)
    err = f - a
    keep = np.abs(a) > 0.01 * np.abs(a).mean()
    frame = pd.DataFrame({"a": a, "f": f, "d": local_date.to_numpy(),
                          "h": (hour if hour is not None else pd.Series(range(len(a)))).to_numpy()})
    by_day = frame.groupby("d")
    peak_a, peak_f = by_day["a"].max(), by_day["f"].max()
    timing = (frame.loc[by_day["a"].idxmax(), "h"].to_numpy()
              - frame.loc[by_day["f"].idxmax(), "h"].to_numpy())
    return {"mape_pct": float(100 * np.mean(np.abs(err[keep] / a[keep]))),
            "wape_pct": float(100 * np.abs(err).sum() / np.abs(a).sum()),
            "rmse": float(np.sqrt(np.mean(err ** 2))),
            "bias_pct": float(100 * err.sum() / np.abs(a).sum()),
            "daily_peak_ape_pct": float(100 * np.mean(np.abs(peak_f - peak_a) / peak_a)),
            "daily_peak_timing_mae_hours": float(np.mean(np.abs(timing)))}


def skill_vs_naive(model_metrics: dict, naive_metrics: dict) -> float:
    """1 − WAPE_model / WAPE_naive (positive = better than the naive benchmark)."""
    return float(1 - model_metrics["wape_pct"] / naive_metrics["wape_pct"])
