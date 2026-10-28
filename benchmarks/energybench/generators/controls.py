"""Control-task generators: energy-flavoured data work that no Energy Skill covers (the no-harm check)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

from ._common import readme, rng_for, write_csv, write_text

STATES = ["TX", "CA", "IA", "OK", "KS", "NY", "FL", "WA", "CO", "IL"]
FUELS = ["coal", "natural_gas", "nuclear", "hydro", "wind", "solar", "petroleum", "other"]


def c01_fuel_mix(out: Path, seed: int) -> dict:
    rng = rng_for("c01", seed)
    rows, share = [], {}
    for year in (2022, 2023):
        for st in STATES:
            gen = {f: rng.randint(100_000, 90_000_000) for f in FUELS}
            rows += [[st, year, f, v] for f, v in gen.items()]
            if year == 2023:
                share[st] = 100 * (gen["wind"] + gen["solar"]) / sum(gen.values())
    write_csv(out / "generation_by_fuel.csv", ["state", "year", "fuel", "net_generation_mwh"], rows)
    readme(out, "Net generation by state and fuel", ["generation_by_fuel.csv: annual net generation (MWh)."])
    return {"wind_solar_share_tx_2023_pct": round(share["TX"], 4), "top_wind_solar_state_2023": max(share,
                                                                                                    key=share.get)}


def c02_price_plot(out: Path, seed: int) -> dict:
    rng = rng_for("c02", seed)
    rows, avg = [], {}
    for st in STATES:
        base = rng.uniform(9, 30)
        vals = [round(base * rng.uniform(0.9, 1.15), 2) for _ in range(12)]
        rows += [[st, f"2023-{m + 1:02d}", f"{v:.2f}"] for m, v in enumerate(vals)]
        avg[st] = sum(vals) / 12
    write_csv(out / "retail_prices.csv", ["state", "month", "residential_cents_per_kwh"], rows)
    readme(out, "Average residential retail electricity price, 2023", ["retail_prices.csv: monthly, cents/kWh."])
    return {"highest_avg_price_state": max(avg, key=avg.get)}


def c03_ev_chargers(out: Path, seed: int) -> dict:
    rng = rng_for("c03", seed)
    cities = ["Austin", "Denver", "Fresno", "Tulsa", "Boise", "Omaha", "Reno", "Tampa", "Mesa", "Akron"]
    rows, dc = [], {c: 0 for c in cities}
    for k in range(1, 301):
        city, kind = rng.choice(cities), rng.choice(["J1772", "J1772", "CCS", "NACS", "CHAdeMO"])
        ports = rng.randint(1, 4)
        rows.append([f"ST{k:04d}", city, kind, ports])
        if kind in ("CCS", "NACS", "CHAdeMO"):
            dc[city] += ports
    write_csv(out / "stations.csv", ["station_id", "city", "connector_type", "ports"], rows)
    readme(out, "Public EV charging stations", [
        "stations.csv: one row per station and connector type. J1772 is Level 2; CCS, NACS and CHAdeMO are DC fast.",
    ])
    return {"cities_over_40_dc_fast_ports": sum(v > 40 for v in dc.values()), "top_dc_fast_city": max(dc, key=dc.get)}


def c04_tariff_bill(out: Path, seed: int) -> dict:
    rng = rng_for("c04", seed)
    tiers = [{"up_to_kwh": 500, "usd_per_kwh": round(rng.uniform(0.09, 0.11), 4)},
             {"up_to_kwh": 1000, "usd_per_kwh": round(rng.uniform(0.12, 0.14), 4)},
             {"up_to_kwh": None, "usd_per_kwh": round(rng.uniform(0.15, 0.18), 4)}]
    tariff = {"name": "Residential Tiered RS-1", "customer_charge_usd": 12.0, "sales_tax_rate": 0.05, "tiers": tiers}
    write_text(out / "tariff.json", json.dumps(tariff, indent=2))
    readme(out, "Residential tariff", ["tariff.json: monthly customer charge, inclining-block energy tiers, and a "
                                       "sales tax applied to the whole bill."])
    usage, energy, lower = 1250, 0.0, 0
    for t in tiers:
        upper = t["up_to_kwh"] or usage
        energy += max(0, min(usage, upper) - lower) * t["usd_per_kwh"]
        lower = upper
    return {"bill_usd": round((energy + 12.0) * 1.05, 2)}


def c05_press_mentions(out: Path, seed: int) -> dict:
    rng = rng_for("c05", seed)
    topics = ["hydrogen hub", "offshore wind", "carbon capture", "Hydrogen fuel cells", "battery storage",
              "grid modernization", "green hydrogen electrolyzer", "small modular reactors"]
    rows, counts = [], {}
    for k in range(1, 81):
        year = rng.choice([2022, 2023, 2024])
        picks = rng.sample(topics, 2)
        text = f"The company announced progress on {picks[0]} and {picks[1]} projects."
        rows.append([k, year, text])
        if "hydrogen" in text.lower():
            counts[str(year)] = counts.get(str(year), 0) + 1
    write_csv(out / "press_releases.csv", ["release_id", "year", "text"], rows)
    readme(out, "Corporate press releases", ["press_releases.csv: one short release per row."])
    return {"hydrogen_releases_by_year": dict(sorted(counts.items()))}


def c06_gasoline_yoy(out: Path, seed: int) -> dict:
    rng = rng_for("c06", seed)
    rows, by_year, price, day = [], {2023: [], 2024: []}, 3.4, datetime(2023, 1, 2)
    while day.year < 2025:
        price = round(max(2.5, price + rng.gauss(0, 0.05)), 3)
        rows.append([day.strftime("%Y-%m-%d"), f"{price:.3f}"])
        by_year[day.year].append(price)
        day += timedelta(days=7)
    write_csv(out / "gasoline_weekly.csv", ["week_of", "regular_usd_per_gal"], rows)
    readme(out, "US regular gasoline retail price, weekly", ["gasoline_weekly.csv: Monday of each week."])
    a23, a24 = (sum(v) / len(v) for v in (by_year[2023], by_year[2024]))
    return {"avg_2023_usd": round(a23, 4), "avg_2024_usd": round(a24, 4), "yoy_change_pct": round(100 * (a24 / a23 - 1), 4)}


def c07_trir(out: Path, seed: int) -> dict:
    rng = rng_for("c07", seed)
    contractors = ["Alpha Services", "Basin Crews", "Delta Wireline", "Eagle Construction", "Frontier Rigging"]
    hours = {c: rng.randint(80_000, 600_000) for c in contractors}
    incidents, rec = [], {c: 0 for c in contractors}
    for k in range(1, 61):
        c, recordable = rng.choice(contractors), rng.random() < 0.55
        incidents.append([f"INC-{k:03d}", c, f"2024-{rng.randint(1, 12):02d}-15", "Y" if recordable else "N"])
        rec[c] += recordable
    write_csv(out / "incidents.csv", ["incident_id", "contractor", "date", "osha_recordable"], incidents)
    write_csv(out / "hours_worked.csv", ["contractor", "hours_worked_2024"], [[c, h] for c, h in hours.items()])
    readme(out, "Contractor safety statistics, 2024", ["incidents.csv and hours_worked.csv."])
    rate = {c: rec[c] * 200_000 / hours[c] for c in contractors}
    return {"trir_overall": round(sum(rec.values()) * 200_000 / sum(hours.values()), 4),
            "highest_trir_contractor": max(rate, key=rate.get)}


def c08_refinery_dedupe(out: Path, seed: int) -> dict:
    rng = rng_for("c08", seed)
    names = ["Port Arthur", "Baytown", "Garyville", "Whiting", "Galveston Bay", "Lake Charles", "Pasadena", "Joliet"]
    rows, total = [], 0
    for name in names:
        cap = rng.randint(80, 600) * 1_000
        total += cap
        variants = [f"{name} Refinery", f"{name.upper()} REF.", f"{name} refinery ", f"Refinery - {name}"]
        for v in rng.sample(variants, rng.randint(1, 3)):
            rows.append([v, cap])
    rng.shuffle(rows)
    write_csv(out / "refineries.csv", ["refinery_name", "crude_capacity_bpd"], rows)
    readme(out, "Refinery list merged from three vendor files", ["refineries.csv: names as typed by each vendor."])
    return {"unique_refineries": len(names), "total_capacity_bpd": total}
