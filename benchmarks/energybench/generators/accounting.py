"""Emissions and energy-accounting planted-truth generators: Scope 2, Scope 1, methane, heat rate, gas units.

Emission factors in these synthetic datasets are written into the task data so the answer does not depend on
outside knowledge. eGRID-style and residual-mix rates are illustrative, not official values.
"""

from __future__ import annotations

from pathlib import Path

from ._common import LB_PER_TONNE, M3_TO_SCF, MMBTU_TO_GJ, readme, rng_for, write_csv

SUBREGIONS = {"RFCE": (650.0, 618.0, 790.0), "SRSO": (905.0, 880.0, 1010.0), "CAMX": (455.0, 430.0, 640.0),
              "ERCT": (840.0, 815.0, 905.0), "NWPP": (630.0, 600.0, 880.0)}  # eGRID2022, eGRID2023, residual mix


# --- p20: Scope 2 location- and market-based ------------------------------------------------------------------------

def p20_scope2(out: Path, seed: int) -> dict:
    rng = rng_for("p20", seed)
    sites = [[f"SITE-{k:02d}", rng.choice(sorted(SUBREGIONS)), rng.randint(500, 20_000)] for k in range(1, 11)]
    recs = {s[0]: int(s[2] * rng.uniform(0.3, 1.0)) for s in rng.sample(sites, 3) if s[0] != "SITE-07"}
    supplier = {"SITE-07": 150.0}
    write_csv(out / "sites.csv", ["site_id", "egrid_subregion", "electricity_mwh_2024"], sites)
    write_csv(out / "recs_retired.csv", ["site_id", "mwh", "vintage_year", "instrument"],
              [[k, v, 2024, "Bundled REC, Green-e certified"] for k, v in recs.items()])
    write_csv(out / "supplier_specific_rates.csv", ["site_id", "supplier", "co2e_lb_per_mwh", "year"],
              [[k, "Utility green tariff", v, 2024] for k, v in supplier.items()])
    factors = [[v, r, f"{vals[i]:.1f}"] for r, vals in sorted(SUBREGIONS.items())
               for i, v in enumerate(["eGRID2022", "eGRID2023"])]
    write_csv(out / "grid_location_factors.csv", ["edition", "egrid_subregion", "co2e_lb_per_mwh"], factors)
    write_csv(out / "residual_mix.csv", ["egrid_subregion", "co2e_lb_per_mwh", "year"],
              [[r, f"{v[2]:.1f}", 2024] for r, v in sorted(SUBREGIONS.items())])
    readme(out, "Purchased electricity for the 2024 GHG inventory", [
        "sites.csv: annual purchased electricity per site and its eGRID subregion.",
        "recs_retired.csv: energy attribute certificates retired on behalf of each site for 2024.",
        "supplier_specific_rates.csv: delivered emission rate disclosed by the site's supplier.",
        "grid_location_factors.csv: grid-average CO2e output rates by eGRID edition (illustrative values for this "
        "benchmark). The eGRID edition for 2024 data has not been published yet.",
        "residual_mix.csv: residual-mix CO2e rates (illustrative).",
    ])
    loc = {e: sum(s[2] * SUBREGIONS[s[1]][i] for s in sites) / LB_PER_TONNE
           for i, e in enumerate(["eGRID2022", "eGRID2023"])}
    market = 0.0
    for sid, region, mwh in sites:
        rest = mwh - recs.get(sid, 0)
        market += rest * supplier.get(sid, SUBREGIONS[region][2])
    return {"scope2_location_tco2e_egrid2023": round(loc["eGRID2023"], 3),
            "scope2_location_tco2e_egrid2022": round(loc["eGRID2022"], 3),
            "scope2_market_tco2e": round(market / LB_PER_TONNE, 3)}


# --- p21: Scope 1 stationary combustion with mixed units and GWP choice ----------------------------------------------

FUEL_FACTORS = {  # kg CO2, g CH4, g N2O per unit; EPA GHG Emission Factors Hub style
    "natural_gas": ("mmbtu", 53.06, 1.0, 0.10), "diesel": ("gal", 10.21, 0.41, 0.08),
    "propane": ("gal", 5.72, 0.27, 0.05),
}
GAS_TO_MMBTU = {"MMBtu": 1.0, "therm": 0.1, "Mcf": 1.026, "ccf": 0.1026}
GWP = {"AR5": (28.0, 265.0), "AR6": (29.8, 273.0)}


def _p21_lines(rng) -> list[list]:
    rows = []
    for k in range(1, 7):
        site = f"PLANT-{k}"
        for _ in range(rng.randint(2, 4)):
            unit = rng.choice(sorted(GAS_TO_MMBTU))
            rows.append([site, "natural_gas", rng.randint(1_000, 400_000), unit])
        rows.append([site, "diesel", rng.randint(500, 30_000), "gal"])
        if rng.random() < 0.5:
            rows.append([site, "propane", rng.randint(200, 8_000), "gal"])
    return rows


def p21_scope1(out: Path, seed: int) -> dict:
    rng = rng_for("p21", seed)
    rows = _p21_lines(rng)
    write_csv(out / "fuel_use_2024.csv", ["site_id", "fuel", "quantity", "unit"], rows)
    write_csv(out / "emission_factors.csv", ["fuel", "per_unit", "kg_co2", "g_ch4", "g_n2o"],
              [[f, *v] for f, v in FUEL_FACTORS.items()])
    write_csv(out / "conversions.csv", ["from_unit", "to_unit", "factor"],
              [[u, "mmbtu", v] for u, v in GAS_TO_MMBTU.items()])
    write_csv(out / "gwp.csv", ["assessment_report", "gas", "gwp_100yr"],
              [[ar, g, v[i]] for ar, v in GWP.items() for i, g in enumerate(["CH4", "N2O"])])
    readme(out, "Stationary combustion fuel use, 2024", [
        "fuel_use_2024.csv: invoiced fuel quantities. Natural gas arrives on bills in several units.",
        "emission_factors.csv: per-unit factors (EPA GHG Emission Factors Hub style; per MMBtu for gas, per gallon "
        "for liquid fuels). conversions.csv: natural gas unit to MMBtu (HHV).",
        "gwp.csv: 100-year global warming potentials from IPCC AR5 and AR6 (AR6 CH4 is the fossil value).",
    ])
    co2, ch4, n2o = 0.0, 0.0, 0.0
    for _, fuel, qty, unit in rows:
        base = qty * GAS_TO_MMBTU[unit] if fuel == "natural_gas" else qty
        _, kg_co2, g_ch4, g_n2o = FUEL_FACTORS[fuel]
        co2, ch4, n2o = co2 + base * kg_co2 / 1000, ch4 + base * g_ch4 / 1e6, n2o + base * g_n2o / 1e6
    total = {ar: co2 + ch4 * g[0] + n2o * g[1] for ar, g in GWP.items()}
    return {"co2_tonnes": round(co2, 4), "scope1_tco2e_ar5": round(total["AR5"], 4),
            "scope1_tco2e_ar6": round(total["AR6"], 4)}


# --- p22: methane from component counts -----------------------------------------------------------------------------

COMPONENT_EF = {"valve": 0.121, "connector": 0.017, "open_ended_line": 0.031, "pressure_relief_valve": 0.193,
                "pneumatic_high_bleed": 37.3, "pneumatic_intermittent": 13.5, "pneumatic_low_bleed": 1.39}
CH4_KG_PER_SCF = 0.0192


def p22_methane(out: Path, seed: int) -> dict:
    rng = rng_for("p22", seed)
    counts, sites = [], {}
    for k in range(1, 5):
        sid = f"PAD-{k}"
        sites[sid] = (round(rng.uniform(0.78, 0.93), 3), rng.choice([8_784, 8_784, 7_900, 6_500]))
        for comp in COMPONENT_EF:
            n = rng.randint(0, 12) if comp.startswith("pneumatic") else rng.randint(20, 900)
            counts.append([sid, comp, n])
    write_csv(out / "component_counts.csv", ["site_id", "component_type", "count"], counts)
    write_csv(out / "emission_factors.csv", ["component_type", "whole_gas_scf_per_hour_per_component"],
              [[c, v] for c, v in COMPONENT_EF.items()])
    write_csv(out / "site_operations.csv", ["site_id", "ch4_mole_fraction", "operating_hours_2024"],
              [[s, f"{v[0]:.3f}", v[1]] for s, v in sites.items()])
    readme(out, "Production pad equipment inventory for methane reporting, 2024", [
        "component_counts.csv: equipment leak and pneumatic device counts per pad.",
        "emission_factors.csv: population emission factors as whole-gas scf/hour/component (illustrative, in the "
        "style of 40 CFR 98 Subpart W Table W-1A).",
        "site_operations.csv: produced-gas CH4 mole fraction and hours in service.",
        "Use a CH4 density of 0.0192 kg/scf.",
    ])
    by_site = {s: 0.0 for s in sites}
    for sid, comp, n in counts:
        frac, hours = sites[sid]
        by_site[sid] += n * COMPONENT_EF[comp] * hours * frac * CH4_KG_PER_SCF / 1000
    total = sum(by_site.values())
    return {"ch4_tonnes_total": round(total, 4), "ch4_tonnes_by_site": {k: round(v, 4) for k, v in by_site.items()},
            "co2e_tonnes_gwp28": round(28 * total, 3)}


# --- p23: net heat rate and capacity factor -------------------------------------------------------------------------

def p23_heat_rate(out: Path, seed: int) -> dict:
    rng = rng_for("p23", seed)
    plants = {"CC-1": ("combined_cycle", 620.0, 6_900), "CC-2": ("combined_cycle", 480.0, 7_200),
              "ST-1": ("coal_steam", 350.0, 10_400), "CT-1": ("combustion_turbine", 180.0, 10_900),
              "WF-1": ("wind", 150.0, 0)}
    rows, acc = [], {p: [0.0, 0.0] for p in plants}
    for pid, (_, mw, hr) in plants.items():
        for m in range(1, 13):
            gross = round(mw * 730 * rng.uniform(0.15, 0.85), 1)
            aux = round(gross * (0.035 if hr else 0.005) * rng.uniform(0.8, 1.2), 1)
            fuel = round((gross - aux) * 1000 * hr * rng.uniform(0.98, 1.03) / 1e6, 1)
            rows.append([pid, f"2024-{m:02d}", f"{fuel:.1f}", f"{gross:.1f}", f"{aux:.1f}"])
            acc[pid] = [acc[pid][0] + fuel, acc[pid][1] + gross - aux]
    write_csv(out / "plants.csv", ["plant_id", "technology", "nameplate_mw"],
              [[p, v[0], v[1]] for p, v in plants.items()])
    write_csv(out / "monthly_operations.csv", ["plant_id", "month", "fuel_consumed_mmbtu", "gross_generation_mwh",
                                               "station_service_mwh"], rows)
    readme(out, "Generation fleet monthly operations, 2024", [
        "monthly_operations.csv: fuel burned (HHV MMBtu), gross generation at the generator terminals, and station "
        "service (auxiliary) load per plant-month.", "plants.csv: nameplate capacity.",
    ])
    thermal = [p for p, v in plants.items() if v[2]]
    return {
        "net_heat_rate_btu_per_kwh_by_plant": {p: round(acc[p][0] * 1e6 / (acc[p][1] * 1000), 3) for p in thermal},
        "fleet_net_heat_rate_btu_per_kwh": round(sum(acc[p][0] for p in thermal) * 1e3 / sum(acc[p][1] for p in thermal),
                                                 3),
        "net_capacity_factor_pct_by_plant": {p: round(100 * acc[p][1] / (plants[p][1] * 8784), 4) for p in plants},
    }


# --- p24: sales-gas volumes and energy across unit systems -----------------------------------------------------------

def p24_gas_units(out: Path, seed: int) -> dict:
    rng = rng_for("p24", seed)
    rows, mmbtu, scf = [], 0.0, 0.0
    for k in range(1, 13):
        country = "CA" if k > 8 else "US"
        unit = rng.choice(["e3m3", "10^3 m3"]) if country == "CA" else rng.choice(["Mcf", "MMcf", "Bcf"])
        vol = {"Mcf": rng.randint(50_000, 900_000), "MMcf": round(rng.uniform(50, 900), 3),
               "Bcf": round(rng.uniform(0.5, 4.0), 4)}.get(unit, rng.randint(2_000, 25_000))
        if country == "CA":
            hhv = round(rng.uniform(37.5, 39.5), 2)
            m3 = vol * 1000
            energy_gj, stream_scf = m3 * hhv / 1000, m3 * M3_TO_SCF
            mmbtu += energy_gj / MMBTU_TO_GJ
            rows.append([f"STR-{k:02d}", country, vol, unit, f"{hhv:.2f}", "MJ/m3"])
        else:
            hhv = rng.randint(1_020, 1_080)
            stream_scf = vol * {"Mcf": 1e3, "MMcf": 1e6, "Bcf": 1e9}[unit]
            mmbtu += stream_scf * hhv / 1e6
            rows.append([f"STR-{k:02d}", country, vol, unit, hhv, "Btu/scf"])
        scf += stream_scf
    write_csv(out / "sales_gas_2024.csv", ["stream_id", "country", "volume", "volume_unit", "heating_value",
                                           "heating_value_unit"], rows)
    readme(out, "Sales gas by stream, 2024", [
        "sales_gas_2024.csv: annual sales volume per stream with its heating value (HHV). US streams report at "
        "60 degF / 14.73 psia; Canadian streams at 15 degC / 101.325 kPa. Treat the base-condition difference as "
        "negligible for this summary.",
    ])
    return {"total_energy_mmbtu": round(mmbtu, 2), "total_energy_gj": round(mmbtu * MMBTU_TO_GJ, 2),
            "total_volume_bcf": round(scf / 1e9, 5)}
