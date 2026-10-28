---
name: drilling-report-npt
description: >-
  Drilling NPT (non-productive time) and invisible lost time (ILT) from daily drilling reports
  (DDR) and WITSML-style operations time logs. Classifies free-text remarks with ai_query using
  span-grounding (keeps a classification only if its verbatim quote is in the remark), negation-
  and subject-aware filters ("no losses observed", "offset well had stuck pipe"), and combines it
  with IADC-style activity codes. Categories: stuck pipe, lost circulation, well control, rig vs
  downhole equipment failure, waiting on weather/materials, fishing, wellbore instability.
  Reconciles each report day to 24 h (DST-aware gaps/overlaps), surfaces code taxonomy, combine
  mode, weather policy, reporting-day start and ILT benchmark for the user to choose, and writes
  NPT hours by category/well/rig/contractor plus an evidence table. Call scripts/npt_run.py
  entrypoints; do not hand-write NPT SQL. For OSDU/PPDM well identity use osdu-ppdm-mapper.
category: "Oil & Gas"
summary: Classify drilling NPT and invisible lost time from DDR remarks and activity codes, with span-grounded evidence and 24-hour reconciliation.
version: 0.1.0
author: Sourabh Ghose
license: Databricks License
---

# Drilling Report NPT & Invisible Lost Time

## Overview

Turns daily drilling report time logs (activity code + free-text remark per line) into
defensible NPT and invisible-lost-time figures. Each NPT hour traces back to a coded activity,
a verbatim quote from the remark, or both. The skill checks every report day sums to its
expected hours before reporting a percentage. Ambiguous reporting choices (which codes are NPT,
whether weather counts, when the reporting day starts) are put to the user, not assumed.

Outputs: NPT hours and NPT % by category, well, rig, and contractor; an evidence table with
verbatim quotes; a 24-hour reconciliation table; ILT per productive line; and a run manifest.

## When to Use

- "What was our NPT by category on Rig 12 last quarter?"
- "Find NPT hidden in the remarks that wasn't coded as NPT" (union of codes and text).
- "Score drilling contractors on rig-equipment downtime, excluding weather."
- "How much time are we losing to stuck pipe and losses in the 8-1/2in section?"
- "Estimate invisible lost time on drilling and tripping against offset P10 performance."
- "Check whether our DDR time logs actually add up to 24 hours per day."
- "Give me evidence, quotes from the reports, for each NPT event so the contractor can review."

## Prerequisites

- **Compute**: Python-enabled compute (serverless or cluster) with Spark for writing tables. A
  SQL warehouse alone cannot run the entrypoints.
- **Input**: a UC table or view with `well_id, rig_id, contractor, start_time, end_time,
  activity_code, remarks` (optional `row_id, footage_ft, hole_section`). See
  `references/ddr_time_log.md` for the WITSML `opsReport` mapping.
- **Model endpoint** (text modes only): a serving endpoint callable by `ai_query`, for example a
  Foundation Model API pay-per-token chat endpoint.
- **Permissions**: SELECT on the input; CREATE TABLE on the output schema.

## Quick Start

```python
import sys
sys.path.append("<this-skill-dir>/scripts")
from npt_run import preview_npt_options, build_confirmed_npt, format_result

# STEP 1: READ-ONLY. Shows decision options and their effect on a sample. Builds nothing.
print(preview_npt_options("main.drilling.ddr_time_log", endpoint="<serving-endpoint>"))

# STEP 2: only after the user chooses each decision.
res = build_confirmed_npt(
    "main.drilling.ddr_time_log", "main.drilling.q3_npt",
    endpoint="<serving-endpoint>",
    code_taxonomy="iadc_style", combine_mode="union", weather_policy="separate",
    report_day_start_hour=6, ilt_benchmark="p10")
print(format_result(res))
```

## Workflow

**⛔ EXECUTE, DO NOT REIMPLEMENT.** Call `preview_npt_options` and `build_confirmed_npt` in
`scripts/npt_run.py` and report their output. Do not write your own NPT SQL or regexes, and do
not choose a decision value yourself. The steps below describe what the entrypoints do so the
user can review them. They are not a recipe to re-code.

### Step 1: Map the source to the time-log contract

If column names differ, create a view that renames them. Never fabricate `well_id`s or codes.

```sql
CREATE OR REPLACE VIEW main.drilling.ddr_time_log AS
SELECT line_id AS row_id, api14 AS well_id, rig_name AS rig_id, drilling_contractor AS contractor,
       from_utc_timestamp(start_utc, 'America/Chicago') AS start_time,
       from_utc_timestamp(end_utc, 'America/Chicago') AS end_time,
       iadc_code AS activity_code, comments AS remarks, footage AS footage_ft
FROM main.drilling.raw_ops;
```

### Step 2: Preview (read-only)

`preview_npt_options` samples the table and reports:
- activity codes that are not in the IADC-style map (decision `code_taxonomy`)
- well-days failing reconciliation under a 00:00 vs 06:00 reporting-day start
- NPT hours for each combine mode × weather policy
- text events dropped by grounding, negation, and subject filters

Show the whole readout to the user and ask for each decision.

### Step 3: Classify remarks (span-grounded)

In text modes, `ai_query` returns JSON events, each with a verbatim quote. An event is kept only
if the quote is in the remark, it is asserted (not negated or hypothetical), and it happened on
this well. See `references/span_grounding.md`.

```python
from npt_text import ground_events
ground_events("r1", "Drilled ahead. No losses observed.",
              [{"category": "LOST_CIRCULATION", "quote": "losses observed"}])  # dropped: negated_in_text
```

### Step 4: Reconcile hours

Each well and report day is checked against its expected hours: 24, or 23/25 on DST days with
tz-aware timestamps. Gaps, overlaps, and negative durations are reported.

### Step 5: Flag NPT and apply policies

Codes and text combine per `combine_mode`. The coded category wins when both agree. The weather
policy then sends waiting-on-weather to NPT, to a separate `weather_downtime_hr` bucket, or
excludes it.

### Step 6: Invisible lost time

Productive lines are benchmarked per group (default `activity_code`; pass
`ilt_group_cols=("activity_code","hole_section")` when available). Footage gives rate-based
ILT. Groups with fewer than 5 rows get no ILT.

### Step 7: Write outputs

Tables `<prefix>_npt_by_category`, `_npt_by_well`, `_npt_by_rig`, `_npt_evidence`,
`_hours_recon`, `_ilt_rows`, and `_run_manifest`, all commented with the skill version and
decisions. `format_result` gives the analyst readout.

## Decision Points

| Decision | Options | Governing reference | What changes |
|---|---|---|---|
| `code_taxonomy` | `iadc_style` or an operator `{code: category\|None}` map | IADC DDR form / operator NPT standard | which coded lines count as NPT |
| `combine_mode` | `code_only`, `text_only`, `union`, `intersection` | operator reporting convention | recall vs precision of NPT |
| `weather_policy` | `npt`, `separate`, `exclude` | drilling contract / KPI definition | whether WOW inflates NPT % |
| `report_day_start_hour` | `0`, `6` | DDR form / contract | which day each line belongs to; reconciliation |
| `ilt_benchmark` | `p10`, `p25`, `technical_limit`, `none` | operator performance programme | size of ILT |

All five are keyword-only arguments with **no defaults**. Passing `None` raises `DecisionRequired`.

## Key Parameters

| Parameter | Default | Range / Options | Effect |
|---|---|---|---|
| `endpoint` | `None` | serving endpoint name | required for text modes |
| `sample_rows` (preview) | `500` | 50–5000 | preview sample size |
| `ilt_group_cols` | `("activity_code",)` | any time-log columns | ILT benchmark grouping |
| `max_rows` | `200000` | — | read cap; manifest records truncation |
| `write` | `True` | bool | `False` returns frames without writing |

## Expected Outputs

- `npt_by_category` / `_by_well` / `_by_rig`: `npt_hr`, `total_hr`, `npt_pct`, and
  `weather_downtime_hr` when the weather policy is `separate`
- `npt_evidence`: one row per NPT line, with `npt_source` (code/text/both) and the verbatim `text_quote`
- `hours_recon`: `logged_hr`, `expected_hr`, `internal_gap_hr`, `overlap_hr`, `status`
- `ilt_rows`: productive lines with `ilt_hr`
- `run_manifest`: inputs, decisions, endpoint, prompt version, dropped-event count

## Troubleshooting

| Problem | Cause | Solution |
|---|---|---|
| `time log is missing required columns` | source not mapped to contract | create a renaming view (Step 1) |
| Many `short_day` rows | wrong reporting-day start or missing lines | compare 00:00 vs 06:00 in preview |
| `long_day` on one day in November | naive timestamps across DST fall-back | convert to tz-aware local time |
| NPT % jumps between modes | uncoded NPT in remarks | review evidence with `npt_source = text` |
| Many `quote_not_in_remark` drops | weak endpoint or truncated remarks | use a stronger endpoint; check remark length |
| ILT all NaN | fewer than 5 rows per group | broaden `ilt_group_cols` or use `technical_limit` |

## Guardrails

1. Never choose a decision value. Show the preview and let the user decide.
2. Report the reconciliation failure count next to every NPT percentage.
3. Never present a text-derived NPT event without its verbatim quote.
4. Evidence tables carry quotes, not full remarks. Treat DDRs as operator-confidential.
5. Confirm with the user before running `ai_query` over more than ~50k remarks (cost).
6. Don't retry failing calls more than 3 times; report the error.

## Related Skills

- `osdu-ppdm-mapper`: canonical well and wellbore identity before joining DDRs across systems
- `equipment-pdm`: root-cause rig-equipment NPT from rig sensor data
- `energy-semantic-builder`: publish NPT % as a governed metric view
- `energy-report-writer`, `presentation-builder`: contractor review packs
- `skill-eval`: benchmark this skill (see `eval/`)

## References

- `references/npt_taxonomy.md`: categories, IADC-style code map, combine modes, ILT method
- `references/ddr_time_log.md`: input contract, WITSML mapping, reporting day, DST
- `references/span_grounding.md`: prompt rules and grounding backstops
- [IADC](https://iadc.org/): Daily Drilling Report and DDR Plus
- [Energistics WITSML](https://www.energistics.org/witsml-data-standards): opsReport / activity objects
- [ai_query function](https://docs.databricks.com/aws/en/sql/language-manual/functions/ai_query)
