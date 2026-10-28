# Benchmark Tasks — Evalset Schema and Task Design

<!-- Adapted from databricks-industry-solutions/vital-skills (skills/skill-eval/references/benchmark-tasks.md); modified for the energy industry. -->

Referenced from SKILL.md Step 1.

## Task Design Rules

1. **3-5 tasks** per skill (AGENTS.md, Contract rule 6). Fewer is unprovable; more is unpaid.
2. **Difficulty spread**: at least 1 easy (core happy path), 1 hard (multi-step, realistic data
   size), 1 edge/adversarial (ambiguous input, missing data, or a planted trap). **Include at least
   one task where the naive no-skill approach fails.** Strong base models pass easy tasks unaided,
   so without a discriminator the honest verdict is a tie.
3. **Ground truth must be checkable** by a grader who was not in the session: exact values where
   possible (interval counts, SAIDI minutes, EUR in Mbbl, tCO2e), guidelines where not.
4. **Planted truth over hand-labelled truth**: generate the data so the answer is known by
   construction (`references/planted-truth-data.md`). Real or public data adds realism but needs
   an expert-written rubric.
5. **Verbatim queries**: the `query` string is pasted into Genie Code character-for-character in
   both arms. Do not mention the skill, the trap, or the expected method in the query.
6. **Decision-point tasks**: for a skill whose value is asking (Contract rule 2), at least one task
   must leave a decision unstated in the query (e.g. "compute SAIDI for 2025" without saying
   whether to exclude Major Event Days). The pass condition is that the agent surfaces it.

## Task Definition Schema

Two files joined on `task_id` and `dataset`.

### evalset.json — task prompts (visible to both arms)

```json
{
  "task_id": "<skill-prefix>-<NNN>",
  "dataset": "/Volumes/<catalog>/<schema>/eval/<skill>/<file or table>",
  "query": "<exact prompt pasted into Genie Code>"
}
```

### expectations.json — grading criteria (answer key, never shown to either arm)

```json
{
  "task_id": "<skill-prefix>-<NNN>",
  "dataset": "<same as evalset>",
  "difficulty": "easy | hard | edge",
  "expectations": {
    "expected_facts": ["<checkable fact 1>", "<checkable fact 2>"],
    "expected_response": "<optional gold answer, for the Correctness scorer>",
    "ground_truth_estimates": {"<metric>": {"value": 0.0, "tolerance": 0.0, "unit": "<unit>"}},
    "guidelines": ["<must rule>", "<must-not rule>"]
  },
  "deterministic_checks": {
    "required_artifacts": ["result_table", "run_manifest"],
    "forbidden_patterns": ["<regex that must NOT appear, e.g. a hallucinated API well number>"]
  }
}
```

Field notes:

- `task_id`: stable string, identical across arms. The comparison joins on it.
- `difficulty`: read by `compare_runs.py --difficulty` straight from `expectations.json`.
- `expected_facts`: facts, not prose. "Daily total for M-0007 on 2025-11-02 is 41.25 kWh", not
  "handles DST well".
- `ground_truth_estimates`: numeric answers with tolerance **and unit**. A number without a unit
  is not checkable in energy (MW vs. MWh, Mcf vs. MMBtu).
- `guidelines`: must / must-not rules for `ExpectationsGuidelines`.
- `deterministic_checks`: consumed by your `@scorer` functions, not by MLflow built-ins.

## Dimension-Tuple Coverage Method

Define 2-3 variation axes, write ~6 tuples, keep the 3-5 a real user would hit.

| Axis | Example values (decline-curve-analysis) | Example values (ami-interval-analytics) |
|------|------------------------------------------|------------------------------------------|
| Data shape | clean monthly history, daily with shut-ins, sparse early data | 15-min, hourly, cumulative register reads |
| Task type | single-well fit, type curve, EUR roll-up | VEE, daily roll-up, anomaly flags |
| Input trap | none, b > 1 transient flow, mixed units | DST fall-back day, estimated-read flags, duplicate reads |

Example tuples for `reliability-metrics`:

| Tuple | Rendered task | Difficulty |
|-------|---------------|------------|
| (clean year, SAIDI/SAIFI, none) | "Compute 2025 SAIDI, SAIFI, CAIDI from this outage table." | easy |
| (year with storm, SAIDI, MED unstated) | "What was our 2025 SAIDI?" (one storm day is a MED) | edge |
| (multi-year, trend, momentary events) | "Trend SAIDI and MAIFI 2021-2025 by region." | hard |

## Converting to MLflow Rows

After both arms finish, merge on `task_id`. Each task becomes one row per arm.
`deterministic_checks` merge into `expectations` so scorers read one place:

```python
row = {
    "inputs": {"query": task["query"], "task_id": task["task_id"]},
    "outputs": {
        "response": "<summary of what the session produced, with numbers and units>",
        "result_table": "<UC table or artifact path, if any>",
        "run_manifest": "<manifest JSON or path, if the skill writes one>",
        "action_log": "<ordered list of tools/steps the session took>",
    },
    "expectations": {**task["expectations"], **task.get("deterministic_checks", {})},
}
```

`outputs` is pre-computed, so `mlflow.genai.evaluate()` needs no `predict_fn`. Genie Code sessions
are not auto-traced; record the session's steps into `action_log` for process judges.
