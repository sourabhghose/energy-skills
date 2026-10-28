# Mapping spec format (YAML)

`propose_mapping_spec` writes a spec with `status: proposed`. A reviewer edits it and sets
`status: reviewed`. `build_confirmed_mapping` rejects anything else.

```yaml
spec_version: 1
entity: wellbore                 # well | wellbore | completion | production
source_table: main.raw.well_header
status: reviewed                 # proposed -> reviewed (human sign-off)
fields:
  wellbore_uwi:
    source: API_NO               # null = unmapped
    confidence: 0.84
    reason: name match 0.80, value-pattern fit 1.00
    required: true
  total_depth_md:
    source: TD
    uom: ft                      # REQUIRED for depth fields: ft | m (never inferred)
  wellbore_status:
    source: WELL_STATUS
    value_map:                   # null values must be filled or are written as null
      PR: PRODUCING
      SI: SHUT_IN
      "P&A": PLUGGED_AND_ABANDONED
      XYZ: null
coordinates:                     # only for entities with lat/lon fields
  surface: {lat: SURF_LAT, lon: SURF_LONG, crs: null}
datum_columns_in_source: [DATUM]
```

Rules:
- One source column can feed several **identifier** fields (an API-14 column feeds
  `wellbore_uwi` and `well_uwi`). Other columns map to at most one field.
- Reference-list codes are in `canonical_model.REFERENCE_LISTS` (status, fluid). Map source
  codes to them, or to your OSDU partition's reference values.
- The spec is hashed (`spec_hash`) into every output table comment and the run manifest, so
  any output traces back to the exact reviewed spec.
