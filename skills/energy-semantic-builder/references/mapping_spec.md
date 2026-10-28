# Source-mapping file spec

The per-customer mapping is the **only** customer-specific input. Keep it in the working
directory (`<customer>_mapping.yaml`), never inside this skill.

```yaml
name: <customer_slug>
description: <one line>
extends: [adapters/nerc_gads_performance.yaml]   # optional; later entries override earlier
target: { catalog: <catalog>, schema: <schema> }
scope: { domains: [upstream, generation] }        # optional; default = everything mappable
entities:
  well_day:
    source: <catalog>.<schema>.<table>
    joins:                                         # optional, MUST be to-one
      - { table: <catalog>.<schema>.<dim>, on: "<predicate>", type: left }
    fields:                                        # canonical_field: column or SQL expression
      well_id: uwi
      gas_mcf: "gas_m3 * 0.0353147"                # convert units HERE, never in measures
    enums:                                         # optional physical code -> canonical value
      technology: { source_column: tech_cd, map: { "PV": solar_pv, "WT": wind }, default: other }
    filter: "status <> 'TEST'"                     # optional
```

## Rules

- **Only map what exists.** Unmapped entities drop their metric views; unmapped optional
  fields drop the measures that need them. The preview lists every skip.
- **Units are canonical** (see `canonical_model.yaml` `unit`). Convert in `fields`
  (m³ → Mcf, kWh → MWh, °C → °F). Measures assume canonical units.
- **Joins must be to-one.** A fan-out join double-counts every SUM.
- **One grain per entity.** Monthly LOE and daily volumes do not share an entity; LOE per
  boe uses `well_month`, where both are conformed to the same grain.
- **Complete grids where a denominator averages over days** (`reliability_day`): every
  circuit × day row must exist. Use the reliability-metrics daily fact.
- **Decisions are not mapping.** Attestation decisions (`capacity_basis`,
  `heat_rate_basis`) state what the mapped field means; the build records them in the
  manifest. Substitution decisions (`gas_mcf_per_boe`, `gads_weighting`) change measure SQL.

## Drafting with the profiler

`scripts/profile_source.py` reads `information_schema.columns` and drafts a mapping: exact
name matches are bound silently, synonym matches and unmapped required fields carry
`# REVIEW`. Resolve every `# REVIEW` with the user before generating.
