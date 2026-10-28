"""Per-source emission calculators (screening level) with factor lineage on every record.

Each calculator takes one activity row (a dict) and returns a list of emission records.
`compute_emissions` dispatches over an activity DataFrame and collects row-level issues
instead of silently skipping rows.

Methods follow EPA's GHG Emission Factors Hub (combustion), 40 CFR 98 Subpart W
(flares, pneumatics, tanks; screening-level), GHG Protocol Scope 2 Guidance (dual
reporting) and GHG Protocol Scope 3 category 11 (use of sold products).
"""

from __future__ import annotations

import logging

import pandas as pd

from ghg_core import (DENSITY_KG_PER_SCF, KG_PER_LB, DecisionRequired, FactorProvenanceError, UnitError, lookup_factor,
                      mass_to_tonnes, normalize_unit, to_mmbtu, to_mwh)

log = logging.getLogger(__name__)

# Flare tiers per the 2024 Subpart W revision (effective RY2025): (destruction eff., combustion eff.)
FLARE_TIERS = {
    "tier1_de98": (0.98, 0.965),
    "tier2_de95": (0.95, 0.935),
    "tier3_de92": (0.92, 0.905),
    "legacy_ce98": (0.98, 0.98),  # pre-RY2025 Subpart W default; one efficiency for both
    "measured": (None, None),     # row must carry destruction_eff and combustion_eff
}
TANK_METHODS = ("measured_vent_volume", "flash_factor")
SOURCE_TYPES = ("stationary_combustion", "mobile_combustion", "flare", "pneumatic_device",
                "tank_vent", "vented_other", "fugitive_component", "process",
                "purchased_electricity", "sold_product")


def _record(row: dict, scope: int, category: str, gas: str, mass_t: float, method: str,
            factors: list, ogmp_level: int | None = None, scope2_method: str | None = None,
            note: str = "") -> dict:
    return {
        "row_id": row.get("row_id"), "facility_id": row["facility_id"], "period": row.get("period"),
        "scope": scope, "category": category, "source_type": row["source_type"], "gas": gas,
        "mass_t": mass_t, "method": method,
        "factor_ids": ";".join(f.factor_id for f in factors),
        "factor_sources": ";".join(sorted({f"{f.source} ({f.vintage})" for f in factors})),
        "factor_status": ";".join(sorted({f.status for f in factors})),
        "ogmp_level": ogmp_level if gas == "CH4" else None,
        "scope2_method": scope2_method, "note": note,
    }


def _ef_to_tonnes(energy_mmbtu: float, factor) -> float:
    per = factor.unit.split("/")[0]
    return mass_to_tonnes(energy_mmbtu * factor.value, per)


def stationary_combustion(row: dict, factors: pd.DataFrame, _d: dict) -> list[dict]:
    fuel = row["fuel_or_product"]
    mmbtu, hhv = to_mmbtu(float(row["quantity"]), row["unit"], factors, fuel)
    out = []
    for gas in ("CO2", "CH4", "N2O"):
        f = lookup_factor(factors, "stationary_combustion", fuel, gas)
        used = [f] + ([hhv] if hhv else [])
        out.append(_record(row, 1, "stationary_combustion", gas, _ef_to_tonnes(mmbtu, f),
                           "fuel_hhv_x_ef", used, ogmp_level=3))
    return out


def mobile_combustion(row: dict, factors: pd.DataFrame, _d: dict) -> list[dict]:
    if normalize_unit(row["unit"]) != "gal":
        raise UnitError("mobile_combustion activity must be fuel volume in gallons")
    f = lookup_factor(factors, "mobile_combustion", row["fuel_or_product"], "CO2")
    mass = mass_to_tonnes(float(row["quantity"]) * f.value, "kg")
    note = "CH4/N2O not estimated: requires vehicle-miles by vehicle type (EPA Hub Table 2)"
    return [_record(row, 1, "mobile_combustion", "CO2", mass, "fuel_volume_x_ef", [f], note=note)]


def _scf(row: dict) -> float:
    key = normalize_unit(row["unit"])
    mult = {"scf": 1.0, "mcf": 1_000.0, "mmscf": 1_000_000.0}.get(key)
    if mult is None:
        raise UnitError(f"{row['source_type']} volume must be scf/Mcf/MMscf, got {row['unit']!r}")
    return float(row["quantity"]) * mult


def flare(row: dict, _f: pd.DataFrame, d: dict) -> list[dict]:
    de, ce = FLARE_TIERS[d["flare_efficiency_tier"]]
    if de is None:
        de, ce = float(row["destruction_eff"]), float(row["combustion_eff"])
    v = _scf(row)
    x_ch4, x_co2 = float(row["ch4_mol_frac"]), float(row.get("co2_mol_frac") or 0.0)
    x_c2, n_c2 = float(row.get("c2plus_mol_frac") or 0.0), float(row.get("c2plus_carbon_number") or 0.0)
    if x_c2 > 0 and n_c2 <= 0:
        raise ValueError("c2plus_mol_frac given without c2plus_carbon_number")
    ch4_t = v * x_ch4 * (1 - de) * DENSITY_KG_PER_SCF["CH4"] / 1000
    co2_scf = v * (x_co2 + ce * (x_ch4 + x_c2 * n_c2))
    co2_t = co2_scf * DENSITY_KG_PER_SCF["CO2"] / 1000
    method = f"subpart_w_flare_{d['flare_efficiency_tier']}(DE={de},CE={ce})"
    return [_record(row, 1, "flaring", "CH4", ch4_t, method, [], ogmp_level=3),
            _record(row, 1, "flaring", "CO2", co2_t, method, [])]


def _whole_gas_split(row: dict, scf: float, method: str, used: list, level: int,
                     category: str) -> list[dict]:
    x_ch4, x_co2 = float(row["ch4_mol_frac"]), float(row.get("co2_mol_frac") or 0.0)
    return [
        _record(row, 1, category, "CH4", scf * x_ch4 * DENSITY_KG_PER_SCF["CH4"] / 1000, method, used,
                ogmp_level=level),
        _record(row, 1, category, "CO2", scf * x_co2 * DENSITY_KG_PER_SCF["CO2"] / 1000, method, used),
    ]


def pneumatic_device(row: dict, factors: pd.DataFrame, _d: dict) -> list[dict]:
    f = lookup_factor(factors, "pneumatic_device", row["fuel_or_product"], "WHOLE_GAS")
    scf = float(row["device_count"]) * float(row["operating_hours"]) * f.value
    return _whole_gas_split(row, scf, "device_count_x_hours_x_ef", [f], 3, "vented")


def tank_vent(row: dict, _f: pd.DataFrame, d: dict) -> list[dict]:
    if d["tank_method"] == "measured_vent_volume":
        return _whole_gas_split(row, _scf(row), "measured_vent_volume", [], 4, "vented")
    if normalize_unit(row["unit"]) != "bbl":
        raise UnitError("flash_factor method needs oil/condensate throughput in bbl")
    if not row.get("flash_gor_source"):
        raise FactorProvenanceError("flash_gor_scf_per_bbl requires flash_gor_source (lab sample, model)")
    scf = float(row["quantity"]) * float(row["flash_gor_scf_per_bbl"])
    return _whole_gas_split(row, scf, f"flash_factor({row['flash_gor_source']})", [], 3, "vented")


def measured_or_component(row: dict, _f: pd.DataFrame, _d: dict) -> list[dict]:
    """vented_other / fugitive_component / process: measured CH4, or component EF with a source."""
    category = {"fugitive_component": "fugitive", "process": "process"}.get(row["source_type"], "vented")
    if pd.notna(row.get("measured_ch4_kg")):
        level = 5 if bool(row.get("site_level_reconciled")) else 4
        rec = _record(row, 1, category, "CH4", float(row["measured_ch4_kg"]) / 1000, "measured", [],
                      ogmp_level=level)
        return [rec]
    if pd.notna(row.get("measured_co2_kg")):
        return [_record(row, 1, category, "CO2", float(row["measured_co2_kg"]) / 1000, "measured", [])]
    if not row.get("ef_source") or pd.isna(row.get("ef_scf_per_hour")):
        raise FactorProvenanceError(
            f"{row['source_type']} row needs measured_ch4_kg, or ef_scf_per_hour + ef_source")
    scf = float(row["component_count"]) * float(row["operating_hours"]) * float(row["ef_scf_per_hour"])
    return _whole_gas_split(row, scf, f"component_ef({row['ef_source']})", [], 3, category)


def _lb_rate_to_t(mwh: float, factor) -> float:
    if factor.unit != "lb/MWh":
        raise UnitError(f"grid factor {factor.factor_id} must be lb/MWh")
    return mwh * factor.value * KG_PER_LB / 1000


def _market_records(row: dict, mwh: float, factors: pd.DataFrame, d: dict, loc) -> list[dict]:
    rec_mwh = min(float(row.get("rec_mwh") or 0.0), mwh)
    remaining = mwh - rec_mwh
    out = [_record(row, 2, "purchased_electricity", "CO2", 0.0, "market:eac_retired", [],
                   scope2_method="market", note=f"{rec_mwh:.3f} MWh covered by retired EACs")]
    supplier = row.get("supplier_rate_lb_co2_per_mwh")
    if pd.notna(supplier) and remaining > 0:
        if not row.get("supplier_rate_source"):
            raise FactorProvenanceError("supplier_rate_lb_co2_per_mwh requires supplier_rate_source")
        t = remaining * float(supplier) * KG_PER_LB / 1000
        out.append(_record(row, 2, "purchased_electricity", "CO2", t,
                           f"market:supplier_specific({row['supplier_rate_source']})", [],
                           scope2_method="market"))
        return out
    if remaining <= 0:
        return out
    try:
        rm = lookup_factor(factors, "purchased_electricity_residual", row["egrid_subregion"], "CO2")
        out.append(_record(row, 2, "purchased_electricity", "CO2", _lb_rate_to_t(remaining, rm),
                           "market:residual_mix", [rm], scope2_method="market"))
    except FactorProvenanceError:
        if d["market_fallback"] == "raise":
            raise
        out.append(_record(row, 2, "purchased_electricity", "CO2", _lb_rate_to_t(remaining, loc),
                           "market:location_fallback", [loc], scope2_method="market",
                           note="FLAG: no residual mix for subregion; location-based rate used"))
    return out


def purchased_electricity(row: dict, factors: pd.DataFrame, d: dict) -> list[dict]:
    """Scope 2 dual reporting: one location-based and one market-based set of records."""
    mwh = to_mwh(float(row["quantity"]), row["unit"])
    loc = lookup_factor(factors, "purchased_electricity_location", row["egrid_subregion"], "CO2")
    location = _record(row, 2, "purchased_electricity", "CO2", _lb_rate_to_t(mwh, loc),
                       "location:grid_average", [loc], scope2_method="location")
    return [location] + _market_records(row, mwh, factors, d, loc)


def sold_product(row: dict, factors: pd.DataFrame, _d: dict) -> list[dict]:
    fuel = row["fuel_or_product"]
    mmbtu, hhv = to_mmbtu(float(row["quantity"]), row["unit"], factors, fuel)
    f = lookup_factor(factors, "sold_product", fuel, "CO2")
    used = [f] + ([hhv] if hhv else [])
    return [_record(row, 3, "cat11_use_of_sold_products", "CO2", _ef_to_tonnes(mmbtu, f),
                    "sold_volume_x_combustion_ef", used, note="combustion CO2 only")]


DISPATCH = {
    "stationary_combustion": stationary_combustion, "mobile_combustion": mobile_combustion,
    "flare": flare, "pneumatic_device": pneumatic_device, "tank_vent": tank_vent,
    "vented_other": measured_or_component, "fugitive_component": measured_or_component,
    "process": measured_or_component, "purchased_electricity": purchased_electricity,
    "sold_product": sold_product,
}


def compute_emissions(activity: pd.DataFrame, factors: pd.DataFrame,
                      decisions: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (emission records, issues). Issues list every row that could not be computed."""
    records, issues = [], []
    rows = activity.reset_index(drop=True).assign(row_id=lambda x: x.index)
    for row in rows.to_dict("records"):
        calc = DISPATCH.get(row.get("source_type"))
        if calc is None:
            issues.append({"row_id": row["row_id"], "issue": f"unknown source_type {row.get('source_type')!r}"})
            continue
        try:
            records.extend(calc(row, factors, decisions))
        except DecisionRequired:
            raise
        except (UnitError, FactorProvenanceError, ValueError, KeyError) as exc:
            log.warning("row %s (%s) not computed: %s", row["row_id"], row["source_type"], exc)
            issues.append({"row_id": row["row_id"], "issue": f"{type(exc).__name__}: {exc}"})
    return pd.DataFrame(records), pd.DataFrame(issues, columns=["row_id", "issue"])
