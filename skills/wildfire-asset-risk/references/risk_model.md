# Risk model: likelihood × consequence

This skill scores **overhead line segments**. The model is transparent on purpose: every
component is on a fixed 0–1 scale and the weights are the user's decision, recorded in the
manifest. It is a screening and prioritization model. It does **not** replace a utility's
regulator-filed risk model (e.g. ignition probability × wildfire spread consequence models
used in California Wildfire Mitigation Plans).

## Likelihood (per segment)

| Component | Source layer | Scale | Aggregation over segment cells |
|-----------|--------------|-------|--------------------------------|
| `vegetation` | vegetation strike / contact index | 0–1 as supplied (LiDAR tree-strike potential, canopy cover) | max |
| `fuel` | LANDFIRE FBFM40 code | family hazard: NB 0, TL 0.3, TU 0.6, GR 0.6, GS 0.75, SB 0.85, SH 0.9 | max |
| `slope` | terrain slope (degrees) | slope / 45°, clipped | max |
| `ignition_history` | utility-related ignitions per cell | count within buffer / 3, clipped | sum within k rings |

`likelihood = Σ weight_i × component_i`, weights ≥ 0 summing to 1.

Fixed physical scales (not min–max over the network) keep scores comparable between runs
and between service territories. Min–max rescaling makes a segment's score depend on which
other segments were in the query.

Missing hazard data counts as 0 for that component and is flagged in
`missing_hazard_data`. Report the count; do not silently treat missing as safe.

## Consequence (per segment)

Structures and/or population within the segment's cells plus `buffer_k` rings, log-scaled:
`log1p(x) / log1p(cap)` with caps of 1,000 structures and 5,000 people. The
`consequence_basis` decision picks structures, population, or their mean.

## Risk and roll-ups

- `risk = likelihood × consequence` (0–1).
- Circuit risk = sum of segment risk; `risk_per_mile` = circuit risk / circuit miles.
  Report both: long rural circuits dominate the sum, short urban-interface circuits
  dominate per mile.

## Mitigation prioritization (risk-spend efficiency)

For each segment and mitigation option: `risk_reduction = risk × effectiveness`,
`cost = miles × cost_per_mile`, `RSE = risk_reduction / ($ cost / 1e6)`. The best-RSE option
per segment is kept, then segments are taken in RSE order while they fit the budget
(greedy; items that do not fit are skipped, not the end of the list). Greedy is a heuristic,
not an optimal knapsack solve; say so when presenting a plan.

Effectiveness and unit cost are **decisions**, not defaults. Take them from the utility's
own WMP / GRC filings. Published California WMPs give a wide range of values, for example
covered conductor effectiveness estimates around 60–70% and undergrounding near 95–99%
reduction of ignition risk, at very different costs per mile. Treat any number not from the
user's own filings as illustrative.

## Sources

- California OEIS, Wildfire Mitigation Plans and risk methodology guidance — https://energysafety.ca.gov/
- CPUC Risk-based Decision-making Framework (RDF / S-MAP, risk-spend efficiency) — https://www.cpuc.ca.gov/
