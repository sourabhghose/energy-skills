# OGMP 2.0 reporting levels

The Oil & Gas Methane Partnership 2.0 (UNEP IMEO) defines five reporting levels. Summarized:

| Level | What it means | How the skill assigns it |
|---|---|---|
| 1 | One consolidated methane number per venture/asset | Not produced by this skill |
| 2 | Generic emission factors by broad emission category | Not produced (use L3 or better) |
| 3 | Generic emission factors by detailed source type | Combustion, flares, pneumatic devices, component factors, flash factors |
| 4 | Source-specific emission factors or direct measurement | `measured_ch4_kg` rows; `measured_vent_volume` tanks |
| 5 | Level 4 reconciled with site-level (top-down) measurement | Measured rows with `site_level_reconciled = True` |

OGMP 2.0 member companies commit to reach Level 4 for operated assets and Level 5 ("gold standard")
within set timelines. The `ogmp` output shows the CH4 share at each level; that share, not the
total, is the progress metric.

Sources:
- OGMP 2.0 framework: https://ogmpartnership.org/
- UNEP IMEO: https://www.unep.org/topics/energy/methane/international-methane-emissions-observatory
