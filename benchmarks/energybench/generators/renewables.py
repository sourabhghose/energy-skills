"""Renewables planted-truth generators: wind curtailment vs. underperformance, PV performance ratio, MW vs. MWh."""

from __future__ import annotations

import math
from bisect import bisect_right
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from ._common import UTC, fmt_local, fmt_utc, hours_between, readme, rng_for, write_csv

RATED_KW = 2050.0
PHOENIX = ZoneInfo("America/Phoenix")


# --- p17: wind curtailment vs. underperformance ----------------------------------------------------------------------

def power_curve_table() -> list[tuple[float, float]]:
    table = []
    for k in range(51):
        ws = k * 0.5
        if ws < 3 or ws > 25:
            kw = 0.0
        elif ws >= 12.5:
            kw = RATED_KW
        else:
            kw = RATED_KW * ((ws - 3) / 9.5) ** 2.6
        table.append((ws, round(kw, 1)))
    return table


def interp(table: list[tuple[float, float]], x: float) -> float:
    xs = [p[0] for p in table]
    if x <= xs[0]:
        return table[0][1]
    if x >= xs[-1]:
        return table[-1][1]
    i = bisect_right(xs, x) - 1
    (x0, y0), (x1, y1) = table[i], table[i + 1]
    return y0 + (y1 - y0) * (x - x0) / (x1 - x0)


def _p17_wind(rng, n: int) -> list[float]:
    ar, out = 0.0, []
    for k in range(n):
        ar = 0.98 * ar + rng.gauss(0, 0.35)
        out.append(max(0.0, 8 + 2.5 * math.sin(2 * math.pi * k / 144) + ar))
    return out


def _p17_windows(rng, n: int, count: int, lo: int, hi: int) -> set[int]:
    idx: set[int] = set()
    for _ in range(count):
        s = rng.randint(0, n - hi)
        idx |= set(range(s, s + rng.randint(lo, hi)))
    return idx


def _p17_rows(rng, park: list[float], table: list, curtailed: set[int], start: datetime) -> list[list]:
    rows = []
    for t in range(1, 7):
        tid, perf, offset = f"T0{t}", 0.93 if t == 4 else 1.0, rng.gauss(0, 0.3)
        down = _p17_windows(rng, len(park), 2, 36, 144)
        for k, base in enumerate(park):
            ws = round(max(0.0, base + offset + rng.gauss(0, 0.4)), 2)
            setpoint = 1000.0 if k in curtailed else RATED_KW
            available = 0 if k in down else 1
            kw = interp(table, ws) * perf * rng.gauss(1.0, 0.03) if available else 0.0
            kw = round(max(0.0, min(kw, setpoint, RATED_KW)), 1)
            rows.append([fmt_utc(start + timedelta(minutes=10 * k)), tid, f"{ws:.2f}", f"{kw:.1f}",
                         available, f"{setpoint:.0f}"])
    return rows


def _p17_truth(rows: list[list], table: list) -> dict:
    curt, under, ratio = 0.0, 0.0, {}
    for _, tid, ws, kw, available, setpoint in rows:
        if not available:
            continue
        expected, actual = interp(table, float(ws)), float(kw)
        loss = max(0.0, expected - actual) / 6 / 1000
        if float(setpoint) < RATED_KW:
            curt += loss
        else:
            under += loss
            e, a = ratio.get(tid, (0.0, 0.0))
            ratio[tid] = (e + expected, a + actual)
    worst = min(ratio, key=lambda t: ratio[t][1] / ratio[t][0])
    return {"curtailment_loss_mwh": round(curt, 4), "underperformance_loss_mwh": round(under, 4),
            "underperforming_turbines": [worst]}


def p17_wind_curtailment(out: Path, seed: int) -> dict:
    rng = rng_for("p17", seed)
    n, start = 30 * 144, datetime(2024, 3, 1, tzinfo=UTC)
    park, table = _p17_wind(rng, n), power_curve_table()
    windy = [k for k in range(n - 48) if park[k] > 10.0]
    curtailed = {k for s in rng.sample(windy, 5) for k in range(s, s + rng.randint(18, 48))}
    rows = _p17_rows(rng, park, table, curtailed, start)
    write_csv(out / "scada_10min.csv", ["timestamp_utc", "turbine_id", "wind_speed_ms", "active_power_kw",
                                       "available", "park_setpoint_kw"], rows)
    write_csv(out / "reference_power_curve.csv", ["wind_speed_ms", "power_kw"], [[f"{w:.1f}", f"{p:.1f}"]
                                                                                  for w, p in table])
    readme(out, "Wind farm SCADA, six 2.05 MW turbines, March 2024", [
        "scada_10min.csv: 10-minute averages per turbine; timestamp is interval-beginning UTC. available = 0 when "
        "the turbine was down for maintenance or fault. park_setpoint_kw is the active-power limit from the grid "
        "operator (2050 = no limit).",
        "reference_power_curve.csv: contractual power curve at site air density.",
    ])
    return _p17_truth(rows, table)


# --- p18: PV performance ratio --------------------------------------------------------------------------------------

def _p18_hour(rng, h: int, cloud: float) -> tuple[float, float, float]:
    sun = math.sin(math.pi * (h + 0.5 - 5.5) / 14) if 5 <= h <= 19 else 0.0
    poa = round(max(0.0, 1050 * sun * cloud * rng.uniform(0.92, 1.0)), 1)
    ghi = round(poa * rng.uniform(0.80, 0.90), 1)
    tmod = round(26 + 9 * math.sin(math.pi * (h - 8) / 12) + 0.03 * poa, 1)
    return poa, ghi, tmod


def p18_solar_pr(out: Path, seed: int) -> dict:
    rng = rng_for("p18", seed)
    p0, rows = 5_000.0, []
    for d in range(30):
        day, cloud = datetime(2024, 6, 1) + timedelta(days=d), rng.uniform(0.6, 1.0)
        avail = 0.7 if d == 16 else 1.0
        for h in range(24):
            poa, ghi, tmod = _p18_hour(rng, h, cloud)
            dc = p0 * poa / 1000 * (1 - 0.0035 * (tmod - 25)) * 0.86
            e = round(max(0.0, min(4_200.0, dc) * rng.gauss(1.0, 0.01) * avail), 1)
            rows.append([fmt_local(day + timedelta(hours=h)), f"{ghi:.1f}", f"{poa:.1f}", f"{tmod:.1f}", f"{e:.1f}"])
    write_csv(out / "plant_hourly.csv", ["timestamp_local", "ghi_wm2", "poa_wm2", "module_temp_c", "ac_energy_kwh"],
              rows)
    readme(out, "5 MWdc fixed-tilt PV plant, June 2024", [
        "plant_hourly.csv: hour-beginning local time (America/Phoenix, no DST). Irradiance is the hourly mean "
        "(W/m2): GHI from the met station, POA from the plane-of-array pyranometer. ac_energy_kwh is revenue-meter "
        "energy for the hour.",
        "Nameplate: 5,000 kWp DC at STC; 4,200 kW AC. Module temperature coefficient of power: -0.35 %/degC.",
    ])
    return _p18_truth(rows, p0)


def _p18_truth(rows: list[list], p0: float) -> dict:
    e = sum(float(r[4]) for r in rows)
    h_poa = sum(float(r[2]) for r in rows) / 1000
    tc = sum(p0 * float(r[2]) / 1000 * (1 - 0.0035 * (float(r[3]) - 25)) for r in rows)
    daily: dict[str, list[float]] = {}
    for r in rows:
        acc = daily.setdefault(r[0][:10], [0.0, 0.0])
        acc[0], acc[1] = acc[0] + float(r[4]), acc[1] + float(r[2]) / 1000
    worst = min(daily, key=lambda d: daily[d][0] / (p0 * daily[d][1]))
    ghi = sum(float(r[1]) for r in rows) / 1000
    return {"pr_june_pct": round(100 * e / (p0 * h_poa), 4), "pr_temp_corrected_june_pct": round(100 * e / tc, 4),
            "lowest_pr_date": worst, "_pitfall": {"pr_with_ghi_pct": round(100 * e / (p0 * ghi), 4)}}


# --- p19: capacity factor from average-MW interval data ------------------------------------------------------------

def _p19_output(rng, kind: str, t: datetime, state: list[float]) -> float:
    if kind == "wind":
        state[0] = 0.97 * state[0] + rng.gauss(0, 0.06)
        return max(0.0, min(100.0, 100 * (0.35 + state[0])))
    if kind == "solar":
        local_h = (t.hour - 7) % 24 + t.minute / 60  # UTC-7
        sun = math.sin(math.pi * (local_h - 6) / 13) if 6 <= local_h <= 19 else 0.0
        return max(0.0, 50_000 * sun * rng.uniform(0.75, 1.0))  # kW
    on = t.month in (6, 7, 8, 9) and 20 <= t.hour <= 23 or (t.month in (1, 12) and 13 <= t.hour <= 15)
    return rng.uniform(150, 200) if on and rng.random() < 0.9 else 0.0


def p19_capacity_factor(out: Path, seed: int) -> dict:
    rng = rng_for("p19", seed)
    times = hours_between(datetime(2024, 1, 1, tzinfo=UTC), datetime(2025, 1, 1, tzinfo=UTC), timedelta(minutes=15))
    plants = {"WIND-1": ("wind", 100.0, "output_mw"), "SOLAR-1": ("solar", 50.0, "output_kw"),
              "PEAKER-1": ("gas", 200.0, "output_mw")}
    gen, cf = {}, {}
    for pid, (kind, mw, col) in plants.items():
        state, rows = [0.0], []
        for t in times:
            value = round(_p19_output(rng, kind, t, state), 3)
            rows.append([fmt_utc(t), f"{value:.3f}"])
        write_csv(out / f"{pid.lower()}_15min.csv", ["interval_start_utc", col], rows)
        mwh = sum(float(r[1]) for r in rows) * 0.25 / (1000 if col == "output_kw" else 1)
        gen[pid], cf[pid] = round(mwh, 3), round(100 * mwh / (mw * 8784), 4)
    readme(out, "Plant output, calendar year 2024", [
        "<plant>_15min.csv: average output over each 15-minute interval (interval-beginning, UTC). Files come "
        "from different SCADA historians, so check each file's column name for its unit.",
        "Nameplate: WIND-1 100 MW, SOLAR-1 50 MWac, PEAKER-1 200 MW.",
    ])
    return {"generation_mwh_by_plant": gen, "capacity_factor_pct_by_plant": cf}
