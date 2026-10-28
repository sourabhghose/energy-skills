"""Decision points for decline-curve analysis, validated up front.

Every field of DcaDecisions is a choice that belongs to the reservoir engineer, so none has
a default. `DcaDecisions.from_kwargs` raises DecisionRequired naming the missing decision
and its options.

Usage:
    from dca_config import DcaDecisions
    decisions = DcaDecisions.from_kwargs(rate_basis="producing_day", decline_start="peak",
        outlier_method="mad", b_bounds=(0.0, 1.5), terminal_decline_eff=0.08,
        econ_limit_rate=5.0, max_life_years=50.0)
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

RATE_BASES = ("calendar_day", "producing_day")
DECLINE_STARTS = ("peak", "first_production")
OUTLIER_METHODS = ("none", "mad")
NORMALIZATIONS = ("none", "lateral_length")
PERIODS = ("monthly", "daily")
B_MAX_SANE = 2.5


class DecisionRequired(ValueError):
    """A DCA choice that belongs to the user was not supplied (or is invalid)."""

    def __init__(self, decision: str, options, why: str):
        self.decision, self.options, self.why = decision, tuple(options), why
        super().__init__(f"Decision required: {decision!r} ({why}). Options: {', '.join(map(str, options))}")


@dataclass(frozen=True)
class DcaDecisions:
    rate_basis: str
    decline_start: str
    outlier_method: str
    b_bounds: tuple[float, float]
    terminal_decline_eff: float | None    # None only when the user explicitly passed "none"
    econ_limit_rate: float
    max_life_years: float

    @classmethod
    def from_kwargs(cls, **kw) -> "DcaDecisions":
        _choice(kw, "rate_basis", RATE_BASES, "calendar-day vs producing-day rates differ when wells have downtime")
        _choice(kw, "decline_start", DECLINE_STARTS, "fitting the pre-peak cleanup period biases b and Di")
        _choice(kw, "outlier_method", OUTLIER_METHODS, "flush / workover spikes distort the fit")
        b_bounds = _b_bounds(kw.get("b_bounds"))
        terminal = _terminal(kw.get("terminal_decline_eff", "missing"))
        econ = _positive(kw, "econ_limit_rate", "economic limit rate (per day, same unit as the stream)")
        life = _positive(kw, "max_life_years", "maximum well life in years from first production")
        return cls(kw["rate_basis"], kw["decline_start"], kw["outlier_method"], b_bounds, terminal, econ, life)

    def as_dict(self) -> dict:
        return asdict(self)


def _choice(kw: dict, name: str, options: tuple, why: str) -> None:
    if kw.get(name) not in options:
        raise DecisionRequired(name, options, why)


def _b_bounds(value) -> tuple[float, float]:
    why = "b > 1 only describes transient flow; an unbounded b inflates EUR"
    options = ("(0.0, 1.0)", "(0.0, 1.5)", "(0.0, 2.0)", "(b, b) to fix b")
    if value is None or len(value) != 2:
        raise DecisionRequired("b_bounds", options, why)
    lo, hi = float(value[0]), float(value[1])
    if not 0.0 <= lo <= hi <= B_MAX_SANE:
        raise DecisionRequired("b_bounds", options, f"need 0 <= b_min <= b_max <= {B_MAX_SANE}")
    return lo, hi


def _terminal(value) -> float | None:
    why = "hyperbolic b >= 1 without a terminal decline gives unbounded or inflated EUR"
    options = ("0.05", "0.08", "0.10", "'none' (pure Arps, explicit)")
    if value == "none":
        return None
    if value == "missing" or value is None:
        raise DecisionRequired("terminal_decline_eff", options, why)
    value = float(value)
    if not 0.0 < value < 0.5:
        raise DecisionRequired("terminal_decline_eff", options, "effective annual fraction, e.g. 0.08 for 8%/yr")
    return value


def _positive(kw: dict, name: str, why: str) -> float:
    value = kw.get(name)
    if value is None or float(value) <= 0:
        raise DecisionRequired(name, ("positive number",), why)
    return float(value)


@dataclass(frozen=True)
class TypeCurveDecisions:
    normalization: str
    reference_lateral_ft: float | None

    @classmethod
    def from_kwargs(cls, normalization=None, reference_lateral_ft=None) -> "TypeCurveDecisions":
        if normalization not in NORMALIZATIONS:
            raise DecisionRequired("normalization", NORMALIZATIONS,
                                   "lateral-length scaling changes every percentile")
        if normalization == "lateral_length":
            if reference_lateral_ft is None or float(reference_lateral_ft) <= 0:
                raise DecisionRequired("reference_lateral_ft", ("5000", "7500", "10000"),
                                       "normalized volumes are per reference lateral")
            return cls(normalization, float(reference_lateral_ft))
        return cls(normalization, None)
