"""Condition one well's production history for decline fitting (pandas).

Input frame columns: period_start (date), volume (per period), optional days_on.
Steps: validate -> calendar days -> rate (calendar or producing basis) -> exclude shut-in /
zero / inconsistent periods -> decline start (peak or first production) -> outliers (MAD on
log rate) -> time axis in years from the decline-start period start, at period midpoints.

Usage:
    from dca_prep import condition_well
    cw = condition_well(pdf, period="monthly", rate_basis="producing_day",
                        decline_start="peak", outlier_method="mad")
    cw.frame[cw.frame.include]      # points to fit
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from dca_models import DAYS_PER_YEAR

PEAK_SEARCH_PERIODS = {"monthly": 12, "daily": 365}
MAD_K, MAD_WINDOW = 3.0, 5
SIGMA_FLOOR = 0.03   # log-rate units (~3%): smooth data must not make every wiggle an outlier


@dataclass(frozen=True)
class ConditionedWell:
    frame: pd.DataFrame            # one row per period with rate, t_years, include, exclude_reason
    first_production: pd.Timestamp
    decline_start: pd.Timestamp
    cum_volume: float              # all produced volume to date, including pre-decline
    t_last_years: float            # end of the last reported period, on the decline axis
    t_offset_years: float          # first production -> decline start
    exclusions: dict


def _calendar_days(starts: pd.Series, period: str) -> pd.Series:
    if period == "daily":
        return pd.Series(1.0, index=starts.index)
    return starts.dt.days_in_month.astype(float)


def _validate(pdf: pd.DataFrame, period: str, rate_basis: str) -> pd.DataFrame:
    if period not in ("monthly", "daily"):
        raise ValueError("period must be 'monthly' or 'daily'")
    if rate_basis == "producing_day" and "days_on" not in pdf.columns:
        raise ValueError("rate_basis='producing_day' needs a days_on column")
    frame = pdf.assign(period_start=pd.to_datetime(pdf["period_start"]).dt.normalize(),
                       volume=pd.to_numeric(pdf["volume"], errors="coerce"))
    if frame["period_start"].duplicated().any():
        dupes = int(frame["period_start"].duplicated().sum())
        raise ValueError(f"{dupes} duplicate periods for one well; aggregate or dedupe the source first")
    if period == "monthly" and (frame["period_start"].dt.day != 1).any():
        frame = frame.assign(period_start=frame["period_start"].dt.to_period("M").dt.to_timestamp())
    return frame.sort_values("period_start").reset_index(drop=True)


def _rates(frame: pd.DataFrame, period: str, rate_basis: str) -> pd.DataFrame:
    cal = _calendar_days(frame["period_start"], period)
    days_on = pd.to_numeric(frame["days_on"], errors="coerce") if "days_on" in frame else cal
    over = days_on > cal + 1e-9
    days = cal if rate_basis == "calendar_day" else days_on.clip(upper=cal)
    rate = frame["volume"] / days.where(days > 0)
    reason = np.select(
        [frame["volume"].isna(), frame["volume"] <= 0, days.isna() | (days <= 0)],
        ["missing_volume", "shut_in_or_zero", "zero_days_on_with_volume"], default="")
    return frame.assign(calendar_days=cal, days_on=days_on, days_on_exceeds_calendar=over,
                        rate=rate, exclude_reason=reason)


def _decline_start_index(frame: pd.DataFrame, period: str, decline_start: str) -> int:
    producing = frame.index[frame["exclude_reason"] == ""]
    if len(producing) == 0:
        raise ValueError("no producing periods")
    if decline_start == "first_production":
        return int(producing[0])
    window = producing[:PEAK_SEARCH_PERIODS[period]]
    return int(frame.loc[window, "rate"].idxmax())


def _flag_outliers(frame: pd.DataFrame, k: float = MAD_K) -> pd.Series:
    """True where log rate deviates > k robust sigmas from a centred rolling median."""
    usable = frame["exclude_reason"] == ""
    logq = np.log(frame.loc[usable, "rate"])
    med = logq.rolling(MAD_WINDOW, center=True, min_periods=3).median()
    resid = logq - med
    mad = float(np.nanmedian(np.abs(resid - np.nanmedian(resid))))
    if not np.isfinite(mad):
        return pd.Series(False, index=frame.index)
    sigma = max(1.4826 * mad, SIGMA_FLOOR)
    flags = (np.abs(resid) > k * sigma).reindex(frame.index, fill_value=False)
    return flags.fillna(False).astype(bool)


def condition_well(pdf: pd.DataFrame, period: str, rate_basis: str, decline_start: str,
                   outlier_method: str) -> ConditionedWell:
    """Build the fit-ready frame for one well. Does not mutate `pdf`."""
    frame = _rates(_validate(pdf, period, rate_basis), period, rate_basis)
    start_idx = _decline_start_index(frame, period, decline_start)
    reason = frame["exclude_reason"].where(frame["exclude_reason"] != "",
                                           np.where(frame.index < start_idx, "pre_decline", ""))
    frame = frame.assign(exclude_reason=reason)
    if outlier_method == "mad":
        outliers = _flag_outliers(frame) & (frame["exclude_reason"] == "")
        frame = frame.assign(exclude_reason=np.where(outliers, "outlier", frame["exclude_reason"]))
    first_prod = frame.loc[frame["volume"] > 0, "period_start"].min()
    start_date = frame.loc[start_idx, "period_start"]
    elapsed = (frame["period_start"] - start_date).dt.days + frame["calendar_days"] / 2.0
    frame = frame.assign(t_years=elapsed / DAYS_PER_YEAR, include=frame["exclude_reason"] == "")
    last = frame.iloc[-1]
    t_last = ((last["period_start"] - start_date).days + last["calendar_days"]) / DAYS_PER_YEAR
    counts = frame.loc[~frame["include"], "exclude_reason"].value_counts().to_dict()
    return ConditionedWell(frame=frame, first_production=first_prod, decline_start=start_date,
                           cum_volume=float(frame["volume"].clip(lower=0).sum(skipna=True)),
                           t_last_years=float(t_last),
                           t_offset_years=float((start_date - first_prod).days / DAYS_PER_YEAR),
                           exclusions={str(k): int(v) for k, v in counts.items()})
