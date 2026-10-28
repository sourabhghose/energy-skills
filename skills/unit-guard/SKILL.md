---
name: unit-guard
description: >-
  Energy unit conversion and dimensional checking for oil & gas, power, and emissions data:
  bbl, Mcf/MMcf/Bcf, scf vs Sm3/Nm3 with explicit standard conditions, MMBtu/therm/GJ/MWh,
  MW vs MWh vs MW-month, boe (6:1 energy, heating-value, or price parity), heat rate and
  efficiency on an HHV or LHV basis, short/long/metric tons, tCO2e with an AR4/AR5/AR6 GWP set,
  psia vs psig, and temperature. Refuses ambiguous symbols (MBtu, MT, ton, psi, bar, cf) and
  cross-dimension arithmetic (MW + MWh). Lints column names for missing or ambiguous units,
  and converts Unity Catalog columns with a reproducible manifest. Other energy skills call
  its scripts instead of hand-writing factors. For GHG inventories use
  ghg-emissions-calculator; for interval meter data use ami-interval-analytics.
category: Others
summary: Vetted, dimension-checked energy unit conversions (Mcf, boe, MMBtu, MWh, tCO2e) that refuse ambiguous units and ask about standard conditions and conventions.
version: 0.1.0
author: Sourabh Ghose
license: Databricks License
---

# Unit Guard: Energy Units Without Silent Assumptions

## Overview

Energy data mixes oil-field, utility, and SI conventions. `M` means thousand in `Mcf` and
mega in `MW`. A "ton" can be short, long, or metric. `scf` has no universal reference
pressure. `boe` is a convention, not a unit. Unit Guard is a small, tested registry and
conversion library that gets these right. It refuses to guess when a symbol or a convention
is ambiguous, and it puts the choice in front of the user instead.

Outputs: converted values (scalars or UC columns), a lint report of column-name unit problems,
and a manifest recording every factor and decision.

## When to Use

- "Convert this production table from Mcf/d to MSm³/d for our Norwegian partner."
- "Report total production in boe" (the user must choose 6:1 energy, heating value, or price parity).
- "What's the efficiency of a 7,000 Btu/kWh heat-rate unit?" (on an HHV or LHV basis).
- "Turn these 15-minute MW readings into MWh" (needs the actual interval hours, including DST days).
- "Convert methane tonnes to CO₂e" (the user picks the GWP set, and the CH₄ origin for AR6).
- "Check this table's columns for unit problems before we build the dashboard."
- Any other skill that needs a factor: import `units_core` rather than typing a number.

## Prerequisites

- **Compute**: any Python 3.10+ for the core (stdlib only). Runner functions need Python
  compute in Databricks (serverless or cluster) or Databricks Connect.
- **Inputs**: scalar values with unit symbols, or a UC table (`catalog.schema.table`).
- **Permissions** (runner): `SELECT` on the source; `CREATE TABLE` on the target schema.

## Quick Start

```python
import sys
sys.path.append("<this-skill-dir>/scripts")
from units_core import convert, boe_from_gas, to_co2e, power_to_energy, DecisionRequired

convert(1, "MWh", "MMBtu")                                       # 3.412141633
try:
    convert(250, "MMcf/d", "MSm3/d")
except DecisionRequired as d:
    print(d.decision, d.options)                                 # ask the user
convert(250, "MMcf/d", "MSm3/d", {"scf_standard_conditions": "60F_14.696psia"})
boe_from_gas(600, "Mcf", method="energy_6_to_1")                 # 100.0 boe
to_co2e(12.0, "t", gas="CH4", gwp_set="AR5_100")                 # 336.0 tCO2e
power_to_energy(80, "MW", hours=25)                              # 2000 MWh (fall-back DST day)
```

## Workflow

**⛔ EXECUTE, DO NOT REIMPLEMENT.** Call the functions in `scripts/` and report their output.
Do not type conversion factors, do not pick a standard-conditions basis, boe method, GWP set,
or HHV/LHV basis yourself, and do not "fix" an ambiguous unit by guessing.

### Step 1: Lint the data's units (read-only)

For a UC table, run the preview. It lints column names, profiles numeric ranges (a "bbl"
column with a median of 5 × 10⁶ is probably in m³ or a different scale), and lists the
decisions each proposed conversion needs.

```python
from units_run import preview_unit_audit
print(preview_unit_audit("main.ops.daily_production",
      proposed=[{"column": "gas_mcf", "from_unit": "Mcf", "to_unit": "MSm3"}]))
```

For names only: `from units_lint import lint_columns; lint_columns(df.columns)`.

### Step 2: Surface decisions to the user

Each `DecisionRequired` names the decision, the options, and why it matters. Present them as
choices (see Decision Points). Don't proceed on an assumed value.

### Step 3: Convert

Scalars: `convert(value, from_unit, to_unit, decisions)`. Columns: the confirmed build.

```python
from units_run import build_confirmed_conversion
print(build_confirmed_conversion(
    "main.ops.daily_production", "main.ops.daily_production_si",
    conversions=[{"column": "gas_mcf", "from_unit": "Mcf", "to_unit": "MSm3", "new_column": "gas_msm3"}],
    decisions={"scf_standard_conditions": "60F_14.696psia"}))
```

The output table gets a column comment per converted column (`unit=…; from …; × factor`), and
a manifest row is appended to `<output_table>_manifest`.

### Step 4: Conventions that aren't conversions

```python
from units_core import (boe_from_gas, to_co2e, heat_rate_to_efficiency,
                        convert_heating_value_basis, gas_volume_to_energy)
boe_from_gas(1.2e6, "Mcf", method="price_parity", gas_price_per_mcf=3.1, oil_price_per_bbl=72.0)
heat_rate_to_efficiency(6_900, "Btu/kWh", basis="HHV")            # 0.4945 (HHV)
gas_volume_to_energy(10, "MMcf", heating_value_btu_per_scf=1_037, basis="HHV", to_unit="MMBtu")
```

### Step 5: Report

State every converted quantity with its unit and the decisions used, for example:
*"1,234 MSm³ (scf basis 60 °F / 14.696 psia → Sm³ at 15 °C / 101.325 kPa)."*

## Decision Points

| Decision | Options | Governing reference | What changes |
|----------|---------|---------------------|--------------|
| `scf_standard_conditions` | `60F_14.696psia`, `60F_14.73psia`, `60F_14.65psia` | ISO 13443; AGA; state rules | ±0.55% on every gas volume crossing to Sm³/Nm³ |
| `boe_method` | `energy_6_to_1`, `heating_value`, `price_parity` | SEC S-K 1200; SPE PRMS | 6:1 vs ~25:1 can double or halve a gas-weighted boe total |
| `gwp_set` (+ `ch4_origin` for AR6) | `AR4_100`, `AR5_100`, `AR6_100` | IPCC; 40 CFR 98 Table A-1 | CH₄ CO₂e changes 25 → 28 → 29.8 (+19%) |
| `heating_value_basis` | `HHV`, `LHV` | EIA (HHV), IEA (LHV) | ~10% on gas energy, heat rate, efficiency |
| `atmospheric_pressure_psia` | 14.696 or the site value | site elevation | ~1–2 psi at high-altitude fields |
| Ambiguous symbols | e.g. `ton` → `short_ton` / `long_ton` / `t` | — | up to 12% (tons), 1000× (MBtu) |

## Key Parameters

| Parameter | Default | Range / Options | Effect |
|-----------|---------|-----------------|--------|
| `decisions` | none (required in build) | dict of the above | Resolves conventions; recorded in the manifest |
| `new_column` | same as `column` | valid identifier | Name of the converted output column |
| `hours` (`power_to_energy`) | required | ≥ 0 | Actual interval length; 23/25 on DST days |
| `lhv_over_hhv` | required | 0.7–1.0 | Fuel-specific HHV↔LHV ratio |

## Expected Outputs

- Scalar values, or a UC table with converted columns and column comments stating unit and factor
- `<output_table>_manifest` row: source table, row count, conversions with scale/offset, decisions
- Lint report: `[error|warn|info] column: issue -> suggestion`

## Troubleshooting

| Problem | Cause | Solution |
|---------|-------|----------|
| `AmbiguousUnit: 'MBtu'` | Prefix means thousand or million | Ask the user; use `kBtu` or `MMBtu` |
| `DecisionRequired: scf_standard_conditions` | scf ↔ Sm³/Nm³ crosses reference bases | Ask which basis the source data uses (contract, regulator) |
| `DimensionError: MW to MWh` | Power vs energy | `power_to_energy(value, "MW", hours)` with the real interval hours |
| `UnknownUnit` | Symbol not in the registry | Add it to `units_registry.py` with a cited factor and a test |
| Heating value rejected | Value given in MJ/m³ or Btu/Mcf | Convert to Btu/scf first (≈ 800–1600 is plausible) |
| Converted magnitudes look wrong | Source column wasn't in the claimed unit | Check `preview_unit_audit` ranges before converting |

## Guardrails

1. Never type a conversion factor; if the registry lacks a unit, stop and say so.
2. Never choose a decision-point value; surface it with its effect.
3. Refuse cross-dimension arithmetic; explain the correct operation instead.
4. Keep the unit with every number in the response.
5. Confirm before converting tables over ~1 billion rows, and avoid retrying more than 3 times.

## Related Skills

- `ghg-emissions-calculator`: Scope 1/2/3 inventories (uses `to_co2e`, GWP sets)
- `decline-curve-analysis`: EUR in bbl/Mcf; boe roll-ups via `boe_from_gas`
- `ami-interval-analytics`: kW/kWh interval data; DST-aware interval hours
- `iso-market-data`: $/MWh prices, MW awards vs MWh settlement
- `wind-solar-performance`: capacity factor (MWh vs MW × hours)
- `energy-semantic-builder`: governed KPI definitions that cite unit-guard conventions

## Bundled Resources

- `scripts/units_registry.py`: unit registry with cited factors, ambiguous-symbol table, gas bases
- `scripts/units_core.py`: `convert`, `boe_from_gas`, `to_co2e`, heat rate, HHV/LHV, `Quantity`
- `scripts/units_lint.py`: column-name lint
- `scripts/units_run.py`: `preview_unit_audit`, `build_confirmed_conversion` (UC runner)
- `scripts/uc_io.py`: identifier validation, governed writes, manifests
- `references/conversion_factors.md`: factor sources, standard-condition and GWP tables
- `references/traps.md`: the nine unit traps and how they're handled

## References

- [NIST SP 811: Guide for the Use of the SI](https://www.nist.gov/pml/special-publication-811): exact definitions
- [EIA: Units and calculators](https://www.eia.gov/energyexplained/units-and-calculators/): heat content, conversions
- [ISO 13443: Natural gas standard reference conditions](https://www.iso.org/standard/20461.html)
- [SPE units and standards](https://www.spe.org/en/industry/units-standards/)
- [IPCC AR6 WG1 Ch. 7](https://www.ipcc.ch/report/ar6/wg1/): GWP-100 values
- [40 CFR Part 98 Table A-1](https://www.ecfr.gov/current/title-40/chapter-I/subchapter-C/part-98): GHGRP GWPs
