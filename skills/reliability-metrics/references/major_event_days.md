# Major Event Days: the 2.5 beta method

A Major Event Day (MED) is a day whose daily SAIDI exceeds a threshold T_MED derived
statistically from the utility's own history. Excluding MEDs separates day-to-day
performance from catastrophic weather.

## Procedure (as implemented in `scripts/reliability_core.py`)

1. Compute **daily SAIDI** for every day of the previous **five** years:
   daily CMI (sustained, under the confirmed planned / threshold decisions) ÷ N_T for that
   year. Assign each event to the **local** calendar day it began.
2. **Drop days with zero SAIDI.** Their logarithm is undefined; they are excluded from the
   fit, not set to a small number.
3. Take the natural log of the remaining daily SAIDI values.
4. alpha = mean of the logs; beta = standard deviation of the logs (sample, ddof = 1).
5. **T_MED = exp(alpha + 2.5 · beta)**.
6. Any day in the **reporting year** with daily SAIDI > T_MED is a MED.

## Pitfalls

| Pitfall | Effect | Rule |
|---------|--------|------|
| Fitting on the reporting year itself | A big storm year raises its own threshold and hides its MEDs | Use the five years *before* the reporting year |
| Including zero-SAIDI days as tiny values | Drags alpha down; inflates MED count | Exclude them |
| Fewer than five years of history | Threshold less stable | Use what exists, and warn (the skill does) |
| Using UTC days | Storm split across two days, neither exceeds T_MED | Local calendar day |
| Excluding MEDs without reporting the all-days number | Regulators and benchmarking (EIA-861) want both | Always report both |
| Circuit-level MEDs | IEEE MEDs are identified at the system / reporting-area level | Flag days system-wide, then apply to circuits |

## Sources

- IEEE Std 1366-2022 — https://standards.ieee.org/ieee/1366/7243/
- IEEE PES Distribution Reliability Working Group (origin of the 2.5 beta method and annual
  benchmarking) — https://cmte.ieee.org/pes-drwg/
