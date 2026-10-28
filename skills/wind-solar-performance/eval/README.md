# wind-solar-performance evaluation

Four tasks with planted truth, run with and without the skill (see `skills/skill-eval`).

| Task | Difficulty | Trap a general agent falls into |
|---|---|---|
| wsp-001 | medium | Calls the TSO-curtailed turbine an underperformer; skips density normalization |
| wsp-002 | medium | Treats a grid outage like a turbine fault; doesn't state time vs energy basis |
| wsp-003 | hard | Computes "PR" from GHI because POA is missing |
| wsp-004 | medium | Fits a linear trend to raw energy; curtailment days bias the rate |

## Protocol

1. `SKILL_EVAL_DATA_DIR=/tmp/energy-skills-eval/wsp python eval/generate_data.py --check`, then
   upload to `/Volumes/energy_catalog/energy_skills/eval/wsp/`.
2. Run each `evalset.json` query in a fresh Genie Code chat with the skill disabled
   (`<ARM>` = `baseline`); capture response, action log, notebook source and `answer.json`.
3. Enable the skill (bundle without `eval/`), repeat verbatim (`<ARM>` = `with_skill`).
4. Score with `scorers.py` in one MLflow experiment; compare with `skills/skill-eval`.
5. Write `eval_report.md` (paired comparison + failure taxonomy) without editing the skill.

When the agent asks for a decision, answer: wsp-001 `ref_density=1.225`, `interval_beginning`,
pitch; wsp-002 report both external-downtime treatments, time basis; wsp-004 temperature-corrected,
exclude clipping.

## Information isolation

The task agent sees only `evalset.json` and the task data; `expectations.json`, `generate_data.py`
and `scorers.py` are the answer key.

## Ship gate

At least one task-level win and zero regressions.
