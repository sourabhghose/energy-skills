# equipment-pdm Skill Evaluation

## Overview

Benchmark for `equipment-pdm` ([skill-eval](../../skill-eval/SKILL.md) method). It tests
whether the skill makes Genie Code produce a PdM evaluation a maintenance planner can trust,
compared with a baseline that pivots tags, interpolates, and trains on a random split.

## Benchmark Tasks

| task_id | difficulty | task | discriminator |
|---|---|---|---|
| pdm-001 | hard | Early-warning model: caught, lead time, false alarms | PM work order is not a failure; start-up transients; embargoed split; false alarms per asset-month |
| pdm-002 | medium | Hottest motor | degF vs degC tags: raw numbers make ESP-04 look hottest; ESP-08 is (114 °C) |
| pdm-003 | medium | Data-quality review | 12-h outage on ESP-02, PI digital states in analog tags, unmapped tags, unit mix |
| pdm-004 | edge | Vendor claims 98 % accuracy (random split) | leakage + class imbalance; recommend proper metrics |

## Data

Synthetic only (`generate_data.py`, seed 11): 8 ESPs, 120 days, about 277k historian rows.
Planted truth: `python3 generate_data.py --print-truth`.

```bash
python3 generate_data.py --out /Volumes/energy_catalog/energy_skills/eval/equipment-pdm
```
```sql
CREATE OR REPLACE TABLE energy_catalog.energy_skills_eval.esp_historian AS
SELECT tag, to_timestamp(ts) AS ts, value
FROM read_files('/Volumes/energy_catalog/energy_skills/eval/equipment-pdm/historian.csv',
                format => 'csv', header => true, inferSchema => false);
CREATE OR REPLACE TABLE energy_catalog.energy_skills_eval.esp_tag_map AS
SELECT * FROM read_files('/Volumes/energy_catalog/energy_skills/eval/equipment-pdm/tag_map.csv',
                         format => 'csv', header => true);
CREATE OR REPLACE TABLE energy_catalog.energy_skills_eval.esp_work_orders AS
SELECT wo_id, asset_id, failure_mode, wo_type, to_timestamp(failure_start) AS failure_start,
       to_timestamp(restored) AS restored
FROM read_files('/Volumes/energy_catalog/energy_skills/eval/equipment-pdm/work_orders.csv',
                format => 'csv', header => true);
```

Keep `value` as a string (`inferSchema => false`), as PI extracts are, so digital states survive.

## Scorer Summary

| scorer | level | type | checks |
|---|---|---|---|
| artifact_produced | L1 | deterministic | answer saved |
| required_patterns | L1 | deterministic | false alarms, lead time, unit / outage / state mentions |
| no_forbidden_content | L1 | deterministic | WO-900 treated as failure; ESP-04 named hottest |
| numeric_close | L1 | deterministic | ESP-08 temperature (114 °C) |
| facts_correct | L2 | LLM judge | expected facts and guidelines |
| decisions_surfaced | L2 | LLM judge | failure set, horizon, split, threshold asked or stated |

## Ship Gate

`win_rate > 0` and zero regressions at any difficulty.

## Run Protocol

1. Seed the data and create the tables (above).
2. **Baseline arm**: skill not registered. Use a fresh Genie Code chat per task, paste the
   query verbatim, and move outputs to `outputs/baseline/`.
3. **Skill arm**: register the skill (without `eval/`), repeat in fresh chats, and move
   outputs to `outputs/with_skill/`.
4. **Score**: `mlflow.genai.evaluate(data=..., scorers=scorers.mlflow_scorers())` per arm.
5. **Report**: write `eval_report.md` only from a real paired run.

Clear Genie Code memories about this eval before each arm.
