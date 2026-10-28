---
name: skill-eval
description: Skill benchmarking for Genie Code energy agent skills. Benchmark tasks (3-5) with planted-truth synthetic energy data -> paired runs with and without the skill -> MLflow 3 genai.evaluate scoring (deterministic scorers + binary LLM judges) -> per-task win/loss/flip comparison -> failure-taxonomy error analysis -> ship gate and eval_report.md. Validates a skill's eval/ folder layout. For authoring a skill use templates/ and AGENTS.md; for cross-skill benchmarking on public energy data use benchmarks/energybench.
category: Others
summary: "Benchmark a skill: paired runs with/without it on planted-truth energy data, MLflow genai.evaluate scoring, win/loss + failure taxonomy."
version: 0.1.0
author: Sourabh Ghose
license: Databricks License
---

<!-- Adapted from databricks-industry-solutions/vital-skills (skills/skill-eval/SKILL.md); modified for the energy industry. -->

# Skill Eval

## Overview

A standard way to prove an energy skill helps: run the same benchmark tasks with the skill OFF and ON, score both runs in one MLflow experiment, and compare per task. The output is a ship / fix-and-rerun verdict in the evaluated skill's `eval/eval_report.md`, backed by a failure taxonomy. This turns rule 6 of the Energy Skill Contract (AGENTS.md, "Prove it") into a repeatable pipeline.

Energy tasks are easy to get *plausibly* wrong (a dropped DST hour, a silent 6:1 boe conversion, SAIDI with Major Event Days left in). The strongest evidence therefore comes from **planted-truth** data: synthetic inputs with a known defect or a known answer that a grader can check exactly.

## When to Use

- Validating a new energy skill before opening a PR (the repo requires 3-5 benchmark tasks)
- Reviewing someone else's skill PR and needing objective evidence it helps
- Regression-checking a skill after editing its `SKILL.md`, `scripts/`, or `references/`
- Choosing between two variants of a skill (description A vs. B, entrypoint v1 vs. v2)
- Building the failure taxonomy that shows what to fix next (e.g. "skill still lets the agent pick the emission-factor vintage")
- Designing planted-truth synthetic data for a new skill's `eval/generate_data.py`
- Checking that a skill's `eval/` folder is complete and contains no fabricated scores

## Prerequisites

- **Tools**: Databricks workspace with Genie Code; a `databricks` CLI profile for that workspace
- **Python**: `pip install "mlflow[databricks]>=3.5.0"` for scoring (no Spark needed with list-of-dicts datasets). `compare_runs.py`, `run_combined_job.py`, and `validate_eval_dir.py` are stdlib only
- **Inputs**: the skill under test installed in Genie Code **without its `eval/` folder** (`Workspace/.assistant/skills/<name>/` or `~/.assistant/skills/<name>/`)
- **Environment**: an MLflow experiment path you can write to, e.g. `/Users/<you>/skill-eval-<skill-name>`, and a UC volume for synthetic data

## File Layout Convention

Evaluation artifacts live in the **evaluated skill's own `eval/` folder**. Shared tooling stays in `skill-eval/`.

```text
skills/<skill-name>/
├── SKILL.md               ← the skill itself (never modified during eval)
└── eval/
    ├── README.md              ← run protocol, scorer summary, ship gate
    ├── evalset.json           ← 3-5 tasks: task_id, dataset, query only
    ├── expectations.json      ← difficulty, expectations, deterministic_checks per task
    ├── generate_data.py       ← seeded planted-truth synthetic data
    ├── scorers.py             ← deterministic + judge definitions; exports `scorers`
    ├── job_design.json        ← (optional) combined serverless job payload
    ├── score_<skill>.py       ← (generated) scoring notebook
    ├── eval_report.md         ← (after a REAL run only) paired comparison + taxonomy
    ├── baseline_scores.json   ← (after a REAL run only)
    └── with_skill_scores.json ← (after a REAL run only)
```

Data volume default: `/Volumes/<catalog>/<schema>/eval/<skill_name>/`. `generate_data.py` reads `SKILL_EVAL_DATA_DIR`, falling back to a local `OUT_DIR`. The evaluator runs it before either arm; the agent executing tasks never reads it (Guardrail 8).

## Quick Start

```text
# 1. Write 3-5 tasks: eval/evalset.json (prompts) + eval/expectations.json (answer key).
#    Write eval/generate_data.py with planted truth (references/planted-truth-data.md) and seed the volume.
# 2. Check the folder:  python skills/skill-eval/scripts/validate_eval_dir.py skills/<skill>/eval
# 3. In a zero-inheritance session (never shown the skill), author the baseline notebook.
# 4. In a separate session with the skill installed (no eval/), author the candidate notebook.
# 5. Generate score_<skill>.py: imports scorers.py, runs mlflow.genai.evaluate for both arms,
#    extract_scores() -> score JSONs -> compare_runs.main().
# 6. Submit one combined serverless job (references/combined-job.md).
# 7. Error-analyze losses (references/error-analysis.md); write eval/eval_report.md
#    (references/report-template.md). Do NOT edit the skill's SKILL.md.
```

## Workflow

**⛔ EXECUTE, DO NOT REIMPLEMENT.** Use `scripts/compare_runs.py` for score extraction and comparison, `scripts/run_combined_job.py` for the job, and `scripts/validate_eval_dir.py` for folder checks. Do not re-derive win/loss logic in a notebook.

### Step 1: Define Benchmark Tasks

Author 3-5 tasks covering the skill's core jobs, each with ground truth a grader can check: at least one easy, one hard, and one edge/adversarial task, and **at least one task where the naive no-skill approach fails**. In energy that usually means a planted trap: the 25-hour fall-back day, a gas column in Mcf next to oil in bbl, a storm day that is a Major Event Day, a well with b > 1 in early transient flow.

```json
// evalset.json
{"task_id": "ami-002",
 "dataset": "/Volumes/<catalog>/<schema>/eval/ami-interval-analytics/intervals.parquet",
 "query": "Validate the 15-minute meter data in <path> and give daily kWh per meter for November 2025."}
```

```json
// expectations.json
{"task_id": "ami-002", "dataset": "/Volumes/.../intervals.parquet", "difficulty": "edge",
 "expectations": {
   "expected_facts": ["2025-11-02 has 100 intervals per meter in America/Chicago",
                      "Meter M-0007 daily total on 2025-11-02 is 41.25 kWh"],
   "guidelines": ["Must state the timezone and interval convention used",
                  "Must not treat estimated reads as actual"]},
 "deterministic_checks": {"required_artifacts": ["result_table"],
                          "forbidden_patterns": ["96 intervals on 2025-11-02"]}}
```

Schema, coverage method, and row conversion: `references/benchmark-tasks.md`. Planted-truth recipes per energy domain: `references/planted-truth-data.md`.

### Step 2: Validate the eval/ Folder

```bash
python skills/skill-eval/scripts/validate_eval_dir.py skills/<skill>/eval
```

Checks required files, that `evalset.json` and `expectations.json` join one-to-one on `task_id` + `dataset`, task count 3-5, difficulty spread, no answer-key fields leaking into `evalset.json`, and that score files are not present without an `eval_report.md` (or vice versa).

### Step 3: Run Baseline Sessions (Skill OFF)

Start a **zero-inheritance** agent/chat that receives only the queries from `evalset.json`, dataset/output paths, and generic execution constraints. It writes one linear notebook with independent from-scratch sections. Disabling a skill after reading it does not remove leaked knowledge: discard that baseline and restart. Protocol: `references/combined-job.md`.

### Step 4: Run Candidate Sessions (Skill ON)

In a separate session, install the skill **without `eval/`** (copy `SKILL.md`, `references/`, `assets/`, `scripts/`), then author the candidate notebook for the identical tasks in identical order. Same verbatim queries; no extra steering.

### Step 5: Generate the Scoring Notebook

One `score_<skill>.py` in `eval/` with **zero function definitions**: it imports `scorers` from `scorers.py` and `extract_scores` / `main` from `compare_runs.py`, loads queries from `evalset.json`, runs `mlflow.genai.evaluate()` for both arms into one experiment, saves `baseline_scores.json` / `with_skill_scores.json`, and prints the comparison.

```python
from scorers import scorers as all_scorers
from compare_runs import extract_scores, main as compare_main
baseline = mlflow.genai.evaluate(data=rows_baseline, scorers=all_scorers)
candidate = mlflow.genai.evaluate(data=rows_with_skill, scorers=all_scorers)
compare_main([f"{EVAL_DIR}/baseline_scores.json", f"{EVAL_DIR}/with_skill_scores.json",
              "--difficulty", f"{EVAL_DIR}/expectations.json", "--format", "text"])
```

Cell structure: `references/scoring-notebook.md`. Energy scorer starter code: `references/scorer-pack.md`. Extraction semantics: `references/paired-comparison.md`.

### Step 6: Submit the Combined Job

Two independent arm tasks plus one scoring task (`run_if: ALL_SUCCESS`) on serverless:

```bash
python skills/skill-eval/scripts/run_combined_job.py skills/<skill>/eval/job_design.json \
    --profile <PROFILE> --dry-run      # validate
python skills/skill-eval/scripts/run_combined_job.py skills/<skill>/eval/job_design.json \
    --profile <PROFILE>                # submit
```

### Step 7: Error Analysis and Report

Read every `tie-fail` and `regression`. Open-code the **first** failure per trace, then group into a named taxonomy (seed list of energy failure modes in `references/error-analysis.md`). Write `eval/eval_report.md` using `references/report-template.md`. Do not modify the skill's `SKILL.md`.

## Decision Points

These belong to the skill author / reviewer, not the agent running the eval. Ask before choosing.

| Decision | Options | What changes |
|----------|---------|--------------|
| Ship gate | `default` (win_rate > 0 and zero regressions) / `no-regressions` | `no-regressions` is right for regression re-runs and convention skills where parity is the honest result |
| Pass rule | `all_metrics` / `any_metric` | Task-level pass definition in `compare_runs.py` |
| Judge model | any served endpoint other than the generator | Cost/quality; must differ from the model that produced outputs |
| Data source | planted-truth synthetic / public dataset / customer data | Synthetic gives exact ground truth; public data adds realism (see benchmarks/energybench); customer data needs governance approval |
| Run size | 3-5 tasks × 1 rep / more reps | Repeated judge calls cost money; confirm with the user above 20 task-runs |

## Key Parameters

| Parameter | Default | Range / Options | Effect |
|-----------|---------|-----------------|--------|
| `n_tasks` | `4` | `3`-`5` (repo rule) | Coverage vs. effort |
| `judge_model` | `databricks:/databricks-gpt-5-mini` | any served judge endpoint | Must differ from the generator model |
| `score_mode` | `precomputed` | `precomputed`, `predict_fn` | `precomputed` for Genie Code sessions |
| `--pass-rule` | `all_metrics` | `all_metrics`, `any_metric` | Task-level pass definition |
| `--gate` | `default` | `default`, `no-regressions` | Ship gate; any regression always blocks |
| `--strict` | off | flag | Exit 1 on failed gate, missing `--difficulty`, or incomplete pairing |

## Common Recipes

### Recipe: Reference-Free Scoring

When a task has no gold answer (e.g. "summarize the reliability drivers this year"), use a rubric judge.

```python
from mlflow.genai.scorers import Guidelines
Guidelines(name="summary_quality", guidelines=[
    "The response must state SAIDI and SAIFI with units and the reporting year",
    "The response must not invent outage counts or customer numbers"],
    model="databricks:/databricks-gpt-5-mini")
```

### Recipe: Decision-Point Process Judge

When the value of a skill is that it *asked* (Contract rule 2), judge the recorded `action_log`.

```python
from typing import Literal
from mlflow.genai.judges import make_judge
asked_judge = make_judge(
    name="surfaced_decision",
    instructions=("Review the recorded actions in {{ outputs }} for the task in {{ inputs }}. "
                  "Pass only if the agent presented the decision options to the user (for example "
                  "Major Event Day method, emission-factor vintage, b-factor bound) BEFORE building "
                  "the final result, and did not silently choose one. Answer exactly 'yes' or 'no'."),
    feedback_value_type=Literal["yes", "no"], model="databricks:/databricks-gpt-5-mini")
```

### Recipe: Regression Re-Run

After editing a skill, re-run the previously failing tasks plus one easy control against the previous candidate:

```bash
python3 skills/skill-eval/scripts/compare_runs.py prev_candidate.json new_candidate.json \
    --difficulty expectations.json --gate no-regressions --strict
```

## Expected Outputs

- `score_<skill>.py` scoring notebook in `eval/`
- Two MLflow runs in one experiment (`baseline`, `with_skill`) with per-task scorer results
- `baseline_scores.json`, `with_skill_scores.json` (from a real run)
- `job_design.json` for the combined serverless job
- Console comparison: per-task win / regression / tie-pass / tie-fail, per-metric flips, win rate, gate verdict
- Failure taxonomy and `eval/eval_report.md` with verdict, limitations, and reproduce steps

## Troubleshooting

| Problem | Cause | Solution |
|---------|-------|----------|
| `evaluate()` fails on data | Missing nested `inputs` key | Rows must be `{"inputs": {...}, "outputs": {...}, "expectations": {...}}` |
| Correctness scorer errors | No ground truth in row | Add `expected_facts` / `expected_response`, or drop Correctness |
| Judge auth / endpoint error | Bad model URI | Use `databricks:/<endpoint>`, not `databricks:<endpoint>` |
| Skill not picked up | Stale chat or wrong folder | New chat + hard refresh; check `.assistant/skills/<name>/SKILL.md` |
| Baseline passes every task | No discriminator task | Add a planted trap the naive approach misses (`references/planted-truth-data.md`) |
| Judge contradicts deterministic scorers | Judge grading what it cannot see | Scope judges to narrative; exact numbers belong to deterministic scorers |
| "unpaired task" in comparison | `task_id` mismatch | Identical strings in both score JSONs |
| `validate_eval_dir.py` flags scores | Score JSONs without a report | Delete them or finish the real run and write `eval_report.md` |

## Guardrails

1. Binary pass/fail scorers only. Never report Likert averages as skill evidence.
2. Fresh Genie Code chat per task per arm; verbatim queries; no steering differences.
3. Judge model must differ from the model that generated the outputs.
4. A human reads the losses before any win-rate number is shared.
5. Confirm with the user before any run over 20 task-runs or repeated judge calls.
6. Do not retry failed judge/scorer calls more than 3 times; inspect the error first.
7. 3-5 tasks show direction, not significance. Say so in the report.
8. **Information isolation**: the baseline is authored in a zero-inheritance context before it reads any target-skill content, and sees only `evalset.json` queries, dataset/output paths, and generic constraints. Neither arm reads `expectations.json`, `generate_data.py`, `scorers.py`, or prior outputs. `eval/` is never installed with the skill.
9. **Never fabricate results.** Do not write `eval_report.md` or score JSONs unless a real paired run produced them. If a run was not done, say so.
10. Synthetic data only, or public data with its license respected. No CEII, customer meter-level data, or operator-confidential well data in `eval/`.

## Related Skills

- `energy-report-writer`: turn the eval report into a reviewer-facing summary
- `presentation-builder`: present the with/without results
- `benchmarks/energybench` (not a skill): cross-skill benchmark on public energy datasets with covered vs. control tasks

## Bundled Resources

- `references/benchmark-tasks.md`: evalset / expectations schema, task design rules, dimension-tuple coverage
- `references/planted-truth-data.md`: building synthetic energy data with known defects and answers
- `references/scorer-pack.md`: deterministic `@scorer` and binary `make_judge` starter code for energy tasks
- `references/paired-comparison.md`: extracting per-task scores from MLflow; comparison semantics; CLI
- `references/error-analysis.md`: open/axial coding worksheet and energy failure-mode seeds
- `references/report-template.md`: the `eval/eval_report.md` template
- `references/scoring-notebook.md`: scoring notebook cell structure and the `scorers.py` contract
- `references/combined-job.md`: uncontaminated baseline authoring and the two-arms-then-score DAG
- `scripts/compare_runs.py`: score extraction (`extract_scores`) and paired comparison; stdlib only
- `scripts/run_combined_job.py`: validates and submits the combined serverless job
- `scripts/validate_eval_dir.py`: checks an `eval/` folder against this convention

## References

- [Hamel Husain: error analysis in LLM evals](https://hamel.dev/blog/posts/evals-faq/why-is-error-analysis-so-important-in-llm-evals-and-how-is-it-performed.html): open/axial coding
- [Hamel Husain: LLM-as-judge](https://hamel.dev/blog/posts/llm-judge/): binary judges, TPR/TNR validation
- [MLflow 3 GenAI evaluation](https://mlflow.org/docs/latest/genai/eval-monitor/quickstart/): `mlflow.genai.evaluate`, scorers
- [Databricks custom judges](https://docs.databricks.com/aws/en/mlflow3/genai/eval-monitor/custom-judge/): `make_judge`
- [Databricks Jobs: serverless compute for jobs](https://docs.databricks.com/aws/en/jobs/run-serverless-jobs): environments, dependencies
- [Vital Skills skill-eval](https://github.com/databricks-industry-solutions/vital-skills/tree/main/skills/skill-eval): the HLS original this skill adapts
