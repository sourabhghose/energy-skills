"""Decision points, validated VEE configuration, and run manifests for ami-interval-analytics.

Every analyst-owned choice is listed in ``DECISIONS``. ``make_config`` refuses to build a
configuration while any decision is unset (``None``) and raises ``DecisionRequired`` naming
the decision and its options, so the agent cannot silently pick one.

    from ami_decisions import make_config
    cfg = make_config(interval_minutes=15, source_timezone="America/Chicago", ...)
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

SKILL_NAME = "ami-interval-analytics"
SKILL_VERSION = "0.1.0"

DECISIONS: dict[str, dict] = {
    "interval_minutes": {
        "options": [5, 15, 30, 60],
        "why": "Confirm the meter channel interval detected by the preview.",
    },
    "source_timezone": {
        "options": "IANA zone of the meter clocks, e.g. America/Chicago, America/New_York",
        "why": "Local timestamps cannot be placed in UTC (or DST-resolved) without it.",
    },
    "timestamp_basis": {
        "options": ["local_naive", "utc", "offset_aware"],
        "why": "Whether read_ts is local wall-clock without offset, UTC, or carries an offset.",
    },
    "interval_convention": {
        "options": ["ending", "beginning"],
        "why": "AMI head-ends usually stamp interval-ending; MDMs and markets vary.",
    },
    "read_type": {
        "options": ["interval", "register"],
        "why": "Interval kWh per period vs. cumulative register (dial) reads.",
    },
    "net_metering_policy": {
        "options": ["negative_is_export", "negative_is_error", "per_meter"],
        "why": ("Negative values are valid export on net-metered premises, errors otherwise. "
                "'per_meter' needs net_metered_meter_ids (from a premise/DER table)."),
    },
    "linear_max_gap_intervals": {
        "options": "integer ≥ 0; common rulebook choices are 1-2 hours of intervals",
        "why": "Longest gap filled by straight-line interpolation between valid neighbours.",
    },
    "long_gap_method": {
        "options": ["like_day", "leave_missing"],
        "why": "How gaps longer than the linear limit are handled.",
    },
    "max_estimation_gap_hours": {
        "options": "hours > 0; gaps longer than this stay MISSING (e.g. 24, 72, 168)",
        "why": "Billing rules cap how much consumption may be estimated.",
    },
    "spike_max_kw": {
        "options": "kW ceiling, e.g. service size: 200 A x 240 V ≈ 48 kW residential",
        "why": "Demand above the physical service capacity is a meter/data error.",
    },
}

ENUMS = {
    "timestamp_basis": {"local_naive", "utc", "offset_aware"},
    "interval_convention": {"ending", "beginning"},
    "read_type": {"interval", "register"},
    "net_metering_policy": {"negative_is_export", "negative_is_error", "per_meter"},
    "long_gap_method": {"like_day", "leave_missing"},
}


class DecisionRequired(ValueError):
    """Raised when an analyst-owned decision has not been made."""

    def __init__(self, decision: str, detail: str = "") -> None:
        spec = DECISIONS.get(decision, {})
        msg = (f"Decision required: '{decision}'. Options: {spec.get('options', 'see SKILL.md')}. "
               f"{spec.get('why', '')} {detail}").strip()
        super().__init__(msg)
        self.decision = decision


@dataclass(frozen=True)
class VeeConfig:
    """Validated, immutable VEE configuration. Build with ``make_config``."""

    interval_minutes: int
    source_timezone: str
    timestamp_basis: str
    interval_convention: str
    read_type: str
    net_metering_policy: str
    linear_max_gap_intervals: int
    long_gap_method: str
    max_estimation_gap_hours: float
    spike_max_kw: float
    register_rollover_kwh: float | None = None
    net_metered_meter_ids: frozenset[str] | None = None
    flatline_min_hours: float = 4.0
    extended_zero_hours: float = 24.0
    like_days: int = 4
    like_day_lookback_days: int = 21
    reconciliation_tolerance_pct: float = 1.0

    @property
    def interval_hours(self) -> float:
        return self.interval_minutes / 60.0

    def for_meter(self, meter_id: str) -> "VeeConfig":
        """Resolve a per-meter net-metering policy to export / error for ``meter_id``."""
        if self.net_metering_policy != "per_meter":
            return self
        policy = ("negative_is_export" if meter_id in (self.net_metered_meter_ids or ())
                  else "negative_is_error")
        return replace(self, net_metering_policy=policy)

    @property
    def max_estimation_gap_intervals(self) -> int:
        return int(self.max_estimation_gap_hours * 60 // self.interval_minutes)


def _check_enums(values: dict) -> None:
    for key, allowed in ENUMS.items():
        if values[key] not in allowed:
            raise DecisionRequired(key, f"Got {values[key]!r}.")


def _check_numbers(values: dict) -> None:
    if int(values["interval_minutes"]) <= 0 or 1440 % int(values["interval_minutes"]):
        raise DecisionRequired("interval_minutes", "Must divide 1440.")
    if int(values["linear_max_gap_intervals"]) < 0:
        raise DecisionRequired("linear_max_gap_intervals", "Must be ≥ 0.")
    if float(values["max_estimation_gap_hours"]) <= 0:
        raise DecisionRequired("max_estimation_gap_hours", "Must be > 0.")
    if float(values["spike_max_kw"]) <= 0:
        raise DecisionRequired("spike_max_kw", "Must be > 0.")


def make_config(**decisions) -> VeeConfig:
    """Validate decisions and return a ``VeeConfig``; raise ``DecisionRequired`` if any is unset."""
    for name in DECISIONS:
        if decisions.get(name) is None:
            raise DecisionRequired(name)
    try:
        ZoneInfo(decisions["source_timezone"])
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise DecisionRequired("source_timezone", f"Unknown zone: {exc}") from exc
    _check_enums(decisions)
    _check_numbers(decisions)
    if decisions["read_type"] == "register" and not decisions.get("register_rollover_kwh"):
        raise ValueError(
            "Decision required: 'register_rollover_kwh' (dial capacity, e.g. 100000 for a "
            "5-dial kWh register) when read_type='register'.")
    if decisions["net_metering_policy"] == "per_meter":
        ids = decisions.get("net_metered_meter_ids")
        if ids is None:
            raise ValueError("Decision required: 'net_metered_meter_ids' (meters whose "
                             "negative reads are export) when net_metering_policy='per_meter'.")
        decisions = {**decisions, "net_metered_meter_ids": frozenset(str(i) for i in ids)}
    known = set(VeeConfig.__dataclass_fields__)
    unknown = set(decisions) - known
    if unknown:
        raise ValueError(f"Unknown configuration keys: {sorted(unknown)}")
    return VeeConfig(**decisions)


def build_manifest(config: VeeConfig, inputs: dict, outputs: dict) -> dict:
    """Machine-readable record of a run: inputs, every decision, versions, outputs."""
    decisions = {k: (sorted(v) if isinstance(v, frozenset) else v)
                 for k, v in asdict(config).items()}
    digest = hashlib.sha256(json.dumps(decisions, sort_keys=True).encode()).hexdigest()
    return {
        "run_id": str(uuid.uuid4()),
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "skill": SKILL_NAME,
        "skill_version": SKILL_VERSION,
        "inputs": inputs,
        "decisions": decisions,
        "decisions_sha256": digest,
        "conventions": {
            "output_time": "interval_start_utc (interval-beginning, UTC)",
            "energy_unit": "kWh per interval",
        },
        "outputs": outputs,
    }
