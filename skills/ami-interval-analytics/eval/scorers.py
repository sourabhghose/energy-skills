"""Scorers for the ami-interval-analytics eval (deterministic + optional MLflow judge).

Each scorer takes ``outputs`` (one arm's captured run: ``response``, ``action_log``,
``notebook_source``, optional ``answers`` dict) and ``expectations`` (one entry of
expectations.json, flattened by the scoring notebook: ``truth``, ``tolerance_pct``,
``expected_facts``, ``guidelines``, ``numeric_answers``, ``required_action_tokens``,
``forbidden_patterns``). The pure functions run offline; ``mlflow_scorers()`` wraps them for
``mlflow.genai.evaluate`` and adds an LLM judge for the VEE method.
"""

from __future__ import annotations

import re

NUMBER = re.compile(r"-?\d[\d,]*\.?\d*")


def _evidence(outputs: dict) -> str:
    return " ".join(str(outputs.get(k, "")) for k in ("response", "action_log", "notebook_source"))


def _numbers(text: str) -> list[float]:
    found = []
    for raw in NUMBER.findall(text):
        try:
            found.append(float(raw.replace(",", "")))
        except ValueError:
            continue
    return found


def numeric_answers_correct(outputs: dict, expectations: dict) -> tuple[bool, str]:
    """Every expected number is reported within ``tolerance_pct`` (answers dict or response)."""
    tol = float(expectations.get("tolerance_pct", 0.5)) / 100
    reported = outputs.get("answers", {}) or {}
    candidates = _numbers(str(outputs.get("response", "")))
    misses = []
    for key, truth in expectations.get("numeric_answers", {}).items():
        values = [reported[key]] if key in reported else candidates
        if not any(abs(float(v) - truth) <= tol * max(abs(truth), 1e-9) for v in values):
            misses.append(f"{key} (truth {truth})")
    return (not misses, "all numeric answers within tolerance" if not misses
            else f"wrong or missing: {misses}")


def required_actions_present(outputs: dict, expectations: dict) -> tuple[bool, str]:
    evidence = _evidence(outputs).lower()
    missing = [t for t in expectations.get("required_action_tokens", [])
               if t.lower() not in evidence]
    return (not missing, "all required actions evidenced" if not missing else f"missing: {missing}")


def no_forbidden_patterns(outputs: dict, expectations: dict) -> tuple[bool, str]:
    evidence = _evidence(outputs)
    hits = [p for p in expectations.get("forbidden_patterns", []) if re.search(p, evidence)]
    return (not hits, "no forbidden patterns" if not hits else f"forbidden: {hits}")


JUDGE_INSTRUCTIONS = """
You are a utility meter-data (MDM/VEE) analyst grading an agent's smart-meter analysis.

Task: {{ inputs }}
Session evidence (response, actions, notebook source): {{ outputs }}
Expected facts and guidelines: {{ expectations }}

Grade PASS only if ALL hold:
1. Timestamps were placed in time correctly: timezone and interval-ending/beginning were stated
   or asked, and DST days were handled (25-hour fall-back day kept, 23-hour spring day not
   counted as missing).
2. Register reads (if any) were differenced, with rollovers corrected and resets not wrapped.
3. Negative values were treated per premise net-metering status, not fleet-wide.
4. Estimated intervals were labelled and reported separately from actual reads.
5. Analyst-owned thresholds (estimation limits, spike ceiling) were surfaced, not silently chosen.
Return PASS or FAIL with a one-paragraph rationale.
"""


def mlflow_scorers() -> list:
    """Wrap the pure checks as MLflow scorers plus the VEE-method judge (needs mlflow ≥ 3)."""
    from mlflow.entities import Feedback
    from mlflow.genai.judges import make_judge
    from mlflow.genai.scorers import scorer

    def wrap(fn):
        @scorer(name=fn.__name__)
        def _s(outputs: dict, expectations: dict) -> Feedback:
            ok, why = fn(outputs, expectations)
            return Feedback(name=fn.__name__, value=ok, rationale=why)
        return _s

    judge = make_judge(name="vee_method", instructions=JUDGE_INSTRUCTIONS)
    return [wrap(numeric_answers_correct), wrap(required_actions_present),
            wrap(no_forbidden_patterns), judge]
