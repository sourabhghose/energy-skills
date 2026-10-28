"""NPT taxonomy, IADC-style activity-code mapping, and decision-point definitions.

Purpose: one place that names the NPT categories the skill reports, the default
IADC-style activity-code → NPT mapping (an operator may replace it), and every decision
point the runner refuses to assume.

Usage:
    from npt_taxonomy import NPT_CATEGORIES, resolve_code_map, require_decisions
"""

from __future__ import annotations

from dataclasses import dataclass

NPT_CATEGORIES: tuple[str, ...] = (
    "STUCK_PIPE",
    "LOST_CIRCULATION",
    "WELL_CONTROL",
    "EQUIPMENT_RIG",
    "EQUIPMENT_DOWNHOLE",
    "WAIT_WEATHER",
    "WAIT_MATERIALS",
    "FISHING",
    "WELLBORE_INSTABILITY",
    "OTHER_NPT",
)

CATEGORY_HINTS: dict[str, str] = {
    "STUCK_PIPE": "drill string, casing, or BHA unable to move (differential or mechanical sticking, pack-off), including jarring",
    "LOST_CIRCULATION": "partial or total loss of drilling fluid to the formation, LCM pills, curing losses",
    "WELL_CONTROL": "kick, influx, shut-in, circulating out a kick, kill operations, gas cut mud requiring well control",
    "EQUIPMENT_RIG": "failure or repair of rig-owned equipment (top drive, drawworks, mud pumps, BOP, power, iron roughneck)",
    "EQUIPMENT_DOWNHOLE": "failure of downhole or service-company tools (MWD/LWD, mud motor, RSS, bit failure, float equipment)",
    "WAIT_WEATHER": "operations suspended for weather (wind, lightning, sea state, ice, flooding)",
    "WAIT_MATERIALS": "waiting on materials, equipment delivery, third-party services, orders, or personnel",
    "FISHING": "retrieving lost or parted equipment from the hole (fishing jobs, milling junk)",
    "WELLBORE_INSTABILITY": "tight hole, hole collapse, excessive reaming/back-reaming, sloughing shale, ledges",
    "OTHER_NPT": "unplanned non-productive time that fits no category above",
}

# IADC-style daily drilling report activity codes commonly seen on land-rig DDR forms.
# Revisions and operator forms differ, so this map is only a starting point: the user must
# confirm it (decision `code_taxonomy`). Values: an NPT category, or None for productive /
# planned time. Codes absent from the map are reported as unmapped, never guessed.
IADC_STYLE_CODE_MAP: dict[str, str | None] = {
    "1": None,   # rig up / tear down
    "2": None,   # drilling actual
    "3": None,   # reaming (planned); unplanned reaming is caught from text
    "4": None,   # coring
    "5": None,   # condition mud & circulate
    "6": None,   # trips
    "7": None,   # lubricate rig
    "8": "EQUIPMENT_RIG",  # repair rig
    "9": None,   # cut off drilling line
    "10": None,  # deviation survey
    "11": None,  # wireline logs
    "12": None,  # run casing & cement
    "13": None,  # wait on cement (planned)
    "14": None,  # nipple up BOP
    "15": None,  # test BOP
    "16": None,  # drill stem test
    "17": None,  # plug back
    "18": None,  # squeeze cement
    "19": "FISHING",  # fishing
    "20": None,  # directional work
    "21": None,  # other: ambiguous, resolved from text when combine mode uses text
}

COMBINE_MODES: tuple[str, ...] = ("code_only", "text_only", "union", "intersection")
WEATHER_POLICIES: tuple[str, ...] = ("npt", "separate", "exclude")
REPORT_DAY_START_HOURS: tuple[int, ...] = (0, 6)
ILT_BENCHMARKS: tuple[str, ...] = ("p10", "p25", "technical_limit", "none")


class DecisionRequired(ValueError):
    """Raised when a decision that belongs to the user was not supplied."""


@dataclass(frozen=True)
class Decision:
    key: str
    question: str
    options: tuple
    standard: str


DECISIONS: tuple[Decision, ...] = (
    Decision("code_taxonomy", "Which activity-code → NPT mapping applies to these reports?",
             ("iadc_style", "<path or dict of operator mapping>"), "IADC DDR / operator NPT standard"),
    Decision("combine_mode", "How should coded activity and remark text combine to flag NPT?",
             COMBINE_MODES, "operator reporting convention"),
    Decision("weather_policy", "Is waiting-on-weather counted as NPT, reported separately, or excluded?",
             WEATHER_POLICIES, "drilling contract / operator KPI definition"),
    Decision("report_day_start_hour", "When does the reporting day start (midnight or 06:00)?",
             REPORT_DAY_START_HOURS, "DDR form / contract"),
    Decision("ilt_benchmark", "Which benchmark defines invisible lost time (ILT)?",
             ILT_BENCHMARKS, "operator performance programme (technical limit / offset percentile)"),
)


def require_decisions(**values) -> dict:
    """Validate that every decision is supplied and allowed; return them as a dict."""
    by_key = {d.key: d for d in DECISIONS}
    for key, value in values.items():
        decision = by_key[key]
        if value is None:
            raise DecisionRequired(
                f"Decision '{key}' is required: {decision.question} Options: {decision.options}")
        allowed = decision.options
        if key != "code_taxonomy" and value not in allowed:
            raise DecisionRequired(f"Decision '{key}'={value!r} is not one of {allowed}")
    return dict(values)


def resolve_code_map(code_taxonomy) -> dict[str, str | None]:
    """Return the code → category map for a taxonomy choice ('iadc_style' or a user dict)."""
    if code_taxonomy == "iadc_style":
        return dict(IADC_STYLE_CODE_MAP)
    if isinstance(code_taxonomy, dict):
        bad = {c: v for c, v in code_taxonomy.items() if v is not None and v not in NPT_CATEGORIES}
        if bad:
            raise ValueError(f"Operator code map uses unknown NPT categories: {bad}")
        return {str(k): v for k, v in code_taxonomy.items()}
    raise DecisionRequired("code_taxonomy must be 'iadc_style' or a dict {code: category|None}")


def classify_weather(category: str | None, weather_policy: str) -> tuple[str | None, bool]:
    """Apply the weather policy. Returns (npt_category_or_None, is_weather_downtime)."""
    if category != "WAIT_WEATHER":
        return category, False
    if weather_policy == "npt":
        return category, True
    return None, True
