# decline-curve-analysis evaluation

Four tasks on planted-truth synthetic wells. Each well follows a known modified-hyperbolic
curve (b 1.0–1.4, D_min 8%), with a cleanup ramp, partial-month downtime, a shut-in month,
a flush-production spike, and 4% lognormal noise:

| Task | Tests | Truth |
|------|-------|-------|
| dca-001 | 30-well EURs: peak start, shut-ins, producing-day rates, bounded b + terminal decline | total EUR (±5%) |
| dca-002 | Lateral-normalized type curve and EUR distribution, PRMS labels, missing laterals | P10/P50/P90 EUR per 10,000 ft |
| dca-003 | One messy well: explain exclusions, forecast to the economic limit | judged |
| dca-004 | Secant vs tangent effective decline → nominal Di; first-year cumulative | Di = 3.006 /yr, 176 Mbbl |

On the dca-001 data, a naive fit (calendar-day rates from first production, b ≤ 2.5, no
terminal decline) is about 13% below truth. The skill's decisions land within 2%.

## Protocol

1. Generate data and upload everything **except** `_answer_key/`:
   ```bash
   SKILL_EVAL_DATA_DIR=/tmp/dca-eval python3 eval/generate_data.py
   databricks fs cp -r /tmp/dca-eval/task_001 dbfs:/Volumes/energy_catalog/energy_skills/eval/dca/task_001
   databricks fs cp -r /tmp/dca-eval/task_002 dbfs:/Volumes/energy_catalog/energy_skills/eval/dca/task_002
   ```
2. **Baseline arm**: run each query in a fresh Genie Code chat with energy skills disabled
   (`<ARM>` = `baseline`). Capture the response, action log, notebook source, artifacts, and
   headline numbers (`answer_values`) into `baseline_outputs.json`.
3. **Skill arm**: install the skill without `eval/` and run the same queries verbatim
   (`<ARM>` = `with_skill`).
4. **Decision answers**: when either arm asks a decision question, the operator answers from
   the task's `decision_answers` in `expectations.json`. Answers are identical across arms,
   and an arm that never asks gets no answers.
5. Score with `scorers.py` (`score_deterministic`, or `mlflow_scorers()` in
   `mlflow.genai.evaluate`). Compare with `skills/skill-eval/scripts/compare_runs.py`.
6. Write `eval_report.md` only from real runs.

## Information isolation

The task agent may read only `evalset.json` and the task folders: not `expectations.json`,
`generate_data.py`, `scorers.py`, `_answer_key/`, or prior outputs.

## Gate

Ship with at least one task-level win and zero regressions.
