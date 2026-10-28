"""Scorers for the energy-report-writer eval (MLflow 3 genai.evaluate).

Exports `scorers`. Rows follow skills/skill-eval/references/benchmark-tasks.md:
outputs.response holds the delivered document text; deterministic_checks are
merged into expectations.
"""

from __future__ import annotations

import re
from typing import Literal

from mlflow.entities import Feedback
from mlflow.genai.judges import make_judge
from mlflow.genai.scorers import Correctness, ExpectationsGuidelines, scorer

JUDGE = "databricks:/databricks-gpt-5-mini"
MINUTES = re.compile(r"(\d[\d,]*\.?\d*)\s*min(?:utes)?\b", re.IGNORECASE)


@scorer
def artifact_produced(outputs: dict, expectations: dict) -> bool:
    """Pass if every required artifact name appears in the session's artifact list."""
    artifacts = str(outputs.get("artifacts", ""))
    return all(name in artifacts for name in expectations.get("required_artifacts", []))


@scorer
def required_notices_present(outputs: dict, expectations: dict) -> Feedback:
    text = " ".join(str(outputs.get("response", "")).lower().split())
    missing = [p for p in expectations.get("required_phrases", []) if p.lower() not in text]
    return Feedback(name="required_notices_present", value=not missing,
                    rationale=f"missing: {missing}" if missing else "all present")


@scorer
def no_forbidden_content(outputs: dict, expectations: dict) -> Feedback:
    response = str(outputs.get("response", ""))
    hits = [p for p in expectations.get("forbidden_patterns", []) if re.search(p, response)]
    return Feedback(name="no_forbidden_content", value=not hits,
                    rationale=f"found: {hits}" if hits else "none found")


@scorer
def planted_value_within_tolerance(outputs: dict, expectations: dict) -> Feedback:
    """Every planted number must appear next to its unit, within tolerance."""
    response = str(outputs.get("response", ""))
    for metric, spec in expectations.get("ground_truth_estimates", {}).items():
        unit = re.escape(spec["unit"])
        found = [float(m.replace(",", "")) for m in
                 re.findall(rf"(\d[\d,]*\.?\d*)\s*{unit}\b", response, re.IGNORECASE)]
        if not any(abs(v - spec["value"]) <= spec["tolerance"] for v in found):
            return Feedback(name="planted_value_within_tolerance", value=False,
                            rationale=f"{metric}: expected {spec['value']} {spec['unit']}, found {found}")
    return Feedback(name="planted_value_within_tolerance", value=True)


@scorer
def no_invented_index_values(outputs: dict, expectations: dict) -> Feedback:
    """Index-sized minute values (>= 100 min) must match a value in the input table.

    Smaller values (year-over-year changes) are derived and not checked here.
    """
    allowed = expectations.get("allowed_minutes")
    if not allowed:
        return Feedback(name="no_invented_index_values", value=True, rationale="not applicable")
    tol = float(expectations.get("minute_tolerance", 1.0))
    stated = [float(m.replace(",", "")) for m in MINUTES.findall(str(outputs.get("response", "")))]
    invented = [v for v in stated if v >= 100 and not any(abs(v - a) <= tol for a in allowed)]
    return Feedback(name="no_invented_index_values", value=not invented,
                    rationale=f"not in input: {invented}" if invented else "all traced")


surfaced_basis_judge = make_judge(
    name="surfaced_decision",
    instructions="""
Review {{ outputs }} for the task in {{ inputs }}. Expectations: {{ expectations }}.
If expectations list required_decisions, pass only if the agent asked the user which basis to
headline (for reliability: including vs. excluding Major Event Days) before finalizing, OR the
document reports both bases clearly labelled. Fail if it silently used one basis.
If no required_decisions are listed, answer 'yes'.
Answer with exactly one word: 'yes' or 'no'.
""",
    feedback_value_type=Literal["yes", "no"],
    model=JUDGE,
)

scorers = [
    artifact_produced,
    required_notices_present,
    no_forbidden_content,
    planted_value_within_tolerance,
    no_invented_index_values,
    Correctness(model=JUDGE),
    ExpectationsGuidelines(),
    surfaced_basis_judge,
]
