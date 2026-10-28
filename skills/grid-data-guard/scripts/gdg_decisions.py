"""Decision points and validated release configuration for grid-data-guard.

Which decisions are required depends on ``release_audience``:

- ``internal_need_to_know``: record-level governed view. Needs ``privileged_group`` (sees
  CEII and direct PII) and, if ID columns exist, ``tokenization_secret`` (``scope/key``).
- ``external_partner`` / ``public``: aggregate-only release. Needs ``aggregation_rule``,
  ``group_by``, ``time_grain``, and a ``geo_method`` when grouping by location.

    from gdg_decisions import make_config
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

SKILL_NAME = "grid-data-guard"
SKILL_VERSION = "0.1.0"
AUDIENCES = ("internal_need_to_know", "external_partner", "public")

DECISIONS: dict[str, dict] = {
    "release_audience": {"options": list(AUDIENCES),
                         "why": "Determines record-level (internal) vs aggregate-only release."},
    "privileged_group": {"options": "UC account group allowed to see CEII / direct PII",
                         "why": "Internal views mask sensitive columns for everyone else."},
    "tokenization_secret": {"options": "Databricks secret as 'scope/key' (salt for HMAC tokens)",
                            "why": "Unsalted hashes of account numbers are reversible by "
                                   "enumeration."},
    "aggregation_rule": {"options": ["15_15", "k_only"],
                         "why": "15/15: ≥15 customers and no customer >15 % of the group's load "
                                "(CPUC aggregation standard); k_only: ≥k customers."},
    "k_min": {"options": "integer ≥ 2 (15 for 15/15)", "why": "Minimum customers per cell."},
    "group_by": {"options": "columns to aggregate by (e.g. zip, rate_class) and/or 'geo'",
                 "why": "Grouping grain sets both utility and re-identification risk."},
    "time_grain": {"options": ["month", "day", "hour"],
                   "why": "Finer grains raise re-identification risk from load shapes."},
    "geo_method": {"options": ["h3", "round", "none"],
                   "why": "How precise coordinates are generalized when grouping by 'geo'."},
    "geo_precision": {"options": "H3 resolution (e.g. 7 ≈ 5 km², 8 ≈ 0.7 km²) or decimal "
                                 "places for rounding (2 ≈ 1.1 km)",
                      "why": "Coarser cells protect location; finer cells serve planning."},
}

ID_SAFE = re.compile(r"^[A-Za-z0-9_]+$")


class DecisionRequired(ValueError):
    """Raised when an analyst / privacy-officer decision has not been made."""

    def __init__(self, decision: str, detail: str = "") -> None:
        spec = DECISIONS.get(decision, {})
        super().__init__(f"Decision required: '{decision}'. Options: "
                         f"{spec.get('options', 'see SKILL.md')}. {spec.get('why', '')} "
                         f"{detail}".strip())
        self.decision = decision


@dataclass(frozen=True)
class GuardConfig:
    """Validated, immutable release configuration. Build with ``make_config``."""

    release_audience: str
    privileged_group: str | None = None
    tokenization_secret: str | None = None
    aggregation_rule: str | None = None
    k_min: int | None = None
    max_share_pct: float = 15.0
    group_by: tuple[str, ...] = ()
    time_grain: str | None = None
    geo_method: str | None = None
    geo_precision: float | None = None
    complementary_suppression: bool = True

    @property
    def aggregate_only(self) -> bool:
        return self.release_audience != "internal_need_to_know"


def _require(values: dict, name: str, detail: str = "") -> None:
    if values.get(name) in (None, "", ()):
        raise DecisionRequired(name, detail)


def _internal(values: dict, has_ids: bool) -> dict:
    _require(values, "privileged_group")
    if not ID_SAFE.match(str(values["privileged_group"]).replace("-", "_")):
        raise DecisionRequired("privileged_group", "Use a plain group name.")
    if has_ids:
        _require(values, "tokenization_secret", "ID columns were found.")
        if not re.match(r"^[\w.-]+/[\w.-]+$", str(values["tokenization_secret"])):
            raise DecisionRequired("tokenization_secret", "Format 'scope/key'.")
    return values


def _aggregate(values: dict) -> dict:
    for name in ("aggregation_rule", "group_by", "time_grain"):
        _require(values, name)
    if values["aggregation_rule"] not in ("15_15", "k_only"):
        raise DecisionRequired("aggregation_rule", f"Got {values['aggregation_rule']!r}.")
    if values["time_grain"] not in ("month", "day", "hour"):
        raise DecisionRequired("time_grain", f"Got {values['time_grain']!r}.")
    if values["aggregation_rule"] == "15_15":
        if values.get("k_min") not in (None, 15) or float(values.get("max_share_pct", 15)) != 15:
            raise DecisionRequired("aggregation_rule", "15/15 fixes k=15 and share=15 %; use "
                                                      "'k_only' for other thresholds.")
        k = 15
    else:
        k = values.get("k_min")
        if k is None or int(k) < 2:
            raise DecisionRequired("k_min")
    group_by = tuple(values["group_by"])
    if "geo" in group_by:
        _require(values, "geo_method")
        if values["geo_method"] not in ("h3", "round"):
            raise DecisionRequired("geo_method", "Grouping by 'geo' needs 'h3' or 'round'.")
        _require(values, "geo_precision")
    return {**values, "k_min": int(k), "group_by": group_by}


def make_config(*, has_id_columns: bool, **decisions) -> GuardConfig:
    """Validate decisions for the chosen audience; raise ``DecisionRequired`` when unset."""
    _require(decisions, "release_audience")
    if decisions["release_audience"] not in AUDIENCES:
        raise DecisionRequired("release_audience", f"Got {decisions['release_audience']!r}.")
    unknown = set(decisions) - set(GuardConfig.__dataclass_fields__)
    if unknown:
        raise ValueError(f"Unknown configuration keys: {sorted(unknown)}")
    clean = {k: v for k, v in decisions.items() if v is not None}
    if decisions["release_audience"] == "internal_need_to_know":
        return GuardConfig(**_internal(clean, has_id_columns))
    return GuardConfig(**_aggregate(clean))


def build_manifest(config: GuardConfig, inputs: dict, outputs: dict, plan: dict) -> dict:
    decisions = asdict(config)
    return {"run_id": str(uuid.uuid4()), "created_utc": datetime.now(timezone.utc).isoformat(),
            "skill": SKILL_NAME, "skill_version": SKILL_VERSION, "inputs": inputs,
            "decisions": decisions, "column_plan": plan,
            "decisions_sha256": hashlib.sha256(
                json.dumps(decisions, sort_keys=True, default=str).encode()).hexdigest(),
            "outputs": outputs}
