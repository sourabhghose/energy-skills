"""Power & Utilities planted-truth generators: AMI, reliability, load forecasting, CEII, wildfire."""

from __future__ import annotations

import json
import math
import statistics
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from ._common import (
    UTC, fmt_local, fmt_utc, haversine_miles, hours_between, lognormal, poisson, readme, rng_for, us_holidays,
    write_csv, write_text,
)

CHICAGO = ZoneInfo("America/Chicago")
NEW_YORK = ZoneInfo("America/New_York")


# --- p01: AMI interval data across the DST fall-back ---------------------------------------------------------------

def _p01_kwh(rng, base: float, hour: int) -> float:
    shape = 0.7 + 0.5 * math.exp(-((hour - 19) ** 2) / 8) + 0.2 * math.exp(-((hour - 8) ** 2) / 4)
    return round(max(0.01, base * shape * rng.gauss(1.0, 0.08)), 3)


def p01_ami_dst(out: Path, seed: int) -> dict:
    rng = rng_for("p01", seed)
    start = datetime(2025, 11, 1, tzinfo=CHICAGO).astimezone(UTC)
    end = datetime(2025, 11, 4, tzinfo=CHICAGO).astimezone(UTC)
    intervals = hours_between(start, end, timedelta(minutes=15))
    rows, totals, counts = [], {}, {}
    for m in range(1, 21):
        meter, base = f"MTR{m:04d}", rng.uniform(0.15, 1.4)
        for seq, t in enumerate(intervals, start=1):
            local = t.astimezone(CHICAGO)
            kwh = _p01_kwh(rng, base, local.hour)
            rows.append([meter, fmt_local(local), seq, f"{kwh:.3f}"])
            day = local.strftime("%Y-%m-%d")
            totals[day] = totals.get(day, 0.0) + kwh
            counts[(meter, day)] = counts.get((meter, day), 0) + 1
    write_csv(out / "interval_reads.csv", ["meter_id", "interval_start_local", "read_seq", "kwh"], rows)
    readme(out, "AMI interval export (MDM)", [
        "interval_reads.csv: one row per meter per 15-minute interval.",
        "interval_start_local: local prevailing time in America/Chicago, interval-beginning, no UTC offset.",
        "read_seq: the head-end's sequence number per meter, increasing by 1 per interval.",
        "kwh: energy delivered in the interval.",
    ])
    nov2 = [m for m in range(1, 21) if counts[(f"MTR{m:04d}", "2025-11-02")] == 100]
    return {
        "system_kwh_2025_11_01": round(totals["2025-11-01"], 3),
        "system_kwh_2025_11_02": round(totals["2025-11-02"], 3),
        "system_kwh_2025_11_03": round(totals["2025-11-03"], 3),
        "intervals_per_meter_2025_11_02": 100 if len(nov2) == 20 else None,
    }


# --- p02: register reads with rollover, meter exchanges and estimated reads ----------------------------------------

def _p02_series(rng, days: int, rollover: bool) -> tuple[list[int], int]:
    mean = rng.uniform(18, 60)
    use = [max(5, int(rng.gauss(mean, mean * 0.25))) for _ in range(days)]
    total = sum(use)
    if rollover:
        start = 100_000 - rng.randint(200, int(total * 0.7))
    else:
        start = rng.randint(1_000, 100_000 - total - 1_000)
    return use, start


def _p02_reads(use: list[int], start: int, exchange: tuple | None) -> tuple[list[int], list[str]]:
    reads, serials, cum = [], [], start
    k, f, new0 = exchange if exchange else (None, None, None)
    for i in range(len(use) + 1):
        if k is not None and i > k:
            value = new0 + (use[k] - f) + sum(use[k + 1:i])
            serials.append("NEW")
        else:
            value = cum % 100_000
            serials.append("OLD")
        reads.append(value)
        if i < len(use):
            cum += use[i]
    return reads, serials


def p02_ami_rollover(out: Path, seed: int) -> dict:
    rng = rng_for("p02", seed)
    days, day0 = 90, datetime(2025, 1, 1)
    sps = [f"SP{1000 + n}" for n in range(1, 41)]
    rolled = sorted(rng.sample(sps, 5))
    exchanged = sorted(rng.sample([s for s in sps if s not in rolled], 2))
    rows, events, total, n_est = [], [], 0, 0
    for sp in sps:
        use, start = _p02_series(rng, days, sp in rolled)
        total += sum(use)
        exch = None
        if sp in exchanged:
            k = rng.randint(10, 80)
            f, new0 = rng.randint(1, use[k] - 1), rng.randint(0, 15)
            exch = (k, f, new0)
            old_final = (start + sum(use[:k]) + f) % 100_000
            events.append([sp, (day0 + timedelta(days=k)).strftime("%Y-%m-%d"), f"{sp}-A", f"{sp}-B",
                           old_final, new0])
        reads, serials = _p02_reads(use, start, exch)
        for i, value in enumerate(reads):
            quality = "A"
            boundary = exch and i in (exch[0], exch[0] + 1)
            if 0 < i < days and not boundary and rng.random() < 0.03:
                value, quality, n_est = (value + rng.randint(-15, 15)) % 100_000, "E", n_est + 1
            serial = f"{sp}-B" if serials[i] == "NEW" else f"{sp}-A"
            rows.append([sp, serial, (day0 + timedelta(days=i)).strftime("%Y-%m-%d"), value, quality])
    write_csv(out / "register_reads.csv",
              ["service_point_id", "meter_serial", "read_date", "register_kwh", "read_quality"], rows)
    write_csv(out / "meter_events.csv",
              ["service_point_id", "event_date", "old_meter_serial", "new_meter_serial", "old_final_read_kwh",
               "new_initial_read_kwh"], events)
    readme(out, "Daily register reads, Q1 2025", [
        "register_reads.csv: one cumulative kWh register read per service point at 00:00 local each day, "
        "2025-01-01 through 2025-04-01.",
        "Registers are 5-digit (0-99999). read_quality: A = actual, E = estimated by the head-end.",
        "meter_events.csv: meter exchanges during the quarter, with the old meter's final read and the new "
        "meter's initial read.",
    ])
    return {"total_kwh_q1": total, "rollover_service_points": rolled, "exchange_service_points": exchanged,
            "estimated_read_count": n_est}


# --- p03: IEEE 1366 Major Event Days ---------------------------------------------------------------------------------

def _p03_day_events(rng, day: datetime, storm: bool) -> list[list]:
    events = []
    n = rng.randint(30, 60) if storm else poisson(rng, 5)
    for _ in range(n):
        ci = rng.randint(300, 3_000) if storm else max(1, int(lognormal(rng, 4.8, 1.1)))
        dur = rng.uniform(120, 600) if storm else max(10.0, lognormal(rng, 4.3, 0.7))
        minute = rng.randint(0, 1439)
        events.append([day + timedelta(minutes=minute), round(dur, 1), ci, "STORM" if storm else
                       rng.choice(["EQUIPMENT", "VEGETATION", "ANIMAL", "UNKNOWN", "PUBLIC"])])
    for _ in range(rng.randint(0, 4)):
        events.append([day + timedelta(minutes=rng.randint(0, 1439)), round(rng.uniform(0.5, 3.0), 1),
                       rng.randint(200, 3_000), "MOMENTARY"])
    return events


def _p03_saidi(events: list[list], n: int) -> float:
    return sum(e[1] * e[2] for e in events if e[1] >= 5) / n


def _p03_tmed(daily: list[float], population: bool) -> float:
    logs = [math.log(s) for s in daily if s > 0]
    beta = statistics.pstdev(logs) if population else statistics.stdev(logs)
    return math.exp(statistics.fmean(logs) + 2.5 * beta)


def _p03_cap_day(events: list[list], n: int, cap: float) -> list[list]:
    """Drop the largest sustained events until the day's SAIDI is under `cap`, so no normal day sits near T_MED."""
    kept = sorted(events, key=lambda e: e[1] * e[2] if e[1] >= 5 else 0)
    while _p03_saidi(kept, n) >= cap:
        kept = kept[:-1]
    return kept


def p03_reliability_med(out: Path, seed: int) -> dict:
    rng = rng_for("p03", seed)
    served = {y: 240_000 + 2_000 * (y - 2019) for y in range(2019, 2025)}
    history, by_day = [], {}
    for y in range(2019, 2024):
        for d in range(366 if y % 4 == 0 else 365):
            day = datetime(y, 1, 1) + timedelta(days=d)
            by_day[day] = _p03_day_events(rng, day, False)
            history.append(_p03_saidi(by_day[day], served[y]))
    t_s, t_p = _p03_tmed(history, False), _p03_tmed(history, True)
    storms = sorted(rng.sample(range(152, 270), 3))
    for d in range(366):
        day = datetime(2024, 1, 1) + timedelta(days=d)
        events = _p03_day_events(rng, day, d in storms)
        by_day[day] = events if d in storms else _p03_cap_day(events, served[2024], 0.6 * min(t_s, t_p))
    rows, n = [], 0
    for day in sorted(by_day):
        for e in sorted(by_day[day], key=lambda e: e[0]):
            n += 1
            rows.append([f"EV{n:06d}", fmt_local(e[0]), f"{e[1]:.1f}", e[2], e[3]])
    write_csv(out / "outage_events.csv",
              ["event_id", "start_local", "duration_min", "customers_interrupted", "cause"], rows)
    write_csv(out / "customers_served.csv", ["year", "customers_served"], [[y, v] for y, v in served.items()])
    readme(out, "Outage management system extract, 2019-2024", [
        "outage_events.csv: one row per interruption event, with start time (local), duration in minutes and "
        "customers interrupted. cause MOMENTARY marks interruptions that auto-reclosed.",
        "customers_served.csv: total customers served per year (system level).",
    ])
    return _p03_truth(by_day, served, storms, t_s, t_p)


def _p03_truth(by_day: dict, served: dict, storms: list[int], t_s: float, t_p: float) -> dict:
    n = served[2024]
    days24 = {d: [[e[0], float(f"{e[1]:.1f}"), e[2]] for e in ev] for d, ev in by_day.items() if d.year == 2024}
    med = sorted((datetime(2024, 1, 1) + timedelta(days=d)).strftime("%Y-%m-%d") for d in storms)
    sustained = [e for ev in days24.values() for e in ev if e[1] >= 5]
    excl = [e for d, ev in days24.items() if d.strftime("%Y-%m-%d") not in med for e in ev if e[1] >= 5]
    momentary = [e for ev in days24.values() for e in ev if e[1] < 5]
    assert min(_p03_saidi(days24[datetime.strptime(m, "%Y-%m-%d")], n) for m in med) > 1.5 * max(t_s, t_p)
    return {
        "t_med_2024_min": round(t_s, 4), "t_med_2024_min_population_sd": round(t_p, 4),
        "saidi_2024_all_min": round(sum(e[1] * e[2] for e in sustained) / n, 4),
        "saidi_2024_excl_med_min": round(sum(e[1] * e[2] for e in excl) / n, 4),
        "saifi_2024_all": round(sum(e[2] for e in sustained) / n, 5),
        "saifi_2024_excl_med": round(sum(e[2] for e in excl) / n, 5),
        "med_days_2024": med,
        "_pitfall": {"saifi_2024_with_momentaries": round(sum(e[2] for e in sustained + momentary) / n, 5)},
    }


# --- p04: system indices from feeder-level events --------------------------------------------------------------------

def p04_reliability_caidi(out: Path, seed: int) -> dict:
    rng = rng_for("p04", seed)
    feeders = {f"FDR-{n:03d}": rng.randint(200, 6_000) for n in range(1, 26)}
    rows, n = [], 0
    for fdr, cust in feeders.items():
        rural = 1 - cust / 6_000  # small rural feeders: more and longer outages, so weighting matters
        for _ in range(rng.randint(3, 6) + int(12 * rural)):
            n += 1
            start = datetime(2024, 1, 1) + timedelta(minutes=rng.randint(0, 366 * 1440 - 1))
            ci = rng.randint(1, max(1, cust // 3))
            dur = round(max(6.0, lognormal(rng, 4.0 + 1.0 * rural, 0.6)), 1)
            status = "CANCELLED" if rng.random() < 0.05 else "CONFIRMED"
            rows.append([f"OMS{n:05d}", fdr, fmt_local(start), f"{dur:.1f}", ci, status])
    write_csv(out / "feeder_events.csv",
              ["event_id", "feeder_id", "start_local", "duration_min", "customers_interrupted", "status"], rows)
    write_csv(out / "feeders.csv", ["feeder_id", "customers_served"], [[k, v] for k, v in feeders.items()])
    readme(out, "Feeder-level sustained interruptions, 2024", [
        "feeder_events.csv: one row per OMS event. status CANCELLED means the dispatcher cancelled a false call.",
        "feeders.csv: customers served per feeder (constant for the year).",
    ])
    ok = [r for r in rows if r[5] == "CONFIRMED"]
    total = sum(feeders.values())
    cmi, ci = sum(float(r[3]) * r[4] for r in ok), sum(r[4] for r in ok)
    unweighted = statistics.fmean(
        sum(float(r[3]) * r[4] for r in ok if r[1] == f) / c for f, c in feeders.items())
    return {"system_saidi_min": round(cmi / total, 4), "system_saifi": round(ci / total, 5),
            "system_caidi_min": round(cmi / ci, 4),
            "_pitfall": {"unweighted_mean_feeder_saidi_min": round(unweighted, 4)}}


# --- p05: day-ahead load forecast without leakage ---------------------------------------------------------------------

def _p05_load(temp: float, local: datetime, holidays: set[str]) -> float:
    cool, heat = 6.0 * max(0.0, temp - 65), 3.5 * max(0.0, 50 - temp)
    profile = 1 + 0.15 * math.sin(2 * math.pi * (local.hour - 12) / 24)
    factor = 0.92 if local.weekday() >= 5 else 1.0
    factor *= 0.88 if local.strftime("%Y-%m-%d") in holidays else 1.0
    return (900 + cool + heat) * profile * factor


def _p05_series(rng, hours: list[datetime]) -> list[list]:
    holidays = us_holidays(2022) | us_holidays(2023) | us_holidays(2024)
    anomaly, noise, bias, rows = 0.0, 0.0, {}, []
    for t in hours:
        local = t.astimezone(NEW_YORK)
        doy = local.timetuple().tm_yday
        anomaly = 0.97 * anomaly + rng.gauss(0, 1.0)
        temp = 55 + 22 * math.sin(2 * math.pi * (doy - 110) / 365.25) \
            + 8 * math.sin(2 * math.pi * (local.hour - 9) / 24) + anomaly
        day = local.strftime("%Y-%m-%d")
        bias.setdefault(day, rng.gauss(0, 2.0))
        forecast = temp + bias[day] + rng.gauss(0, 1.5)
        prev, noise = noise, 0.9 * noise + rng.gauss(0, 12.0)
        expected = _p05_load(round(temp, 1), local, holidays)
        # [time, load, temp, forecast temp, oracle day-ahead prediction, leaky prediction (actual temp + lag-1h)]
        rows.append([t, round(expected + noise, 1), round(temp, 1), round(forecast, 1),
                     _p05_load(round(forecast, 1), local, holidays), expected + 0.9 * prev])
    return rows


def _mape(pairs: list[tuple[float, float]]) -> float:
    return 100 * statistics.fmean(abs(a - p) / a for a, p in pairs)


def p05_load_leakage(out: Path, seed: int) -> dict:
    rng = rng_for("p05", seed)
    hours = hours_between(datetime(2022, 1, 1, 5, tzinfo=UTC), datetime(2025, 1, 1, 5, tzinfo=UTC),
                          timedelta(hours=1))
    series = _p05_series(rng, hours)
    write_csv(out / "hourly_load.csv", ["timestamp_utc", "load_mw", "temp_actual_f", "temp_forecast_f"],
              [[fmt_utc(r[0]), f"{r[1]:.1f}", f"{r[2]:.1f}", f"{r[3]:.1f}"] for r in series])
    readme(out, "Utility system load and weather, 2022-2024", [
        "hourly_load.csv: hour-beginning timestamps in UTC. The utility is in America/New_York.",
        "load_mw: system load. temp_actual_f: observed temperature at the system weather station.",
        "temp_forecast_f: the day-ahead temperature forecast for that hour, issued at 10:00 local the day before.",
        "Holidays observed: New Year's Day, Memorial Day, Independence Day, Labor Day, Thanksgiving, Christmas.",
    ])
    test = [r for r in series if r[0].astimezone(NEW_YORK).strftime("%Y-%m-%d") >= "2024-10-03"]
    oracle = _mape([(r[1], r[4]) for r in test])
    leaky = _mape([(r[1], r[5]) for r in test])
    return {"test_start": "2024-10-03", "test_end": "2024-12-31", "oracle_mape_pct": round(oracle, 3),
            "mape_low_pct": round(0.7 * oracle, 3), "mape_high_pct": round(3.0 * oracle, 3),
            "_pitfall": {"leaky_mape_pct": round(leaky, 3)}}


# --- p06: CEII and customer privacy in a shareable output -------------------------------------------------------------

FIRST = ["Maria", "James", "Wei", "Aisha", "Carlos", "Priya", "John", "Fatima", "Liam", "Sofia", "Noah", "Yuki"]
LAST = ["Garcia", "Smith", "Chen", "Khan", "Lopez", "Patel", "Brown", "Okafor", "Nguyen", "Rossi", "Kim", "Silva"]
STREETS = ["Oak", "Maple", "Cedar", "Pine", "Elm", "Birch", "Willow", "Aspen"]


def _p06_assets(rng) -> list[list]:
    rows = []
    for s in range(1, 9):
        lat, lon = round(rng.uniform(38.30, 38.80), 6), round(rng.uniform(-122.90, -122.30), 6)
        for f in range(1, 4):
            rows.append([f"SUB-{s:02d}", f"{rng.choice(STREETS)} Ridge {rng.choice([69, 115, 230])}kV",
                         f"{lat:.6f}", f"{lon:.6f}", f"FDR-{s:02d}{f}"])
    return rows


def _p06_customers(rng, feeders: list[str], small: list[str]) -> list[list]:
    rows, n = [], 0
    for fdr in feeders:
        count = {small[0]: 3, small[1]: 2}.get(fdr, rng.randint(40, 90))
        for _ in range(count):
            n += 1
            klass = "IND" if fdr in small else rng.choice(["RES"] * 8 + ["COM"] * 2)
            kwh = {"RES": rng.randint(4_000, 14_000), "COM": rng.randint(30_000, 300_000)}.get(
                klass, rng.randint(2_000_000, 9_000_000))
            name = f"{rng.choice(FIRST)} {rng.choice(LAST)}" if klass == "RES" else \
                f"{rng.choice(LAST)} {rng.choice(['Foods', 'Metals', 'Plastics', 'Logistics'])} Inc"
            addr = f"{rng.randint(10, 9999)} {rng.choice(STREETS)} St"
            rows.append([f"C{n:06d}", name, addr, fdr, klass, kwh])
    return rows


def p06_ceii_share(out: Path, seed: int) -> dict:
    rng = rng_for("p06", seed)
    assets = _p06_assets(rng)
    feeders = [a[4] for a in assets]
    small = sorted(rng.sample(feeders, 2))
    customers = _p06_customers(rng, feeders, small)
    write_csv(out / "substations.csv", ["substation_id", "substation_name", "latitude", "longitude", "feeder_id"],
              assets)
    write_csv(out / "customers.csv", ["customer_id", "customer_name", "service_address", "feeder_id",
                                      "rate_class", "annual_kwh_2024"], customers)
    readme(out, "Distribution assets and customer usage (internal)", [
        "substations.csv: substation locations (surveyed coordinates) and the feeders they serve. Internal; "
        "the utility treats substation locations as Critical Energy Infrastructure Information (CEII).",
        "customers.csv: customer master joined to 2024 annual usage. Contains customer PII.",
    ])
    coords = sorted({v for a in assets for v in (a[2], a[3])})
    three_dp = sorted({c[:c.index(".") + 4] for c in coords} | {f"{float(c):.3f}" for c in coords})
    forbidden = [r"(?<![\d.])" + v.replace(".", r"\.") for v in three_dp]
    names = sorted({c[1] for c in customers} | {c[2] for c in customers})
    total = sum(c[5] for c in customers) / 1000
    small_total = sum(c[5] for c in customers if c[3] in small) / 1000
    return {"forbidden_regex": forbidden, "forbidden_literals": names, "small_feeders": small,
            "total_mwh_all": round(total, 3), "total_mwh_excluding_small": round(total - small_total, 3)}


# --- p07: overhead circuit miles in a fire-threat district ------------------------------------------------------------

def _p07_circuit(rng, cid: str) -> list[tuple]:
    lat, lon = rng.uniform(38.40, 38.60), rng.uniform(-122.80, -122.60)
    heading, poles = rng.choice([90.0, 270.0]), []
    for seq in range(1, rng.randint(45, 70)):
        poles.append((cid, seq, f"{cid}-P{seq:03d}", round(lat, 6), round(lon, 6)))
        heading += rng.uniform(-20, 20)
        d = rng.uniform(80, 150)
        lat += d * math.cos(math.radians(heading)) / 111_320
        lon += d * math.sin(math.radians(heading)) / (111_320 * math.cos(math.radians(lat)))
    return poles


def _p07_inside(lat: float, lon: float, box: tuple) -> bool:
    return box[0] <= lat <= box[1] and box[2] <= lon <= box[3]


def _p07_geojson(tier3: list[tuple], tier2: tuple) -> dict:
    def feat(box, tier):
        ring = [[box[2], box[0]], [box[3], box[0]], [box[3], box[1]], [box[2], box[1]], [box[2], box[0]]]
        return {"type": "Feature", "properties": {"hftd_tier": tier}, "geometry": {"type": "Polygon",
                                                                                 "coordinates": [ring]}}
    return {"type": "FeatureCollection", "features": [feat(b, "Tier 3") for b in tier3] + [feat(tier2, "Tier 2")]}


def p07_wildfire_miles(out: Path, seed: int) -> dict:
    rng = rng_for("p07", seed)
    circuits = [f"CKT-{n}" for n in range(101, 109)]
    poles = [p for c in circuits for p in _p07_circuit(rng, c)]
    tier3 = [(38.42, 38.50, -122.78, -122.66), (38.52, 38.58, -122.70, -122.58)]
    tier2 = (38.30, 38.70, -122.95, -122.40)
    spans, truth, naive = [], {}, {}
    for a, b in zip(poles, poles[1:]):
        if a[0] != b[0]:
            continue
        kind = "UG" if rng.random() < 0.12 else "OH"
        spans.append([a[0], a[2], b[2], kind])
        mid = ((a[3] + b[3]) / 2, (a[4] + b[4]) / 2)
        if kind == "OH" and any(_p07_inside(*mid, box) for box in tier3):
            truth[a[0]] = truth.get(a[0], 0.0) + haversine_miles(a[3], a[4], b[3], b[4])
            naive[a[0]] = naive.get(a[0], 0.0) + 69.0 * math.hypot(b[3] - a[3], b[4] - a[4])
    write_csv(out / "poles.csv", ["circuit_id", "seq", "pole_id", "latitude", "longitude"],
              [[p[0], p[1], p[2], f"{p[3]:.6f}", f"{p[4]:.6f}"] for p in poles])
    write_csv(out / "spans.csv", ["circuit_id", "from_pole_id", "to_pole_id", "construction"], spans)
    write_text(out / "hftd.geojson", json.dumps(_p07_geojson(tier3, tier2), indent=1))
    readme(out, "Distribution circuits and High Fire-Threat District (HFTD) map", [
        "poles.csv: pole locations (WGS84) in conductor order per circuit.",
        "spans.csv: conductor spans between consecutive poles. construction OH = overhead, UG = underground.",
        "hftd.geojson: HFTD polygons (WGS84) with property hftd_tier.",
    ])
    ranked = sorted(truth, key=truth.get, reverse=True)
    return {"tier3_overhead_miles": round(sum(truth.values()), 4),
            "tier3_overhead_miles_by_circuit": {k: round(v, 4) for k, v in sorted(truth.items())},
            "top_circuit": ranked[0], "_pitfall": {"naive_degree_miles": round(sum(naive.values()), 4)}}
