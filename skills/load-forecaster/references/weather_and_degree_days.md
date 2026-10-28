# Weather, degree days, and normalization

## Station selection

The right station is where the load is, with complete data. The preview ranks candidates by
coverage of the load period, then by R² of daily energy against a quadratic in daily mean
temperature (a quick test of both heating and cooling fit), and by distance when station
coordinates and a load centroid are supplied. Airport ASOS stations (NOAA ISD) are the usual
choice. For large territories, a load-weighted blend of several stations beats any single
one. Blending is out of scope for v0.1; run per zone instead.

## Units and bases

- **Degree days.** HDD = max(base − T_daily_mean, 0) and CDD = max(T_daily_mean − base, 0),
  using the daily mean of hourly temperatures.
- **US convention.** Both bases are 65 °F (NOAA CPC, EIA). The European/metric convention
  is 18 °C (some use 15.5 °C for HDD).
- **Balance point.** The real balance point of a load is often lower for heating (55–62 °F)
  and higher for cooling (68–72 °F) than the convention, because of internal gains and
  thermostat habits. The preview fits a five-parameter change-point model (in the spirit of
  ASHRAE Guideline 14's inverse models) over a grid of bases and shows how much worse the
  65/65 convention fits than the best pair. The user chooses.
- **Temperature unit.** Check the unit before choosing bases. A summer p95 below ~45 means
  Celsius. The preview reports it, and the user confirms.

## Weather normalization

`normalized = actual + (model(normal weather) − model(actual weather))`, with a daily model
`energy = a + b·HDD + c·CDD + day-of-week + holiday`.

- **Normals** are the mean of each calendar day's degree days across `normal_years`. Don't
  compute degree days from a mean temperature: averaging first understates degree days.
- **Choice of period.** NOAA's official normals use 30 years (1991–2020). Many utilities use
  a trailing 10 or 20 years to capture warming. This is a decision point; it can move
  normalized energy by a few percent.
- **Quality checks.** Report fit R² and CV(RMSE); ASHRAE Guideline 14 commonly cites
  CV(RMSE) thresholds for monthly and hourly calibration.

## Sources

- NOAA NCEI Integrated Surface Database (ISD): https://www.ncei.noaa.gov/products/land-based-station/integrated-surface-database
- NOAA U.S. Climate Normals 1991–2020: https://www.ncei.noaa.gov/products/land-based-station/us-climate-normals
- NOAA CPC degree day definitions: https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/cdus/degree_days/
- EIA-930 Hourly Electric Grid Monitor (hourly demand by balancing authority, UTC hour-ending): https://www.eia.gov/electricity/gridmonitor/
- ASHRAE Guideline 14, *Measurement of Energy, Demand, and Water Savings* (paywalled; summarised in our words): https://www.ashrae.org/
- NERC off-peak holidays (NAESB/NERC "additional off-peak days"): https://www.naesb.org/
