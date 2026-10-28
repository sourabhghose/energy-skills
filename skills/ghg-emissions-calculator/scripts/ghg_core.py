"""Core primitives for the GHG calculator: decisions, GWP sets, units, factor lookup.

Pure Python (pandas). No Spark, no network. Every factor used is returned together with
its factor_id, source and vintage so the inventory carries full lineage.

    from ghg_core import load_factors, lookup_factor, gwp, to_mmbtu
    factors = load_factors(["epa_hub_2025", "egrid_2023"])
    f = lookup_factor(factors, "stationary_combustion", "natural_gas", "CO2")
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

ASSETS = Path(__file__).resolve().parent.parent / "assets"
FACTOR_FILE = ASSETS / "emission_factors.csv"

# 100-year GWPs. AR6 CH4 uses the fossil-origin value (29.8); non-fossil is 27.0.
GWP_SETS: dict[str, dict[str, float]] = {
    "AR4": {"CO2": 1.0, "CH4": 25.0, "N2O": 298.0},
    "AR5": {"CO2": 1.0, "CH4": 28.0, "N2O": 265.0},
    "AR6": {"CO2": 1.0, "CH4": 29.8, "N2O": 273.0},
}

# Standard-condition gas densities used by EPA Subpart W (60 degF, 14.7 psia).
DENSITY_KG_PER_SCF = {"CH4": 0.0192, "CO2": 0.0526}

KG_PER_LB = 0.45359237
MMBTU_PER_MWH = 3.412142

ENERGY_UNITS = {"mmbtu": 1.0, "therm": 0.1, "dth": 1.0, "gj": 0.947817, "mwh": MMBTU_PER_MWH}
VOLUME_UNITS = {  # to the factor table's base volume units
    "scf": ("scf", 1.0), "mcf": ("scf", 1_000.0), "mmscf": ("scf", 1_000_000.0),
    "gal": ("gal", 1.0), "bbl": ("bbl", 1.0),
}
ELECTRICITY_UNITS = {"kwh": 0.001, "mwh": 1.0, "gwh": 1_000.0}
UNIT_ALIASES = {
    "mmbtu": "mmbtu", "mmbtus": "mmbtu", "million btu": "mmbtu", "therms": "therm",
    "dekatherm": "dth", "mcf": "mcf", "mscf": "mcf", "mmcf": "mmscf", "mmscf": "mmscf",
    "gallon": "gal", "gallons": "gal", "barrel": "bbl", "barrels": "bbl",
}
AMBIGUOUS_UNITS = {
    "m3": "cubic metres: state reference conditions (15 degC/101.325 kPa vs 0 degC) and convert",
    "mscf_or_mmscf": "M/MM prefix ambiguous", "btu": "Btu without prefix: confirm magnitude",
    "ton": "short ton vs metric tonne", "t": "tonne vs short ton",
}


class DecisionRequired(ValueError):
    """A decision point that belongs to the user was not supplied."""

    def __init__(self, name: str, options: list | tuple, why: str = ""):
        self.name, self.options = name, list(options)
        super().__init__(f"Decision required: {name!r}; choose one of {self.options}. {why}".strip())


class UnitError(ValueError):
    """A unit was unknown or ambiguous."""


class FactorProvenanceError(ValueError):
    """A factor was missing, ambiguous, or lacked a source/vintage."""


@dataclass(frozen=True)
class Factor:
    factor_id: str
    value: float
    unit: str
    source: str
    vintage: str
    status: str
    factor_set: str


def require(name: str, value, options, applicable: bool = True, why: str = ""):
    """Validate a decision. Not-applicable decisions may be None and are recorded as such."""
    if not applicable and value is None:
        return "not_applicable"
    if value is None or value not in options:
        raise DecisionRequired(name, options, why)
    return value


def gwp(gas: str, gwp_set: str) -> float:
    if gwp_set not in GWP_SETS:
        raise DecisionRequired("gwp_set", list(GWP_SETS))
    if gas not in GWP_SETS[gwp_set]:
        raise ValueError(f"No GWP for gas {gas!r} in {gwp_set}")
    return GWP_SETS[gwp_set][gas]


def normalize_unit(unit: str) -> str:
    key = str(unit).strip().lower()
    if key in AMBIGUOUS_UNITS:
        raise UnitError(f"Ambiguous unit {unit!r}: {AMBIGUOUS_UNITS[key]}")
    key = UNIT_ALIASES.get(key, key)
    if key not in ENERGY_UNITS and key not in VOLUME_UNITS and key not in ELECTRICITY_UNITS:
        raise UnitError(f"Unknown unit {unit!r}")
    return key


def to_mwh(quantity: float, unit: str) -> float:
    key = normalize_unit(unit)
    if key not in ELECTRICITY_UNITS:
        raise UnitError(f"Electricity must be in kWh/MWh/GWh, got {unit!r}")
    return quantity * ELECTRICITY_UNITS[key]


def load_factors(factor_sets: list[str], path: Path = FACTOR_FILE) -> pd.DataFrame:
    """Load the versioned factor table restricted to the chosen factor sets."""
    table = pd.read_csv(path, dtype={"vintage": str})
    available = sorted(table["factor_set"].unique())
    if not factor_sets:
        raise DecisionRequired("factor_sets", available, "Pick factor source + vintage.")
    unknown = sorted(set(factor_sets) - set(available))
    if unknown:
        raise FactorProvenanceError(f"Unknown factor sets {unknown}; available {available}")
    chosen = table[table["factor_set"].isin(factor_sets)]
    missing = chosen[chosen["source"].isna() | chosen["vintage"].isna()]
    if not missing.empty:
        raise FactorProvenanceError(f"Factors without source/vintage: {list(missing.factor_id)}")
    return chosen.reset_index(drop=True)


def available_factor_sets(path: Path = FACTOR_FILE) -> pd.DataFrame:
    table = pd.read_csv(path, dtype={"vintage": str})
    return (table.groupby(["factor_set", "source", "vintage"]).size()
            .rename("n_factors").reset_index())


def lookup_factor(factors: pd.DataFrame, category: str, key: str, gas: str) -> Factor:
    """Exactly one factor must match among the chosen sets, else raise."""
    hit = factors[(factors.category == category) & (factors.fuel_or_key == key) & (factors.gas == gas)]
    if hit.empty:
        raise FactorProvenanceError(f"No factor for {category}/{key}/{gas} in chosen factor sets")
    if len(hit) > 1:
        raise FactorProvenanceError(
            f"Ambiguous factor for {category}/{key}/{gas}: {list(hit.factor_id)}; "
            "choose a single factor set for this source")
    r = hit.iloc[0]
    return Factor(r.factor_id, float(r.value), r.unit, r.source, str(r.vintage), r.status, r.factor_set)


def to_mmbtu(quantity: float, unit: str, factors: pd.DataFrame, fuel: str) -> tuple[float, Factor | None]:
    """Convert an activity quantity to mmBtu (HHV). Returns (mmBtu, HHV factor used or None)."""
    key = normalize_unit(unit)
    if key in ENERGY_UNITS:
        return quantity * ENERGY_UNITS[key], None
    if key not in VOLUME_UNITS:
        raise UnitError(f"{unit!r} is not an energy or fuel-volume unit")
    base, mult = VOLUME_UNITS[key]
    hhv = lookup_factor(factors, "heat_content", fuel, "HHV")
    if not hhv.unit.endswith(f"/{base}"):
        raise UnitError(f"HHV {hhv.factor_id} is per {hhv.unit}, activity is in {base}")
    return quantity * mult * hhv.value, hhv


def mass_to_tonnes(value: float, unit: str) -> float:
    """Convert a mass expressed in kg, g or lb to metric tonnes."""
    scale = {"kg": 1e-3, "g": 1e-6, "lb": KG_PER_LB * 1e-3}
    if unit not in scale:
        raise UnitError(f"Unsupported mass unit {unit!r}")
    return value * scale[unit]
