# Subpart W screening methods

Screening-level implementations inspired by 40 CFR Part 98 Subpart W (Petroleum and Natural Gas
Systems). They are adequate for inventory screening, internal targets, and comparison; they are
**not** a substitute for the exact regulatory calculation methods when you file under the GHGRP.

Sources:
- eCFR 40 CFR 98 Subpart W: https://www.ecfr.gov/current/title-40/chapter-I/subchapter-C/part-98/subpart-W
- 2024 Subpart W final rule preamble: https://www.epa.gov/system/files/documents/2024-05/subpart-w-final-preamble-rule-2024.pdf
- RY2025 Subpart W webinar: https://www.epa.gov/system/files/documents/2024-12/ghgrp_subpartw_ry2025_webinar.pdf

## Standard conditions

Subpart W uses 60 degF and 14.7 psia. Gas densities at those conditions: CH4 0.0192 kg/scf,
CO2 0.0526 kg/scf. Volumes at other reference conditions (e.g. m3 at 15 degC) must be converted
first; the skill rejects `m3` as ambiguous.

## Flares (decision: `flare_efficiency_tier`)

Mass balance on the flare gas:

- CH4 emitted = V × x_CH4 × (1 − DE)
- CO2 emitted = V × [x_CO2 + CE × (x_CH4 + Σ x_j × n_j)] × ρ_CO2

where DE is the destruction efficiency, CE the combustion efficiency, n_j the carbon atoms of
hydrocarbon j. The 2024 revision (effective RY2025) replaced the single 98% assumption with tiers:

| Tier | DE | CE | When (summary; read the rule) |
|---|---|---|---|
| `tier1_de98` | 98% | 96.5% | Flare meets the referenced continuous monitoring / performance provisions |
| `tier2_de95` | 95% | 93.5% | Flare meets NSPS OOOOb-type monitoring or has approved test results |
| `tier3_de92` | 92% | 90.5% | Requirements for tiers 1 and 2 not met |
| `legacy_ce98` | 98% | 98% | Pre-RY2025 default; use only to reproduce historical inventories |
| `measured` | row | row | Site test values in `destruction_eff`, `combustion_eff` |

The choice moves flare methane by up to 4x (2% vs 8% slip), so the preview shows CH4 under every
tier. Unlit periods should be entered as venting, not flaring.

## Pneumatic devices

Screening: device count × operating hours × whole-gas emission factor × gas composition. The
factors in `assets/emission_factors.csv` (`subpart_w_legacy`) are the pre-2024 Table W-1A onshore
production factors (high bleed 37.3, intermittent 13.5, low bleed 1.39, pumps 13.3 scf/h/device).
The 2024 revision changed pneumatic methods for RY2025 (including measurement options). These
factors are marked `verify_before_use`.

## Storage tanks (decision: `tank_method`)

- `measured_vent_volume`: metered or calculated vent gas volume × composition (OGMP level 4 when
  measured).
- `flash_factor`: throughput (bbl) × flash gas-oil ratio (scf/bbl) × composition. The flash GOR
  must name its source (lab sample, process simulation such as E&P TANK / ProMax).

Tanks with vapor recovery or routed to a flare: enter the uncaptured share as `tank_vent` and the
routed share as `flare`.

## Equipment leaks and other venting

Provide measured CH4 (`measured_ch4_kg`) where you have it (OGMP level 4; level 5 when reconciled
with site-level measurement). Otherwise component count × hours × component factor with a mandatory
`ef_source`. The skill does not ship component factors; pick them from Subpart W Table W-1 or your
program and record the source.
