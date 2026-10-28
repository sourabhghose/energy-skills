"""Curve mnemonic families, unit aliases, canonical units, and plausibility ranges.

Families group vendor mnemonics that measure the same property (e.g. RHOB, RHOZ, ZDEN ->
RHOB bulk density). Each family has one canonical unit; every declared LAS unit string is
mapped to a canonical unit with a scale factor. Ranges are broad physical plausibility
windows (in canonical units) used to catch wrong units, not to quality-control the log.

See references/mnemonics.md for the sources and the reasoning behind each alias.

Usage:
    from mnemonics import family_of, resolve_unit, FAMILIES
    family_of("RHOZ")                 # "RHOB"
    resolve_unit("RHOB", "K/M3")      # ("g/cm3", 0.001)
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Family:
    name: str
    description: str
    canonical_unit: str
    plausible: tuple[float, float]
    aliases: tuple[str, ...]


FAMILIES = {f.name: f for f in (
    Family("DEPTH", "Measured depth index", "ft", (-50_000.0, 50_000.0),
           ("DEPT", "DEPTH", "MD", "DEPTH_MD", "TDEP")),
    Family("GR", "Gamma ray (total)", "gAPI", (0.0, 1500.0),
           ("GR", "GRC", "GRD", "GR_EDTC", "GRGC", "HGR", "SGR", "ECGR", "GRR", "GAMMA")),
    Family("CGR", "Computed gamma ray (Th+K, no U)", "gAPI", (0.0, 1500.0), ("CGR", "HCGR")),
    Family("RHOB", "Bulk density", "g/cm3", (1.0, 3.5),
           ("RHOB", "RHOZ", "DEN", "ZDEN", "RHO8", "DENB", "HDEN", "BDEL", "RHOM")),
    Family("NPHI", "Neutron porosity", "v/v", (-0.15, 1.0),
           ("NPHI", "TNPH", "NPOR", "CNC", "NPHS", "NPHL", "NPRL", "CN", "PHIN", "HNPO", "NPHD")),
    Family("DT", "Compressional slowness", "us/ft", (30.0, 250.0),
           ("DT", "DTC", "DTCO", "AC", "DT24", "DTLN", "DTLF", "SONIC", "DT4P")),
    Family("DTS", "Shear slowness", "us/ft", (50.0, 800.0), ("DTS", "DTSM", "DTSH", "DT4S", "DTSD")),
    Family("RT", "Deep resistivity", "ohm.m", (0.01, 100_000.0),
           ("ILD", "RILD", "LLD", "RT", "AT90", "AF90", "RD", "HDRS", "RLA5", "M2R9", "RDEP", "IDPH", "RES_DEEP")),
    Family("RM", "Medium resistivity", "ohm.m", (0.01, 100_000.0),
           ("ILM", "RILM", "AT30", "AF30", "RM", "HMRS", "RLA3", "M2R3", "IMPH", "RMED")),
    Family("RS", "Shallow / flushed-zone resistivity", "ohm.m", (0.01, 100_000.0),
           ("LLS", "SFL", "SFLU", "MSFL", "RXO", "RXOZ", "AT10", "AF10", "LL8", "RS", "RSHAL")),
    Family("CALI", "Caliper (hole diameter)", "in", (2.0, 40.0),
           ("CALI", "CAL", "HCAL", "C1", "C2", "CALX", "CALY", "CAL1", "LCAL", "DCAL")),
    Family("SP", "Spontaneous potential", "mV", (-500.0, 500.0), ("SP", "SPBR", "SSP", "SPR")),
    Family("PEF", "Photoelectric factor", "b/e", (0.0, 20.0), ("PEF", "PE", "PEFZ", "PEF8", "HPEF")),
)}

ALIAS_TO_FAMILY = {alias: f.name for f in FAMILIES.values() for alias in f.aliases}

# Declared unit string (upper-cased, spaces removed) -> (canonical unit, scale to canonical).
UNIT_ALIASES: dict[str, tuple[str, float]] = {
    **{u: ("gAPI", 1.0) for u in ("GAPI", "API", "APIU", "GAPI-U", "APIUNITS")},
    **{u: ("g/cm3", 1.0) for u in ("G/C3", "G/CC", "GM/CC", "G/CM3", "GR/CC", "GRAM/CC", "GMCC", "G/CM^3")},
    **{u: ("g/cm3", 1e-3) for u in ("K/M3", "KG/M3", "KG/M^3")},
    **{u: ("v/v", 1.0) for u in ("V/V", "FRAC", "DEC", "CFCF", "M3/M3", "FT3/FT3", "FRACTION")},
    **{u: ("v/v", 0.01) for u in ("PU", "P.U.", "%", "PERCENT", "PERC", "NPU")},
    **{u: ("us/ft", 1.0) for u in ("US/F", "US/FT", "USEC/FT", "µS/FT", "μS/FT", "USFT", "MICS/FT")},
    **{u: ("us/ft", 0.3048) for u in ("US/M", "USEC/M", "µS/M", "μS/M", "USM")},
    **{u: ("ohm.m", 1.0) for u in ("OHMM", "OHM.M", "OHM-M", "OHM_M", "OHMS", "OHM", "OHMM2/M", "OHM.M2/M")},
    **{u: ("in", 1.0) for u in ("IN", "INCH", "INCHES", "\"")},
    **{u: ("in", 1 / 25.4) for u in ("MM",)},
    **{u: ("in", 1 / 2.54) for u in ("CM",)},
    **{u: ("mV", 1.0) for u in ("MV",)},
    **{u: ("b/e", 1.0) for u in ("B/E", "BARN", "B/EL", "BARNS/E", "B/ELEC")},
    **{u: ("ft", 1.0) for u in ("F", "FT", "FEET", "FOOT")},
    **{u: ("m", 1.0) for u in ("M", "METER", "METERS", "METRE", "METRES")},
}
# Strings seen in the wild that do not identify a unit on their own.
AMBIGUOUS_UNITS = {"", "NONE", "UNKNOWN", "MS/FT", "MS/M", "UNITLESS", "-", "NA"}

DEPTH_SCALE = {("ft", "ft"): 1.0, ("m", "m"): 1.0, ("ft", "m"): 0.3048, ("m", "ft"): 1 / 0.3048}


def normalize_mnemonic(mnemonic: str) -> str:
    """Upper-case and strip lasio duplicate suffixes (GR:1) and run suffixes (GR_1, GR.1)."""
    base = mnemonic.strip().upper().split(":")[0]
    return re.sub(r"([_.]\d+)$", "", base)


def family_of(mnemonic: str) -> str:
    """Family name, or 'UNMAPPED' if the mnemonic is not in the alias table."""
    return ALIAS_TO_FAMILY.get(normalize_mnemonic(mnemonic), "UNMAPPED")


def normalize_unit_string(unit: str | None) -> str:
    return (unit or "").strip().upper().replace(" ", "")


def resolve_unit(family: str, unit: str | None) -> tuple[str, float] | None:
    """(canonical unit, scale) if `unit` is a known unit compatible with `family`, else None."""
    key = normalize_unit_string(unit)
    if key in AMBIGUOUS_UNITS or key not in UNIT_ALIASES:
        return None
    canonical, scale = UNIT_ALIASES[key]
    fam = FAMILIES.get(family)
    if fam is None:
        return canonical, scale
    if family == "DEPTH":
        return (canonical, scale) if canonical in ("ft", "m") else None
    return (canonical, scale) if canonical == fam.canonical_unit else None


def candidate_units(family: str) -> list[str]:
    """Declared-unit spellings that map to the family's canonical unit (for prompts)."""
    fam = FAMILIES.get(family)
    if fam is None:
        return []
    preferred = {"gAPI": ["GAPI"], "g/cm3": ["G/C3", "K/M3"], "v/v": ["V/V", "PU"],
                 "us/ft": ["US/F", "US/M"], "ohm.m": ["OHMM"], "in": ["IN", "MM", "CM"],
                 "mV": ["MV"], "b/e": ["B/E"], "ft": ["F", "M"]}
    return preferred.get(fam.canonical_unit, [])


def infer_unit_from_values(family: str, median: float) -> str | None:
    """Best-guess declared unit from a curve's median (used only to PROPOSE, never to apply)."""
    if not (median == median):           # NaN
        return None
    guesses = {
        "NPHI": "V/V" if -0.15 <= median <= 1.0 else ("PU" if median <= 100 else None),
        "RHOB": "G/C3" if 1.0 <= median <= 3.5 else ("K/M3" if 1000 <= median <= 3500 else None),
        "DT": "US/F" if 30 <= median <= 250 else ("US/M" if 100 <= median <= 820 else None),
        "DTS": "US/F" if 50 <= median <= 800 else None,
        "CALI": "IN" if 2 <= median <= 40 else ("MM" if 50 <= median <= 1000 else None),
    }
    return guesses.get(family)
