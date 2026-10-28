# Data sources and preparation

| Layer | Public source | Notes |
|-------|---------------|-------|
| Fuel models | LANDFIRE FBFM40 (Scott & Burgan 40 fire behavior fuel models), 30 m raster | Aggregate to H3 by majority or worst family per cell; keep the code (e.g. `SH5`) |
| Terrain slope | LANDFIRE Slope or USGS 3DEP DEM | Degrees, not percent. 100% slope = 45° |
| Vegetation contact | Utility LiDAR tree-strike / encroachment surveys; LANDFIRE canopy cover as a proxy | Proxy must be labelled as such |
| Fire weather | NWS / NDFD gridded forecasts, utility weather stations, HRRR | Wind in **mph**, temperature in **°F**, RH in **%** for Fosberg; sustained wind for FFWI, gusts for PSPS triggers |
| Fire danger | NFDRS outputs (ERC, BI) via WFAS | Optional extra PSPS criterion |
| Historical ignitions | Utility ignition reports (CPUC fire incident data), NIFC WFIGS incident locations | Keep only utility-related causes for likelihood; WFIGS cause fields are often blank |
| Exposure | Microsoft / Overture building footprints, Census block population | Count per cell |
| High fire-threat districts | CPUC Fire-Threat Map (Tier 2 / Tier 3) or the state equivalent | Polygon → `h3_polyfillash3` → `hftd_tier` per segment |

## Pitfalls

- **Units.** Fosberg expects °F / mph / %RH. Celsius temperatures pass a naive range check
  in summer (30 °C reads as a cold 30 °F) and produce a wildly low index. Convert first.
- **Gust vs. sustained.** Fosberg uses sustained wind; PSPS criteria usually name both.
- **Lat/lon order.** Databricks `h3_longlatash3(lon, lat, res)`; python `h3.latlng_to_cell(lat, lng, res)`.
- **Span gaps.** Indexing poles only misses the conductor between them. Use
  `h3_coverash3` on the LINESTRING (Databricks) or the core's densified spans.
- **Time zones.** Forecast hours must be tz-aware; PSPS windows are communicated in local time.
- **CEII.** Segment coordinates and circuit topology are sensitive. Share only
  `shareable_cells` (H3 res 7, no ids). Use `grid-data-guard` for anything else.

## Sources

- LANDFIRE FBFM40 — https://landfire.gov/
- Scott, J.H.; Burgan, R.E. (2005) *Standard fire behavior fuel models*, RMRS-GTR-153 —
  https://www.fs.usda.gov/rm/pubs_series/rmrs/gtr/rmrs_gtr153.pdf
- Wildland Fire Assessment System (NFDRS outputs) — https://www.wfas.net/
- NIFC WFIGS open data — https://data-nifc.opendata.arcgis.com/
- CPUC fire-threat maps and PSPS — https://www.cpuc.ca.gov/psps
- Fosberg, M.A. (1978) "Weather in wildland fire management: the fire weather index",
  Conference on Sierra Nevada Meteorology.
- H3 resolution table — https://h3geo.org/docs/core-library/restable
- Databricks H3 functions — https://docs.databricks.com/aws/en/sql/language-manual/sql-ref-h3-geospatial-functions
