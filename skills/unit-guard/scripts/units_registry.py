"""Vetted energy unit registry: symbols, aliases, dimensions, and factors.

Every factor converts one unit of the symbol into the dimension's base unit:
  volume (liquid / actual)  -> m3          energy -> J        power -> W
  std_gas_volume            -> m3 at the unit's own reference conditions (see GAS_BASES)
  mass                      -> kg          mass_co2e -> kg CO2e
  oil_equivalent            -> boe         gas_equivalent -> Mcfe
  pressure_abs / gauge      -> Pa          time -> s         temperature -> K (affine)
  capacity_month / _day     -> MW-month / MW-day (capacity products, not energy)

Factors cite exact definitions where they exist (NIST SP 811, 1959 international foot and
pound, IT Btu). The oil & gas "M = thousand" convention (Mcf, Mbbl, MMBtu) is encoded here;
symbols whose prefix is genuinely ambiguous (MBtu, Mlb, MT, ton, psi, bar) live in AMBIGUOUS
and are refused until the caller names the intended unit.

Usage:
    from units_registry import lookup
    unit = lookup("MMcf")      # Unit(symbol='MMcf', dimension='std_gas_volume', ...)
"""

from __future__ import annotations

from dataclasses import dataclass

BBL_M3 = 0.158987294928          # 42 US gal x 3.785411784 L (exact)
FT3_M3 = 0.028316846592          # (0.3048 m)^3 (exact)
BTU_J = 1055.05585262            # International Table Btu (exact by definition)
LB_KG = 0.45359237               # international avoirdupois pound (exact)
PSI_PA = 6894.757293168          # lbf/in^2 (derived from exact lbf and inch)
ATM_PA = 101325.0


@dataclass(frozen=True)
class Unit:
    symbol: str
    dimension: str
    factor: float
    offset: float = 0.0
    gas_basis: str | None = None   # "scf" (needs a decision), "Sm3_15C", "Nm3_0C"
    note: str = ""


@dataclass(frozen=True)
class GasBasis:
    name: str
    temperature_k: float
    pressure_kpa: float
    source: str


# Reference conditions for standard gas volumes. The scf family has no single universal
# basis, so its basis is always a caller decision.
GAS_BASES = {
    "60F_14.696psia": GasBasis("60F_14.696psia", 288.705556, 101.325, "SPE / ISO 13443 imperial"),
    "60F_14.73psia": GasBasis("60F_14.73psia", 288.705556, 14.73 * PSI_PA / 1000, "AGA / US federal royalty"),
    "60F_14.65psia": GasBasis("60F_14.65psia", 288.705556, 14.65 * PSI_PA / 1000, "some US state regulators"),
    "Sm3_15C": GasBasis("Sm3_15C", 288.15, 101.325, "ISO 13443 metric standard"),
    "Nm3_0C": GasBasis("Nm3_0C", 273.15, 101.325, "normal conditions (DIN 1343)"),
}
SCF_BASIS_OPTIONS = ("60F_14.696psia", "60F_14.73psia", "60F_14.65psia")


def _units(dimension: str, entries: list[tuple], **kw) -> dict[str, Unit]:
    out: dict[str, Unit] = {}
    for symbol, factor, aliases, note in entries:
        unit = Unit(symbol=symbol, dimension=dimension, factor=factor, note=note, **kw)
        for alias in (symbol, *aliases):
            out[alias] = unit
    return out


VOLUME = _units("volume", [
    ("bbl", BBL_M3, ("bbls", "BBL", "barrel", "barrels", "stb", "STB"), "42 US gallons"),
    ("Mbbl", 1e3 * BBL_M3, ("MBbl", "MBBL", "mbbl", "Mstb", "MSTB"), "M = thousand (oil & gas)"),
    ("MMbbl", 1e6 * BBL_M3, ("MMBbl", "MMBBL", "mmbbl", "MMstb", "MMSTB"), "MM = million"),
    ("m3", 1.0, ("m^3", "M3", "cubic_meter"), "actual cubic metre (liquids)"),
    ("gal", 0.003785411784, ("usgal", "gallon", "gallons"), "US gallon"),
    ("L", 0.001, ("l", "litre", "liter"), ""),
    ("ft3", FT3_M3, ("ft^3", "cubic_foot"), "actual (line-condition) cubic foot"),
])

STD_GAS = {
    **_units("std_gas_volume", [
        ("scf", FT3_M3, ("SCF",), "standard cubic foot; basis is a decision"),
        ("Mcf", 1e3 * FT3_M3, ("MCF", "mcf", "Mscf", "MSCF", "mscf"), "M = thousand"),
        ("MMcf", 1e6 * FT3_M3, ("MMCF", "mmcf", "MMscf", "MMSCF", "mmscf"), "MM = million"),
        ("Bcf", 1e9 * FT3_M3, ("BCF", "bcf", "Bscf", "BSCF"), "billion"),
        ("Tcf", 1e12 * FT3_M3, ("TCF", "tcf"), "trillion"),
    ], gas_basis="scf"),
    **_units("std_gas_volume", [
        ("Sm3", 1.0, ("sm3", "Sm^3", "SM3"), "standard m3 at 15 C, 101.325 kPa"),
        ("kSm3", 1e3, ("kSM3",), "SI prefix: k = thousand"),
        ("MSm3", 1e6, ("MSM3",), "SI prefix: M = MEGA (million), unlike Mcf"),
        ("GSm3", 1e9, ("GSM3",), "SI prefix: G = billion"),
    ], gas_basis="Sm3_15C"),
    **_units("std_gas_volume", [
        ("Nm3", 1.0, ("nm3", "Nm^3", "NM3"), "normal m3 at 0 C, 101.325 kPa"),
    ], gas_basis="Nm3_0C"),
}

ENERGY = _units("energy", [
    ("J", 1.0, (), ""), ("kJ", 1e3, (), ""), ("MJ", 1e6, (), ""), ("GJ", 1e9, (), ""),
    ("TJ", 1e12, (), ""), ("PJ", 1e15, (), ""),
    ("Btu", BTU_J, ("BTU", "btu"), "IT Btu"),
    ("MMBtu", 1e6 * BTU_J, ("MMBTU", "mmbtu", "MMbtu", "Dth", "dth", "DTH", "dekatherm"), "million Btu"),
    ("therm", 1e5 * BTU_J, ("thm", "therms"), "100,000 Btu"),
    ("quad", 1e15 * BTU_J, ("quads",), "10^15 Btu"),
    ("Wh", 3600.0, (), ""), ("kWh", 3.6e6, ("KWH", "kwh"), ""), ("MWh", 3.6e9, ("MWH", "mwh"), ""),
    ("GWh", 3.6e12, ("GWH", "gwh"), ""), ("TWh", 3.6e15, ("TWH", "twh"), ""),
])

POWER = _units("power", [
    ("W", 1.0, (), ""), ("kW", 1e3, ("KW", "kw"), ""), ("MW", 1e6, ("mw",), "MEGAwatt (SI)"),
    ("GW", 1e9, ("gw",), ""), ("TW", 1e12, (), ""), ("hp", 745.69987158227, ("HP",), "mechanical hp"),
])

CAPACITY = {
    **_units("capacity_month", [
        ("MW-month", 1.0, ("MW-mo", "MW_month", "MWmonth"), "capacity product: MW held for a month"),
        ("kW-month", 1e-3, ("kW-mo", "kW_month", "kWmonth"), "capacity product"),
    ]),
    **_units("capacity_day", [
        ("MW-day", 1.0, ("MW_day", "MWday", "MW-d"), "capacity product: MW held for a day"),
    ]),
}

MASS = _units("mass", [
    ("g", 1e-3, (), ""), ("kg", 1.0, (), ""),
    ("t", 1e3, ("tonne", "tonnes", "metric_ton", "metric_tonne"), "metric tonne"),
    ("kt", 1e6, ("kilotonne",), ""), ("Mt", 1e9, ("megatonne",), "MEGAtonne"),
    ("MMT", 1e9, ("MMt", "million_metric_tons"), "million metric tons (US EPA usage)"),
    ("lb", LB_KG, ("lbs", "LB", "LBS"), ""),
    ("short_ton", 2000 * LB_KG, ("short ton", "US_ton", "sh_ton"), "2000 lb"),
    ("long_ton", 2240 * LB_KG, ("long ton", "UK_ton"), "2240 lb"),
])

MASS_CO2E = _units("mass_co2e", [
    ("kgCO2e", 1.0, ("kg_co2e", "kgCO2eq"), ""),
    ("tCO2e", 1e3, ("tco2e", "t_co2e", "tCO2eq"), "metric tonne CO2e"),
    ("ktCO2e", 1e6, ("kt_co2e",), ""),
    ("MtCO2e", 1e9, ("Mt_co2e",), "megatonne CO2e"),
    ("MMTCO2e", 1e9, ("MMT_CO2e", "MMTCO2eq"), "million metric tons CO2e (EPA)"),
    ("lbCO2e", LB_KG, ("lb_co2e",), ""),
    ("short_ton_CO2e", 2000 * LB_KG, ("short_tons_CO2e",), ""),
    ("tCO2", 1e3, ("t_co2",), "CO2 mass (GWP = 1)"),
])

OIL_EQ = _units("oil_equivalent", [
    ("boe", 1.0, ("BOE", "Boe"), "barrel of oil equivalent; gas conversion is a decision"),
    ("Mboe", 1e3, ("MBOE", "MBoe"), "thousand boe"),
    ("MMboe", 1e6, ("MMBOE", "MMBoe"), "million boe"),
])
GAS_EQ = _units("gas_equivalent", [
    ("Mcfe", 1.0, ("MCFE", "mcfe"), "thousand cubic feet equivalent"),
    ("MMcfe", 1e3, ("MMCFE", "mmcfe"), ""), ("Bcfe", 1e6, ("BCFE", "bcfe"), ""),
])

PRESSURE = {
    **_units("pressure_abs", [
        ("Pa", 1.0, (), "absolute"), ("kPa", 1e3, ("kPaa", "kPa(a)"), "absolute (SI convention)"),
        ("MPa", 1e6, ("MPaa",), "absolute"), ("psia", PSI_PA, ("PSIA",), "absolute"),
        ("bara", 1e5, ("bar(a)",), "absolute"), ("atm", ATM_PA, (), "standard atmosphere"),
    ]),
    **_units("pressure_gauge", [
        ("psig", PSI_PA, ("PSIG",), "gauge"), ("barg", 1e5, ("bar(g)",), "gauge"),
        ("kPag", 1e3, ("kPa(g)",), "gauge"),
    ]),
}

TIME = _units("time", [
    ("s", 1.0, ("sec",), ""), ("min", 60.0, (), ""), ("h", 3600.0, ("hr", "hour", "hours"), ""),
    ("d", 86400.0, ("day", "days"), "calendar day"),
])

TEMPERATURE = {
    "K": Unit("K", "temperature", 1.0, 0.0),
    **{a: Unit("degC", "temperature", 1.0, 273.15) for a in ("degC", "C", "°C", "celsius")},
    **{a: Unit("degF", "temperature", 5 / 9, 459.67 * 5 / 9) for a in ("degF", "F", "°F", "fahrenheit")},
    **{a: Unit("degR", "temperature", 5 / 9, 0.0) for a in ("degR", "R", "°R", "rankine")},
}

# Single-token rate shorthands used in production reporting.
SHORTHAND = {
    "bopd": "bbl/d", "BOPD": "bbl/d", "bpd": "bbl/d", "BPD": "bbl/d", "bwpd": "bbl/d", "BWPD": "bbl/d",
    "boepd": "boe/d", "BOEPD": "boe/d", "BOE/D": "boe/d",
    "Mcfd": "Mcf/d", "MCFD": "Mcf/d", "mcfd": "Mcf/d", "Mscfd": "Mcf/d", "MSCFD": "Mcf/d",
    "MMcfd": "MMcf/d", "MMCFD": "MMcf/d", "MMscfd": "MMcf/d", "MMSCFD": "MMcf/d", "mmscfd": "MMcf/d",
    "Bcfd": "Bcf/d", "BCFD": "Bcf/d",
}

# Symbols refused until the caller picks a meaning: value = (options, why).
AMBIGUOUS = {
    "MBtu": (("Btu x 1e3 (write 'kBtu')", "MMBtu"),
             "'M' means thousand in US gas practice but is read as million by others"),
    "MBTU": (("Btu x 1e3 (write 'kBtu')", "MMBtu"), "same as MBtu"),
    "Mlb": (("1000 lb (write 'klb')", "1e6 lb"), "'M' = thousand (steam Mlb/hr) or mega"),
    "MT": (("t (metric tonne)", "Mt (megatonne)"), "upper-case MT is used for both"),
    "mt": (("t (metric tonne)", "Mt (megatonne)"), "lower-case mt is used for both"),
    "ton": (("short_ton", "long_ton", "t"), "US short, UK long, or metric tonne"),
    "tons": (("short_ton", "long_ton", "t"), "US short, UK long, or metric tonne"),
    "psi": (("psia", "psig"), "absolute vs gauge differs by ~14.7 psi"),
    "bar": (("bara", "barg"), "absolute vs gauge differs by ~1.013 bar"),
    "cf": (("scf", "ft3"), "standard vs actual cubic feet"),
    "MCM": (("thousand m3", "million m3"), "Mcm is used for both thousand and million m3"),
    "yr": (("365 d", "365.25 d", "8760 h"), "year length changes annual totals by up to 0.3%"),
    "Mm3": (("thousand m3", "million m3"), "M as thousand vs SI mega"),
}

kBtu = _units("energy", [("kBtu", 1e3 * BTU_J, ("KBTU", "kbtu"), "thousand Btu")])
klb = _units("mass", [("klb", 1e3 * LB_KG, ("KLB",), "thousand lb")])

REGISTRY: dict[str, Unit] = {
    **VOLUME, **STD_GAS, **ENERGY, **kBtu, **POWER, **CAPACITY, **MASS, **klb, **MASS_CO2E,
    **OIL_EQ, **GAS_EQ, **PRESSURE, **TIME, **TEMPERATURE,
}


class UnknownUnit(ValueError):
    """The symbol is not in the vetted registry."""


class AmbiguousUnit(ValueError):
    """The symbol has more than one industry meaning; the caller must choose."""

    def __init__(self, symbol: str, options: tuple, why: str):
        self.symbol, self.options, self.why = symbol, options, why
        super().__init__(f"Ambiguous unit {symbol!r}: {why}. Specify one of: {', '.join(options)}")


def lookup(symbol: str) -> Unit:
    """Resolve a single (non-compound) unit symbol, refusing ambiguous ones."""
    key = symbol.strip()
    if key in AMBIGUOUS:
        options, why = AMBIGUOUS[key]
        raise AmbiguousUnit(key, options, why)
    if key in REGISTRY:
        return REGISTRY[key]
    raise UnknownUnit(f"Unknown unit {symbol!r}. Add it to units_registry.py with a cited factor.")
