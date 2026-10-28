# Historian data: tags, compression, digital states, units

## Input contracts

**Historian samples** (long format, one row per stored value):

| Column | Type | Notes |
|---|---|---|
| `tag` | string | historian tag name, e.g. `ESP-101.MTR_AMPS` |
| `ts` | timestamp, tz-aware | historians store UTC; keep it UTC |
| `value` | string or double | analog value **or** a digital-state string |
| `quality` | optional | `good` / `0` / `192` (OPC good) / `true` are kept; anything else is dropped |

**Tag map** (curated, the only way tags enter the analysis):

| Column | Example |
|---|---|
| `tag` | `ESP-101.MTR_TEMP` |
| `asset_id` | `ESP-101` |
| `equipment_class` | `esp`, `compressor`, `pump`, `gas_turbine` |
| `measurement` | canonical name from `pdm_taxonomy.MEASUREMENTS` |
| `unit` | engineering unit as configured in the historian (`degF`, `psi`, `in/s` …) |

Build the tag map from the historian's tag attributes (PI point `engunits`, `descriptor`,
`pointsource`) or the asset framework (PI AF / AVEVA templates). Never derive it from tag
name patterns alone without review. Naming conventions drift between sites.

## Why tags are grounded, not guessed

- Historian tags absent from the map are **excluded** and listed (`unmapped_tags`).
- Tags in the map with no samples are listed (`missing_in_historian`). These are usually
  decommissioned or renamed points.
- Unknown measurement names or units with no conversion are excluded (`unit_problems`).

## Compression and exception reporting

PI and similar historians store a value only when it moves outside an exception deviation,
and then apply swinging-door compression. Consequences:

- Stored samples are irregular. A flat signal may have one sample per hour or per day.
- Linear interpolation between stored points is the historian's own reconstruction for
  analog tags. Tags flagged **step** (setpoints, counters, states) must be held, not
  interpolated (decision `analog_interpolation`, with state tags always held).
- A long gap can mean "flat" (compression) or "no data" (interface outage). The skill only
  fills a grid point when the bracketing samples are within `max_gap`. Choose `max_gap` from
  the preview's sampling-interval table (p95 gap). Use a small multiple, never hours, for
  fast signals.

## Digital states in analog tags

When an interface fails or a device is off, PI writes **system digital states** into analog
points: `I/O Timeout`, `Bad Input`, `Shutdown`, `Comm Fail`, `Calc Failed`, `No Data`.
Coercing them to numbers gives NaN or, worse, 0 after a careless `fillna(0)`, and 0 amps
looks like a pump-off. The skill drops them and reports counts per tag and state.

## Units

Canonical units: A, kPa (gauge stays gauge), degC, Hz, rpm, m3/h, kW, mm/s RMS velocity.
Conversions are listed in `pdm_taxonomy.UNIT_CONVERSIONS`. Gauge vs absolute pressure is
not converted. Keep them as separate measurements if both exist. For vibration, check the
measurement is **velocity RMS**. Peak, peak-to-peak, or acceleration (g) values aren't
comparable with ISO zone limits.

## Sources

- AVEVA PI Server documentation (exception and compression, digital states): https://docs.aveva.com/
- ISO 13374-1:2003, Condition monitoring and diagnostics of machines: data processing,
  communication and presentation (summarized; architecture of data acquisition → data
  manipulation → state detection → health assessment → prognostics → advisory generation):
  https://www.iso.org/search.html?q=ISO%2013374-1
- MIMOSA OSA-CBM (open implementation of ISO 13374 layers): https://www.mimosa.org/
