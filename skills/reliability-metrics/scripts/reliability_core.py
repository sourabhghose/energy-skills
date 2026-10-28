"""IEEE 1366 distribution reliability indices: pure-python core (pandas / numpy).

Purpose
    Compute SAIDI, SAIFI, CAIDI, CAIFI, ASAI, MAIFI, MAIFI_E, CEMI-n and CELID from
    step-restoration outage records, identify Major Event Days (MED) with the
    2.5 beta method, and break customer-minutes down by cause. No Spark, no network.

Usage
    from reliability_core import preview_reliability_options, build_confirmed_reliability
    print(preview_reliability_options(steps, customers_served, reporting_year=2024,
                                      tz="America/Chicago")["readout"])
    result = build_confirmed_reliability(steps, customers_served, reporting_year=2024,
                                         tz="America/Chicago", sustained_threshold_min=5,
                                         denominator_basis="average",
                                         planned_handling="exclude_planned",
                                         med_method="ieee_2_5_beta")

Input contract (column names are canonical; map yours before calling)
    steps:             event_id, outage_start, restore_ts (tz-aware), customers_restored,
                       cause_code, is_planned [, circuit_id, device_id]
                       One row per restoration step. An unstepped outage is one row.
    customers_served:  period_start (date), customers_served [, circuit_id]
                       One row per month (or per year) of the customer count.
    momentary_ops:     device_id, op_ts (tz-aware), customers_affected      (optional)
    customer_events:   customer_id, event_id, duration_min                  (optional)
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

LOG = logging.getLogger(__name__)

SUSTAINED_THRESHOLD_OPTIONS = (1, 5)
DENOMINATOR_OPTIONS = ("average", "year_end")
PLANNED_OPTIONS = ("exclude_planned", "include_planned")
MED_OPTIONS = ("ieee_2_5_beta", "none")
MED_BETA_MULTIPLIER = 2.5
MED_HISTORY_YEARS = 5
STEP_COLUMNS = ("event_id", "outage_start", "restore_ts", "customers_restored",
                "cause_code", "is_planned")


class DecisionRequired(ValueError):
    """A decision that belongs to the reliability engineer was not supplied."""

    def __init__(self, decision: str, options: tuple, why: str):
        super().__init__(
            f"Decision required: '{decision}' must be one of {list(options)}. {why}"
        )
        self.decision = decision
        self.options = options


@dataclass(frozen=True)
class Decisions:
    sustained_threshold_min: int
    denominator_basis: str
    planned_handling: str
    med_method: str

    def as_dict(self) -> dict:
        return {
            "sustained_threshold_min": self.sustained_threshold_min,
            "denominator_basis": self.denominator_basis,
            "planned_handling": self.planned_handling,
            "med_method": self.med_method,
        }


def require_decisions(sustained_threshold_min, denominator_basis, planned_handling,
                      med_method) -> Decisions:
    """Validate every decision; raise DecisionRequired naming the first missing one."""
    checks = (
        ("sustained_threshold_min", sustained_threshold_min, SUSTAINED_THRESHOLD_OPTIONS,
         "IEEE 1366 uses > 5 min; some regulators still use > 1 min."),
        ("denominator_basis", denominator_basis, DENOMINATOR_OPTIONS,
         "Average vs. year-end customers served changes every per-customer index."),
        ("planned_handling", planned_handling, PLANNED_OPTIONS,
         "Regulatory reporting rules differ on planned (pre-notified) interruptions."),
        ("med_method", med_method, MED_OPTIONS,
         "Major Event Day exclusion is the largest driver of reported SAIDI."),
    )
    for name, value, options, why in checks:
        if value is None or value not in options:
            raise DecisionRequired(name, options, why)
    return Decisions(int(sustained_threshold_min), denominator_basis, planned_handling,
                     med_method)


# --------------------------------------------------------------------------- validation

def validate_steps(steps: pd.DataFrame) -> list[str]:
    """Return a list of data-quality problems (empty list = clean)."""
    missing = [c for c in STEP_COLUMNS if c not in steps.columns]
    if missing:
        return [f"steps is missing columns: {missing}"]
    problems = []
    for col in ("outage_start", "restore_ts"):
        if getattr(steps[col].dt, "tz", None) is None:
            problems.append(f"{col} must be timezone-aware (got naive timestamps)")
    if problems:
        return problems
    negative = int((steps["restore_ts"] < steps["outage_start"]).sum())
    if negative:
        problems.append(f"{negative} step(s) restore before the outage starts")
    bad_customers = int((steps["customers_restored"] <= 0).sum())
    if bad_customers:
        problems.append(f"{bad_customers} step(s) have customers_restored <= 0")
    return problems


def _assert_clean(steps: pd.DataFrame) -> None:
    problems = validate_steps(steps)
    if problems:
        raise ValueError("Outage step data failed validation: " + "; ".join(problems))


# --------------------------------------------------------------------------- events

def classify_steps(steps: pd.DataFrame, sustained_threshold_min: int) -> pd.DataFrame:
    """Add duration_min, customer_minutes, is_sustained per restoration step.

    Classification is per *step*: customers restored within the threshold experienced a
    momentary interruption even when the event as a whole was sustained.
    """
    _assert_clean(steps)
    duration = (steps["restore_ts"] - steps["outage_start"]).dt.total_seconds() / 60.0
    sustained = duration > sustained_threshold_min
    return steps.assign(
        duration_min=duration,
        is_sustained=sustained,
        customer_minutes=np.where(sustained, duration * steps["customers_restored"], 0.0),
        sustained_customers=np.where(sustained, steps["customers_restored"], 0),
        momentary_customers=np.where(sustained, 0, steps["customers_restored"]),
    )


def summarize_events(classified: pd.DataFrame, tz: str) -> pd.DataFrame:
    """One row per event, dated by the local calendar day the event began."""
    grouped = classified.groupby("event_id", as_index=False).agg(
        outage_start=("outage_start", "min"),
        last_restore=("restore_ts", "max"),
        customers_interrupted=("sustained_customers", "sum"),
        momentary_customers=("momentary_customers", "sum"),
        customer_minutes=("customer_minutes", "sum"),
        cause_code=("cause_code", "first"),
        is_planned=("is_planned", "max"),
        n_steps=("event_id", "size"),
    )
    local_day = grouped["outage_start"].dt.tz_convert(tz).dt.date
    return grouped.assign(event_date=local_day, year=pd.to_datetime(local_day).dt.year)


# --------------------------------------------------------------------------- denominator

def customers_served_for(customers_served: pd.DataFrame, year: int, basis: str) -> float:
    """N_T for a reporting year under the chosen basis."""
    dates = pd.to_datetime(customers_served["period_start"])
    in_year = customers_served.assign(_d=dates).loc[lambda d: d["_d"].dt.year == year]
    if in_year.empty:
        raise ValueError(f"No customers_served rows for {year}")
    by_period = in_year.groupby("_d")["customers_served"].sum().sort_index()
    if basis == "average":
        return float(by_period.mean())
    if basis == "year_end":
        return float(by_period.iloc[-1])
    raise DecisionRequired("denominator_basis", DENOMINATOR_OPTIONS, "Unknown basis.")


def period_minutes(year: int) -> float:
    """Minutes in a calendar year: 525,600 or 527,040 in a leap year."""
    days = 366 if (year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)) else 365
    return days * 24 * 60.0


# --------------------------------------------------------------------------- MED

def daily_saidi(events: pd.DataFrame, customers_served: pd.DataFrame,
                basis: str) -> pd.Series:
    """Daily SAIDI (minutes) for every calendar day of every year present in events."""
    years = sorted(events["year"].unique())
    parts = []
    for year in years:
        n_t = customers_served_for(customers_served, int(year), basis)
        days = pd.date_range(f"{year}-01-01", f"{year}-12-31", freq="D").date
        cmi = events.loc[events["year"] == year].groupby("event_date")["customer_minutes"].sum()
        parts.append(pd.Series(cmi.reindex(days, fill_value=0.0).values / n_t, index=days))
    if not parts:
        return pd.Series(dtype=float)
    return pd.concat(parts).sort_index()


def med_threshold(daily: pd.Series, reporting_year: int) -> dict:
    """T_MED for reporting_year from the *prior* five years of daily SAIDI.

    alpha / beta are the mean and sample standard deviation of ln(daily SAIDI) over
    days with SAIDI > 0 (zero days have no logarithm and are excluded from the fit).
    """
    idx = pd.to_datetime(pd.Index(daily.index))
    first = reporting_year - MED_HISTORY_YEARS
    window = daily[(idx.year >= first) & (idx.year < reporting_year)]
    positive = window[window > 0]
    years_used = sorted(set(pd.to_datetime(pd.Index(window.index)).year))
    if len(positive) < 30:
        raise ValueError(
            f"Only {len(positive)} non-zero SAIDI days in {first}-{reporting_year - 1}; "
            "need prior-year history to set T_MED."
        )
    logs = np.log(positive.to_numpy(dtype=float))
    alpha, beta = float(np.mean(logs)), float(np.std(logs, ddof=1))
    warnings = []
    if len(years_used) < MED_HISTORY_YEARS:
        warnings.append(f"Only {len(years_used)} of {MED_HISTORY_YEARS} history years available.")
    return {
        "alpha": alpha, "beta": beta,
        "t_med_minutes": math.exp(alpha + MED_BETA_MULTIPLIER * beta),
        "history_years": years_used, "nonzero_days": int(len(positive)),
        "warnings": warnings,
    }


def major_event_days(daily: pd.Series, reporting_year: int, t_med: float) -> list:
    """Dates in reporting_year whose daily SAIDI exceeds T_MED."""
    idx = pd.to_datetime(pd.Index(daily.index))
    in_year = daily[idx.year == reporting_year]
    return sorted(d for d, v in in_year.items() if v > t_med)


# --------------------------------------------------------------------------- momentary

def group_momentary_events(ops: pd.DataFrame, window_min: float = 5.0) -> pd.DataFrame:
    """Collapse reclosing operations on one device into MAIFI_E events.

    Operations on the same device that start within `window_min` of the first
    operation of a sequence are one momentary event; customers = max in the sequence.
    """
    if ops is None or ops.empty:
        return pd.DataFrame(columns=["device_id", "event_start", "customers_affected"])
    ordered = ops.sort_values(["device_id", "op_ts"])
    rows = []
    for device, group in ordered.groupby("device_id"):
        rows.extend(_sequences_for_device(device, group, window_min))
    return pd.DataFrame(rows)


def _sequences_for_device(device, group: pd.DataFrame, window_min: float) -> list[dict]:
    sequences, start, peak = [], None, 0
    for ts, customers in zip(group["op_ts"], group["customers_affected"]):
        if start is not None and (ts - start).total_seconds() / 60.0 <= window_min:
            peak = max(peak, int(customers))
            continue
        if start is not None:
            sequences.append({"device_id": device, "event_start": start, "customers_affected": peak})
        start, peak = ts, int(customers)
    if start is not None:
        sequences.append({"device_id": device, "event_start": start, "customers_affected": peak})
    return sequences


# --------------------------------------------------------------------------- indices

def compute_indices(events: pd.DataFrame, n_t: float, year: int,
                    momentary_events: pd.DataFrame | None = None) -> dict:
    """Core IEEE 1366 indices for one filtered set of events."""
    ci = float(events["customers_interrupted"].sum())
    cmi = float(events["customer_minutes"].sum())
    saidi, saifi = cmi / n_t, ci / n_t
    out = {
        "customers_served": n_t,
        "customers_interrupted": ci,
        "customer_minutes_interrupted": cmi,
        "saidi_min": saidi,
        "saifi": saifi,
        "caidi_min": (saidi / saifi) if saifi else float("nan"),
        "asai": 1.0 - cmi / (n_t * period_minutes(year)),
        "maifi": float(events["momentary_customers"].sum()) / n_t,
        "sustained_events": int((events["customers_interrupted"] > 0).sum()),
    }
    if momentary_events is not None and not momentary_events.empty:
        out["maifi_e"] = float(momentary_events["customers_affected"].sum()) / n_t
    return out


def customer_level_indices(customer_events: pd.DataFrame, n_t: float,
                           cemi_n: int = 3, celid_hours: float = 8.0) -> dict:
    """CAIFI, CEMI-n, CELID-s and CELID-t from customer-level sustained interruptions."""
    per_customer = customer_events.groupby("customer_id").agg(
        n=("event_id", "nunique"),
        longest=("duration_min", "max"),
        total=("duration_min", "sum"),
    )
    affected = len(per_customer)
    threshold = celid_hours * 60.0
    return {
        "caifi": (per_customer["n"].sum() / affected) if affected else float("nan"),
        f"cemi_{cemi_n}": float((per_customer["n"] > cemi_n).sum()) / n_t,
        f"celid_s_{celid_hours:g}h": float((per_customer["longest"] >= threshold).sum()) / n_t,
        f"celid_t_{celid_hours:g}h": float((per_customer["total"] >= threshold).sum()) / n_t,
    }


def cause_breakdown(events: pd.DataFrame) -> pd.DataFrame:
    """Customer-minutes and customers interrupted by cause code, with CMI share."""
    by_cause = events.groupby("cause_code", as_index=False).agg(
        events=("event_id", "nunique"),
        customers_interrupted=("customers_interrupted", "sum"),
        customer_minutes=("customer_minutes", "sum"),
    )
    total = by_cause["customer_minutes"].sum()
    share = by_cause["customer_minutes"] / total if total else 0.0
    return by_cause.assign(cmi_share=share).sort_values("customer_minutes", ascending=False)
