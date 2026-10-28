"""Oil & gas planted-truth generators: decline curves, BOE, well identity, ESP failure prediction."""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from pathlib import Path

from ._common import UTC, fmt_utc, readme, rng_for, write_csv

DMIN = 0.10          # terminal nominal decline, 1/yr, stated in the task
ECON_LIMIT = 5.0     # bbl/d
LIFE_MONTHS = 360    # 30 years from first production


# --- p10: modified hyperbolic EUR -------------------------------------------------------------------------------------

def mh_rate(t: float, qi: float, di: float, b: float, dmin: float | None) -> float:
    """Arps hyperbolic rate (bbl/d) at producing time t (yr); switches to exponential at dmin if given."""
    if dmin is not None:
        t_sw = (di / dmin - 1) / (b * di)
        if t > t_sw:
            q_sw = qi * (1 + b * di * t_sw) ** (-1 / b)
            return q_sw * math.exp(-dmin * (t - t_sw))
    return qi * (1 + b * di * t) ** (-1 / b)


def forecast_volume(params: tuple, t0: float, days: int, dmin: float | None) -> float:
    """Daily integration from producing time t0 (yr) for `days`, stopping at the economic limit."""
    total = 0.0
    for k in range(days):
        q = mh_rate(t0 + (k + 0.5) / 365.25, *params, dmin)
        if q < ECON_LIMIT:
            break
        total += q
    return total


def _p10_history(rng, params: tuple, first: datetime, shut: set[int], partial: dict[int, int]) -> tuple:
    rows, t, month = [], 0.0, first
    for m in range(48):
        nxt = datetime(month.year + (month.month == 12), month.month % 12 + 1, 1)
        days_on = 0 if m in shut else partial.get(m, (nxt - month).days)
        vol = sum(mh_rate(t + (k + 0.5) / 365.25, *params, DMIN) for k in range(days_on))
        t += days_on / 365.25
        oil = int(round(vol * max(0.8, rng.gauss(1.0, 0.05)))) if days_on else 0
        rows.append([month.strftime("%Y-%m"), days_on, oil, int(oil * rng.uniform(1.8, 2.4))])
        month = nxt
    return rows, t


def p10_dca_eur(out: Path, seed: int) -> dict:
    rng = rng_for("p10", seed)
    rows, eur, eur_unbounded = [], {}, {}
    for w in range(1, 7):
        well = f"EB-{w:02d}H"
        params = (rng.uniform(600, 1200), rng.uniform(2.2, 3.0), rng.uniform(1.5, 1.8))
        first = datetime(2020 + (w > 3), rng.randint(1, 6), 1)
        shut = {rng.randint(10, 30), rng.randint(31, 44)} if w in (2, 5) else set()
        partial = {rng.randint(5, 40): 11} if w == 3 else {}
        hist, t_end = _p10_history(rng, params, first, shut, partial)
        rows += [[well, *r] for r in hist]
        days = int((LIFE_MONTHS - 48) * 30.4375)
        cum = sum(r[2] for r in hist)
        eur[well] = (cum + forecast_volume(params, t_end, days, DMIN)) / 1000
        eur_unbounded[well] = (cum + forecast_volume(params, t_end, days, None)) / 1000
    write_csv(out / "monthly_production.csv", ["well_id", "month", "days_on", "oil_bbl", "gas_mcf"], rows)
    readme(out, "Monthly production, six horizontal oil wells", [
        "monthly_production.csv: lease-allocated monthly volumes per well; days_on = producing days in the month.",
        "Months with days_on = 0 are shut-ins (workover or offset frac protection).",
    ])
    return {"eur_total_mbbl": round(sum(eur.values()), 3),
            "eur_by_well_mbbl": {k: round(v, 3) for k, v in eur.items()},
            "_pitfall": {"eur_total_unbounded_mbbl": round(sum(eur_unbounded.values()), 3)}}


# --- p11: BOE across operators that report gas in different units ------------------------------------------------------

def p11_boe(out: Path, seed: int) -> dict:
    rng = rng_for("p11", seed)
    a_rows, b_rows, oil, ngl, gas_mcf = [], [], 0.0, 0.0, 0.0
    for lease in range(1, 11):
        for m in range(1, 13):
            o, n, g = rng.randint(2_000, 15_000), rng.randint(300, 3_000), rng.randint(8_000, 60_000)
            if lease <= 6:
                a_rows.append([f"A-{lease:03d}", f"2024-{m:02d}", o, n, g])
                gas_mcf += g
            else:
                mmcf = round(g / 1000, 3)
                b_rows.append([f"B-{lease:03d}", f"2024-{m:02d}", o, n, f"{mmcf:.3f}"])
                gas_mcf += mmcf * 1000
            oil, ngl = oil + o, ngl + n
    write_csv(out / "operator_a.csv", ["lease_id", "month", "oil_bbl", "ngl_bbl", "gas_mcf"], a_rows)
    write_csv(out / "operator_b.csv", ["lease_id", "month", "oil_bbl", "ngl_bbl", "gas_mmcf"], b_rows)
    readme(out, "Non-operated working-interest statements, 2024 (8/8ths volumes)", [
        "operator_a.csv: monthly volumes; gas in Mcf (thousand cubic feet).",
        "operator_b.csv: monthly volumes; gas in MMcf (million cubic feet).",
    ])
    gas_boe = gas_mcf / 6
    total = oil + ngl + gas_boe
    return {"total_mboe": round(total / 1000, 4), "gas_share_pct": round(100 * gas_boe / total, 4),
            "_pitfall": {"total_mboe_mmcf_as_mcf": round((oil + ngl + sum(
                float(r[4]) for r in b_rows) / 6 + sum(r[4] for r in a_rows) / 6) / 1000, 4)}}


# --- p15: API well numbers across two systems ------------------------------------------------------------------------

def _p15_wells(rng) -> list[tuple[str, str, str, int]]:
    """(state code, county code, 5-digit unique well id, number of wellbores)."""
    wells, seen = [], set()
    for state, n in (("42", 80), ("05", 25), ("30", 15)):
        while sum(1 for w in wells if w[0] == state) < n:
            key = (state, f"{rng.randint(1, 499):03d}", f"{rng.randint(10_000, 99_999)}")
            if key not in seen:
                seen.add(key)
                wells.append((*key, rng.choice([1, 1, 1, 1, 2, 2, 3])))
    return wells


def _p15_messy(rng, api10: str) -> str:
    s, c, w = api10[:2], api10[2:5], api10[5:]
    if s == "05" and rng.random() < 0.6:
        return str(int(api10))  # leading zero lost when the column was read as a number
    style = rng.randint(0, 3)
    return [f"{s}-{c}-{w}", api10, api10 + "0000", f"{s}{c}{w}-00"][style]


def p15_well_identity(out: Path, seed: int) -> dict:
    rng = rng_for("p15", seed)
    wells = _p15_wells(rng)
    b_rows = [[f"{s}{c}{w}{st:02d}00", f"WB-{i:04d}-{st:02d}", rng.choice(["DRILLED", "COMPLETED"])]
              for i, (s, c, w, n) in enumerate(wells) for st in range(n)]
    a_rows, unmatched, a_wells = [], [], set()
    producing = rng.sample(wells, 95)
    for k, (s, c, w, _) in enumerate(producing * 2):
        if rng.random() < 0.5 and k >= len(producing):
            continue
        rid = f"PA-{len(a_rows) + 1:05d}"
        a_rows.append([rid, _p15_messy(rng, f"{s}{c}{w}"), f"Lease {rng.randint(1, 60)}"])
        a_wells.add(f"{s}{c}{w}")
    for _ in range(6):
        api10 = f"42{rng.randint(500, 507):03d}{rng.randint(10_000, 99_999)}"
        rid = f"PA-{len(a_rows) + 1:05d}"
        a_rows.append([rid, f"{api10[:2]}-{api10[2:5]}-{api10[5:]}", "Lease 99"])
        unmatched.append(rid)
        a_wells.add(api10)
    write_csv(out / "drilling_wellbores.csv", ["api14", "wellbore_name", "status"], b_rows)
    write_csv(out / "production_accounting.csv", ["record_id", "api_number", "lease_name"], a_rows)
    readme(out, "Well master extracts from two systems", [
        "drilling_wellbores.csv: one row per wellbore from the drilling system, keyed by 14-digit API number.",
        "production_accounting.csv: completion records from production accounting; api_number was keyed in by "
        "hand over many years and exported through a spreadsheet.",
    ])
    return {"drilling_unique_wells": len(wells), "drilling_unique_wellbores": len(b_rows),
            "production_unique_wells": len(a_wells), "unmatched_production_record_ids": sorted(unmatched)}


# --- p16: ESP failure prediction with a tag rename and a frozen sensor -----------------------------------------------

def _p16_value(rng, tag: str, ramp: float, day: float) -> float:
    base = {"INTAKE_PSI": 850.0, "MTR_TEMP_F": 180.0, "MOTOR_AMPS": 42.0, "VIB_IPS": 0.15}[tag]
    effect = {"INTAKE_PSI": -60 * ramp, "MTR_TEMP_F": 26 * ramp, "MOTOR_AMPS": 5 * ramp, "VIB_IPS": 0.22 * ramp}[tag]
    noise = {"INTAKE_PSI": 8.0, "MTR_TEMP_F": 1.5, "MOTOR_AMPS": 0.6, "VIB_IPS": 0.01}[tag]
    seasonal = 1.5 * math.sin(day / 5) if tag == "MTR_TEMP_F" else 0.0
    return base + effect + seasonal + rng.gauss(0, noise)


def _p16_ramp(day: float, onset: float | None, length: float = 9.0) -> float:
    if onset is None or day < onset:
        return 0.0
    return min(1.5, (day - onset) / length)


def _p16_plan(rng, pumps: list[str]) -> tuple[dict, dict, list[str]]:
    history = {p: rng.uniform(30, 85) for p in rng.sample(pumps, 6)}
    candidates = [p for p in pumps if p not in ("P07", "P12")]
    future = {p: rng.uniform(97, 100) for p in rng.sample(candidates, 4)}
    return history, future, sorted(future)


def _p16_rows(rng, pump: str, history: dict, future: dict, start: datetime) -> list[list]:
    rows, last_val = [], {}
    for step in range(106 * 12):
        day = step / 12
        fail = history.get(pump)
        onset = (fail - 9) if fail is not None and day < fail else future.get(pump)
        ramp = _p16_ramp(day, onset)
        ts = fmt_utc(start + timedelta(hours=2 * step))
        for tag in ("INTAKE_PSI", "MTR_TEMP_F", "MOTOR_AMPS", "VIB_IPS"):
            value = _p16_value(rng, tag, ramp, day)
            name = tag
            if pump == "P07" and tag == "MTR_TEMP_F" and day >= 95:
                name, value = "MOTOR_TEMP_C", (value - 32) * 5 / 9
            if pump == "P12" and day >= 100:
                value = last_val.setdefault(tag, value)
            rows.append([ts, pump, name, f"{value:.3f}"])
    return rows


def p16_esp_failures(out: Path, seed: int) -> dict:
    rng = rng_for("p16", seed)
    pumps = [f"P{n:02d}" for n in range(1, 31)]
    history, future, at_risk = _p16_plan(rng, pumps)
    start = datetime(2024, 1, 1, tzinfo=UTC)
    rows = [r for p in pumps for r in _p16_rows(rng, p, history, future, start)]
    write_csv(out / "esp_sensors.csv", ["timestamp_utc", "pump_id", "tag", "value"], rows)
    write_csv(out / "failure_history.csv", ["pump_id", "failure_timestamp_utc", "failure_mode"],
              [[p, fmt_utc(start + timedelta(days=d)), "MOTOR_BURN"] for p, d in sorted(history.items())])
    readme(out, "Electric submersible pump (ESP) historian extract", [
        "esp_sensors.csv: 2-hourly historian samples, long format (timestamp, pump, tag, value), 2024-01-01 to "
        "2024-04-16. Tags: INTAKE_PSI, MTR_TEMP_F (deg F), MOTOR_AMPS, VIB_IPS (in/s).",
        "failure_history.csv: past failures. Each failed pump was replaced the same day.",
    ])
    return {"at_risk_pumps": at_risk, "_pitfall": {"tag_renamed_pump": "P07", "frozen_sensor_pump": "P12"}}
