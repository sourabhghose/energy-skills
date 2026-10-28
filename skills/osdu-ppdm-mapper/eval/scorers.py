#!/usr/bin/env python3
"""Scorers for the osdu-ppdm-mapper evaluation.

Level 1 (deterministic): artifact_produced, required_patterns, no_forbidden_content,
numeric_close.
Level 2 (binary LLM judges): facts_correct, decisions_surfaced.

Outputs are the markdown answers Genie Code saved per task (outputs["response"]).
The pure check functions import nothing beyond the stdlib so they can be unit-tested;
`mlflow_scorers()` wraps them for mlflow.genai.evaluate (MLflow 3):
    pip install "mlflow[databricks]>=3.5.0"
"""

from __future__ import annotations

import re

JUDGE_MODEL = "databricks:/databricks-gpt-5-mini"


def check_artifact(outputs: dict) -> tuple[bool, str]:
    ok = bool(str(outputs.get("response", "")).strip())
    return ok, "answer present" if ok else "no answer saved"


def check_required(outputs: dict, checks: dict) -> tuple[bool, str]:
    text = str(outputs.get("response", ""))
    for group in checks.get("required_patterns", []):
        if not any(re.search(p, text, re.IGNORECASE) for p in group):
            return False, f"no match for any of {group}"
    return True, "all required groups matched"


def check_forbidden(outputs: dict, checks: dict) -> tuple[bool, str]:
    text = str(outputs.get("response", ""))
    for pattern in checks.get("forbidden_patterns", []):
        if re.search(pattern, text, re.IGNORECASE):
            return False, f"forbidden pattern found: {pattern}"
    return True, "no forbidden content"


def check_numeric(outputs: dict, checks: dict) -> tuple[bool, str]:
    """Each expected number must appear in the answer within tolerance."""
    text = str(outputs.get("response", ""))
    found = [float(x.replace(",", "")) for x in re.findall(r"-?\d[\d,]*\.?\d*", text)]
    for item in checks.get("numeric", []):
        if not any(abs(v - item["value"]) <= item["tol"] for v in found):
            return False, f"{item['name']}: no value within {item['tol']} of {item['value']}"
    return True, "numeric values present"


DETERMINISTIC = {
    "artifact_produced": lambda o, c: check_artifact(o),
    "required_patterns": check_required,
    "no_forbidden_content": check_forbidden,
    "numeric_close": check_numeric,
}

FACTS_JUDGE = """Judge whether the answer in {{ outputs }} is consistent with every expected fact
and guideline in {{ expectations }}. Numbers must match within rounding. Return true only if no
expected fact is contradicted or missing and no guideline is violated."""

DECISIONS_JUDGE = """The task in {{ inputs }} hides data-steward decisions (what one source row
represents - well, wellbore, completion or lease; the coordinate datum; how unknown codes map;
how lease volumes are allocated). Return true if the answer in {{ outputs }} asks the user or
states each such choice explicitly as an assumption, and invents no identifiers or datums.
Return false if it silently picks one."""


def mlflow_scorers() -> list:
    """Wrap the checks for mlflow.genai.evaluate (imports MLflow lazily)."""
    from mlflow.entities import Feedback
    from mlflow.genai.judges import make_judge
    from mlflow.genai.scorers import scorer

    def _wrap(name, fn):
        @scorer(name=name)
        def _s(outputs: dict, expectations: dict) -> Feedback:
            ok, why = fn(outputs, expectations.get("deterministic_checks", {}))
            return Feedback(name=name, value=ok, rationale=why)
        return _s

    judges = [make_judge(name="facts_correct", instructions=FACTS_JUDGE, model=JUDGE_MODEL),
              make_judge(name="decisions_surfaced", instructions=DECISIONS_JUDGE, model=JUDGE_MODEL)]
    return [_wrap(n, f) for n, f in DETERMINISTIC.items()] + judges
