"""Scorers for a skill benchmark (shared shape across energy skills).

Deterministic checks are plain Python (importable offline). `mlflow_scorers()` wraps them,
plus an ExpectationsGuidelines judge, for mlflow.genai.evaluate. `outputs` per task:
    {"response": str, "action_log": str, "notebook_source": str, "answer": {metric: value}}
"""

from __future__ import annotations

import re


def _evidence(outputs: dict) -> str:
    return " ".join(str(outputs.get(k, "")) for k in ("response", "action_log", "notebook_source"))


def numeric_truth_score(outputs: dict, checks: dict) -> tuple[float, str]:
    """Fraction of planted numbers reproduced within relative tolerance in answer.json."""
    truth, tol = checks.get("numeric_truth", {}), float(checks.get("numeric_tolerance_rel", 0.02))
    answer = outputs.get("answer") or {}
    hits, misses = 0, []
    for key, expected in truth.items():
        got = answer.get(key)
        if isinstance(expected, bool) or not isinstance(expected, (int, float)):
            ok = got == expected
        else:
            ok = isinstance(got, (int, float)) and abs(got - expected) <= tol * max(abs(expected), 1e-9)
        hits += ok
        if not ok:
            misses.append(f"{key}: expected {expected}, got {got}")
    score = hits / len(truth) if truth else 1.0
    return score, "all numbers within tolerance" if not misses else "; ".join(misses)


def required_tokens_present(outputs: dict, checks: dict) -> tuple[bool, str]:
    text = _evidence(outputs).lower()
    missing = [t for t in checks.get("required_tokens", []) if t.lower() not in text]
    return not missing, "ok" if not missing else f"missing: {missing}"


def no_forbidden_patterns(outputs: dict, checks: dict) -> tuple[bool, str]:
    text = _evidence(outputs)
    found = [p for p in checks.get("forbidden_patterns", []) if re.search(p, text, re.IGNORECASE)]
    return not found, "ok" if not found else f"found: {found}"


DETERMINISTIC = {"numeric_truth": numeric_truth_score, "required_tokens": required_tokens_present,
                 "no_forbidden_patterns": no_forbidden_patterns}


def mlflow_scorers() -> list:
    """Build MLflow scorers lazily (mlflow is only needed inside the scoring notebook)."""
    from mlflow.entities import Feedback
    from mlflow.genai.scorers import ExpectationsGuidelines, scorer

    def wrap(name, fn):
        @scorer(name=name)
        def _s(outputs: dict, expectations: dict) -> Feedback:
            value, why = fn(outputs, expectations.get("deterministic_checks", {}))
            return Feedback(name=name, value=value, rationale=why)
        return _s

    return [wrap(n, f) for n, f in DETERMINISTIC.items()] + [ExpectationsGuidelines()]
