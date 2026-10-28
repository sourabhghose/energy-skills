"""Synthetic grid customer table with planted sensitive columns and risky cells (seeded)."""

from __future__ import annotations

import numpy as np
import pandas as pd


def customers(n: int = 400, seed: int = 11) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    zips = rng.choice(["60601", "60602", "60603", "60604"], size=n, p=[0.45, 0.35, 0.17, 0.03])
    df = pd.DataFrame({
        "account_number": [f"{9000000000 + i}" for i in range(n)],
        "premise_id": [f"P{i:06d}" for i in range(n)],
        "customer_name": [f"Customer {i}" for i in range(n)],
        "service_address": [f"{100 + i} Main St" for i in range(n)],
        "email": [f"c{i}@example.com" for i in range(n)],
        "zip": zips,
        "rate_class": rng.choice(["RES", "SGS"], size=n, p=[0.85, 0.15]),
        "feeder_id": rng.choice(["FDR-12", "FDR-13", "FDR-14"], size=n),
        "substation": "SUB-ALPHA",
        "relay_pickup_amps": rng.choice([400, 600], size=n),
        "lat": 41.88 + rng.normal(0, 0.01, n).round(6),
        "lon": -87.63 + rng.normal(0, 0.01, n).round(6),
    })
    return df


def monthly_usage(cust: pd.DataFrame, months: int = 3, seed: int = 12) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    for m in range(months):
        kwh = rng.gamma(4, 200, len(cust))
        rows.append(cust.assign(read_month=pd.Timestamp("2024-01-01") + pd.DateOffset(months=m),
                                kwh=kwh.round(1)))
    usage = pd.concat(rows, ignore_index=True)
    big = usage["premise_id"] == usage.loc[usage["zip"] == "60603", "premise_id"].iloc[0]
    return usage.assign(kwh=usage["kwh"].where(~big, 250_000.0))  # dominant industrial load
