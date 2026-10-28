# wildfire-asset-risk evaluation

Five tasks built around the mistakes general agents make with utility wildfire data.

| Task | Trap | Difficulty |
|------|------|-----------|
| wf-001 | SPAN1's poles sit in benign cells; its conductor crosses a hazardous, populated pocket | hard |
| wf-002 | Forecast in °C and km/h; protocol in °F / mph; circuit Z meets weather but is not in an HFTD | hard |
| wf-003 | Budget-constrained mitigation by risk-spend efficiency; greedy must skip, not stop | medium |
| wf-004 | Three segments have lat/lon swapped | medium |
| wf-005 | Shareable layer must not expose segment ids or coordinates (CEII) | medium |

## Protocol

1. Install the `h3` package so the generator uses real H3 cells (the answer key records
   `grid_backend`; a `square-fallback` key is for offline smoke tests only).
   `python3 eval/generate_data.py` → task data in `$SKILL_EVAL_DATA_DIR`
   (default `/tmp/wildfire-eval`), answer key in `$SKILL_EVAL_KEY_DIR`.
2. Upload only the task data to `/Volumes/energy_catalog/energy_skills/eval/wildfire-asset-risk/`
   and load the CSVs as tables if the agent needs them.
3. Run each `evalset.json` query in a fresh Genie Code chat, skill disabled
   (`<ARM>` = `baseline`). If the agent asks for weights in wf-001/wf-004/wf-005, answer
   with the wf-003 weights and basis. Capture response, action log, notebook source and
   `answer.json`.
4. Enable the skill (without `eval/`), repeat with `<ARM>` = `with_skill`.
5. Score with `scorers.score_task` or `scorers.mlflow_scorers(truth)`; compare arms with
   `skills/skill-eval`. Write `eval_report.md` only from a real run.

## Information isolation

The task agent sees only `evalset.json` and the task data — never `expectations.json`,
`generate_data.py`, `scorers.py`, or the answer key.

## Ship gate

At least one task-level win and zero regressions versus baseline.
