# osdu-ppdm-mapper Skill Evaluation

## Overview

Benchmark for `osdu-ppdm-mapper` ([skill-eval](../../skill-eval/SKILL.md) method). It tests
whether the skill makes Genie Code respect identifier levels, datums, reference codes, and
reporting entities, compared with a baseline that maps columns by name and joins on `API_NO`.

## Benchmark Tasks

| task_id | difficulty | task | discriminator |
|---|---|---|---|
| map-001 | medium | Wellbore master + counts | completion rows (29) vs wellbores (22) vs wells (18); conflicting TD on 423011000000 |
| map-002 | hard | Surface locations to WGS 84 | DATUM column mixes NAD27/NAD83; baseline assumes WGS 84 |
| map-003 | medium | Status code mapping | `OBS` has no standard equivalent; must be surfaced, not guessed |
| map-004 | edge | Oil per well from lease production | lease-level reporting; naive join repeats lease volume per well |
| map-005 | easy | Malformed API numbers | 3 malformed values; Colorado rows lost the leading zero; don't pad `42-301-1234` |

## Data

Synthetic only (`generate_data.py`, seed 7): `vendor_well_header.csv` (32 completion rows,
18 wells, 22 wellbores) and `lease_production.csv` (6 months by lease). Planted truth:
`python3 generate_data.py --print-truth`.

```bash
python3 generate_data.py --out /Volumes/energy_catalog/energy_skills/eval/osdu-ppdm-mapper
```
```sql
CREATE OR REPLACE TABLE energy_catalog.energy_skills_eval.vendor_well_header AS
SELECT * FROM read_files('/Volumes/energy_catalog/energy_skills/eval/osdu-ppdm-mapper/vendor_well_header.csv',
                         format => 'csv', header => true, inferSchema => false);
CREATE OR REPLACE TABLE energy_catalog.energy_skills_eval.lease_production AS
SELECT * FROM read_files('/Volumes/energy_catalog/energy_skills/eval/osdu-ppdm-mapper/lease_production.csv',
                         format => 'csv', header => true);
```

Load the header with `inferSchema => false` so `API_NO` stays a string, as vendor extracts do.

## Scorer Summary

| scorer | level | type | checks |
|---|---|---|---|
| artifact_produced | L1 | deterministic | answer saved |
| required_patterns | L1 | deterministic | pattern groups (datums, IDs, OBS, lease, allocation) |
| no_forbidden_content | L1 | deterministic | e.g. "29 wellbores", "already WGS 84", padded `0423011234` |
| numeric_close | L1 | deterministic | well count 18 (map-001) |
| facts_correct | L2 | LLM judge | expected facts and guidelines |
| decisions_surfaced | L2 | LLM judge | level / datum / code / allocation choices asked or stated |

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
