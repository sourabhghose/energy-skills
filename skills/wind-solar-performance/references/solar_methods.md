# Solar PV performance methods

Summarized in our own words.

## Performance ratio (IEC 61724-1)

PR = E_AC / (P_STC × H_POA / G_STC), where H_POA is plane-of-array insolation and G_STC = 1000 W/m2.
It must use **POA** irradiance; GHI-based "PR" is not a PR. The skill raises if only GHI exists.

Decision `pr_method`:

| Method | Reference yield | Use |
|---|---|---|
| `iec_61724_uncorrected` | P_STC × G/1000 | Simple, but swings seasonally with temperature |
| `temperature_corrected_stc` | × (1 + gamma (T_cell − 25)) | Removes temperature effect relative to STC |
| `nrel_weather_corrected` | × (1 + gamma (T_cell − T_cell,typ)) with T_cell,typ the irradiance-weighted average cell temperature | Capacity tests and contracts (Dierauf et al., NREL 2013) |

`gamma_pmax_per_c` comes from the module datasheet (typically −0.0026 to −0.0045 /degC). The skill
refuses implausible values.

Cell temperature: Sandia model (King et al.). From back-of-module temperature
T_cell = T_mod + G/1000 × dT; or from ambient and wind T_mod = G e^(a + b WS) + T_a. Defaults
are the open-rack glass/cell/polymer coefficients (a = −3.56, b = −0.075, dT = 3).

## Exclusions and decisions

- **Curtailment** (plant-controller setpoint, ISO instruction): always excluded from PR and
  reported as `lost_curtailment_kwh`. Curtailment is not underperformance.
- **Clipping** (`clipping_handling`): AC ≥ 98% of inverter AC rating. Excluding clipped intervals
  gives a "plant health" PR; including them gives the as-built PR, which bakes in the DC/AC ratio.
- **Inverter downtime** (`availability_in_pr`): IEC PR includes all losses; many O&M contracts
  report a performance-only PR excluding downtime and report availability separately.
- `min_poa_wm2` (default 50 W/m2) removes low-light intervals; state it.

## Degradation (year-on-year, RdTools-style)

Daily insolation- and temperature-normalized energy; for each day, the % change versus the same day
one year earlier; Rd = median of those changes. A 68.2% bootstrap interval matches RdTools
convention. Needs ≥ 1 year + 30 days. Filter out curtailed and clipped data upstream for long
studies, and check sensor drift (reference cells drift too).

## Soiling (screening)

Daily normalized energy divided by a trailing 30-day 95th percentile (proxy for clean
performance). This is a screen; confirm with RdTools' stochastic rate and recovery (SRR) method
before quoting a soiling loss.

## Sources

- IEC 61724-1 (PV system performance monitoring): https://webstore.iec.ch/en/publication/65561
- Dierauf et al., "Weather-Corrected Performance Ratio", NREL/TP-5200-57991 (2013):
  https://www.nrel.gov/docs/fy13osti/57991.pdf
- RdTools (NREL): https://github.com/NREL/rdtools ; Jordan et al., "Robust PV degradation methodology
  and application", IEEE JPV (2018)
- Deceglie et al., soiling SRR method: https://www.nrel.gov/docs/fy18osti/70216.pdf
- King et al., Sandia PV array performance model (SAND2004-3535):
  https://www.osti.gov/biblio/919131
- NREL PVDAQ public PV data: https://openei.org/wiki/PVDAQ
