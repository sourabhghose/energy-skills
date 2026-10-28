# NPT taxonomy, activity codes, and invisible lost time

## Definitions

- **Non-productive time (NPT)**: rig time spent on unplanned events that stop progress on the
  well plan, such as stuck pipe, losses, well control, equipment failure, or waiting. Operators
  usually report it as hours and as a percentage of total rig time.
- **Invisible lost time (ILT)**: time lost while doing *productive*, planned work slower than a
  benchmark (slow tripping, slow connections, slow casing runs). It never appears as an NPT code.
  It is measured against a **technical limit** (the best achievable time for that activity in
  that hole section) or an offset-well percentile (P10 = best 10 %).
- **Weather downtime**: waiting on weather (WOW). Some contracts count it as NPT, some report it
  separately, and some exclude it from contractor KPIs because the contractor can't control it.
  The skill treats this as a decision (`weather_policy`).

## Categories used by this skill

| Category | Typical evidence in remarks | Responsibility notes |
|---|---|---|
| STUCK_PIPE | "jarring", "worked stuck pipe", "pack-off", "differentially stuck" | Formation / practices |
| LOST_CIRCULATION | "partial losses 40 bbl/hr", "total losses", "pumped LCM" | Formation |
| WELL_CONTROL | "kick", "influx", "shut in", "circulate out gas", "kill" | Well / practices |
| EQUIPMENT_RIG | "repair top drive", "mud pump down", "drawworks", "BOP repair" | Drilling contractor |
| EQUIPMENT_DOWNHOLE | "MWD failure", "motor stalled/failed", "RSS no comms" | Service company |
| WAIT_WEATHER | "WOW", "lightning", "high winds", "sea state" | Nobody (force majeure) |
| WAIT_MATERIALS | "waiting on casing", "WO cement unit", "waiting on crew" | Logistics / third party |
| FISHING | "fishing for", "overshot", "milling junk", "lost in hole" | Varies |
| WELLBORE_INSTABILITY | "tight hole", "excessive back-reaming", "hole collapse" | Formation |
| OTHER_NPT | unplanned time that fits no class | Review |

Splitting **EQUIPMENT_RIG** from **EQUIPMENT_DOWNHOLE** matters. Contractor scorecards and
service-company scorecards must not charge each other's failures.

## Activity codes

IADC-style DDR forms carry a numeric activity code per time-log line. Land-rig forms commonly
use codes 1–21 (for example 2 = drilling, 6 = trips, 8 = repair rig, 19 = fishing, 21 = other).
Revisions, offshore forms, and operator systems (WellView, OpenWells, DDR Plus) differ, and many
operators add an NPT flag plus their own sub-codes.

The skill ships `IADC_STYLE_CODE_MAP` (in `scripts/npt_taxonomy.py`) only as a starting point:

- Only codes that unambiguously mean NPT map to a category (8 → EQUIPMENT_RIG, 19 → FISHING).
- Code 21 "other" and planned activities map to `None`. Unplanned reaming or circulating
  hidden under productive codes is only recoverable from text (`combine_mode` union/text_only).
- Codes not in the map are **reported as unmapped**, never guessed.
- An operator mapping (`code_taxonomy={...}`) replaces the default entirely.

## Combining codes and text

| Mode | Row is NPT when | Use when |
|---|---|---|
| code_only | activity code maps to NPT | codes are audited and trusted |
| text_only | grounded remark text asserts NPT | codes are missing or unreliable |
| union | either | recovering uncoded NPT (most common audit) |
| intersection | both | high-precision KPI reporting |

When both sources flag a row, the **coded category wins** because the coded record is the
contractual one, and `npt_source = both`. Rows whose text yields more than one category are
flagged `multi_category` for review instead of having their hours split silently.

## ILT method (offset percentile)

For each group (default: activity code; better: activity code + hole section):

- With footage (drilling): rate = footage / hours; the benchmark rate is the P90 of rates
  (the P10-best performance); ILT = hours − footage / benchmark rate, floored at 0.
- Without footage: the benchmark duration is the P10 of durations; ILT = hours − benchmark.
- Groups with fewer than 5 rows get NaN ILT, because there are too few offsets to benchmark.
- `technical_limit` uses an engineer-supplied table keyed by the same group columns.

Duration-only ILT is crude for trips and casing runs, whose time depends on depth. Prefer
rate-based groups, or a technical-limit table, for those activities.

## Sources

- IADC, Daily Drilling Report (DDR) and DDR Plus programme: https://iadc.org/
- Energistics WITSML 2.x data standards (opsReport / time log objects), now part of The Open
  Group OSDU Forum: https://www.energistics.org/witsml-data-standards and https://www.opengroup.org/
- Bond, D.F., Scott, P.W., Page, P.E., Windham, T.M., "Step Change Improvement and High Rate
  Learning are Delivered by Targeting Technical Limits on Sub-Sea Wells", IADC/SPE 35077, 1996.
  Source of the technical-limit and invisible-lost-time concepts (search on https://onepetro.org/).
- ISO 14224 (equipment failure taxonomy), useful for coding EQUIPMENT_* sub-causes:
  https://www.iso.org/search.html?q=ISO%2014224
