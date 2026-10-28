# ghg-emissions-calculator evaluation

Four tasks with planted truth, run with and without the skill (see `skills/skill-eval`).

| Task | Difficulty | Trap a general agent falls into |
|---|---|---|
| ghg-001 | easy | Reports one Scope 2 number; ignores RECs; skips HHV for Mcf |
| ghg-002 | hard | Accepts "98% flare efficiency" although RY2025 Subpart W uses tiers; GWP unstated |
| ghg-003 | medium | Sums JV assets at 100% without choosing a consolidation approach |
| ghg-004 | hard | Silently converts m3 at unknown reference conditions; invents a residual mix |

## Protocol

1. `SKILL_EVAL_DATA_DIR=/tmp/energy-skills-eval/ghg python eval/generate_data.py --check`
   (asserts the planted truth equals `expectations.json`), then upload to
   `/Volumes/energy_catalog/energy_skills/eval/ghg/`.
2. Run each `evalset.json` query in a fresh Genie Code chat with the skill **disabled**
   (`<ARM>` = `baseline`); capture response, action log, notebook source and `answer.json`.
3. Enable the skill (published bundle has no `eval/`), run the same queries verbatim in fresh
   chats (`<ARM>` = `with_skill`).
4. Score both arms with `scorers.py` in one MLflow experiment and compare with
   `skills/skill-eval` (`compare_runs.py`).
5. Write `eval_report.md` with the paired comparison and failure taxonomy. Do not edit the skill
   between arms.

When the agent (correctly) stops to ask a decision, the evaluator answers with the option named in
the task's guidelines (ghg-002: `tier2_de95`, AR5; ghg-003: report both) and lets the run continue.

## Information isolation

The task agent may read only `evalset.json` and the task data. `expectations.json`,
`generate_data.py` and `scorers.py` hold the answer key.

## Ship gate

At least one task-level win and zero regressions. Four tasks are directional evidence only.
