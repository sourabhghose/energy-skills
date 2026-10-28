# PSPS candidate screening

Public Safety Power Shutoff decisions are made by the utility's emergency operations under
its regulator-approved protocol. This skill only **screens** circuits whose segments in a
high fire-threat district meet the user's weather thresholds in some forecast hour.

## Inputs

- Forecast per H3 cell and hour: `wind_gust_mph`, `wind_sustained_mph`, `rh_pct`, `temp_f`,
  `valid_ts` (tz-aware).
- `psps_thresholds` (decision, no defaults): `wind_gust_mph`, `rh_pct`, optional `ffwi`.
- Optional `circuit_customers` (circuit_id, customers, medical_baseline_customers) for impact.

## Output columns

`circuit_id, segments_flagged, first_hour, last_hour, peak_gust_mph, min_rh_pct, peak_ffwi`
(+ customer counts when supplied).

## Choosing thresholds

Protocols differ by utility and change between seasons. Commonly cited examples in
California utility communications combine low humidity (≤ ~30%), sustained winds above
~25 mph, gusts above ~45 mph, and dry fuels. The preview shows how many circuits
three example threshold sets would flag; they are illustrative, not recommendations.
Ask the user for their protocol's values.

## Not in scope

Fuel moisture (dead/live), red-flag warnings, meteorologist judgement, sectionalizing
devices, and community resource centers. Name them in the readout as factors the
screening did not consider.
