# Activity input schema

One row per source and period, long format. Columns not needed by a row's `source_type` may be null.

| Column | Type | Used by | Notes |
|---|---|---|---|
| `facility_id` | string | all | Ground in your asset register; never invent IDs |
| `period` | string | all | Reporting period, e.g. `2025` or `2025-Q1` |
| `source_type` | string | all | One of: `stationary_combustion`, `mobile_combustion`, `flare`, `pneumatic_device`, `tank_vent`, `vented_other`, `fugitive_component`, `process`, `purchased_electricity`, `sold_product` |
| `fuel_or_product` | string | all | Factor key: `natural_gas`, `distillate_fuel_oil_2`, `propane`, `diesel`, `motor_gasoline`, `crude_oil`; pneumatic device type `high_bleed`, `intermittent_bleed`, `low_bleed`, `pneumatic_pump` |
| `quantity`, `unit` | float, string | all | Units accepted: mmBtu, therm, Dth, GJ, MWh (energy); scf, Mcf, MMscf, gal, bbl (volume); kWh, MWh, GWh (electricity). `m3`, `ton`, `t`, `Btu` are rejected as ambiguous |
| `operational_control`, `financial_control` | bool | consolidation | Per facility |
| `equity_share` | float 0–1 | consolidation | Per facility |
| `ch4_mol_frac`, `co2_mol_frac` | float | flare, pneumatic, tank, component | From gas analysis; state the sample date in your manifest notes |
| `c2plus_mol_frac`, `c2plus_carbon_number` | float | flare | C2+ fraction and its average carbon atoms per molecule |
| `destruction_eff`, `combustion_eff` | float | flare (`measured` tier) | From performance test / OTM-52 |
| `device_count`, `operating_hours` | float | pneumatic, component | |
| `flash_gor_scf_per_bbl`, `flash_gor_source` | float, string | tank (`flash_factor`) | Source is mandatory (lab sample id, process simulation) |
| `measured_ch4_kg`, `measured_co2_kg` | float | vented/fugitive/process | Direct measurement (OGMP L4) |
| `site_level_reconciled` | bool | measured rows | True when reconciled against site-level measurement (OGMP L5) |
| `component_count`, `ef_scf_per_hour`, `ef_source` | float, float, string | fugitive_component | Component factor must name its source |
| `egrid_subregion` | string | purchased_electricity | eGRID acronym (e.g. `ERCT`, `CAMX`); `US` for national average |
| `rec_mwh` | float | purchased_electricity | MWh covered by retired EACs/RECs meeting Scope 2 Quality Criteria |
| `supplier_rate_lb_co2_per_mwh`, `supplier_rate_source` | float, string | purchased_electricity | Supplier-specific rate (market-based hierarchy) |

## Production input (optional, for intensity)

| Column | Notes |
|---|---|
| `facility_id` | Same IDs as activity |
| `oil_bbl` | Oil + condensate |
| `gas_mcf` | Gross gas produced |
| `gas_marketed_mcf` | Preferred denominator for methane intensity (OGCI-style); falls back to `gas_mcf` and records the basis |
