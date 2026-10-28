"""Scorers for the unit-guard benchmark: deterministic checks + an MLflow judge.

Deterministic checks run offline on a captured session (`outputs` dict with keys
response, action_log, notebook_source, artifacts, answer_values). The MLflow judge is
built lazily so this module imports without mlflow.

    from scorers import score_deterministic, mlflow_scorers
    score_deterministic(outputs, expectations["deterministic_checks"])
"""

from __future__ import annotations

import re

JUDGE_INSTRUCTIONS = """
You are grading an energy-data agent session on unit handling.

Task: {{ inputs }}
Session evidence (response, action log, executed code): {{ outputs }}
Expected facts and guidelines: {{ expectations }}

Pass only if every unit conversion is dimensionally valid, every convention-dependent
choice (standard conditions for scf, boe method, GWP set, ton type, HHV/LHV basis) is
either asked of the user or explicitly stated with its source, and every reported number
carries its unit. Fail if the agent silently assumes a convention, mixes power and energy,
uses 35.3147 scf/Sm3 without temperature correction, or treats 'ton' as metric without
saying so. Grade only what is visible in the evidence.

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

    judge = make_judge(name="unit_method", instructions=JUDGE_INSTRUCTIONS,
                       feedback_value_type=Literal["yes", "no"], model=judge_model)
    return [_wrap(n, f) for n, f in CHECKS.items()] + [judge]
