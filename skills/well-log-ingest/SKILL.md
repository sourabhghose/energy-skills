---
name: well-log-ingest
description: >-
  LAS well log ingestion (LAS 1.2/2.0, partial 3.0, via lasio) from Unity Catalog Volumes into
  governed Delta tables: well header, curve catalog, tidy long curves, and a wide
  per-family table. Standardizes vendor mnemonics to curve families (GR, RHOB, NPHI, DT,
  DTS, RT/RM/RS, CALI, SP, PEF). Normalizes units (kg/m3 to g/cm3, % to v/v, us/m to us/ft,
  mm to in) and flags units that are missing or contradicted by the values. Handles -999.25
  nulls and other sentinels, converts depth between KB, DF, and GL datums and between ft
  and m, validates US API 10/12/14 numbers (including lost leading zeros) and Canadian
  UWIs, and resolves duplicate curves and overlapping runs by explicit policy. Never
  produces TVDSS without a survey. For production decline use decline-curve-analysis; for
  OSDU/PPDM well master mapping use osdu-ppdm-mapper.
category: "Oil & Gas"
summary: LAS logs to governed Delta tables with standardized mnemonics, verified units, explicit depth datum, API number checks, and run-overlap policy.
version: 0.1.0
author: Sourabh Ghose
license: Databricks License
---

# Well Log Ingest: LAS to Governed Delta Tables

## Overview

Loads a folder of LAS files into four Unity Catalog tables petrophysicists can trust. A
general agent typically runs `lasio.read(...).df()` and concatenates the results. That
leaves `RHOZ` in kg/m³ next to `RHOB` in g/cm³, neutron in percent next to v/v, −9999
values in the gamma ray, depths from different datums in one column, and API numbers
missing their leading zero.

This skill profiles every file first. It then puts each ambiguity in front of the user and
writes:

- `<prefix>_well_header`: one row per file (API check, elevations, datum, log date)
- `<prefix>_curve_catalog`: per-curve family, declared vs canonical unit, scale, QC counts
- `<prefix>_curves_long`: api14, source_file, depth, family, mnemonic, value, unit
- `<prefix>_curves_wide`: one column per family per depth, with overlaps resolved by policy
- `<prefix>_manifest`: every decision, plus files that failed or were skipped

## When to Use

- "Load these 3,000 LAS files from the volume into Delta so we can query them."
- "Standardize curve names across vendors: I want one GR, RHOB, NPHI column per well."
- "Some neutron logs are in percent and some in decimal. Fix that."
- "Convert all depths to ground level in feet."
- "Our API numbers don't match the production database." (lost leading zeros, 10 vs 14 digits)
- "Two logging runs overlap. Keep the newer run in the composite."
- "What curves do we actually have, and for which wells?" (curve catalog)

## Prerequisites

- **Compute**: Python-enabled compute with `lasio` installed (`%pip install lasio`).
  Files are read through the `/Volumes/...` mount.
- **Inputs**: a UC Volume path containing `.las` files (searched recursively), or one file.
- **Permissions**: `READ VOLUME`; `CREATE TABLE` on the target schema.
- **Scale**: parsing runs on the driver, at roughly 20–200 files/s depending on size. For
  more than ~5,000 files, run by sub-folder.

## Quick Start

```python
import sys
sys.path.append("<this-skill-dir>/scripts")
from las_run import preview_las_ingest, build_confirmed_las_ingest

# STEP 1: READ-ONLY profile. Lists ambiguous units, sentinels, datums, and API issues per file.
print(preview_las_ingest("/Volumes/main/subsurface/raw/las"))

# STEP 2: ONLY after the user answered every listed decision.
print(build_confirmed_las_ingest("/Volumes/main/subsurface/raw/las", "main.subsurface.logs",
      sentinel_policy="common_sentinels", depth_unit="ft", depth_datum="KB",
      family_conflict_policy="keep_all", unit_resolution={"TNPH": "PU"},
      api_zero_pad="pad", overlap_policy="prefer_latest_run"))
```

## Workflow

**⛔ EXECUTE, DO NOT REIMPLEMENT.** Call the entrypoints in `scripts/las_run.py` and report
their output. Do not write your own LAS parsing or unit scaling, do not guess a unit from
values, and do not choose a datum or sentinel policy yourself.

### Step 1: Locate files

Confirm the Volume path. `list_las_files` searches recursively for `*.las`, case-insensitive.

### Step 2: Preview (read-only)

`preview_las_ingest` prints, per file:

- LAS version and wrap
- depth unit, log-measured-from datum, and elevations
- API status
- every curve that is not clean: family, declared unit, status, median, proposed unit,
  sentinel count
- family conflicts
- LAS 3.0 warnings
- the list of decisions that file needs

### Step 3: Ask the user

Group the questions:

1. **Units.** List each `ambiguous_unit` / `implausible_range` curve with its median and
   proposed unit. Get an explicit unit per curve, or a mnemonic-wide answer.
2. **Sentinels.** Should −999 / −9999 values beyond the header NULL be treated as nulls?
3. **Depth.** Which output unit (ft/m)? Which datum (as logged, KB, DF, GL)?
4. **API.** If the preview reports `leading_zero_lost`, restore the zero ("pad") or reject?
5. **Duplicates.** Should duplicate curves in a file be kept (all) or reduced to the first
   listed? Which run wins in overlaps (latest, earliest, or skip the wide table)?

### Step 4: Build

Call `build_confirmed_las_ingest(...)` with every decision. `DecisionRequired` means a curve
or file still needs an answer. Ask, then call again. Files whose datum can't be converted
(no `LMF`, missing elevations) are skipped and listed; they are not guessed.

### Step 5: Report

Report the counts (files, curves, samples), skipped and failed files with reasons, curves
with `n_out_of_range > 0`, and the unmapped mnemonics, so the alias table can grow.

## Decision Points

| Decision | Options | Governing reference | What changes |
|----------|---------|---------------------|--------------|
| `unit_resolution` | `{"file::MNEM" or "MNEM": unit}`; `{}` if none listed | CWLS LAS; vendor docs | 100× (NPHI %), 1000× (kg/m³) errors |
| `sentinel_policy` | `header_null_only`, `common_sentinels` | LAS `NULL` | −9999 values in statistics and cutoffs |
| `depth_unit` | `ft`, `m` | — | All depth columns |
| `depth_datum` | `as_logged`, `KB`, `DF`, `GL` | `LMF`, `EKB`/`EDF`/`EGL` | Shifts depths by the KB / DF height (often 15–30 ft onshore) |
| `api_zero_pad` | `pad`, `reject` (only when listed) | PPDM US Well Number | Whether joins to production / permits succeed |
| `family_conflict_policy` | `keep_all`, `first_listed` | — | Which duplicate curves are stored |
| `overlap_policy` | `prefer_latest_run`, `prefer_earliest_run`, `skip_wide` | — | Composite (wide) curve values in overlap intervals |

## Key Parameters

| Parameter | Default | Range / Options | Effect |
|-----------|---------|-----------------|--------|
| `depth_step` | 0.5 ft / 0.1524 m | > 0 | Grid used to align runs in the wide table |
| `max_files` (preview) | 50 | 1–500 | Files profiled in the preview |
| `output_prefix` | required | `catalog.schema.name` | Table name prefix |

## Expected Outputs

- `<prefix>_well_header`: source_file, file_sha256, las_version, api14, api_status, uwi_raw,
  well_name, company, field, log_date, elev_kb/df/gl, log_measured_from, depth_unit,
  depth_datum, warnings
- `<prefix>_curve_catalog`: source_file, mnemonic, family, unit_declared, unit_canonical, scale,
  status, kept, n_values, n_null, n_sentinel_replaced, n_out_of_range, min, max
- `<prefix>_curves_long`: api14, source_file, depth, family, mnemonic, value, unit, depth_unit, depth_datum
- `<prefix>_curves_wide`: api14, depth, gr_gapi, rhob_gcc, nphi_vv, dt_usft, rt_ohmm, … (unit-suffixed)

## Troubleshooting

| Problem | Cause | Solution |
|---------|-------|----------|
| `ModuleNotFoundError: lasio` | Library not installed | `%pip install lasio`, then restart Python |
| `DecisionRequired: unit_resolution[...]` | Missing or contradictory unit | Ask; pass the unit per file or per mnemonic |
| File skipped: `LMF ... missing` | No log-measured-from datum | Use `depth_datum="as_logged"`, or fix the header upstream |
| PARSE FAILED | Malformed LAS (bad section, wrong column count) | Inspect the file; lasio's error names the line |
| LAS 3.0 warning | Only the first data section was read | Check for core / other `~Log` sections |
| Many `UNMAPPED` curves | Vendor-specific mnemonics | Add aliases to `mnemonics.py` with a test |

## Guardrails

1. Never apply a value-inferred unit without the user's confirmation.
2. Never output TVD or TVDSS from MD alone. A deviation survey is required.
3. Never silently re-pad or truncate identifiers.
4. Keep every run in the long table; resolve overlaps only in the wide view.
5. Confirm before ingesting more than ~5,000 files in one call, and avoid retrying more than 3 times.

## Related Skills

- `osdu-ppdm-mapper`: map headers to the OSDU / PPDM well master; surveys for TVD
- `decline-curve-analysis`: production forecasting, joined on `api14`
- `unit-guard`: general unit conversions
- `energy-semantic-builder`: governed petrophysical KPIs over the wide table
- `energy-foundation-models`: embeddings or foundation models over log curves

## Bundled Resources

- `scripts/las_parse.py`: lasio → `ParsedLas` adapter (lazy lasio import)
- `scripts/las_core.py`: profiling, decisions, unit/sentinel/datum normalization
- `scripts/mnemonics.py`: family aliases, unit aliases, plausibility ranges
- `scripts/api_number.py`: US API / Canadian DLS validation
- `scripts/las_wide.py`: per-family wide table with run-overlap policy
- `scripts/las_run.py`, `scripts/uc_io.py`: Volume listing, preview, governed writes
- `references/las_format.md`: LAS versions, sections, nulls, depth datums, DLIS
- `references/mnemonics_and_units.md`: family table, unit traps, API number standard

## References

- [CWLS LAS standards](https://www.cwls.org/products/#products-las)
- [lasio documentation](https://lasio.readthedocs.io/)
- [PPDM US Well Number standard](https://ppdm.org/)
- [dlisio (DLIS reader)](https://dlisio.readthedocs.io/)
- [SLB curve mnemonic dictionary](https://www.apps.slb.com/cmd/)
