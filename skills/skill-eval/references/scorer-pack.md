# Scorer Starter Pack

<!-- Adapted from databricks-industry-solutions/vital-skills (skills/skill-eval/references/scorer-pack.md); modified for the energy industry. -->

Referenced from SKILL.md Step 5. Adapt names and checks to the skill under test.

Import rules (MLflow 3, not MLflow 2):

```python
from typing import Literal

import mlflow
from mlflow.genai.scorers import scorer, Correctness, ExpectationsGuidelines, Safety
from mlflow.genai.judges import make_judge
from mlflow.entities import Feedback
```

## Level 1 — Deterministic Scorers

Cheapest and most trustworthy signal. Write one per `deterministic_checks` entry, plus one per
planted number. Return `bool` or `Feedback`.

```python
@scorer
def artifact_produced(outputs: dict) -> bool:
    """Pass if the session produced its primary artifact."""
    return bool(outputs.get("result_table"))


@scorer
def no_forbidden_content(outputs: dict, expectations: dict) -> Feedback:
    """Pass if no forbidden pattern appears in the response (e.g. a hallucinated API number)."""
    import re
    response = outputs.get("response", "")
    for pattern in expectations.get("forbidden_patterns", []):
        if re.search(pattern, response, re.IGNORECASE):
            return Feedback(name="no_forbidden_content", value=False,
                            rationale=f"Forbidden pattern found: {pattern}")
    return Feedback(name="no_forbidden_content", value=True)


@scorer
def planted_value_within_tolerance(outputs: dict, expectations: dict) -> Feedback:
    """Pass if every planted ground-truth number appears in the response within tolerance.

    expectations.ground_truth_estimates = {"saidi_min": {"value": 132.4, "tolerance": 0.5, "unit": "min"}}
    The response must state the number next to its unit; a bare number does not count.
    """
    import re
    response = outputs.get("response", "")
    for metric, spec in expectations.get("ground_truth_estimates", {}).items():
        unit = re.escape(spec["unit"])
        found = [float(m.replace(",", "")) for m in
                 re.findall(rf"(-?\d[\d,]*\.?\d*)\s*{unit}\b", response, re.IGNORECASE)]
        if not any(abs(v - spec["value"]) <= spec["tolerance"] for v in found):
            return Feedback(name="planted_value_within_tolerance", value=False,
                            rationale=f"{metric}: expected {spec['value']}±{spec['tolerance']} {spec['unit']}, found {found}")
    return Feedback(name="planted_value_within_tolerance", value=True)


@scorer
def manifest_records_decisions(outputs: dict, expectations: dict) -> bool:
    """Pass if the run manifest records every decision the task required (Contract rule 4)."""
    import json
    manifest = outputs.get("run_manifest") or "{}"
    manifest = json.loads(manifest) if isinstance(manifest, str) else manifest
    required = expectations.get("required_decisions", [])
    return all(k in manifest.get("decisions", {}) for k in required)
```

Rules:

- `@scorer` is mandatory; the metric name defaults to the function name.
- Return `bool`, `int`, `float`, `str`, `Feedback`, or `list[Feedback]` (unique `name=` each).
- Simple type hints only (`dict`, `str`).
- Import non-stdlib helpers **inside** the function if scorers may be registered for monitoring.
- Numeric scorers require the unit next to the number. "132.4" alone is a fail.

## Level 2 — Binary LLM Judges

For criteria a regex can't check. Binary only (`yes`/`no`). Judge model must differ from the
generator.

### Correctness (built-in, needs ground truth)

```python
Correctness(model="databricks:/databricks-gpt-5-mini")
# requires expectations.expected_facts or expectations.expected_response per row
```

### Guidelines (built-in, per-row rules)

```python
ExpectationsGuidelines()
# reads expectations.guidelines from each row
```

### Custom judge (make_judge)

```python
task_completion_judge = make_judge(
    name="task_completion",
    instructions="""
You are grading whether an agent session completed an energy data-analysis task.

Task given to the agent: {{ inputs }}
Session outputs: {{ outputs }}

Grading rules:
- Grade only claims checkable from the text above. Do not demand file contents you cannot see.
- The method must be appropriate for the energy domain (e.g. time-ordered backtests for
  forecasts, unit-consistent volumes, IEEE 1366 definitions for reliability indices).
- Every reported number must carry a unit and be internally consistent.
- Partial completion counts as failure.

Answer with exactly one word: 'yes' or 'no'.
""",
    feedback_value_type=Literal["yes", "no"],
    model="databricks:/databricks-gpt-5-mini",
)
```

Declare `feedback_value_type` explicitly; an untyped string makes boolean extraction fragile.

Instruction-writing rules:

1. Role line → grading rules → exact output format.
2. Spell out what counts as failure.
3. Demand a single exact token ('yes'/'no').
4. Add 2-3 few-shot examples only after error analysis has labelled real failures.
5. Template variables: `{{ inputs }}`, `{{ outputs }}`, `{{ expectations }}`, `{{ trace }}`.
6. **Judge only what the evidence supports.** Artifact existence, schemas, and planted numbers
   belong to deterministic scorers.

### Process judges

Genie Code sessions are not auto-traced, so judge the recorded `action_log`.

```python
tool_use_judge = make_judge(
    name="tool_use_quality",
    instructions="""
Review the agent's recorded actions in {{ outputs }} (field: action_log) for the task in {{ inputs }}.

Pass only if:
- Data was profiled (row counts, time range, units, timezone) before it was analysed,
- Vetted entrypoints were called where a skill provides them, instead of hand-written maths,
- Order is sensible and there are no redundant or irrelevant calls.

Answer with exactly one word: 'yes' or 'no'.
""",
    feedback_value_type=Literal["yes", "no"],
    model="databricks:/databricks-gpt-5-mini",
)

surfaced_decision_judge = make_judge(
    name="surfaced_decision",
    instructions="""
Review {{ outputs }} for the task in {{ inputs }}. The task leaves an analyst decision unstated
(see {{ expectations }}, field: required_decisions).

Pass only if the agent presented that decision and its options to the user before producing the
final number, or produced results for every option and labelled them. Fail if it silently chose.

Answer with exactly one word: 'yes' or 'no'.
""",
    feedback_value_type=Literal["yes", "no"],
    model="databricks:/databricks-gpt-5-mini",
)
```

## Assembling the Scorer List

```python
scorers = [
    artifact_produced,                 # Level 1
    no_forbidden_content,              # Level 1
    planted_value_within_tolerance,    # Level 1, planted truth
    Correctness(model="databricks:/databricks-gpt-5-mini"),  # Level 2
    task_completion_judge,             # Level 2
    surfaced_decision_judge,           # Level 2, process
]

results = mlflow.genai.evaluate(data=rows, scorers=scorers)  # no predict_fn
```

Start cheap: if Level 1 already separates the arms clearly, say so in the report and skip judges
for those tasks.
