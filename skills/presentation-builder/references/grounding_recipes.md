# Grounding recipes

<!-- Adapted from databricks-industry-solutions/vital-skills (skills/presentation-builder/references/grounding_recipes.md); modified for the energy industry. -->

A deck is only trustworthy if every number came from the data and carries its unit.
`scripts/ground.py` is how you pull them. This is the reference for each helper and the SQL
behind it.

Sensitive data is handled **upstream**: aggregate or mask customer-level and CEII data with
the `grid-data-guard` skill (or confirm with the user) *before* grounding. See SKILL.md,
"Protect sensitive data before you present."

## The rule: ground, then present

1. **Protect first** if the source holds customer meter-level rows, customer identifiers, or
   critical-asset locations (delegate to `grid-data-guard`; if unavailable, ask the user).
2. **Ground** the figures with the helpers below, or reuse the facts ledger from
   `energy-report-writer` with `tiles_from_facts()` so the deck and the report match.
3. Drop the returned `display` strings / `bars` into the spec and the `source` string into the
   slide `caption` / `notes`.
4. Never type a figure by hand. If a number can't be grounded, it is an assumption: label it on
   a `statement` slide, not a `metrics` tile.

All helpers authenticate through the Databricks SDK: ambient in-workspace, or `profile=`
locally; `warehouse_id=` is auto-selected if omitted. All accept `q=` to inject a runner (the
offline tests use this). Table names must be `catalog.schema.table`; table and column names are
validated and back-quoted; filter values travel as statement parameters.

## Helpers → SQL

### `profile_table(table)`
`DESCRIBE {table}` + `SELECT COUNT(*)`. Returns `{table, row_count, columns}`. Use it to check
units in column names and comments before choosing what to present.

### `dataset_summary(table, id_col=None)`
```sql
SELECT COUNT(*), COUNT(DISTINCT id_col) FROM {table}
```
Returns `{n_rows, n_entities, id_col, source}`: meters, wells, turbines, feeders, outages.

### `time_range(table, ts_col)`
```sql
SELECT CAST(MIN(ts) AS STRING), CAST(MAX(ts) AS STRING) FROM {table}
```
Put the period on the cover and say which timezone the column is in (from the upstream skill's
manifest or column comment).

### `numeric_summary(table, column, unit)`
```sql
SELECT COUNT(c), MIN(c), MAX(c), AVG(c), percentile_approx(c, 0.5) FROM {table}
```
Returns stats, `unit`, `display` strings, and `source`. **Check min/max before showing a mean**:
a meter rollover (99,999 kWh), a `-999.25` log null, or an unflagged price cap distorts averages.
Prefer the median, or filter upstream.

### `filtered_total(table, value_col, unit, where={col: value})`
```sql
SELECT SUM(value_col), COUNT(*) FROM {table} WHERE col1 = :p0 AND col2 = :p1
```
Totals for one scope, year, region, product. The filter is printed in `source`.

### `column_distribution(table, column, top=8, value_col=None, unit="-", suppress_below=None)`
```sql
SELECT CAST(column AS STRING) v, <COUNT(*) | SUM(value_col)> m, COUNT(*) n
FROM {table} GROUP BY 1 ORDER BY m DESC LIMIT top
```
Returns `{bars, unit, source}` for a `bar_chart`. With `suppress_below=k`, groups with fewer than
`k` rows are folded into one "(suppressed)" bar. Use it whenever groups could be small (customers
on a feeder, wells per lease).

### `tiles_from_facts(facts.json, fact_ids, labels=None)`
Reads the facts ledger written by `energy-report-writer` (`[{fact_id, value, unit, source}]`) and
returns `metrics` tiles with unit-bearing values and source captions.

## Recipes

### Reliability readout
```python
tiles = ground.tiles_from_facts(FACTS, ["y2025_saidi_excl_med", "y2025_saidi_incl_med",
                                        "y2025_saifi_excl_med"])
causes = ground.column_distribution("main.rel.interruptions_2025", "cause_category",
                                    value_col="customer_minutes", unit="customer-min")
```
Show MED-excluded and MED-included values side by side, labelled; never only one without saying
which.

### Production review
```python
wells = ground.dataset_summary("main.prod.monthly_volumes", id_col="well_id")
oil = ground.filtered_total("main.prod.monthly_volumes", "oil_bbl", unit="bbl", where={"year": 2025})
```
Present decline outputs as "decline-analysis EUR" or "technical forecast", never as reserves.

### Emissions readout
```python
s1 = ground.filtered_total("main.esg.inventory", "co2e_t", unit="tCO2e", where={"scope": "1"})
s2_loc = ground.filtered_total("main.esg.inventory", "co2e_t", unit="tCO2e",
                               where={"scope": "2", "method": "location"})
s2_mkt = ground.filtered_total("main.esg.inventory", "co2e_t", unit="tCO2e",
                               where={"scope": "2", "method": "market"})
```
Both Scope 2 methods appear; the factor vintage goes in the slide notes.

### Model or forecast metrics (MLflow)
```python
import mlflow
r = mlflow.get_run("<run_id>")
tiles = [{"value": ground.format_value(r.data.metrics["mape_pct"], "%"), "label": "Backtest MAPE",
          "caption": f"Source: MLflow run {r.info.run_id[:8]} · holdout {r.data.params['holdout']}"}]
```
