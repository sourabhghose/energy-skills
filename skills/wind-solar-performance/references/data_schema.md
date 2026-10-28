# Input schemas

## Wind SCADA (10-minute)

| Column | Unit | Required | Notes |
|---|---|---|---|
| `turbine_id` | — | yes | Ground in the asset register |
| `timestamp` | tz-aware | yes | State `timestamp_convention` (vendors differ: many export interval-*beginning*, some interval-*ending*) |
| `wind_speed_ms` | m/s | yes | Nacelle anemometer (apply nacelle transfer function if you have one) |
| `power_kw` | kW | yes | 10-minute mean active power |
| `state` | — | yes | Map vendor status codes to: `running`, `curtailed`, `derated`, `fault`, `maintenance`, `grid_outage`, `weather_standby` |
| `ambient_temp_c` | degC | for density | |
| `pressure_hpa` | hPa | for density | Or pass `site_elevation_m` (barometric estimate) |
| `setpoint_kw` | kW | optional | Active-power setpoint; below 99% of rated = curtailed |
| `vane_rel_deg` | deg | optional | Wind direction relative to nacelle (yaw misalignment) |

Status-code mapping is a customer-specific step: put the vendor-code → state table in UC and join it
before calling the skill. Never guess what an unknown code means; the skill raises on unknown states.

## Warranted power curve

`ws_ms`, `power_kw` at the density stated in the turbine supply agreement (pass that density as
`ref_density`).

## Solar (5- to 15-minute)

| Column | Unit | Required | Notes |
|---|---|---|---|
| `timestamp` | tz-aware | yes | State `timestamp_convention` |
| `poa_wm2` | W/m2 | yes | Plane-of-array irradiance (pyranometer or reference cell — state which) |
| `ac_power_kw` | kW | yes | Plant or inverter AC output |
| `inverter_id` | — | optional | Enables per-inverter availability |
| `module_temp_c` | degC | one of | Back-of-module temperature |
| `ambient_temp_c`, `wind_speed_ms` | degC, m/s | one of | Used for Sandia cell-temperature model |
| `setpoint_kw` / `curtailed` | kW / bool | optional | Plant controller / ISO instruction |
| `inverter_status` | — | optional | `ok` or a fault label |
| `ghi_wm2` | W/m2 | optional | Not a substitute for POA |
