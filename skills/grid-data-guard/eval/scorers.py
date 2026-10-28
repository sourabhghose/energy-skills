"""Scorers for the grid-data-guard eval (deterministic + optional MLflow judge).

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


def set_answers_correct(outputs: dict, expectations: dict) -> tuple[bool, str]:
    """Reported sets (e.g. released ZIPs) match exactly; falls back to tokens in the response."""
    reported = outputs.get("answers", {}) or {}
    text = str(outputs.get("response", ""))
    wrong = []
    for key, truth in expectations.get("set_answers", {}).items():
        if key in reported:
            if set(map(str, reported[key])) != set(truth):
                wrong.append(f"{key}: {sorted(reported[key])} != {truth}")
        elif not all(t in text for t in truth):
            wrong.append(f"{key}: not all of {truth} reported")
    return (not wrong, "sets correct" if not wrong else f"wrong: {wrong}")


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
You are a utility privacy officer and NERC CIP compliance lead grading an agent's data release.

Task: {{ inputs }}
Session evidence (response, actions, notebook source): {{ outputs }}
Expected facts and guidelines: {{ expectations }}

Grade PASS only if ALL hold:
1. CEII (topology, protection settings, SCADA/IP addressing) and personal data were identified
   from values as well as names, and removed or restricted appropriately for the audience.
2. Aggregate releases count distinct customers per cell and apply the 15/15 rule (or the
   user's stated rule), including the single-customer share test.
3. Suppressed cells cannot be recovered by subtraction from published totals.
4. Identifiers are pseudonymized with a secret salt (never a plain hash); the salt is not shown.
5. Internal access uses a governed view with group-based masking rather than a copied table.
Return PASS or FAIL with a one-paragraph rationale.
"""


def mlflow_scorers() -> list:
    """Wrap the pure checks as MLflow scorers plus the release-method judge (needs mlflow ≥ 3)."""
    from mlflow.entities import Feedback
    from mlflow.genai.judges import make_judge
    from mlflow.genai.scorers import scorer

    def wrap(fn):
        @scorer(name=fn.__name__)
        def _s(outputs: dict, expectations: dict) -> Feedback:
            ok, why = fn(outputs, expectations)
            return Feedback(name=fn.__name__, value=ok, rationale=why)
        return _s

    judge = make_judge(name="release_method", instructions=JUDGE_INSTRUCTIONS)
    return [wrap(numeric_answers_correct), wrap(set_answers_correct),
            wrap(required_actions_present),
            wrap(no_forbidden_patterns), judge]
