"""Scorers for the reliability-metrics eval: deterministic checks + LLM judge guidelines.

Deterministic scorers are plain functions over (outputs, expectation, truth) so they run
offline. `mlflow_scorers()` wraps them for mlflow.genai.evaluate when MLflow is present.

outputs: {"response": str, "action_log": str, "notebook_source": str, "answer": dict}
truth:   the answer key written by generate_data.py (truth.json)
"""

from __future__ import annotations

import math
from typing import Literal


def _scenario_values(truth: dict, path: str) -> list[float]:
    """Truth values for a dotted path; 'scenarios.x.y' expands across all 16 scenarios."""
    parts = path.split(".")
    if parts[0] != "scenarios":
        return [float(truth[parts[0]])]
    return [float(s[parts[1]][parts[2]]) for s in truth["scenarios"]]


def numeric_matches(outputs: dict, checks: dict, truth: dict) -> dict:
    """Each reported number must match some valid decision scenario within tolerance.

    Any defensible decision combination is accepted; a wrong method (final-restore CMI,
    same-year MED fit, UTC dating) matches none of them.
    """
    answer = outputs.get("answer") or {}
    failures = []
    for spec in checks.get("numeric", []):
        got = answer.get(spec["key"])
        if got is None:
            failures.append(f"missing {spec['key']}")
            continue
        valid = _scenario_values(truth, spec["truth"])
        if not any(math.isclose(float(got), v, rel_tol=spec["rel_tol"], abs_tol=1e-9)
                   for v in valid):
            failures.append(f"{spec['key']}={got} matches no valid scenario")
    return {"name": "numeric_matches", "value": not failures,
            "rationale": "; ".join(failures) or "all numbers match a valid scenario"}


def med_days_correct(outputs: dict, checks: dict, truth: dict) -> dict:
    days = {str(d)[:10] for d in (outputs.get("answer") or {}).get("major_event_days", [])}
    missing = [d for d in checks.get("med_days_must_include", []) if d not in days]
    wrong = [d for d in checks.get("med_days_must_exclude", []) if d in days]
    ok = not missing and not wrong
    return {"name": "med_days_correct", "value": ok,
            "rationale": f"missing {missing}, wrongly included {wrong}" if not ok else "ok"}


def sql_tokens_present(outputs: dict, checks: dict, truth: dict) -> dict:
    sql = str((outputs.get("answer") or {}).get("metric_view_sql", ""))
    missing = [t for t in checks.get("required_sql_tokens", []) if t not in sql]
    return {"name": "sql_tokens_present", "value": not missing,
            "rationale": f"missing {missing}" if missing else "ok"}


def no_forbidden_patterns(outputs: dict, checks: dict, truth: dict) -> dict:
    evidence = " ".join(str(outputs.get(k, "")) for k in ("response", "action_log",
                                                          "notebook_source"))
    evidence += str((outputs.get("answer") or {}).get("metric_view_sql", ""))
    hits = [p for p in checks.get("forbidden_patterns", []) if p.lower() in evidence.lower()]
    return {"name": "no_forbidden_patterns", "value": not hits,
            "rationale": f"found {hits}" if hits else "ok"}


DETERMINISTIC = (numeric_matches, med_days_correct, sql_tokens_present, no_forbidden_patterns)


def score_task(outputs: dict, expectation: dict, truth: dict) -> list[dict]:
    """Run every deterministic scorer relevant to one task."""
    checks = expectation.get("deterministic_checks", {})
    relevant = {
        numeric_matches: "numeric" in checks,
        med_days_correct: "med_days_must_include" in checks,
        sql_tokens_present: "required_sql_tokens" in checks,
        no_forbidden_patterns: "forbidden_patterns" in checks,
    }
    return [fn(outputs, checks, truth) for fn, use in relevant.items() if use]


JUDGE_INSTRUCTIONS = """
You are grading a distribution reliability analysis against IEEE 1366.
Task: {{ inputs }}
Session evidence: {{ outputs }}
Expected facts and guidelines: {{ expectations }}
Pass only if the evidence computes customer-minutes per restoration step, separates
momentary from sustained interruptions, derives T_MED from prior-year history with the
2.5 beta method (zero days excluded), and either asks the user for the reporting decisions
or states them explicitly. Answer exactly 'yes' or 'no'.
"""


def mlflow_scorers(truth: dict) -> list:
    """Wrap deterministic scorers + an IEEE 1366 judge for mlflow.genai.evaluate."""
    from mlflow.entities import Feedback
    from mlflow.genai.judges import make_judge
    from mlflow.genai.scorers import ExpectationsGuidelines, scorer

    def wrap(fn):
        @scorer(name=fn.__name__)
        def _s(outputs: dict, expectations: dict) -> Feedback:
            r = fn(outputs, expectations.get("deterministic_checks", {}), truth)
            return Feedback(name=r["name"], value=r["value"], rationale=r["rationale"])
        return _s

    judge = make_judge(name="ieee1366_method", instructions=JUDGE_INSTRUCTIONS,
                       feedback_value_type=Literal["yes", "no"],
                       model="databricks:/databricks-claude-sonnet-5-5")
    return [*(wrap(f) for f in DETERMINISTIC), ExpectationsGuidelines(), judge]
