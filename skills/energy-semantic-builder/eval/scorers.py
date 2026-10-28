"""Scorers for the energy-semantic-builder eval: deterministic checks + an LLM judge.

outputs: {"response": str, "action_log": str, "notebook_source": str, "answer": dict}
truth:   answer key from generate_data.py (truth.json)
"""

from __future__ import annotations

import math
from typing import Literal


def _lookup(truth: dict, path: str) -> float:
    node = truth
    for part in path.split("."):
        node = node[part]
    return float(node)


def numeric_matches(outputs: dict, checks: dict, truth: dict) -> dict:
    """Each number must match one of the defensible truths (one per decision option)."""
    answer = outputs.get("answer") or {}
    failures = []
    for spec in checks.get("numeric", []):
        got = answer.get(spec["key"])
        valid = [_lookup(truth, p) for p in spec["truth_any"]]
        if got is None or not any(math.isclose(float(got), v, rel_tol=spec["rel_tol"]) for v in valid):
            failures.append(f"{spec['key']}={got} not within {spec['rel_tol']:.1%} of {valid}")
    return {"name": "numeric_matches", "value": not failures,
            "rationale": "; ".join(failures) or "ok"}


def sql_tokens_present(outputs: dict, checks: dict, truth: dict) -> dict:
    sql = str((outputs.get("answer") or {}).get("metric_view_sql", ""))
    missing = [t for t in checks.get("required_sql_tokens", []) if t not in sql]
    return {"name": "sql_tokens_present", "value": not missing,
            "rationale": f"missing {missing}" if missing else "ok"}


def no_forbidden_patterns(outputs: dict, checks: dict, truth: dict) -> dict:
    text = " ".join(str(outputs.get(k, "")) for k in ("response", "notebook_source"))
    text += str((outputs.get("answer") or {}).get("metric_view_sql", ""))
    hits = [p for p in checks.get("forbidden_patterns", []) if p.lower() in text.lower()]
    return {"name": "no_forbidden_patterns", "value": not hits,
            "rationale": f"found {hits}" if hits else "ok"}


def score_task(outputs: dict, expectation: dict, truth: dict) -> list[dict]:
    checks = expectation.get("deterministic_checks", {})
    fns = {numeric_matches: "numeric", sql_tokens_present: "required_sql_tokens",
           no_forbidden_patterns: "forbidden_patterns"}
    return [fn(outputs, checks, truth) for fn, key in fns.items() if key in checks]


JUDGE_INSTRUCTIONS = """
You are grading an energy KPI analysis or semantic-layer build.
Task: {{ inputs }}
Session evidence: {{ outputs }}
Expected facts and guidelines: {{ expectations }}
Pass only if every rate is computed as a ratio of sums (never an average of per-well or
per-unit ratios), units are converted to canonical units before use, and choices that
change the number (boe conversion ratio, GADS pooling, capacity basis) are asked for or
explicitly stated. Answer exactly 'yes' or 'no'.
"""


def mlflow_scorers(truth: dict) -> list:
    from mlflow.entities import Feedback
    from mlflow.genai.judges import make_judge
    from mlflow.genai.scorers import ExpectationsGuidelines, scorer

    @scorer
    def deterministic(outputs: dict, expectations: dict) -> list[Feedback]:
        return [Feedback(name=r["name"], value=r["value"], rationale=r["rationale"])
                for r in score_task(outputs, expectations, truth)]

    judge = make_judge(name="kpi_method", instructions=JUDGE_INSTRUCTIONS,
                       feedback_value_type=Literal["yes", "no"],
                       model="databricks:/databricks-claude-sonnet-5-5")
    return [deterministic, ExpectationsGuidelines(), judge]
