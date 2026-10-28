# Coordinate reference systems and datums for well locations

## Why this is a decision

The same well's latitude/longitude differs between **NAD27** (EPSG:4267), **NAD83**
(EPSG:4269), and **WGS 84** (EPSG:4326). NAD27→NAD83 shifts are typically tens of metres and
can approach 100 m in parts of the US. NAD83→WGS 84 differs by about 1–2 m. Nothing in the
numbers tells you which datum they are on. Older US regulatory well locations (including
many state databases) are NAD27, and newer ones NAD83. Vendor extracts often mix both, with
a `DATUM` column if you're lucky.

Silent mixing puts wells on the wrong side of lease lines and spacing-unit boundaries, and
breaks anti-collision and offset-well queries.

## Options for `source_crs`

| Value | When |
|---|---|
| `NAD27`, `NAD83`, `WGS84`, `EPSG:<code>` | one datum for the whole source, confirmed by its owner |
| `column:<DATUM_COL>` | per-row datum column (values resolved via aliases or EPSG codes) |
| `not_applicable` | spec maps no coordinates |

Projected coordinates (state plane, UTM) must be declared with their EPSG code. The preview
flags `looks_projected` when a "latitude" column holds values over 90.

## Transformation

`target_crs="EPSG:4326"` (for example) adds `*_target` columns via **pyproj** (PROJ). It runs
only when pyproj is installed, and NAD27 grid-shift accuracy depends on the PROJ grids
available. The as-ingested values and `source_crs` are always kept: OSDU stores both
`AsIngestedCoordinates` and `Wgs84Coordinates`.

## Other checks in the preview

- `possibly_swapped`: latitude column holds a longitude-like value
- `unexpected_lon_sign`: positive longitude where the region expects negative (Western
  Hemisphere), usually a dropped minus sign
- `zero_zero`: null island (0, 0) placeholder

## Sources

- EPSG Geodetic Parameter Dataset: https://epsg.org/
- PROJ / pyproj: https://pyproj4.github.io/pyproj/stable/
- NOAA NGS, NADCON datum transformations: https://geodesy.noaa.gov/TOOLS/Nadcon/Nadcon.shtml
- IOGP Geomatics Guidance Note 7 part 2, "Coordinate Conversions and Transformations including Formulas" (IOGP 373-7-2), from https://www.iogp.org/
