# reliability-metrics evaluation

Five tasks that target the mistakes general agents make with IEEE 1366: final-restore
customer-minutes, momentary steps counted as sustained, MED threshold fitted on the
reporting year, UTC event dating, per-shot MAIFI_E, and averaged ratios in a metric view.

| Task | Tests | Difficulty |
|------|-------|-----------|
| rel-001 | SAIDI/SAIFI/CAIDI with and without MED, T_MED, MED list | medium |
| rel-002 | Step restoration and momentary steps (MAIFI) | hard |
| rel-003 | Evening storm: local-day dating keeps it on 2024-08-10 | hard |
| rel-004 | MAIFI_E from recloser shots (one event per 5-min sequence) | medium |
| rel-005 | Metric view with ratio-of-measures and a complete daily grid | medium |

## Protocol

1. `python3 eval/generate_data.py` → task data in `$SKILL_EVAL_DATA_DIR`
   (default `/tmp/reliability-eval`), answer key in `$SKILL_EVAL_KEY_DIR`
   (default `/tmp/reliability-eval_answer_key`). Upload **only** the task data to
   `/Volumes/energy_catalog/energy_skills/eval/reliability-metrics/`.
2. Run every query in `evalset.json` in a fresh Genie Code chat with the skill **disabled**
   (`<ARM>` = `baseline`). If the agent asks for a decision, answer: 5-minute threshold,
   average customers served, exclude planned, IEEE 2.5 beta. Capture response, action log,
   notebook source and `answer.json`.
3. Enable the skill (without `eval/`), repeat with `<ARM>` = `with_skill`.
4. Score with `scorers.score_task` (offline) or `scorers.mlflow_scorers(truth)` in
   `mlflow.genai.evaluate`, then compare arms with `skills/skill-eval`.
5. Write `eval_report.md` only from a real run.

## Scoring

- **numeric_matches** — each number must match *some* valid decision scenario (all 16
  combinations are in the answer key) within 1–2%. Defensible choices pass; wrong methods
  match none.
- **med_days_correct** — 2024-08-10 must be a MED; 2024-08-11 (the UTC day) must not.
- **sql_tokens_present / no_forbidden_patterns** — metric view shape.
- **ieee1366_method** judge + `ExpectationsGuidelines` over `expected_facts`.

## Information isolation

The task agent may read only `evalset.json` and the task data. It must never see
`expectations.json`, `generate_data.py`, `scorers.py`, or the answer key.

## Ship gate

At least one task-level win and zero regressions versus baseline. Five tasks are
directional evidence, not statistical significance.
