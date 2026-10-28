# OSDU well-known schema (WKS) notes

The skill maps to a **flat canonical model** (`scripts/canonical_model.py`). Each canonical
field records the OSDU data-block path it corresponds to, and `osdu_records.py` builds record
skeletons for `master-data--Well` and `master-data--Wellbore`.

## Record envelope

Every OSDU storage record carries:

- `id`: `<data-partition-namespace>:master-data--Well:<unique>`. The skill derives `<unique>`
  from the grounded UWI and never generates synthetic IDs.
- `kind`: `osdu:wks:master-data--Well:<semver>`. Pass the exact version your platform's
  Schema service has registered; the skill has no default.
- `acl`: `{owners: [...], viewers: [...]}` entitlement groups.
- `legal`: `{legaltags: [...], otherRelevantDataCountries: [...]}`.
- `data`: the entity block.

`acl` and `legal` are platform governance settings. The skill refuses to fill them in.

## Fields used

| Canonical | OSDU path (data block) | Notes |
|---|---|---|
| `well_name` | `FacilityName` | |
| `well_uwi` | `NameAliases[]` with `AliasNameTypeID` → `reference-data--AliasNameType:UWI` | primary identifier kept as an alias |
| `surface_latitude/longitude` | `SpatialLocation.AsIngestedCoordinates` | `AnyCrsFeatureCollection` with `CoordinateReferenceSystemID`; WGS 84 goes in `Wgs84Coordinates` after a platform-side transform |
| `well_status` | `FacilityStates[].FacilityStateTypeID` | reference-data value; map source codes first |
| `wellbore_uwi` / `well_uwi` | `NameAliases[]` / `WellID` | `WellID` is a relationship: `<ns>:master-data--Well:<id>:` (trailing colon = latest version) |
| `trajectory_type` | `TrajectoryTypeID` | reference-data value |
| depths | `VerticalMeasurements[]` | each measurement needs a vertical reference (`VerticalMeasurementPathID`, datum) and a unit |

## Before ingesting

1. Fetch the registered schema for the `kind` from the Schema service and validate records.
2. Make sure the reference-data values (AliasNameType, FacilityStateType, trajectory types)
   exist in your partition. Map source codes to *your* reference values.
3. Use the manifest-based ingestion workflow (Airflow DAG `Osdu_ingest`) to load the
   manifest written by `build_confirmed_mapping(osdu_manifest_path=...)`.

Production volumes are not part of the core WKS master data. Most operators keep them in a
lakehouse table keyed by the reporting entity, so the skill emits a PPDM-style
`PDEN_VOL_SUMMARY` view instead.

## Sources

- OSDU data definitions, schemas and reference data: https://community.opengroup.org/osdu/data/data-definitions
- OSDU Forum (The Open Group): https://osduforum.org/
- Energistics (WITSML, PRODML, RESQML), part of The Open Group: https://www.energistics.org/
