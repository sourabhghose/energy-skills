# Conditioning production data before fitting

Most bad decline fits come from the data, not the model. `dca_prep.condition_well`
applies these rules and records why each period was excluded (`exclude_reason`).

## Rate basis: calendar-day vs producing-day (decision)

Monthly volumes are reported per calendar month. Two different rates can be derived:

- **Calendar-day rate** = volume / days in month. Downtime appears as lower rates, so
  forecasts carry the historical downtime forward implicitly.
- **Producing-day rate** = volume / days on. This is the well's capability. Forecast volumes
  then assume the forecast is run at 100% uptime, unless you apply an uptime factor.

A month with 10 days on and the rest shut in shows a calendar-day rate one-third of the
producing-day rate. Fitting calendar-day rates through downtime months pulls the curve down
and changes b. Which basis to use depends on how the forecast is consumed (reserves vs
operations). It is a decision. Producing-day requires a reliable days-on column; days-on
greater than calendar days is clipped and counted.

## Shut-in and zero periods

Periods with zero or missing volume, or with volume but zero days-on (a data error), are
excluded from the fit. Their volume still counts toward cumulative production to date.
They are never interpolated.

## Start of decline (decision)

- **peak**: the maximum rate within the first 12 producing months (or 365 days). This
  excludes cleanup and flowback ramp-up, which otherwise forces a poor early fit.
- **first_production**: use all history. This is appropriate for conventional wells
  without a ramp.

Restarts after long shut-ins or refracs create a new decline segment. Fit them separately
by passing the post-event history; the skill does not auto-detect segments.

## Outliers (decision)

`mad` flags points whose log rate deviates from a centered 5-point rolling median by more
than 3 robust sigmas, where sigma is 1.4826 × MAD with a 3% floor. This catches workover
spikes, allocation errors, and flush production after shut-ins. `none` keeps every
producing point. Excluded outliers are listed, so a reviewer can restore any that were
real.

## Gas, oil, and boe

Fit each stream (oil, gas, water) in its own unit. Never fit boe. The boe roll-up depends
on a convention (6:1 energy, heating value, or price parity) and on GOR changing over time.
Convert after forecasting with `unit-guard`'s `boe_from_gas`.

## Units

The volume unit is a required argument (`bbl`, `Mcf`, `MMcf`, `m3`, `Sm3`). Rates are per
day in that unit, and outputs carry a `volume_unit` column.
