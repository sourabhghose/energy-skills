# VEE rules used by this skill

Validation, Estimation and Editing (VEE) is how a meter data management system (MDMS) turns
raw head-end reads into billing- and analytics-grade data. Utility rulebooks differ in their
thresholds but share the same structure. This file summarises that structure in our own
words; consult the sources for normative text.

## Validation checks

| Check | Rule in this skill | Invalidates? | Why it matters |
|-------|--------------------|--------------|----------------|
| Missing interval | Expected grid slot (UTC, DST-aware) has no read | yes | Completeness drives billing estimates and settlement |
| Duplicate | Same meter + interval start twice | only if values conflict | Head-end retries resend identical reads; conflicting ones are an error |
| Nonexistent local time | Label falls in the spring-forward gap (e.g. 02:15 local) | yes (dropped) | Usually a vendor clock bug; cannot be placed in time |
| Ambiguous single | Fall-back label (01:xx) seen once only | no, flagged | Order cannot tell DST from standard; assumed DST |
| Negative value | `kwh < 0` | per `net_metering_policy` | Valid export on net-metered/DER premises, error otherwise |
| Spike / high demand | `kwh / interval_hours > spike_max_kw` | yes | Above service capacity is physically impossible |
| Spike suspect | `> 10 x` the meter's own p99 but under the ceiling | no, flagged | Worth review; can be real (EV charging, well pump) |
| Flatline | Identical non-zero value for ≥ `flatline_min_hours` (default 4 h) | yes | Stuck register or repeated last-good value |
| Extended zero | Zero for ≥ `extended_zero_hours` (default 24 h) | no, flagged | Vacancy is legitimate; also a tamper/bypass signal |
| Source estimated | Head-end/MDM quality code `E` | no, kept as `SOURCE_ESTIMATED` | Never present upstream estimates as actuals |
| Register rollover | Negative delta from ≥ 90 % of dial capacity to ≤ 10 % | no (corrected) | 5-dial register wraps at 99 999 → 0 |
| Register reset | Any other negative delta | yes | Meter exchange or reprogramming |

Resolution pitfall: meters that report at 0.1 kWh resolution produce long identical runs at
low load. If the preview shows many flatlines on a coarse-resolution fleet, raise
`flatline_min_hours` rather than estimating real data away.

## Estimation hierarchy

1. **Linear interpolation** for short gaps (≤ `linear_max_gap_intervals`) bounded by valid
   reads on both sides. Many rulebooks allow interpolation for gaps up to 1–2 hours.
2. **Like-day (historical) estimation** for longer gaps up to `max_estimation_gap_hours`:
   mean of the same local wall-clock slot on the most recent `like_days` (default 4) valid
   days of the same type (weekday / weekend) within `like_day_lookback_days` (21). At least
   two like days are required.
3. **Register proration**: when register reads bracket a gap, estimates are rescaled so the
   gap sums to the metered register delta (energy conserving). With no usable shape the delta
   is spread uniformly.
4. Otherwise the interval stays **MISSING** (`kwh` NULL). Long outages should go to a field
   order, not an estimate.

Estimates never overwrite valid actual reads, and every interval carries a `quality_code` so
downstream billing, settlement, and analytics can filter (`ACTUAL`, `SOURCE_ESTIMATED`,
`ESTIMATED_LINEAR`, `ESTIMATED_LIKE_DAY`, `ESTIMATED_REGISTER_PRORATED`, `MISSING`).

## Editing

This skill does not edit actual reads. Manual edits belong in the MDMS with an audit trail;
the run manifest records every rule and threshold used so a run can be reproduced.

## Sources

- AEIC Meter & Service Technical Committee, *Guidelines for Validating, Editing, and
  Estimating Data* (AEIC VEE guidelines): https://aeic.org/
- Ontario Smart Metering Entity, MDM/R VEE standard and technical specifications (IESO):
  https://www.ieso.ca/en/Sector-Participants/Smart-Metering-Entity
- California IOU Direct Access / Rule 22 / Rule 25 VEE practices (CPUC tariffs):
  https://www.cpuc.ca.gov/
