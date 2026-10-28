# unit-guard evaluation

Four tasks that a general coding agent tends to get subtly wrong: the scf → Sm³ temperature
correction and the boe convention (ug-001), MW vs MWh across a DST day (ug-002), ambiguous
"tons" and the GWP set (ug-003), and HHV vs LHV efficiency (ug-004).

## Protocol

1. Generate data and upload everything **except** `_answer_key/`:
   ```bash
   SKILL_EVAL_DATA_DIR=/tmp/unit-guard-eval python3 eval/generate_data.py
   databricks fs cp -r /tmp/unit-guard-eval/task_001 dbfs:/Volumes/energy_catalog/energy_skills/eval/unit_guard/task_001
   # repeat for task_002, task_003
   ```
2. **Baseline arm**: run each `evalset.json` query in a fresh Genie Code chat with energy skills
   disabled, replacing `<ARM>` with `baseline`. Capture the response, action log, notebook
   source, artifact names, and the headline numbers (`answer_values`) into `baseline_outputs.json`.
3. **Skill arm**: install `unit-guard` without its `eval/` folder (the UC sync does this), run
   the same queries verbatim with `<ARM>` = `with_skill`, and capture `with_skill_outputs.json`.
   When the agent asks a decision question, answer from the task's source files (contract
   excerpt, README); for ug-003, answer "short tons, AR5" if asked.
4. Score both arms with `scorers.py` (`score_deterministic` offline, or `mlflow_scorers()` in
   `mlflow.genai.evaluate`), then compare with `skills/skill-eval/scripts/compare_runs.py`.
5. Write `eval_report.md` (paired comparison + failure taxonomy) only from real runs.

## Information isolation

The task-running agent may read only `evalset.json` and the task folders. It must not read
`expectations.json`, `generate_data.py`, `scorers.py`, `_answer_key/`, prior outputs, or reports.

## Scorers

| Scorer | Kind | Passes when |
|--------|------|-------------|
| `required_artifacts_present` | deterministic | requested files exist |
| `required_actions_present` | deterministic | decision tokens (e.g. `14.696`, `HHV`) appear in evidence |
| `no_forbidden_patterns` | deterministic | no `35.3147` shortcut, no forced 96 intervals/day |
| `numeric_answers_correct` | deterministic | headline numbers within the stated relative tolerance |
| `unit_method` | LLM judge | conventions surfaced, dimensions valid, units on every number |

## Gate

Ship with at least one task-level win and zero regressions. Four tasks are directional
evidence, not statistical significance.
