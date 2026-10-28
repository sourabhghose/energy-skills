# Type curves, normalization, and the PRMS percentile convention

## P10 is the HIGH case

Under SPE PRMS, a probabilistic estimate is labelled by **probability of exceedance**:

- **P90**: 90% probability the actual outcome is at least this. This is the low estimate,
  i.e. the 10th percentile of the distribution.
- **P50**: the median.
- **P10**: 10% probability of exceeding. This is the high estimate, i.e. the 90th percentile.

So `np.percentile(eurs, 10)` is the **P90**, not the P10. `dca_typecurve.prms_percentiles`
names its outputs `p10_high`, `p50`, `p90_low`, and asserts P10 ≥ P50 ≥ P90.

## Building a monthly type curve

1. Condition each well with the same decisions as the per-well fits.
2. Align wells at the start of decline (month 0 = peak month, when `decline_start=peak`).
3. Optionally normalize (decision, see below).
4. For each month, take percentiles across the wells that have data that month.
5. **Truncate** months with fewer than `min_wells` wells (default 5). Late months contain
   only the oldest wells, which are often the best-performing early wells in a play. That
   survivor bias props up the tail.
6. Fit the modified hyperbolic to the P10, P50, and P90 series.

The P50 *of rates by month* is not the rate profile of the P50 *EUR* well. Report the EUR
distribution separately, computed from the per-well EURs.

## Normalization (decision)

- `none`: raw volumes.
- `lateral_length`: scale each well's rates and EUR by `reference_lateral_ft /
  well_lateral_ft`. This is common for horizontal unconventional wells, but it assumes
  production is linear in lateral length. It tends to overstate short laterals and
  understate long ones. Wells without a valid lateral length are excluded and listed.

Proppant-intensity or completion-design normalizations are play-specific. They should be
done upstream and passed in as an adjusted volume column, with the method documented.

## Alternatives to Arps (not implemented; know when to suggest them)

- **Duong (2011)**: for long-duration fracture-dominated linear flow in shale gas. It fits
  the early period well, but it also needs a terminal switch.
- **Stretched exponential (SEPD, Valkó 2009)**: bounded EUR without a switch. Popular for
  Barnett-type shale gas.
- **Rate-transient analysis**: uses flowing pressures, so it is better when pressure data
  exists. That is outside the scope of rate-only DCA.

## Sources

- SPE PRMS 2018, Section 4 (probabilistic terminology): https://www.spe.org/en/industry/petroleum-resources-management-system-2018/
- SPEE Monograph 3 / 4 (type wells, analog selection): https://spee.org/
- Duong, A.N. (2011). SPE-137748-PA. https://doi.org/10.2118/137748-PA
- Valkó, P.P. (2009). SPE-119369-MS. https://doi.org/10.2118/119369-MS
