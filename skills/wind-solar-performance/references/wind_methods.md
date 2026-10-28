# Wind performance methods

Summarized in our own words; consult the standards for normative requirements.

## Power curve (IEC 61400-12-1)

- **Method of bins**: 0.5 m/s wind-speed bins centred on integer multiples of 0.5 m/s; each bin's
  power is the mean of its 10-minute values. A bin needs at least 3 samples to count; the standard
  also requires a minimum total database duration (on the order of 180 h) and coverage from below
  cut-in to well above rated before a curve is "complete". The skill marks bins `complete` but does
  not certify the database.
- **Air-density normalization**: rho = p / (R T) with R = 287.05 J/(kg K) (Ed. 2 adds a humidity
  term; omitted here). Pitch-regulated turbines normalize wind speed: V_n = V (rho / rho_ref)^(1/3).
  Stall-regulated turbines normalize power: P_n = P rho_ref / rho.
- **Reference density** (decision): the density the warranted curve is quoted at (often 1.225
  kg/m3, sometimes site-specific). Normalizing to the site mean and then comparing against a
  1.225 curve biases the AEP ratio by a few percent at high-altitude or warm sites.
- **Nacelle anemometry**: SCADA wind speed is measured behind the rotor. Results are relative
  (turbine vs. turbine, before vs. after) unless a nacelle transfer function is applied. Say so in
  the report.

## Filtering

| Filter | Rule in this skill |
|---|---|
| Missing / out of range | ws < 0 or > 40 m/s; power < -5% or > 110% rated |
| Stuck anemometer | ≥ 6 consecutive identical non-zero wind speeds |
| Curtailment / derate | state curtailed/derated, or setpoint < 99% rated |
| Turbine down | state fault / maintenance |
| External down | state grid_outage |
| Icing (suspect) | ambient ≤ 2 degC, running, power < 50% of expected |

## Lost production split

Per interval, expected power comes from the reference curve at the (normalized) wind speed:

- `lost_availability_kwh`: turbine fault / maintenance
- `lost_external_kwh`: grid outage
- `lost_curtailment_kwh`: curtailed / derated intervals — **never** counted as underperformance
- `performance_gap_kwh`: running, uncurtailed intervals, signed (negative = overperformance)

## Availability (IEC 61400-26 style; decisions `availability_basis`, `external_downtime`)

- **Time-based**: 1 − unavailable hours / (period hours − excluded hours).
- **Energy-based** (production-based): actual / (actual + lost energy from unavailability).
- External downtime (grid, force majeure) is commonly excluded in contractual availability but
  counted in technical availability. Pick one and state it.

## Yaw misalignment

Median of vane-relative wind direction in 5–10 m/s running data; |offset| > 4 deg is flagged. The
loss band uses cos² to cos³ of the offset (field studies report exponents in that range).

## Sources

- IEC 61400-12-1 (Power performance measurements): https://webstore.iec.ch/en/publication/68499
- IEC 61400-26-1 (Availability): https://webstore.iec.ch/en/publication/32855
- NREL OpenOA (operational analysis library; battle-tested alternative for AEP and losses):
  https://github.com/NREL/OpenOA
- Kelmarsh wind farm open SCADA dataset (Cubico, Zenodo): https://zenodo.org/records/5841834
- Penmanshiel wind farm open SCADA dataset (Cubico, Zenodo): https://zenodo.org/records/5946808
