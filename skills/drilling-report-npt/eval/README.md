# drilling-report-npt Skill Evaluation

## Overview

Benchmark for `drilling-report-npt`, following the [skill-eval](../../skill-eval/SKILL.md)
method. It tests whether the skill makes Genie Code report NPT that is grounded, negation-aware,
reconciled, and decision-explicit, compared with a baseline that writes its own keyword SQL.

## Benchmark Tasks

| task_id | difficulty | task | discriminator |
|---|---|---|---|
| npt-001 | medium | NPT hours by category per rig, decisions stated in the prompt | finds uncoded stuck pipe/losses in remarks; weather kept separate; rig vs downhole split |
| npt-002 | hard | Which wells had lost circulation? | keyword search hits "No losses observed" and offset-well losses on W-102 |
| npt-003 | medium | Do the time logs add up? | 2 planted faults; the 25-hour DST day must *not* be flagged |
| npt-004 | edge | NPT % per contractor, no decisions given | weather policy changes Acme's NPT % from 3.0 % to 4.2 %; must surface or state it |

## Data

Synthetic only (`generate_data.py`, seed 42): 95 time-log lines, 6 wells, 2 rigs, 7 days
(2026-10-29 to 2026-11-04, America/Chicago, spanning the 2026-11-01 DST fall-back). Planted
truth: `python3 generate_data.py --print-truth`.

```bash
python3 generate_data.py --out /Volumes/energy_catalog/energy_skills/eval/drilling-report-npt
```
```sql
CREATE OR REPLACE TABLE energy_catalog.energy_skills_eval.ddr_time_log AS
SELECT row_id, well_id, rig_id, contractor,
       from_utc_timestamp(to_timestamp(start_time), 'America/Chicago') AS start_time,
       from_utc_timestamp(to_timestamp(end_time), 'America/Chicago') AS end_time,
       activity_code, remarks, CAST(footage_ft AS DOUBLE) AS footage_ft
FROM read_files('/Volumes/energy_catalog/energy_skills/eval/drilling-report-npt/ddr_time_log.csv',
                format => 'csv', header => true);
```

## Scorer Summary

| scorer | level | type | checks |
|---|---|---|---|
| artifact_produced | L1 | deterministic | answer saved |
| required_patterns | L1 | deterministic | every pattern group in `deterministic_checks` matches |
| no_forbidden_content | L1 | deterministic | e.g. the DST day is not called an error |
| wells_scope | L1 | deterministic | npt-002: W-101 present, W-102/W-105 not asserted as losses |
| numeric_close | L1 | deterministic | planted totals present within tolerance |
| facts_correct | L2 | LLM judge | consistent with expected facts and guidelines |
| decisions_surfaced | L2 | LLM judge | weather / reporting day / combine mode asked or stated |

The judge model must differ from the Genie Code model. Pass rule: all metrics.

## Ship Gate

`win_rate > 0` across tasks and zero regressions at any difficulty.

## Run Protocol

1. Seed the data and create the table (above).
2. **Baseline arm**: make sure `drilling-report-npt` is not registered. Open a fresh Genie Code
   chat per task, paste the `evalset.json` query verbatim, and let it finish. Move outputs to
   `outputs/baseline/`.
3. **Skill arm**: register the skill (without `eval/`), hard-refresh, and repeat in fresh chats.
   Move outputs to `outputs/with_skill/`.
4. **Score** with `mlflow.genai.evaluate(data=..., scorers=scorers.mlflow_scorers())`, one run per arm.
5. **Report**: write `eval_report.md` from the paired comparison
   (`skill-eval/references/report-template.md`). Do not commit scores a real run did not produce.

Genie Code keeps memories across chats. Ask it to forget this eval before each arm.
