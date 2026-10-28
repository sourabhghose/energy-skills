# energy-report-writer — evaluation

Protocol: [`skills/skill-eval`](../../skill-eval/SKILL.md). Three tasks, run once with the skill
and once without, in fresh Genie Code chats with the verbatim queries in `evalset.json`.

## Data

```bash
SKILL_EVAL_DATA_DIR=/Volumes/<catalog>/<schema>/eval/energy-report-writer python generate_data.py
```

Writes `reliability_annual.csv` (SAIDI/SAIFI/CAIDI 2021-2025 on both MED bases),
`reliability_manifest.json` (T_MED, MED dates), and `decline_summary.csv` (EUR per well,
labelled as technical forecasts). Planted answers print to stdout only.

## Tasks

| task_id | difficulty | Trap the naive approach falls into |
|---------|-----------|------------------------------------|
| erw-001 | easy | States numbers not in the table; omits draft/review notice |
| erw-002 | edge | Headlines MED-included SAIDI (241.5 min) or mixes bases in the trend; no not-advice notice |
| erw-003 | edge | Query says "reserves"; naive output calls decline EUR "proved reserves" |

## Scorers (`scorers.py`)

Deterministic: `artifact_produced`, `required_notices_present`, `no_forbidden_content`,
`planted_value_within_tolerance`, `no_invented_index_values`.
Judges: `Correctness`, `ExpectationsGuidelines`, `surfaced_decision` (binary).

## Ship gate

`compare_runs.py --difficulty expectations.json --strict`: win rate > 0 and zero regressions.
No results have been recorded yet; `eval_report.md` and score files are added only after a real run.
