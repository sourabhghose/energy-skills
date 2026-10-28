# Factor sources and versioning

All factors live in `assets/emission_factors.csv` with `factor_set`, `source`, `vintage`, `status`
and `url`. The skill refuses to use a factor without a source and vintage, and the run manifest
lists every factor id used plus the ones still marked `verify_before_use`.

| factor_set | Source | Vintage | URL |
|---|---|---|---|
| `epa_hub_2025` | EPA GHG Emission Factors Hub (combustion, HHV, mobile) | 2025 | https://www.epa.gov/climateleadership/ghg-emission-factors-hub |
| `egrid_2023` | EPA eGRID2023 total-output CO2 rates by subregion | 2023 data | https://www.epa.gov/egrid/summary-data |
| `greene_rm_2025` | Green-e Residual Mix Emission Rates (2023 data) | 2025 release | https://resource-solutions.org/2025-residual-mix/ |
| `subpart_w_legacy` | 40 CFR 98 Subpart W Table W-1A (pre-2024 revision) | 2016 rule text | https://www.ecfr.gov/current/title-40/chapter-I/subchapter-C/part-98/subpart-W |

`status = verified`: checked against the cited source when the table was assembled (2026-10-28).
`status = verify_before_use`: plausible and cited, but not re-checked line by line; confirm against
the source before external disclosure.

## Adding factors

1. Add rows with a new `factor_set` name that encodes source + vintage (e.g. `epa_hub_2026`).
2. Never overwrite an existing set's values; inventories reference set names in their manifest.
3. If two chosen sets both have a factor for the same key, the lookup raises: pick one set per
   source type for a run.
4. Other common sources: IPCC 2006 Guidelines and 2019 Refinement (https://www.ipcc-nggip.iges.or.jp/),
   API Compendium of GHG Emissions Methodologies for the O&G Industry (2021), DEFRA/DESNZ
   conversion factors (UK), IEA emission factors (licensed).
