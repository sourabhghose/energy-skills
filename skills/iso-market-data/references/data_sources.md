# Data sources and fetching

Fetching needs network access and sometimes API keys; tests never fetch. Land raw data in a bronze
UC table, then run the skill on it.

| ISO | Public source | Key needed | Notes |
|---|---|---|---|
| CAISO | OASIS API (`oasis.caiso.com/oasisapi/SingleZip?queryname=PRC_LMP` DA, `PRC_INTVL_LMP` RT) | no | Zip/CSV; GMT start/end columns; request windows ≤ 31 days |
| ERCOT | Public API (`api.ercot.com/api/public-reports/...`), MIS reports (NP4-190 DAM SPP, NP6-905 RT SPP) | yes (free registration) | DSTFlag on repeated hour |
| PJM | Data Miner 2 API (`api.pjm.com/api/v1/da_hrl_lmps`, `rt_fivemin_hrl_lmps`) | yes (free subscription key) | Row limits per request |
| MISO | Market reports CSV (DA ex-post LMP, RT 5-min) | no | EST |
| NYISO | MIS CSV archives (`mis.nyiso.com/public/csv/damlbmp/`) | no | Zone and generator LBMP files |
| ISO-NE | ISO Express CSV / web services | web services need account | Hourly and 5-min LMPs |
| SPP | Marketplace file browser (DA LMP by location, RTBM LMP) | no | GMTIntervalEnd |

Battle-tested option: [gridstatus](https://github.com/gridstatus/gridstatus) (open source) wraps all
seven ISOs and returns `Interval Start`/`Interval End`. `scripts/iso_run.fetch_with_gridstatus`
calls it lazily. Normalize its output with `time_format="utc_column"`, `ts_col="Interval Start"`,
`source_timestamp_convention="interval_beginning"` after renaming `Location`→`node`, `LMP`→`lmp`.

EIA-930 (hourly BA demand and generation, not prices): https://www.eia.gov/electricity/gridmonitor/
