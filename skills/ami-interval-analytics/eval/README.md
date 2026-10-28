# ami-interval-analytics evaluation

Four tasks with planted truth, each run with the skill and without it.

| Task | Difficulty | Planted trap |
|------|------------|--------------|
| ami-001 | easy | Fall-back Sunday: interval-ending local labels repeat 01:xx; truth needs 100 intervals/meter |
| ami-002 | hard | Mixed fleet: export on net-metered premises vs negative errors elsewhere; spikes above 48 kW service; 3-interval gaps |
| ami-003 | hard | Cumulative 5-dial registers with rollovers at 100 000 kWh and one meter exchange (reset) |
| ami-004 | medium | Spring-forward day (92 intervals), vendor-bug 02:xx labels, 300 upstream-estimated reads |

## Protocol

1. Generate the data (seeded; the answer key goes to a separate folder):
   ```bash
   python eval/generate_data.py --out-dir /tmp/ami-eval/tasks --truth-dir /tmp/ami-eval/truth
   databricks fs cp -r /tmp/ami-eval/tasks dbfs:/Volumes/energy_catalog/energy_skills/eval/ami
   ```
   Upload **only** `tasks/`. `truth.json` must never sit next to task data.
2. **Baseline arm:** run each `evalset.json` query in a fresh Genie Code chat with energy
   skills disabled, replacing `<ARM>` with `baseline`. Capture the response, action log,
   notebook source, and any reported numbers in `baseline_outputs.json`.
3. **Skill arm:** install the skill *without* `eval/` and `tests/` (the UC sync excludes
   them), start fresh chats, run the same queries with `<ARM>` = `with_skill`, and capture
   `with_skill_outputs.json`. When the agent asks a decision question, answer from this
   table and nothing more:

   | Decision | Answer |
   |----------|--------|
   | timezone / basis / convention | America/Chicago, local wall-clock, interval-ending (ami-003: UTC) |
   | net metering | per premise, from premises.csv |
   | linear gap limit / long gaps | 4 intervals / like-day up to 24 h |
   | spike ceiling | 48 kW |
   | register dial capacity | 100 000 kWh |

4. Score both arms with `skills/skill-eval` (MLflow `genai.evaluate` with
   `scorers.mlflow_scorers()`), and write `eval_report.md` with the paired comparison and
   failure taxonomy.

## Scorers

| Scorer | Type | Passes when |
|--------|------|-------------|
| `numeric_answers_correct` | deterministic | each truth number reported within `tolerance_pct` |
| `required_actions_present` | deterministic | required tokens appear in the evidence |
| `no_forbidden_patterns` | deterministic | no known-bad code pattern (e.g. `drop_duplicates` on local timestamps) |
| `vee_method` | LLM judge | DST, registers, net metering, estimate labelling, and surfaced thresholds all correct |

## Ship gate

The with-skill arm must win or tie on every task and win on at least 3 of 4 on
`numeric_answers_correct` + `vee_method`, with no regression on any deterministic check.

No scores have been recorded yet. `eval_report.md` and the score JSON files are written only
after a real paired run.
