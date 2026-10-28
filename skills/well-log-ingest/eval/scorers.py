"""Scorers for the well-log-ingest benchmark: deterministic checks + an MLflow judge.

Deterministic checks run offline on a captured session (`outputs` dict with keys
response, action_log, notebook_source, artifacts, answer_values). The MLflow judge is
built lazily so this module imports without mlflow.

    from scorers import score_deterministic, mlflow_scorers
    score_deterministic(outputs, expectations["deterministic_checks"])
"""

from __future__ import annotations

import re

JUDGE_INSTRUCTIONS = """
You are grading a petrophysical data-engineering agent session on LAS ingestion.

Task: {{ inputs }}
Session evidence (response, action log, executed code): {{ outputs }}
Expected facts and guidelines: {{ expectations }}

Pass only if the agent standardizes vendor mnemonics to curve families, detects and
confirms units that are missing or contradicted by the values (neutron in percent,
density in kg/m3, sonic in us/m), treats -9999-style sentinels explicitly, converts depth
datum using the header elevations and log-measured-from datum, keeps API numbers as
strings and restores lost leading zeros only with confirmation, and resolves overlapping
runs by a stated policy. Fail if it produces TVDSS from measured depth without a survey,
averages overlapping runs silently, or mixes units in one column. Grade only what is visible.

Answer exactly 'yes' or 'no'.
"""


def _evidence(outputs: dict) -> str:
    return " ".join(str(outputs.get(k, "")) for k in ("response", "action_log", "notebook_source"))


def check_tokens(outputs: dict, checks: dict) -> tuple[bool, str]:
    text = _evidence(outputs).lower()
    missing = [t for t in checks.get("required_action_tokens", []) if t.lower() not in text]
    return not missing, "all required tokens present" if not missing else f"missing: {missing}"


def check_forbidden(outputs: dict, checks: dict) -> tuple[bool, str]:
    text = _evidence(outputs)
    hits = [p for p in checks.get("forbidden_patterns", []) if re.search(p, text, re.IGNORECASE)]
    return not hits, "no forbidden patterns" if not hits else f"forbidden: {hits}"


def check_numeric(outputs: dict, checks: dict) -> tuple[bool, str]:
    expected = checks.get("numeric_answers", {})
    actual = outputs.get("answer_values", {}) or {}
    bad = []
    for key, spec in expected.items():
        value = actual.get(key)
        if value is None or abs(float(value) - spec["value"]) > spec["rel_tol"] * abs(spec["value"]):
            bad.append(f"{key}: got {value}, want {spec['value']} ±{spec['rel_tol']:.1%}")
    return not bad, "numeric answers within tolerance" if not bad else "; ".join(bad)


def check_artifacts(outputs: dict, checks: dict) -> tuple[bool, str]:
    actual = {str(a) for a in outputs.get("artifacts", [])}
    missing = sorted(set(checks.get("required_artifacts", [])) - actual)
    return not missing, "artifacts present" if not missing else f"missing artifacts: {missing}"


CHECKS = {
    "required_actions_present": check_tokens,
    "no_forbidden_patterns": check_forbidden,
    "numeric_answers_correct": check_numeric,
    "required_artifacts_present": check_artifacts,
}


def score_deterministic(outputs: dict, checks: dict) -> dict[str, dict]:
    """Run every deterministic check; returns {name: {"pass": bool, "rationale": str}}."""
    results = {}
    for name, fn in CHECKS.items():
        passed, why = fn(outputs, checks)
        results[name] = {"pass": passed, "rationale": why}
    return results


def mlflow_scorers(judge_model: str = "databricks:/databricks-claude-sonnet-5-5") -> list:
    """MLflow 3 scorers wrapping the deterministic checks plus the method judge."""
    from typing import Literal

    from mlflow.entities import Feedback
    from mlflow.genai.judges import make_judge
    from mlflow.genai.scorers import scorer

    def _wrap(name, fn):
        @scorer(name=name)
        def _s(outputs: dict, expectations: dict) -> Feedback:
            passed, why = fn(outputs, expectations.get("deterministic_checks", {}))
            return Feedback(name=name, value=passed, rationale=why)
        return _s

    judge = make_judge(name="log_ingest_method", instructions=JUDGE_INSTRUCTIONS,
                       feedback_value_type=Literal["yes", "no"], model=judge_model)
    return [_wrap(n, f) for n, f in CHECKS.items()] + [judge]
