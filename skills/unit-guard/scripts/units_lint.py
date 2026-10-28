"""Column-name unit lint: flag missing, ambiguous, or power/energy-confused units.

Works on names only (no data), so it is cheap to run on every table a skill touches.

Usage:
    from units_lint import lint_columns
    for f in lint_columns(["oil_bbl", "gas_m3", "generation_mw", "co2_tons"]):
        print(f.severity, f.column, f.issue)
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from units_registry import AMBIGUOUS, REGISTRY, SHORTHAND

QUANTITY_HINTS = (
    "vol", "volume", "rate", "prod", "production", "energy", "power", "load", "demand",
    "generation", "gen", "consumption", "usage", "emission", "emissions", "co2", "ch4",
    "flare", "fuel", "heat", "capacity", "oil", "gas", "water", "ngl", "throughput",
)
ENERGY_WORDS = ("energy", "generation", "consumption", "usage", "sold", "delivered", "daily", "monthly", "total")
CASE_SENSITIVE_TOKENS = {"MT", "Mt", "mt", "MW", "mW"}


@dataclass(frozen=True)
class Finding:
    column: str
    severity: str     # "error" | "warn" | "info"
    issue: str
    suggestion: str


def _tokens(column: str) -> list[str]:
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", column)
    return [t for t in re.split(r"[_\-\s.]+", spaced) if t]


def _match_unit(token: str) -> str | None:
    for candidate in (token, token.lower(), token.upper()):
        if candidate in REGISTRY or candidate in SHORTHAND:
            return candidate
    return None


def _ambiguous(token: str) -> str | None:
    if token in AMBIGUOUS:
        return token
    lowered = {k.lower(): k for k in AMBIGUOUS if k not in CASE_SENSITIVE_TOKENS}
    return lowered.get(token.lower())


def lint_column(column: str) -> list[Finding]:
    """All findings for one column name."""
    tokens = _tokens(column)
    lower = [t.lower() for t in tokens]
    findings: list[Finding] = []
    units = [u for u in (_match_unit(t) for t in tokens) if u]
    for token in tokens:
        amb = _ambiguous(token)
        if amb:
            options, why = AMBIGUOUS[amb]
            findings.append(Finding(column, "error", f"ambiguous unit '{token}': {why}",
                                    f"rename with one of: {', '.join(options)}"))
    if "mw" in lower and any(w in lower for w in ENERGY_WORDS):
        findings.append(Finding(column, "warn", "MW (power) on an energy-like column",
                                "if this is energy over an interval, it should be MWh"))
    if any(t in ("m3", "M3") for t in tokens) and "gas" in lower:
        findings.append(Finding(column, "warn", "gas in actual m3: standard or line conditions?",
                                "use Sm3 (15 C) or Nm3 (0 C), or document line conditions"))
    if any(t.lower() in ("scf", "mcf", "mmcf", "bcf", "mcfd", "mmcfd", "mmscfd") for t in tokens):
        findings.append(Finding(column, "info", "standard cubic feet: reference pressure varies",
                                "record scf_standard_conditions (14.696 / 14.73 / 14.65 psia) in metadata"))
    if any(t.lower() in ("btu", "mmbtu", "therm", "dth") for t in tokens) and not {"hhv", "lhv"} & set(lower):
        findings.append(Finding(column, "info", "heating value basis (HHV/LHV) not stated",
                                "suffix _hhv or _lhv"))
    if not units and not findings and any(h in lower for h in QUANTITY_HINTS):
        findings.append(Finding(column, "warn", "quantity column without a unit",
                                "add a unit suffix (e.g. _bbl, _mcf, _mwh, _tco2e)"))
    return findings


def lint_columns(columns: list[str]) -> list[Finding]:
    """Findings for many columns, in input order."""
    return [f for column in columns for f in lint_column(column)]
