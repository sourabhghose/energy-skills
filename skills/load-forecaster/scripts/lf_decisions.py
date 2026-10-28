"""Decision points, validated forecast configuration, and run manifests for load-forecaster.

``make_config`` refuses to build while any analyst-owned decision is unset and raises
``DecisionRequired`` naming the decision and its options.

    from lf_decisions import make_config
    cfg = make_config(weather_station="KORD", temperature_unit="F", hdd_base=65, ...)
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

SKILL_NAME = "load-forecaster"
SKILL_VERSION = "0.1.0"

DECISIONS: dict[str, dict] = {
    "local_timezone": {"options": "IANA zone of the load area, e.g. America/Chicago",
                       "why": "Calendar features (hour, weekday, holidays) are local."},
    "load_timestamp_basis": {"options": ["utc", "local_naive"],
                             "why": "EIA-930 is UTC; many utility historians export local."},
    "load_interval_convention": {"options": ["ending", "beginning"],
                                 "why": "Hour-ending (HE01 = 00:00-01:00) is the utility norm."},
    "load_unit": {"options": ["MW", "kW"], "why": "Hourly average demand unit; energy is MWh."},
    "weather_station": {"options": "station id from the preview ranking",
                        "why": "Coverage, distance, and fit to load differ by station."},
    "temperature_unit": {"options": ["F", "C"],
                         "why": "Degree-day bases are unit-specific (65 F ≈ 18.3 C)."},
    "hdd_base": {"options": "base temperature in temperature_unit (65 F / 18 C convention, or "
                            "the fitted balance point from the preview)",
                 "why": "Sets where heating load starts."},
    "cdd_base": {"options": "base temperature in temperature_unit",
                 "why": "Sets where cooling load starts."},
    "holiday_calendar": {"options": ["nerc", "us_federal", "none"],
                         "why": "NERC off-peak holidays vs federal holidays change load shape."},
    "horizon_hours": {"options": "24 (day-ahead), 168 (week-ahead), ...",
                      "why": "Load lags shorter than the horizon would leak the future."},
    "model_family": {"options": ["degree_day_regression", "gbm"],
                     "why": "Transparent regression vs gradient boosting (needs scikit-learn)."},
    "normal_years": {"options": "inclusive (first_year, last_year) for weather normals, e.g. "
                                "(1991, 2020) NOAA normals period or a trailing 10/20 years",
                     "why": "Weather-normalized energy depends on what 'normal' means."},
}

ENUMS = {"load_timestamp_basis": {"utc", "local_naive"},
         "load_interval_convention": {"ending", "beginning"},
         "load_unit": {"MW", "kW"}, "temperature_unit": {"F", "C"},
         "holiday_calendar": {"nerc", "us_federal", "none"},
         "model_family": {"degree_day_regression", "gbm"}}


class DecisionRequired(ValueError):
    """Raised when an analyst-owned decision has not been made."""

    def __init__(self, decision: str, detail: str = "") -> None:
        spec = DECISIONS.get(decision, {})
        super().__init__(f"Decision required: '{decision}'. Options: "
                         f"{spec.get('options', 'see SKILL.md')}. {spec.get('why', '')} "
                         f"{detail}".strip())
        self.decision = decision


@dataclass(frozen=True)
class ForecastConfig:
    """Validated, immutable forecast configuration. Build with ``make_config``."""

    local_timezone: str
    load_timestamp_basis: str
    load_interval_convention: str
    load_unit: str
    weather_station: str
    temperature_unit: str
    hdd_base: float
    cdd_base: float
    holiday_calendar: str
    horizon_hours: int
    model_family: str
    normal_years: tuple[int, int]
    backtest_folds: int = 6
    backtest_step_hours: int = 168
    min_train_days: int = 365
    max_weather_gap_hours: int = 3

    @property
    def mw_factor(self) -> float:
        return 1.0 if self.load_unit == "MW" else 1e-3


def _validate(values: dict) -> dict:
    for key, allowed in ENUMS.items():
        if values[key] not in allowed:
            raise DecisionRequired(key, f"Got {values[key]!r}.")
    try:
        ZoneInfo(values["local_timezone"])
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise DecisionRequired("local_timezone", str(exc)) from exc
    if int(values["horizon_hours"]) < 1:
        raise DecisionRequired("horizon_hours", "Must be ≥ 1.")
    years = tuple(int(y) for y in values["normal_years"])
    if len(years) != 2 or years[0] > years[1]:
        raise DecisionRequired("normal_years", "Give (first_year, last_year).")
    if float(values["cdd_base"]) < float(values["hdd_base"]):
        raise DecisionRequired("cdd_base", "cdd_base must be ≥ hdd_base.")
    return {**values, "normal_years": years, "horizon_hours": int(values["horizon_hours"])}


def make_config(**decisions) -> ForecastConfig:
    """Validate decisions and return a ``ForecastConfig``; raise ``DecisionRequired`` if unset."""
    for name in DECISIONS:
        if decisions.get(name) is None:
            raise DecisionRequired(name)
    unknown = set(decisions) - set(ForecastConfig.__dataclass_fields__)
    if unknown:
        raise ValueError(f"Unknown configuration keys: {sorted(unknown)}")
    return ForecastConfig(**_validate(decisions))


def build_manifest(config: ForecastConfig, inputs: dict, outputs: dict) -> dict:
    """Machine-readable record of a run: inputs, every decision, versions, outputs."""
    decisions = asdict(config)
    return {
        "run_id": str(uuid.uuid4()),
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "skill": SKILL_NAME, "skill_version": SKILL_VERSION,
        "inputs": inputs, "decisions": decisions,
        "decisions_sha256": hashlib.sha256(
            json.dumps(decisions, sort_keys=True, default=str).encode()).hexdigest(),
        "conventions": {"time": "hour_start_utc (hour-beginning, UTC)", "load": "MW",
                        "energy": "MWh", "backtest_weather": "actual (ex-post) weather"},
        "outputs": outputs,
    }
