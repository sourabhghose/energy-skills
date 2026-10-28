# DDR time-log data model and reconciliation

## Expected input columns

| Column | Type | Notes |
|---|---|---|
| `well_id` | string | API/UWI or operator well ID. Ground it in the data and never invent it. |
| `rig_id`, `contractor` | string | for rig / contractor scorecards |
| `start_time`, `end_time` | timestamp | prefer tz-aware (rig local time with zone) |
| `activity_code` | string | IADC-style or operator code |
| `remarks` | string | free-text operation description |
| `row_id` | string, optional | stable line ID; generated if absent |
| `footage_ft`, `hole_section` | optional | enable rate-based ILT and section grouping |

Rename source columns to this contract with a SQL view before calling the skill. WITSML
`opsReport` → `activity` elements map naturally: `dTimStart`/`dTimEnd` → start/end,
`codeActivity`/`proprietaryCode` → `activity_code`, `comments` → `remarks`.

## Reporting day

DDRs cover a reporting period, commonly midnight–midnight or 06:00–06:00 (morning report).
Assigning lines to the wrong period moves NPT between days and breaks the "every day sums to
24 hours" check. That is why `report_day_start_hour` is a decision and the preview shows the
reconciliation under both conventions.

## Daylight saving time

A reporting day that contains a DST transition has 23 or 25 elapsed hours. With tz-aware
timestamps the skill computes the expected hours for each day, so a correct 25-hour log on the
fall-back day is `ok`. With naive timestamps every day is expected to be 24 h. A 25-hour log
then shows as `long_day`, which is correct to flag because the source should carry its zone.
Offshore rigs often log in UTC or a fixed offset, so check which.

## Reconciliation statuses

| Status | Meaning |
|---|---|
| ok | logged hours equal expected hours (±0.01 h), no overlaps |
| short_day | logged < expected: missing lines or internal gaps |
| long_day | logged > expected: duplicated lines or wrong day assignment |
| overlap | consecutive lines overlap in time |
| negative_duration | end before start (data-entry error) |

NPT percentages computed on days that fail reconciliation are unreliable. Report how many
well-days failed next to every NPT figure.
