"""Wholesale market planted-truth generators: interval-ending price conventions and two-settlement charges."""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from pathlib import Path

from ._common import fmt_local, readme, rng_for, write_csv


def _hour_ending(minutes_after_midnight: int) -> int:
    """Interval ending at HH:MM belongs to hour ending ceil(minutes / 60); 24:00 is HE24."""
    return math.ceil(minutes_after_midnight / 60)


def _rt_price(rng, he: int, minute_end: int) -> float:
    base = 28 + 30 * math.exp(-((he - 18) ** 2) / 10) + rng.gauss(0, 4)
    # Two scarcity spikes in the last two intervals of HE18: a floor-to-hour grouping splits them across hours.
    if minute_end in (17 * 60 + 55, 18 * 60):
        base += 1_400 if minute_end == 17 * 60 + 55 else 1_900
    return round(base, 2)


def p08_iso_interval_ending(out: Path, seed: int) -> dict:
    rng = rng_for("p08", seed)
    day = datetime(2024, 7, 15)
    rows, by_he = [], {}
    for k in range(1, 289):
        end = k * 5
        he = _hour_ending(end)
        price = _rt_price(rng, he, end)
        rows.append(["HUB_NORTH", fmt_local(day + timedelta(minutes=end)), f"{price:.2f}"])
        by_he.setdefault(he, []).append(price)
    load = {he: round(4_000 + 1_800 * math.exp(-((he - 17) ** 2) / 18) + rng.gauss(0, 40), 1) for he in by_he}
    write_csv(out / "rt_lmp_5min.csv", ["pnode", "interval_ending_local", "rt_lmp_usd_per_mwh"], rows)
    write_csv(out / "hourly_load.csv", ["operating_date", "hour_ending", "load_mw"],
              [["2024-07-15", he, f"{v:.1f}"] for he, v in sorted(load.items())])
    readme(out, "Real-time LMPs and load, operating day 2024-07-15", [
        "rt_lmp_5min.csv: 5-minute real-time LMP at HUB_NORTH. interval_ending_local is the END of each 5-minute "
        "interval in market time (America/Chicago); the last interval of the day ends at 2024-07-16 00:00.",
        "hourly_load.csv: average load MW for each hour ending (HE01 = 00:00-01:00).",
    ])
    hourly = {he: sum(v) / len(v) for he, v in by_he.items()}
    return {
        "rt_price_he17": round(hourly[17], 4), "rt_price_he18": round(hourly[18], 4),
        "total_rt_cost_usd": round(sum(hourly[he] * load[he] for he in hourly), 2),
        "max_price_hour_ending": max(hourly, key=hourly.get),
    }


def _p09_rt(rng, da_mw: float, da_lmp: float, he: int) -> tuple[float, float]:
    shock = rng.gauss(0, 1)
    rt_lmp = max(-20.0, da_lmp + 12 * shock + (60 if he in (17, 18, 19) and rng.random() < 0.2 else 0))
    metered = max(0.0, da_mw * (1 + 0.04 * shock + rng.gauss(0, 0.02)))
    return round(rt_lmp, 2), round(metered, 3)


def p09_iso_settlement(out: Path, seed: int) -> dict:
    rng = rng_for("p09", seed)
    day = datetime(2024, 8, 1)
    da_rows, rt_rows, da, rt = [], [], {}, []
    for he in range(1, 25):
        mw = round(300 + 120 * math.exp(-((he - 17) ** 2) / 20) + rng.gauss(0, 8), 1)
        lmp = round(32 + 40 * math.exp(-((he - 18) ** 2) / 8) + rng.gauss(0, 3), 2)
        da[he] = (mw, lmp)
        da_rows.append(["2024-08-01", he, f"{mw:.1f}", f"{lmp:.2f}"])
        for k in range(1, 13):
            end = (he - 1) * 60 + 5 * k
            price, metered = _p09_rt(rng, mw, lmp, he)
            rt.append((he, price, metered))
            rt_rows.append([fmt_local(day + timedelta(minutes=end)), f"{price:.2f}", f"{metered:.3f}"])
    write_csv(out / "da_awards.csv", ["operating_date", "hour_ending", "da_award_mw", "da_lmp_usd_per_mwh"], da_rows)
    write_csv(out / "rt_5min.csv", ["interval_ending_local", "rt_lmp_usd_per_mwh", "metered_load_mw"], rt_rows)
    readme(out, "Load-serving entity settlement inputs, operating day 2024-08-01", [
        "da_awards.csv: day-ahead cleared load (MW, flat for each hour ending) and day-ahead LMP.",
        "rt_5min.csv: 5-minute real-time LMP and the metered load, as average MW over each 5-minute interval "
        "(interval ending, market time).",
    ])
    da_charge = sum(mw * lmp for mw, lmp in da.values())
    balancing = sum((m - da[he][0]) * p * 5 / 60 for he, p, m in rt)
    hourly_approx = sum(
        (sum(m for h, _, m in rt if h == he) / 12 - da[he][0]) * (sum(p for h, p, _ in rt if h == he) / 12)
        for he in da)
    return {
        "da_charge_usd": round(da_charge, 2), "rt_balancing_usd": round(balancing, 2),
        "total_charge_usd": round(da_charge + balancing, 2),
        "_pitfall": {"balancing_mw_as_mwh_usd": round(balancing * 12, 2),
                     "balancing_hourly_average_usd": round(hourly_approx, 2)},
    }
