# Input data contract

Map your physical columns to these canonical names with `steps_columns` /
`customers_columns` (`{canonical: physical}`) when calling the runner.

## restoration steps (OMS / outage history)

| Column | Type | Notes |
|--------|------|-------|
| `event_id` | string | One outage event; repeated across its restoration steps |
| `outage_start` | timestamp (tz-aware) | When the customers lost power |
| `restore_ts` | timestamp (tz-aware) | When *this step's* customers were restored |
| `customers_restored` | int | Customers restored at this step (> 0) |
| `cause_code` | string | Utility cause code (vegetation, equipment, animal, ...) |
| `is_planned` | boolean | Pre-notified, utility-initiated interruption |
| `circuit_id` | string | Optional; feeder for circuit-level metric view slicing |

An OMS that stores one row per event (no steps) is a single-step event: one row with all
customers and the final restore time. Say so in the readout; it overstates CMI when the
utility actually restored in stages.

## customers served (CIS)

| Column | Type | Notes |
|--------|------|-------|
| `period_start` | date | Month (preferred) or year start |
| `customers_served` | int | Active metered customers |
| `circuit_id` | string | Optional; required for circuit-level N_T |

## momentary operations (SCADA / recloser logs, optional)

`device_id`, `op_ts` (tz-aware), `customers_affected`.

## customer-level interruptions (AMI last-gasp or OMS customer links, optional)

`customer_id`, `event_id`, `duration_min` (sustained only) — enables CAIFI, CEMI_n, CELID.
