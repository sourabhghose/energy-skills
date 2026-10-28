---
name: osdu-ppdm-mapper
description: >-
  OSDU and PPDM data-model mapping for upstream well data: well header, wellbore, completion,
  and production tables from vendor or operator schemas mapped to OSDU well-known schemas
  (master-data--Well, master-data--Wellbore) and PPDM 3.9-style tables. Profiles the source,
  proposes a column mapping with confidence and reasons, writes a reviewable YAML mapping spec,
  and previews unmapped required fields, cast failures, identifier collisions, unmapped
  status/fluid codes, and coordinate problems. Grounds UWI / API-10/12/14 identifiers in the
  data (no fabricated IDs), surfaces "what is a well" level (well vs wellbore vs completion vs
  lease), API padding, source datum/CRS (NAD27 vs NAD83 vs WGS84, never mixed silently) and
  target standard for the user to choose, then writes canonical Delta tables, rejects, field
  lineage, and OSDU manifest skeletons. Call scripts/mapping_run.py entrypoints; do not
  hand-write mapping SQL. For log curves use well-log-ingest.
category: "Oil & Gas"
summary: Map vendor well, wellbore, completion and production data to OSDU / PPDM with a reviewed spec, grounded API IDs, explicit datums, and lineage.
version: 0.1.0
author: Sourabh Ghose
license: Databricks License
---

# OSDU / PPDM Mapper

## Overview

Maps messy upstream source tables (well header extracts, vendor data, regulatory downloads,
operator master data) onto a canonical well / wellbore / completion / production model that
lands in OSDU well-known schemas and PPDM 3.9-style tables. The mapping is a reviewable YAML
spec, not code the agent improvises. Identifiers are grounded in the data, the well-vs-wellbore
level is explicit, datums are never mixed, and every output column traces back to its source
column through the lineage table.

Outputs: `<prefix>_canonical`, `<prefix>_rejects` (with reasons), `<prefix>_lineage` (source →
canonical → OSDU path / PPDM column), `<prefix>_ppdm` (PPDM-named view), a run manifest with the
spec hash, and optionally an OSDU manifest JSON.

## When to Use

- "Load this IHS / Enverus / state well header extract into our OSDU-aligned well master."
- "Map our completion table to wellbores. Which API digits identify what?"
- "Why do some wells show up twice after joining production to the well header?"
- "Our well locations come from two vendors. Are they NAD27 or NAD83?"
- "Generate OSDU master-data--Well records from our Delta well table."
- "Produce a PPDM 3.9-style WELL table from our operator database."
- "Map our status codes (PR, SI, TA, P&A) to standard reference values."

## Prerequisites

- **Compute**: Python-enabled compute with Spark for writes. `pyyaml` for specs; `pyproj` only
  for optional datum transforms.
- **Input**: any UC table or view. The skill profiles whatever columns exist.
- **Spec storage**: a UC Volume or workspace path for the YAML spec (review artifact).
- **For OSDU output**: the target platform's `kind` version, data-partition namespace, ACL
  groups, and legal tags.

## Quick Start

```python
import sys
sys.path.append("<this-skill-dir>/scripts")
from mapping_run import propose_mapping_spec, preview_mapping_options, build_confirmed_mapping, format_result

SPEC = "/Volumes/main/upstream/specs/wellbore_spec.yaml"
# 1. Profile + propose (writes a spec with status: proposed)
print(propose_mapping_spec("main.raw.well_header", "wellbore", SPEC))
# 2. Human edits the spec: uom for depths, value_map gaps, crs; sets status: reviewed
# 3. READ-ONLY preview of what's left to resolve
print(preview_mapping_options("main.raw.well_header", SPEC))
# 4. Build, only after the user chooses each decision
res = build_confirmed_mapping("main.raw.well_header", SPEC, "main.upstream.wellbore",
                              source_identifier_level="completion", api_padding="leave_null",
                              source_crs="column:DATUM", target_standard="both")
print(format_result(res))
```

## Workflow

**⛔ EXECUTE, DO NOT REIMPLEMENT.** Call the entrypoints in `scripts/mapping_run.py` and report
their output. Do not write your own mapping SQL, pad or truncate API numbers yourself, or assume
a datum. The steps below explain what the entrypoints do.

### Step 1: Profile and propose

`propose_mapping_spec(table, entity, spec_path)` profiles each column (null %, distinct count,
API-like / lat-like / date-like value shares, datum-like column names) and proposes a mapping.
Exact synonym matches score 1.0, whole-token matches 0.8, close fuzzy matches up to 0.75; the
score is weighted by value-pattern fit. Only identifier fields may share a column. Fields below
0.6 stay unmapped.

### Step 2: Review the spec (human)

Have the user (or a data steward) open the YAML. Required edits: `uom` for every depth field,
`value_map` entries left `null`, and the `coordinates.*.crs` or datum column. Then set
`status: reviewed`. See `references/mapping_spec.md`.

### Step 3: Preview (read-only)

`preview_mapping_options` reports unmapped required fields, low-confidence mappings, cast
failures, identifier levels (10/12/14-digit mix and distinct prefixes), identifier collisions
(same ID with different names or TDs), unmapped reference values, depth fields without units,
coordinate issues (swapped, projected, sign, 0/0), and the datum values found in the source.

### Step 4: Decide "what is a well"

Use the identifier-level counts to ask the user what one source row is (`well`, `wellbore`,
`completion`, or `lease`). Going from a finer to a coarser level truncates the identifier and
collapses identical rows; rows that conflict are rejected. Going from a coarser to a finer level
needs `api_padding`. See `references/what_is_a_well.md`.

### Step 5: Build

`build_confirmed_mapping` applies the spec, writes canonical rows with `<depth>_uom` and
`source_crs` columns, rejects (`null_<field>;`, `conflicting_duplicate`), lineage, the PPDM view,
and the manifest. With `target_crs=` and pyproj installed it adds transformed `*_target`
coordinates and keeps the as-ingested values.

### Step 6: OSDU records (optional)

```python
build_confirmed_mapping(..., osdu={"kind": "osdu:wks:master-data--Well:1.2.0", "namespace": "opendes",
                                   "acl": {"owners": ["data.default.owners@opendes.example.com"],
                                           "viewers": ["data.default.viewers@opendes.example.com"]},
                                   "legal": {"legaltags": ["opendes-public-usa"],
                                             "otherRelevantDataCountries": ["US"]}},
                        osdu_manifest_path="/Volumes/main/upstream/osdu/wells_manifest.json")
```

Validate against the platform's Schema service before ingesting (`references/osdu_wks_notes.md`).

## Decision Points

| Decision | Options | Governing reference | What changes |
|---|---|---|---|
| `source_identifier_level` | `well`, `wellbore`, `completion`, `lease` | PPDM "What Is A Well"; US Well Number standard | truncation/collapse of IDs; conflicting-duplicate rejects |
| `api_padding` | `pad_zeros`, `leave_null` | US Well Number standard (00 = original hole) | whether well-level rows become wellbores |
| `source_crs` | `NAD27`, `NAD83`, `WGS84`, `EPSG:<code>`, `column:<datum col>`, `not_applicable` | EPSG; IOGP GN 7-2 | datum recorded per row; transform input |
| `target_standard` | `osdu`, `ppdm`, `both` | OSDU WKS / PPDM 3.9 | lineage targets; PPDM view |
| spec `status: reviewed` | human sign-off | data governance | build refuses proposed specs |
| depth `uom` in spec | `ft`, `m` | — | units recorded; never inferred |

The four build decisions are keyword-only with no defaults. `None` raises `DecisionRequired`.

## Key Parameters

| Parameter | Default | Range / Options | Effect |
|---|---|---|---|
| `entity` | — | `well`, `wellbore`, `completion`, `production` | target canonical entity |
| `sample_rows` | `5000` / `20000` | — | profile / preview sample size |
| `target_crs` | `None` | EPSG code | adds transformed coordinates (needs pyproj) |
| `osdu` | `None` | dict(kind, namespace, acl, legal) | emit OSDU record skeletons |
| `max_rows` | `5000000` | — | build read cap; truncation recorded |
| `write` | `True` | bool | `False` returns frames only |

## Expected Outputs

- `canonical`: one row per entity ID, canonical column names, `<depth>_uom`, `source_crs`, `source_row`
- `rejects`: rows with `reject_reason`
- `lineage`: `canonical_field, source_column, transform, uom, osdu_path, ppdm_column, spec_hash`
- `ppdm`: PPDM-named view (dots in column names become `__` in UC)
- `osdu_records` / manifest JSON: `id, kind, acl, legal, data` skeletons
- `run_manifest`: decisions, spec, spec hash, row counts

## Troubleshooting

| Problem | Cause | Solution |
|---|---|---|
| `mapping spec status must be 'reviewed'` | spec not signed off | review the YAML and set `status: reviewed` |
| `declare uom` error | depth field without `uom` | set `ft` or `m` in the spec |
| `needs 14-digit APIs but the data has lengths [10]` | declared level finer than the data | choose the level the data supports |
| Many `conflicting_duplicate` rejects | coarser target than source with differing attributes | map to the finer entity, or fix the source |
| All `null_wellbore_uwi` rejects | API-10 source mapped to wellbores with `leave_null` | confirm no sidetracks, then `pad_zeros` |
| `Unrecognized CRS` | free-text datum value | map datum values to EPSG codes in a view |
| `pyproj` error | transform requested without pyproj | install pyproj or omit `target_crs` |

## Guardrails

1. Never pad, truncate, or invent identifiers outside `apply_api_level` and the user's decisions.
2. Never assume a datum. "Probably NAD83" is a question for the data owner.
3. Never set `status: reviewed` on the user's behalf.
4. Don't fill OSDU `acl` / `legal` / `kind`; ask for the platform's values.
5. Report reject counts and reasons with every result.
6. Don't retry failing calls more than 3 times; report the error.

## Related Skills

- `well-log-ingest`: LAS/DLIS log curves keyed to the canonical wellbore IDs
- `decline-curve-analysis`: production forecasting once production is keyed to the right entity
- `drilling-report-npt`: DDR analysis keyed by canonical well IDs
- `unit-guard`: unit conversions for depths and volumes
- `energy-semantic-builder`: governed well-count and production metric views

## References

- `references/what_is_a_well.md`: hierarchy, API-10/12/14, padding, quirks
- `references/osdu_wks_notes.md`: record envelope, field paths, ingestion steps
- `references/crs_datums.md`: NAD27/NAD83/WGS84, projected CRS, checks
- `references/mapping_spec.md`: YAML spec format
- [OSDU data definitions](https://community.opengroup.org/osdu/data/data-definitions)
- [PPDM Association](https://ppdm.org/)
- [EPSG dataset](https://epsg.org/)
