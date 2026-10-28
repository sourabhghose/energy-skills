# Settlement and revenue

Decision `settlement`:

| Method | Revenue | When |
|---|---|---|
| `two_settlement` | DA_MW × DA_LMP × hours + Σ_RT (MWh_i − DA_MW × Δt_i) × RT_LMP_i | Resources with day-ahead awards (most ISO generators, batteries) |
| `rt_only` | Σ_RT MWh_i × RT_LMP_i | Merchant resources without DA positions; ERCOT RT-only resources |
| `da_only` | DA_MW × DA_LMP × hours | Financial view of the DA position only |

- Interval-level: RT deviations settle per settlement interval (5-minute in most ISOs, 15-minute
  in ERCOT). Using hourly-average RT price × hourly deviation misstates revenue whenever price and
  output co-vary within the hour (solar ramps, battery dispatch).
- Sign convention: injections positive MWh, withdrawals (battery charging, station load) negative.
- Not included: ancillary services, uplift/make-whole, capacity, congestion hedges (FTR/CRR),
  ERCOT RT adder allocation details, imbalance charges specific to each tariff. Report them as
  out of scope rather than approximating.
- Node: settle at the resource's settlement point (ERCOT resource node, PJM pnode), not the hub.
  Hub prices are for hedges; the node-minus-hub basis is the hedge risk.
