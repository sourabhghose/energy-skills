"""Daily reliability fact table + Unity Catalog metric view YAML for IEEE 1366 indices.

Purpose
    build_daily_fact     One row per (event_date, circuit_id) for EVERY calendar day and
                         circuit (zero-outage days included), carrying customer-minutes,
                         customers interrupted, the confirmed N_T, and the system MED flag.
    metric_view_yaml     YAML body for CREATE VIEW ... WITH METRICS LANGUAGE YAML.
    metric_view_sql      Full CREATE OR REPLACE VIEW statement.

Why a complete daily grid: SAIDI over any slice is
    SUM(customer_minutes) / (SUM(customers_served) / COUNT(DISTINCT event_date))
which is only N_T-correct when every circuit has a row for every day.

Usage
    fact = build_daily_fact(result_events, customers_served, meds, year, basis)
    print(metric_view_sql("main.reliability.mv_reliability_daily", "main.reliability.daily_fact"))
"""

from __future__ import annotations

import re

import pandas as pd
import yaml

from reliability_core import customers_served_for

IDENT = re.compile(r"^[A-Za-z0-9_]+(\.[A-Za-z0-9_]+){0,2}$")
SYSTEM = "SYSTEM"


def _circuit_counts(customers_served: pd.DataFrame, year: int, basis: str) -> dict:
    if "circuit_id" not in customers_served.columns:
        return {SYSTEM: customers_served_for(customers_served, year, basis)}
    return {
        cid: customers_served_for(group, year, basis)
        for cid, group in customers_served.groupby("circuit_id")
    }


def build_daily_fact(events: pd.DataFrame, customers_served: pd.DataFrame, meds: list,
                     year: int, basis: str) -> pd.DataFrame:
    """Complete date x circuit grid for one reporting year (events from summarize_events)."""
    counts = _circuit_counts(customers_served, year, basis)
    days = pd.date_range(f"{year}-01-01", f"{year}-12-31", freq="D").date
    grid = pd.MultiIndex.from_product([days, list(counts)], names=["event_date", "circuit_id"])
    ev = events.loc[events["year"] == year]
    ev = ev.assign(circuit_id=ev["circuit_id"] if "circuit_id" in ev.columns else SYSTEM)
    agg = ev.groupby(["event_date", "circuit_id"]).agg(
        customer_minutes=("customer_minutes", "sum"),
        customers_interrupted=("customers_interrupted", "sum"),
        momentary_customers=("momentary_customers", "sum"),
    )
    fact = agg.reindex(grid, fill_value=0).reset_index()
    med_set = set(meds)
    return fact.assign(
        customers_served=fact["circuit_id"].map(counts).astype(float),
        is_med=fact["event_date"].isin(med_set),
    )


def _measures() -> list[dict]:
    n_t = "SUM(customers_served) / COUNT(DISTINCT event_date)"
    not_med = "CASE WHEN NOT is_med THEN {col} ELSE 0 END"
    return [
        {"name": "customer_minutes", "expr": "SUM(customer_minutes)",
         "comment": "Sustained customer-minutes interrupted (CMI)."},
        {"name": "customers_interrupted", "expr": "SUM(customers_interrupted)",
         "comment": "Sustained customer interruptions (CI)."},
        {"name": "momentary_customers", "expr": "SUM(momentary_customers)",
         "comment": "Momentary customer interruptions."},
        {"name": "customers_served", "expr": n_t,
         "comment": "N_T: customers served over the selected days (confirmed basis)."},
        {"name": "customer_minutes_excl_med",
         "expr": f"SUM({not_med.format(col='customer_minutes')})",
         "comment": "CMI on non-Major-Event days."},
        {"name": "customers_interrupted_excl_med",
         "expr": f"SUM({not_med.format(col='customers_interrupted')})",
         "comment": "CI on non-Major-Event days."},
        {"name": "saidi_min", "expr": "MEASURE(customer_minutes) / MEASURE(customers_served)",
         "comment": "SAIDI (minutes), all days."},
        {"name": "saifi", "expr": "MEASURE(customers_interrupted) / MEASURE(customers_served)",
         "comment": "SAIFI, all days."},
        {"name": "caidi_min", "expr": "MEASURE(saidi_min) / MEASURE(saifi)",
         "comment": "CAIDI = SAIDI / SAIFI (minutes)."},
        {"name": "maifi", "expr": "MEASURE(momentary_customers) / MEASURE(customers_served)",
         "comment": "MAIFI (momentary interruptions per customer)."},
        {"name": "saidi_excl_med_min",
         "expr": "MEASURE(customer_minutes_excl_med) / MEASURE(customers_served)",
         "comment": "SAIDI excluding IEEE 1366 Major Event Days."},
        {"name": "saifi_excl_med",
         "expr": "MEASURE(customers_interrupted_excl_med) / MEASURE(customers_served)",
         "comment": "SAIFI excluding IEEE 1366 Major Event Days."},
    ]


def metric_view_yaml(source_table: str, skill_version: str = "0.1.0") -> str:
    """YAML body for the reliability metric view (Databricks metric view spec v1.1)."""
    _check_ident(source_table)
    body = {
        "version": "1.1",
        "comment": f"IEEE 1366 reliability indices — reliability-metrics v{skill_version}",
        "source": source_table,
        "dimensions": [
            {"name": "event_date", "expr": "event_date", "comment": "Local calendar day."},
            {"name": "event_month", "expr": "DATE_TRUNC('MONTH', event_date)"},
            {"name": "circuit_id", "expr": "circuit_id"},
            {"name": "is_med", "expr": "is_med", "comment": "System Major Event Day flag."},
        ],
        "measures": _measures(),
    }
    return yaml.safe_dump(body, sort_keys=False, width=100)


def metric_view_sql(view_name: str, source_table: str) -> str:
    """CREATE OR REPLACE VIEW statement wrapping metric_view_yaml."""
    _check_ident(view_name)
    quoted = ".".join(f"`{p}`" for p in view_name.split("."))
    return (f"CREATE OR REPLACE VIEW {quoted}\nWITH METRICS\nLANGUAGE YAML\nAS $$\n"
            f"{metric_view_yaml(source_table)}$$")


def _check_ident(name: str) -> None:
    if not IDENT.match(name):
        raise ValueError(f"Invalid Unity Catalog identifier: {name!r}")
