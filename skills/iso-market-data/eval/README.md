# iso-market-data evaluation

Four tasks with planted truth, run with and without the skill (see `skills/skill-eval`).

| Task | Difficulty | Trap a general agent falls into |
|---|---|---|
| iso-001 | hard | ERCOT DST repeated hour dropped (720 h); Thanksgiving counted as on-peak; HE vs clock hour |
| iso-002 | medium | Interval beginning vs ending; missing 5-minute intervals averaged silently |
| iso-003 | hard | NYISO congestion sign read as PJM's; ranks the wrong zone |
| iso-004 | medium | Hourly-average price × hourly MWh understates battery revenue (planted naive answer: $14,962.85) |

## Protocol

1. `SKILL_EVAL_DATA_DIR=/tmp/energy-skills-eval/iso python eval/generate_data.py --check`, then upload
   to `/Volumes/energy_catalog/energy_skills/eval/iso/`.
2. Run each `evalset.json` query in a fresh Genie Code chat with the skill disabled
   (`<ARM>` = `baseline`); capture response, action log, notebook source and `answer.json`.
3. Enable the skill (bundle without `eval/`), repeat verbatim (`<ARM>` = `with_skill`).
4. Score with `scorers.py` in one MLflow experiment; compare with `skills/skill-eval`.
5. Write `eval_report.md` (paired comparison + failure taxonomy) without editing the skill.

When the agent asks for a decision, answer: iso-001 `5x16`, `America/Chicago`, time-weighted,
bounds −251/5000; iso-002 `interval_beginning` (PJM), time-weighted; iso-004 `rt_only`.

## Information isolation

The task agent sees only `evalset.json` and the task data; `expectations.json`, `generate_data.py`
and `scorers.py` are the answer key.

## Ship gate

At least one task-level win and zero regressions.
