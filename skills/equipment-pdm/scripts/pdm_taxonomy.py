"""Equipment classes, canonical measurements and units, vibration zones, failure modes, decisions.

Purpose: shared vocabulary for equipment-pdm. Canonical measurements carry a canonical unit
and a kind (analog or state). ISO 10816-3 style vibration zone boundaries are given per
machine group and foundation; site-specific limits replace them when the user supplies them.
Failure-mode codes follow the spirit of the ISO 14224 taxonomy (summarized, not copied).

Usage:
    from pdm_taxonomy import MEASUREMENTS, VIBRATION_ZONES, require_decisions, DecisionRequired
"""

from __future__ import annotations

from dataclasses import dataclass

EQUIPMENT_CLASSES: dict[str, tuple[str, ...]] = {
    "esp": ("motor_current", "intake_pressure", "discharge_pressure", "motor_temperature",
            "intake_temperature", "frequency", "vibration_velocity", "run_status"),
    "compressor": ("suction_pressure", "discharge_pressure", "discharge_temperature", "speed",
                   "vibration_velocity", "bearing_temperature", "run_status"),
    "pump": ("suction_pressure", "discharge_pressure", "flow_rate", "motor_current",
             "vibration_velocity", "bearing_temperature", "run_status"),
    "gas_turbine": ("speed", "exhaust_temperature", "vibration_velocity", "bearing_temperature",
                    "power_output", "run_status"),
}

# canonical measurement -> (canonical unit, kind)
MEASUREMENTS: dict[str, tuple[str, str]] = {
    "motor_current": ("A", "analog"),
    "intake_pressure": ("kPa", "analog"),
    "suction_pressure": ("kPa", "analog"),
    "discharge_pressure": ("kPa", "analog"),
    "motor_temperature": ("degC", "analog"),
    "intake_temperature": ("degC", "analog"),
    "discharge_temperature": ("degC", "analog"),
    "bearing_temperature": ("degC", "analog"),
    "exhaust_temperature": ("degC", "analog"),
    "frequency": ("Hz", "analog"),
    "speed": ("rpm", "analog"),
    "flow_rate": ("m3/h", "analog"),
    "power_output": ("kW", "analog"),
    "vibration_velocity": ("mm/s", "analog"),
    "run_status": ("state", "state"),
}

# (multiplier, offset): canonical = value * multiplier + offset
UNIT_CONVERSIONS: dict[tuple[str, str], tuple[float, float]] = {
    ("degF", "degC"): (5.0 / 9.0, -32.0 * 5.0 / 9.0),
    ("K", "degC"): (1.0, -273.15),
    ("psi", "kPa"): (6.894757, 0.0),
    ("psig", "kPa"): (6.894757, 0.0),
    ("bar", "kPa"): (100.0, 0.0),
    ("barg", "kPa"): (100.0, 0.0),
    ("MPa", "kPa"): (1000.0, 0.0),
    ("in/s", "mm/s"): (25.4, 0.0),
    ("ips", "mm/s"): (25.4, 0.0),
    ("bbl/d", "m3/h"): (0.158987 / 24.0, 0.0),
    ("gpm", "m3/h"): (0.227125, 0.0),
    ("MW", "kW"): (1000.0, 0.0),
    ("hp", "kW"): (0.745700, 0.0),
}
UNIT_ALIASES = {"amps": "A", "amp": "A", "a": "A", "°c": "degC", "c": "degC", "degc": "degC",
                "°f": "degF", "f": "degF", "degf": "degF", "kpa": "kPa", "hz": "Hz", "rpm": "rpm",
                "mm/sec": "mm/s", "mm/s": "mm/s", "in/sec": "in/s", "psi": "psi", "psig": "psig"}

# ISO 10816-3 style velocity RMS zone boundaries (mm/s): (A/B, B/C, C/D)
VIBRATION_ZONES: dict[str, tuple[float, float, float]] = {
    "group1_rigid": (2.3, 4.5, 7.1),
    "group1_flexible": (3.5, 7.1, 11.0),
    "group2_rigid": (1.4, 2.8, 4.5),
    "group2_flexible": (2.3, 4.5, 7.1),
}

FAILURE_MODES: dict[str, str] = {
    "ELF": "electrical failure (motor, cable, penetrator, VSD)",
    "BRD": "breakdown / mechanical failure",
    "VIB": "excessive vibration",
    "OHE": "overheating",
    "LOO": "low output / degraded performance",
    "PLU": "plugged / choked (sand, scale)",
    "SER": "seal / external leakage",
    "FTS": "fail to start",
    "STP": "fail to stop / spurious stop",
    "OTH": "other",
}

ANALOG_INTERPOLATIONS = ("linear", "step")
RUNNING_DEFINITIONS = ("status_tag", "threshold")
SPLIT_STRATEGIES = ("time", "asset", "asset_and_time")
ANOMALY_METHODS = ("robust_z", "isolation_forest")


class DecisionRequired(ValueError):
    """Raised when a decision that belongs to the user was not supplied."""


@dataclass(frozen=True)
class Decision:
    key: str
    question: str
    options: tuple
    reference: str


DECISIONS: tuple[Decision, ...] = (
    Decision("analog_interpolation", "Fill analog values between samples linearly or as steps (last value)?",
             ANALOG_INTERPOLATIONS, "historian compression / PI 'step' attribute"),
    Decision("running_definition", "How is 'running' defined: a run-status tag, or a threshold on a measurement?",
             RUNNING_DEFINITIONS, "operating procedure / ISO 13374 data acquisition"),
    Decision("transient_exclusion_minutes", "Minutes after start and before stop to exclude as transients?",
             ("<int, e.g. 30>",), "OEM start-up guidance"),
    Decision("failure_modes", "Which work-order failure modes count as failures (labels)?",
             tuple(FAILURE_MODES), "ISO 14224 failure taxonomy / CMMS coding"),
    Decision("label_horizon_hours", "How many hours before a failure count as 'pre-failure'?",
             ("<int, e.g. 72, 168, 336>",), "maintenance lead time needed to act"),
    Decision("split_strategy", "How to split train/test without leakage?", SPLIT_STRATEGIES, "ML validation practice"),
    Decision("anomaly_method", "Which anomaly baseline?", ANOMALY_METHODS, "-"),
    Decision("alert_threshold", "Score above which an alert is raised?", ("<float>",), "false-alarm budget"),
)


def require_decisions(**values) -> dict:
    """Validate every decision is supplied and allowed; return them as a dict."""
    by_key = {d.key: d for d in DECISIONS}
    for key, value in values.items():
        d = by_key[key]
        if value is None:
            raise DecisionRequired(f"Decision '{key}' is required: {d.question} Options: {d.options}")
        enumerated = not str(d.options[0]).startswith("<")
        if key == "failure_modes":
            bad = set(value) - set(FAILURE_MODES)
            if not value or bad:
                raise DecisionRequired(f"failure_modes must be a non-empty subset of {tuple(FAILURE_MODES)}")
        elif enumerated and value not in d.options:
            raise DecisionRequired(f"Decision '{key}'={value!r} is not one of {d.options}")
    return dict(values)


def vibration_zone(velocity_mm_s: float, boundaries: tuple[float, float, float]) -> str | None:
    """ISO-style zone A/B/C/D for a velocity RMS value (None for missing values)."""
    if velocity_mm_s is None or velocity_mm_s != velocity_mm_s:
        return None
    ab, bc, cd = boundaries
    if velocity_mm_s < ab:
        return "A"
    if velocity_mm_s < bc:
        return "B"
    return "C" if velocity_mm_s < cd else "D"
