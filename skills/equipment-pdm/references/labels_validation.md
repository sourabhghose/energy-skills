# Failure labels, leakage-safe validation, and alert metrics

## Labels come from maintenance records

Failures are taken from CMMS work orders (SAP PM, Maximo), not inferred from the sensors.
Inferring them from sensors would make the model detect its own definition.

- **`failure_modes`**: which work-order failure modes count. The codes in
  `pdm_taxonomy.FAILURE_MODES` follow the spirit of ISO 14224 (electrical failure, breakdown,
  vibration, overheating, low output, plugged, leakage, fail to start …). Map your CMMS
  codes to them first. Preventive work, inspections, and "no fault found" are **not** failures.
- **`label_horizon_hours`**: rows within the horizon before a failure are positive. Pick it
  from the lead time maintenance needs to act (schedule a workover rig, order a pump, plan a
  shutdown) and the realistic P-F interval (from detectable onset to functional failure).
  Typical values: ESP 72–336 h, compressors 24–168 h.
- Rows **during the outage** (failure start → restored) are excluded, not labelled healthy.
  After a repair the machine is effectively new and its baseline may shift.

## Leakage-safe splits

| `split_strategy` | Train | Test | Use when |
|---|---|---|---|
| `time` | before cutoff | after cutoff **+ embargo (= horizon)** | same fleet, future performance |
| `asset` | some assets | held-out assets (hash-selected, deterministic) | generalising to new assets |
| `asset_and_time` | other assets, before cutoff | held-out assets, after embargo | strictest |

Labels look forward by the horizon. Without the embargo, the last training rows "know"
about failures in the test period. Random row splits leak heavily because neighbouring
10-minute rows are nearly identical. Never use them.

## Baselines

- `robust_z`: median / MAD (×1.4826) per feature on **healthy, steady training rows**. Score
  = max |z| across features. Explainable, and a good first baseline.
- `isolation_forest` (scikit-learn): multivariate. Fitted on the same rows.

## Alerts and metrics

An alert event is the first exceedance of `alert_threshold`, followed by a cooldown of one
horizon per asset, so one bad day doesn't count as 100 alerts.

| Metric | Meaning |
|---|---|
| `caught` / `recall` | test failures with ≥ 1 alert inside the horizon before them |
| `median_lead_time_h` | earliest alert → failure, for caught failures |
| `false_alarms` | alerts not followed by a failure within the horizon |
| `false_alarms_per_asset_month` | the number planners care about: alert fatigue per machine |
| `precision` | share of alerts that preceded a failure |

The threshold is chosen from a sweep on the **training** period
(`sweep_alert_thresholds`). Choosing it on the test period overstates performance.
Few failures means wide uncertainty: with 3 test failures, recall can only be 0, 33, 67, or
100 %. Say so in the readout.

## Sources

- ISO 14224:2016, Collection and exchange of reliability and maintenance data for equipment
  (failure-mode taxonomy; summarized): https://www.iso.org/search.html?q=ISO%2014224
- ISO 17359:2018, Condition monitoring and diagnostics of machines: general guidelines
  (P-F interval / alarm setting concepts): https://www.iso.org/search.html?q=ISO%2017359
- Moubray, J., *Reliability-Centred Maintenance* (P-F interval).
