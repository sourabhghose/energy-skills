# load-forecaster evaluation

Four tasks with planted truth, each run with the skill and without it.

| Task | Difficulty | Planted trap |
|------|------------|--------------|
| lf-001 | medium | Day-ahead backtest; 2 % multiplicative noise sets a WAPE floor of ~1.2 %, so lower numbers reveal a random split or lag-1 leakage |
| lf-002 | hard | Weather in Celsius without saying so; one station 40 % gappy, one noisy; planted balance points 15.6 °C / 21.1 °C |
| lf-003 | hard | Weather normalization of a +3 °F year against 2013–2022 normals; truth from the generating model |
| lf-004 | medium | Hour-ending local labels with the repeated fall-back hour, load in kW, Thanksgiving in November |

## Protocol

1. Generate the data (the answer key goes to a separate folder):
   ```bash
   python eval/generate_data.py --out-dir /tmp/lf-eval/tasks --truth-dir /tmp/lf-eval/truth
   databricks fs cp -r /tmp/lf-eval/tasks dbfs:/Volumes/energy_catalog/energy_skills/eval/lf
   ```
   Upload **only** `tasks/`.
2. **Baseline arm:** run each `evalset.json` query in a fresh Genie Code chat with energy
   skills disabled (`<ARM>` = `baseline`); capture response, action log, notebook source.
3. **Skill arm:** install the skill without `eval/` and `tests/`, run the same queries
   (`<ARM>` = `with_skill`). Answer decision questions from this table only:

   | Decision | Answer |
   |----------|--------|
   | timezone | America/Chicago |
   | load timestamps | lf-001/002/003: UTC hour-ending (lf-002: hour-beginning); lf-004: local hour-ending |
   | load unit | as named in the column (`load_mw` → MW, `load_kw` → kW) |
   | station / bases | "use the best-fitting station and the fitted balance points" |
   | holidays | NERC |
   | model | degree_day_regression |
   | normal period | lf-003: 2013–2022; otherwise all available years |

4. Score both arms with `skills/skill-eval` (`scorers.mlflow_scorers()`) and write
   `eval_report.md`.

## Scorers

| Scorer | Type | Passes when |
|--------|------|-------------|
| `numeric_answers_correct` | deterministic | truth numbers reported within `tolerance_pct` |
| `metrics_not_implausibly_low` | deterministic | no reported WAPE/MAPE below the planted noise floor |
| `required_actions_present` | deterministic | required tokens appear (e.g. `naive`, `Celsius`) |
| `no_forbidden_patterns` | deterministic | no shuffled `train_test_split`, no `shift(1)` lag, no `drop_duplicates` on timestamps |
| `forecast_method` | LLM judge | forward-in-time evaluation, naive benchmark, units/DST, justified weather choices |

## Ship gate

With-skill arm wins or ties every task and wins at least 3 of 4 on `numeric_answers_correct`
+ `forecast_method`, with no regression on deterministic checks.

No scores have been recorded yet. `eval_report.md` and score files are written only after a
real paired run.
