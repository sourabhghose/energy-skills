# energy-semantic-builder evaluation

Five tasks on the KPI errors that make energy dashboards disagree.

| Task | Trap | Difficulty |
|------|------|-----------|
| sem-001 | Gas in m³; boe ratio is a decision; field boe/d vs. per-well averages | hard |
| sem-002 | Field water cut (~55%) vs. average of well water cuts (~72%) | medium |
| sem-003 | Fleet EAF: unweighted (~73%) vs. MW-weighted (~87%) pooling | hard |
| sem-004 | Leap year + DST period hours vs. 8,760 h | medium |
| sem-005 | Metric views with ratio-of-measures and unit conversion in the conforming view | medium |

Truth is computed with plain pandas in `generate_data.py`, independently of the skill.

## Protocol

1. `python3 eval/generate_data.py` → task data in `$SKILL_EVAL_DATA_DIR`
   (default `/tmp/semantic-eval`), answer key in `$SKILL_EVAL_KEY_DIR`. Upload only the
   task data to `/Volumes/energy_catalog/energy_skills/eval/energy-semantic-builder/`.
2. Run each `evalset.json` query in a fresh Genie Code chat, skill disabled
   (`<ARM>` = `baseline`). If asked: 6 Mcf per boe, MW-weighted GADS pooling, NMC is net
   maximum (dependable) capacity, HHV. Capture response, action log, notebook source and
   `answer.json`.
3. Enable the skill (without `eval/`), repeat with `<ARM>` = `with_skill`.
4. Score with `scorers.score_task` or `scorers.mlflow_scorers(truth)`; compare with
   `skills/skill-eval`. Write `eval_report.md` only from a real run.

## Information isolation

The task agent sees only `evalset.json` and the task data.

## Ship gate

At least one task-level win and zero regressions versus baseline.
