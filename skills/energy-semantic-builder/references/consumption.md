# Consuming the metric views

```sql
-- Field production by month
SELECT DATE_TRUNC('MONTH', production_date) AS month, field_name,
       MEASURE(boe_per_day), MEASURE(water_cut_pct), MEASURE(gas_oil_ratio_scf_per_bbl)
FROM <cat>.<sch>.mv_upstream__well_day
GROUP BY ALL ORDER BY ALL;

-- Fleet availability, MW-weighted or unweighted as decided at build time
SELECT fuel_type, MEASURE(capacity_factor_pct), MEASURE(eaf_pct), MEASURE(efor_pct)
FROM <cat>.<sch>.mv_generation__unit_period
WHERE period_start >= '2024-01-01' GROUP BY ALL;
```

- **Genie**: add the metric views (not the silver views) to a Genie space; measure comments
  carry definition and unit so Genie can explain them.
- **AI/BI dashboards**: use metric views as datasets; never re-aggregate a composite.
- **Grants**: `GRANT SELECT ON VIEW ... TO <group>`; consumers do not need access to sources
  if the view owner has it.
- `SELECT *` is not supported on metric views; every measure needs `MEASURE()`.
