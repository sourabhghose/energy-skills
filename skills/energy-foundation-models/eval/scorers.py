#!/usr/bin/env python3
"""Scorers for the energy-foundation-models skill evaluation.

Level 1 (deterministic @scorer): artifact_produced, required_patterns, no_forbidden_content.
Level 2 (binary LLM judges): decisions_surfaced, factually_grounded.

Outputs are the markdown answers Genie Code saved per task (outputs["response"]).
expectations come from expectations.json (expected_facts, guidelines, deterministic_checks).

    pip install "mlflow[databricks]>=3.5.0"
"""

from __future__ import annotations

import re
from typing import Literal

from mlflow.entities import Feedback
from mlflow.genai.judges import make_judge
from mlflow.genai.scorers import scorer

JUDGE_MODEL = "databricks:/databricks-gpt-5-mini"  # must differ from the Genie Code model


def _groups_matched(text: str, groups: list[list[str]]) -> list[list[str]]:
    """Return the pattern groups with no match (case-insensitive)."""
    return [g for g in groups if not any(re.search(p, text, re.IGNORECASE) for p in g)]


@scorer
def artifact_produced(outputs: dict) -> bool:
    return bool(str(outputs.get("response", "")).strip())


@scorer
def required_patterns(outputs: dict, expectations: dict) -> Feedback:
    checks = expectations.get("deterministic_checks", {})
    missing = _groups_matched(str(outputs.get("response", "")), checks.get("required_patterns", []))
    return Feedback(name="required_patterns", value=not missing,
                    rationale=f"No match for {missing}" if missing else None)


@scorer
def no_forbidden_content(outputs: dict, expectations: dict) -> Feedback:
    text = str(outputs.get("response", ""))
    hits = [p for p in expectations.get("deterministic_checks", {}).get("forbidden_patterns", [])
            if re.search(p, text, re.IGNORECASE)]
    return Feedback(name="no_forbidden_content", value=not hits,
                    rationale=f"Forbidden pattern(s): {hits}" if hits else None)


decisions_surfaced = make_judge(
    name="decisions_surfaced",
    instructions="""
You are grading whether an assistant left user-owned decisions to the user when packaging an
energy forecasting or satellite model.

User request: {{ inputs }}
Assistant answer: {{ outputs }}

Pass only if the answer either asks the user to confirm, or explicitly states as an assumption
to be confirmed, the decisions that apply to this request among: model choice, weights licence
acceptance, compute (CPU/GPU/batch), forecast horizon, quantile levels, whether to clip
forecasts at zero, and how to treat gaps. Silently hard-coding these is a failure.

Answer with exactly one word: 'yes' or 'no'.
""",
    feedback_value_type=Literal["yes", "no"],
    model=JUDGE_MODEL,
)

factually_grounded = make_judge(
    name="factually_grounded",
    instructions="""
You are grading whether an assistant's answer about open-weight energy foundation models is
consistent with known facts.

User request: {{ inputs }}
Assistant answer: {{ outputs }}
Known facts and guidelines: {{ expectations }}

Fail if the answer contradicts any known fact (for example, calls a non-commercial licence
permissive, or claims a model supports a horizon or covariates it does not) or breaks any
guideline. Missing facts are acceptable unless a guideline requires them.

Answer with exactly one word: 'yes' or 'no'.
""",
    feedback_value_type=Literal["yes", "no"],
    model=JUDGE_MODEL,
)

scorers = [artifact_produced, required_patterns, no_forbidden_content, decisions_surfaced,
           factually_grounded]
