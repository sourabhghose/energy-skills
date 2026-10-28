# well-log-ingest evaluation

Three tasks on synthetic LAS 2.0 files with planted ingestion traps:

| Task | Traps | Truth |
|------|-------|-------|
| wli-001 | 3 vendor conventions: RHOZ in kg/m³, TNPH labelled V/V but in %, blank-unit NPOR, DTCO in µs/m, −9999 sentinels, KB→GL datum, Colorado APIs with a lost leading zero | per-well curve means, top depth below GL, normalized API14 |
| wli-002 | two runs overlapping 6,400–6,600 ft; the newer tool reads 25 gAPI hotter | overlap mean GR with latest-run policy |
| wli-003 | metric MD log in a horizontal well, user asks for TVDSS | must decline without a directional survey |

## Protocol

1. Generate data and upload everything **except** `_answer_key/`:
   ```bash
   SKILL_EVAL_DATA_DIR=/tmp/wli-eval python3 eval/generate_data.py
   for t in task_001 task_002 task_003; do
     databricks fs cp -r /tmp/wli-eval/$t dbfs:/Volumes/energy_catalog/energy_skills/eval/well_logs/$t; done
   ```
2. **Baseline arm**: run each `evalset.json` query in a fresh Genie Code chat with energy skills
   disabled (`<ARM>` = `baseline`). Capture the response, action log, notebook source,
   artifacts, and `answer_values` (keys as in `expectations.json` `numeric_answers`).
3. **Skill arm**: install the skill without `eval/` (and with `lasio` available), and run the
   same queries (`<ARM>` = `with_skill`).
4. Answer decision questions from `decision_answers` in `expectations.json`, identically across
   arms. Arms that don't ask get no answers.
5. Score with `scorers.py` and compare with `skills/skill-eval/scripts/compare_runs.py`.
6. Write `eval_report.md` only from real runs.

## Information isolation

The task agent may read only `evalset.json` and the task folders.

## Gate

Ship with at least one task-level win and zero regressions.
