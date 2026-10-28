"""unit-guard core: dimension-checked energy unit conversion with explicit decisions.

Pure Python (stdlib only). Other skills import this instead of hand-writing factors:

    import sys; sys.path.append("<unit-guard>/scripts")
    from units_core import convert, boe_from_gas, to_co2e, DecisionRequired

    convert(12.5, "MMcf/d", "MSm3/d", decisions={"scf_standard_conditions": "60F_14.696psia"})
    boe_from_gas(600.0, "Mcf", method="energy_6_to_1")          # -> 100.0 boe
    to_co2e(1.0, "t", gas="CH4", gwp_set="AR5_100")             # -> 28.0 tCO2e

Rules encoded here:
  * Conversions across dimensions are refused (MW is not MWh; MW-month is not MWh).
  * Standard gas volumes carry a reference basis; crossing bases needs a decision.
  * Gauge <-> absolute pressure needs an atmospheric-pressure decision.
  * Ambiguous symbols (MBtu, MT, ton, psi, bar, cf, yr) are refused (units_registry.AMBIGUOUS).
"""

from __future__ import annotations

from dataclasses import dataclass

from units_registry import (
    GAS_BASES,
    PSI_PA,
    SCF_BASIS_OPTIONS,
    SHORTHAND,
    AmbiguousUnit,
    Unit,
    UnknownUnit,
    lookup,
)

__all__ = [
    "AmbiguousUnit", "DecisionRequired", "DimensionError", "UnknownUnit", "Quantity",
    "parse_unit", "dimension_of", "required_decisions", "conversion_factor", "convert",
    "boe_from_gas", "to_co2e", "GWP_100", "heat_rate_to_efficiency", "efficiency_to_heat_rate",
    "convert_heating_value_basis", "gas_volume_to_energy", "power_to_energy", "add",
]


class DecisionRequired(ValueError):
    """A conversion depends on a choice that belongs to the user, not the agent."""

    def __init__(self, decision: str, options: tuple | list, why: str):
        self.decision, self.options, self.why = decision, tuple(options), why
        super().__init__(f"Decision required: {decision!r} ({why}). Options: {', '.join(map(str, options))}")


class DimensionError(ValueError):
    """Two quantities or units have incompatible dimensions."""


@dataclass(frozen=True)
class ParsedUnit:
    text: str
    numerator: Unit
    denominator: Unit | None

    @property
    def dimension(self) -> str:
        if self.denominator is None:
            return self.numerator.dimension
        num, den = self.numerator.dimension, self.denominator.dimension
        return "power" if (num, den) == ("energy", "time") else f"{num}/{den}"


def parse_unit(text: str) -> ParsedUnit:
    """Parse 'Mcf', 'MMcf/d', 'bopd', 'Btu/scf' into a ParsedUnit (one '/' at most)."""
    raw = SHORTHAND.get(text.strip(), text.strip())
    parts = raw.replace(" per ", "/").split("/")
    if len(parts) > 2:
        raise UnknownUnit(f"Only one '/' is supported in a unit, got {text!r}")
    numerator = lookup(parts[0])
    denominator = lookup(parts[1]) if len(parts) == 2 else None
    if numerator.dimension == "temperature" and denominator is not None:
        raise DimensionError("Temperature cannot appear in a compound unit (affine scale)")
    return ParsedUnit(text=text, numerator=numerator, denominator=denominator)


def dimension_of(text: str) -> str:
    """Dimension string of a unit, e.g. 'std_gas_volume/time'."""
    return parse_unit(text).dimension


def _gas_bases(src: ParsedUnit, dst: ParsedUnit) -> list[tuple[str, str]]:
    pairs = []
    for a, b in ((src.numerator, dst.numerator), (src.denominator, dst.denominator)):
        if a is not None and b is not None and a.dimension == "std_gas_volume":
            pairs.append((a.gas_basis, b.gas_basis))
    return pairs


def required_decisions(from_unit: str, to_unit: str) -> list[str]:
    """Names of decisions a conversion from_unit -> to_unit needs (empty if none)."""
    src, dst = parse_unit(from_unit), parse_unit(to_unit)
    needed = []
    if any(a != b and "scf" in (a, b) for a, b in _gas_bases(src, dst)):
        needed.append("scf_standard_conditions")
    gauges = {src.numerator.dimension, dst.numerator.dimension}
    if gauges == {"pressure_abs", "pressure_gauge"}:
        needed.append("atmospheric_pressure_psia")
    return needed


def _require(decisions: dict | None, name: str, options: tuple, why: str):
    value = (decisions or {}).get(name)
    if value is None:
        raise DecisionRequired(name, options, why)
    return value


def _gas_amount_factor(unit: Unit, decisions: dict | None) -> float:
    """m3*kPa/K per unit, i.e. proportional to moles of ideal gas."""
    basis_name = unit.gas_basis
    if basis_name == "scf":
        basis_name = _require(decisions, "scf_standard_conditions", SCF_BASIS_OPTIONS,
                              "standard cubic feet have no single universal reference pressure")
        if basis_name not in SCF_BASIS_OPTIONS:
            raise ValueError(f"scf_standard_conditions must be one of {SCF_BASIS_OPTIONS}")
    basis = GAS_BASES[basis_name]
    return unit.factor * basis.pressure_kpa / basis.temperature_k


def _unit_factor(unit: Unit | None, other: Unit | None, decisions: dict | None) -> float:
    if unit is None:
        return 1.0
    differs = other is None or unit.gas_basis != other.gas_basis
    if unit.dimension == "std_gas_volume" and differs:
        return _gas_amount_factor(unit, decisions)
    return unit.factor


def _parsed_factor(p: ParsedUnit, counterpart: ParsedUnit, decisions: dict | None) -> float:
    """Factor to the base of p's dimension; gas bases resolved against the counterpart."""
    num = _unit_factor(p.numerator, counterpart.numerator, decisions)
    den = _unit_factor(p.denominator, counterpart.denominator, decisions)
    return num / den


def _check_dimensions(src: ParsedUnit, dst: ParsedUnit) -> None:
    pressure = {"pressure_abs", "pressure_gauge"}
    if src.dimension == dst.dimension:
        return
    if {src.dimension, dst.dimension} <= pressure:
        return
    raise DimensionError(
        f"Cannot convert {src.text!r} ({src.dimension}) to {dst.text!r} ({dst.dimension}). "
        + _dimension_hint(src.dimension, dst.dimension)
    )


def _dimension_hint(a: str, b: str) -> str:
    pair = {a, b}
    if pair == {"power", "energy"}:
        return "Power x hours = energy: use power_to_energy(value, unit, hours)."
    if "capacity_month" in pair or "capacity_day" in pair:
        return "Capacity products (MW-month) are not energy; they price MW held over a period."
    if pair == {"std_gas_volume", "oil_equivalent"}:
        return "Gas to boe is a convention: use boe_from_gas(..., method=...)."
    if pair == {"std_gas_volume", "energy"}:
        return "Gas volume to energy needs a heating value: use gas_volume_to_energy(...)."
    if pair == {"mass", "mass_co2e"}:
        return "Gas mass to CO2e needs a GWP set: use to_co2e(...)."
    return "Dimensions differ."


def _pressure_offset(src: Unit, dst: Unit, decisions: dict | None) -> float:
    """Additive offset in Pa when converting between gauge and absolute pressure."""
    pressure = {"pressure_abs", "pressure_gauge"}
    if src.dimension == dst.dimension or not {src.dimension, dst.dimension} <= pressure:
        return 0.0
    atm_psia = float(_require(decisions, "atmospheric_pressure_psia", (14.696, "site value"),
                              "gauge-to-absolute needs local atmospheric pressure"))
    atm_pa = atm_psia * PSI_PA
    return atm_pa if src.dimension == "pressure_gauge" else -atm_pa


def conversion_factor(from_unit: str, to_unit: str, decisions: dict | None = None) -> tuple[float, float]:
    """(scale, offset) such that value_to = value_from * scale + offset."""
    src, dst = parse_unit(from_unit), parse_unit(to_unit)
    _check_dimensions(src, dst)
    if src.numerator.dimension == "temperature":
        s, d = src.numerator, dst.numerator
        return s.factor / d.factor, (s.offset - d.offset) / d.factor
    scale = _parsed_factor(src, dst, decisions) / _parsed_factor(dst, src, decisions)
    offset = _pressure_offset(src.numerator, dst.numerator, decisions) / dst.numerator.factor
    return scale, offset


def convert(value: float, from_unit: str, to_unit: str, decisions: dict | None = None) -> float:
    """Convert a scalar; raises DimensionError / DecisionRequired / AmbiguousUnit."""
    scale, offset = conversion_factor(from_unit, to_unit, decisions)
    return value * scale + offset


# --- Conventions that are not unit conversions -------------------------------------

BOE_METHODS = ("energy_6_to_1", "heating_value", "price_parity")


def boe_from_gas(volume: float, unit: str, method: str, **params: float) -> float:
    """Gas volume -> boe under an explicit convention.

    energy_6_to_1  6 Mcf = 1 boe (SEC / SPE reporting convention; ~5.8 MMBtu/bbl oil vs
                   ~1.0 MMBtu/Mcf gas). params: none.
    heating_value  gas MMBtu / oil MMBtu-per-bbl. params: gas_hhv_btu_per_scf,
                   oil_mmbtu_per_bbl, scf_standard_conditions (if unit is not scf-family).
    price_parity   value parity. params: gas_price_per_mcf, oil_price_per_bbl.
    """
    if method not in BOE_METHODS:
        raise DecisionRequired("boe_method", BOE_METHODS, "boe is a convention, not a unit")
    mcf = convert(volume, unit, "Mcf", {"scf_standard_conditions": params.get("scf_standard_conditions")})
    if method == "energy_6_to_1":
        return mcf / 6.0
    if method == "heating_value":
        hv = _param(params, "gas_hhv_btu_per_scf", method)
        oil = _param(params, "oil_mmbtu_per_bbl", method)
        return mcf * 1e3 * hv / 1e6 / oil
    gas_price = _param(params, "gas_price_per_mcf", method)
    oil_price = _param(params, "oil_price_per_bbl", method)
    return mcf * gas_price / oil_price


def _param(params: dict, name: str, method: str) -> float:
    if params.get(name) is None:
        raise DecisionRequired(name, ("site / contract value",), f"boe method {method!r} needs {name}")
    return float(params[name])


# 100-year GWPs. AR4: IPCC 2007 WG1 Table 2.14. AR5: IPCC 2013 WG1 Table 8.A.1 (without
# climate-carbon feedbacks, as used by UNFCCC / EPA). AR6: IPCC 2021 WG1 Table 7.15.
GWP_100 = {
    "AR4_100": {"CO2": 1.0, "CH4": 25.0, "N2O": 298.0, "SF6": 22800.0, "NF3": 17200.0},
    "AR5_100": {"CO2": 1.0, "CH4": 28.0, "N2O": 265.0, "SF6": 23500.0, "NF3": 16100.0},
    "AR6_100": {"CO2": 1.0, "CH4_fossil": 29.8, "CH4_non_fossil": 27.0, "N2O": 273.0,
                "SF6": 25200.0, "NF3": 17400.0},
}


def to_co2e(mass: float, mass_unit: str, gas: str, gwp_set: str, ch4_origin: str | None = None) -> float:
    """Gas mass -> tCO2e. gwp_set is a decision (regulatory regimes pin one)."""
    if gwp_set not in GWP_100:
        raise DecisionRequired("gwp_set", tuple(GWP_100), "regimes pin a specific IPCC assessment")
    key = gas
    if gas == "CH4" and gwp_set == "AR6_100":
        if ch4_origin not in ("fossil", "non_fossil"):
            raise DecisionRequired("ch4_origin", ("fossil", "non_fossil"), "AR6 splits CH4 GWP by origin")
        key = f"CH4_{ch4_origin}"
    if key not in GWP_100[gwp_set]:
        raise UnknownUnit(f"No GWP for {gas!r} in {gwp_set}")
    tonnes = convert(mass, mass_unit, "t")
    return tonnes * GWP_100[gwp_set][key]


BTU_PER_KWH = 3412.14163312794   # 3.6e6 J / 1055.05585262 J


def heat_rate_to_efficiency(heat_rate: float, unit: str, basis: str) -> float:
    """Heat rate -> thermal efficiency (fraction). basis ('HHV'/'LHV') is carried, not changed."""
    _check_basis(basis)
    per_kwh = convert(heat_rate, unit, "Btu/kWh")
    return BTU_PER_KWH / per_kwh


def efficiency_to_heat_rate(efficiency: float, unit: str, basis: str) -> float:
    """Thermal efficiency (fraction) -> heat rate in `unit` on the same HHV/LHV basis."""
    _check_basis(basis)
    if not 0 < efficiency <= 1:
        raise ValueError("efficiency must be a fraction in (0, 1]")
    return convert(BTU_PER_KWH / efficiency, "Btu/kWh", unit)


def convert_heating_value_basis(value: float, from_basis: str, to_basis: str, lhv_over_hhv: float) -> float:
    """Convert an energy amount, heat rate, or efficiency between HHV and LHV.

    lhv_over_hhv is fuel-specific (natural gas ~0.90, coal ~0.95-0.97, diesel ~0.94) and
    must be supplied. Energy amounts scale by the ratio; heat rates scale inversely.
    """
    _check_basis(from_basis)
    _check_basis(to_basis)
    if not 0.7 < lhv_over_hhv <= 1.0:
        raise ValueError("lhv_over_hhv should be in (0.7, 1.0]")
    if from_basis == to_basis:
        return value
    return value * lhv_over_hhv if from_basis == "HHV" else value / lhv_over_hhv


def _check_basis(basis: str) -> None:
    if basis not in ("HHV", "LHV"):
        raise DecisionRequired("heating_value_basis", ("HHV", "LHV"),
                               "US practice quotes HHV; IEA / Europe quote LHV (~10% apart for gas)")


def gas_volume_to_energy(volume: float, unit: str, heating_value_btu_per_scf: float, basis: str,
                         to_unit: str, scf_standard_conditions: str | None = None) -> float:
    """Gas volume x heating value -> energy. basis and heating value are user-supplied."""
    _check_basis(basis)
    if not 800 <= heating_value_btu_per_scf <= 1600:
        raise ValueError("heating value outside 800-1600 Btu/scf; check units (MJ/m3? Btu/Mcf?)")
    scf = convert(volume, unit, "scf", {"scf_standard_conditions": scf_standard_conditions})
    return convert(scf * heating_value_btu_per_scf, "Btu", to_unit)


def power_to_energy(power: float, power_unit: str, hours: float, to_unit: str = "MWh") -> float:
    """Average power over `hours` -> energy. Hours must be the real interval length (DST!)."""
    if dimension_of(power_unit) != "power":
        raise DimensionError(f"{power_unit!r} is not a power unit")
    if hours < 0:
        raise ValueError("hours must be non-negative")
    joules = convert(power, power_unit, "W") * hours * 3600.0
    return convert(joules, "J", to_unit)


@dataclass(frozen=True)
class Quantity:
    value: float
    unit: str

    @property
    def dimension(self) -> str:
        return dimension_of(self.unit)

    def to(self, unit: str, decisions: dict | None = None) -> "Quantity":
        return Quantity(convert(self.value, self.unit, unit, decisions), unit)


def add(a: Quantity, b: Quantity, decisions: dict | None = None) -> Quantity:
    """a + b in a's unit; refuses MW + MWh and affine temperatures."""
    if a.dimension != b.dimension:
        raise DimensionError(f"Cannot add {a.unit!r} ({a.dimension}) and {b.unit!r} ({b.dimension})")
    if a.dimension == "temperature":
        raise DimensionError("Adding absolute temperatures is undefined; convert to a difference first")
    return Quantity(a.value + b.to(a.unit, decisions).value, a.unit)
