"""Scorers for the load-forecaster eval (deterministic + optional MLflow judge).

Each scorer takes ``outputs`` (one arm's captured run: ``response``, ``action_log``,
``notebook_source``, optional ``answers`` dict) and ``expectations`` (one entry of
expectations.json, flattened by the scoring notebook: ``truth``, ``tolerance_pct``,
``expected_facts``, ``guidelines``, ``numeric_answers``, ``required_action_tokens``,
``forbidden_patterns``). The pure functions run offline; ``mlflow_scorers()`` wraps them for
``mlflow.genai.evaluate`` and adds an LLM judge for forecasting method.
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


def metrics_not_implausibly_low(outputs: dict, expectations: dict) -> tuple[bool, str]:
    """Reported error metrics at or above the planted noise floor (lower implies leakage)."""
    reported = outputs.get("answers", {}) or {}
    text = str(outputs.get("response", ""))
    low = []
    for label, floor in expectations.get("min_plausible", {}).items():
        values = [reported[label]] if label in reported else [
            float(m) for m in re.findall(rf"{label}\D{{0,25}}?(\d+(?:\.\d+)?)\s*%", text, re.I)]
        low += [f"{label}={v}" for v in values if v < floor]
    return (not low, "metrics plausible" if not low else f"below noise floor (leakage?): {low}")


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
You are a utility load-forecasting engineer grading an agent's analysis.

Task: {{ inputs }}
Session evidence (response, actions, notebook source): {{ outputs }}
Expected facts and guidelines: {{ expectations }}

Grade PASS only if ALL hold:
1. Evaluation is forward in time (rolling origin / chronological), never a random split, and no
   load lag shorter than the forecast horizon is used.
2. A seasonal-naive benchmark is reported next to the model; backtest weather is called ex-post.
3. Timestamps, DST, units (kW vs MW, °F vs °C) were handled or asked about explicitly.
4. Weather choices (station, HDD/CDD bases, normal period) were justified from the data or
   surfaced to the user, not silently assumed.
5. Reported accuracy is plausible (not below the data's noise floor).
Return PASS or FAIL with a one-paragraph rationale.
"""


def mlflow_scorers() -> list:
    """Wrap the pure checks as MLflow scorers plus the forecasting-method judge (needs mlflow ≥ 3)."""
    from mlflow.entities import Feedback
    from mlflow.genai.judges import make_judge
    from mlflow.genai.scorers import scorer

    def wrap(fn):
        @scorer(name=fn.__name__)
        def _s(outputs: dict, expectations: dict) -> Feedback:
            ok, why = fn(outputs, expectations)
            return Feedback(name=fn.__name__, value=ok, rationale=why)
        return _s

    judge = make_judge(name="forecast_method", instructions=JUDGE_INSTRUCTIONS)
    return [wrap(numeric_answers_correct), wrap(metrics_not_implausibly_low),
            wrap(required_actions_present),
            wrap(no_forbidden_patterns), judge]
