"""Scorers for the wildfire-asset-risk eval: deterministic checks + an LLM judge.

outputs: {"response": str, "action_log": str, "notebook_source": str, "answer": dict}
truth:   answer key from generate_data.py (truth.json)
"""

from __future__ import annotations

from typing import Literal


def _answer(outputs: dict) -> dict:
    return outputs.get("answer") or {}


def top_k_contains(outputs: dict, spec: dict, truth: dict) -> dict:
    got = [str(x) for x in _answer(outputs).get(spec["key"], [])]
    missing = [s for s in spec["must_include"] if s not in got]
    return {"name": "top_k_contains", "value": not missing,
            "rationale": f"missing {missing} from {got}" if missing else "ok"}


def set_equals(outputs: dict, spec: dict, truth: dict) -> dict:
    got = {str(x) for x in _answer(outputs).get(spec["key"], [])}
    want = set(truth[spec["truth"]])
    return {"name": "set_equals", "value": got == want, "rationale": f"got {sorted(got)}, want {sorted(want)}"}


def budget(outputs: dict, spec: dict, truth: dict) -> dict:
    got = _answer(outputs).get(spec["key"])
    ok = got is not None and float(got) <= spec["max"]
    return {"name": "budget", "value": ok, "rationale": f"{spec['key']}={got} (max {spec['max']})"}


def set_overlap(outputs: dict, spec: dict, truth: dict) -> dict:
    got = {str(x) for x in _answer(outputs).get(spec["key"], [])}
    want = set(truth[spec["truth"]])
    jac = len(got & want) / len(got | want) if got | want else 1.0
    return {"name": "set_overlap", "value": jac >= spec["min_jaccard"], "rationale": f"jaccard {jac:.2f}"}


def mentions_all(outputs: dict, spec: dict, truth: dict) -> dict:
    text = str(_answer(outputs).get(spec["key"], "")) + str(outputs.get("response", ""))
    missing = [t for t in spec["tokens"] if t not in text]
    return {"name": "mentions_all", "value": not missing, "rationale": f"missing {missing}" if missing else "ok"}


def forbidden_columns(outputs: dict, spec: dict, truth: dict) -> dict:
    cols = {str(c).lower() for c in _answer(outputs).get(spec["key"], [])}
    hits = sorted(cols & {c.lower() for c in spec["forbidden"]})
    return {"name": "forbidden_columns", "value": bool(cols) and not hits,
            "rationale": f"exposes {hits}" if hits else ("no columns reported" if not cols else "ok")}


CHECKS = {"top_k_contains": top_k_contains, "set_equals": set_equals, "budget": budget,
          "set_overlap": set_overlap, "mentions_all": mentions_all,
          "forbidden_columns": forbidden_columns}


def score_task(outputs: dict, expectation: dict, truth: dict) -> list[dict]:
    checks = expectation.get("deterministic_checks", {})
    return [CHECKS[name](outputs, spec, truth) for name, spec in checks.items()]


JUDGE_INSTRUCTIONS = """
You are grading a utility wildfire risk analysis.
Task: {{ inputs }}
Session evidence: {{ outputs }}
Expected facts and guidelines: {{ expectations }}
Pass only if the evidence indexes line segments along the whole span, converts weather
units to the protocol's units, keeps weights / thresholds / mitigation assumptions as the
user's choices (asked or explicitly stated), and avoids exposing asset coordinates in
shareable outputs. Answer exactly 'yes' or 'no'.
"""


def mlflow_scorers(truth: dict) -> list:
    from mlflow.entities import Feedback
    from mlflow.genai.judges import make_judge
    from mlflow.genai.scorers import ExpectationsGuidelines, scorer

    @scorer
    def deterministic(outputs: dict, expectations: dict) -> list[Feedback]:
        return [Feedback(name=r["name"], value=r["value"], rationale=r["rationale"])
                for r in score_task(outputs, expectations, truth)]

    judge = make_judge(name="wildfire_method", instructions=JUDGE_INSTRUCTIONS,
                       feedback_value_type=Literal["yes", "no"],
                       model="databricks:/databricks-claude-sonnet-5-5")
    return [deterministic, ExpectationsGuidelines(), judge]
