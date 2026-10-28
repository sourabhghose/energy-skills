# Energy deck storylines

Five to eight slides, one idea per slide. Each storyline lists slide types (see
`deck_framework.md`) and which helper grounds each figure. Charts the bar layout can't draw
(load duration curves, decline curves on log axes, heatmaps, power-curve scatters, anything with
negative values such as negative LMPs) are saved as PNG from the notebook and placed with a
`two_column` slide (`right: {"image": ..., "alt": ...}`), with the source in `notes`.

## Reliability readout (operations or board)

| # | Type | Content | Grounded by |
|---|------|---------|-------------|
| 1 | `cover` | "2025 Distribution Reliability", period, territory | `time_range` |
| 2 | `metrics` | SAIDI, SAIFI, CAIDI excl. MED; SAIDI incl. MED | `tiles_from_facts` |
| 3 | `bar_chart` | Customer-minutes by cause | `column_distribution(value_col=...)` |
| 4 | `two_column` | Five-year trend image (one MED basis) + takeaways | notebook PNG |
| 5 | `bar_chart` | Worst circuits by customer-minutes (`suppress_below`) | `column_distribution` |
| 6 | `closing` | Actions, owners | none (no figures) |

## Production and decline review (asset team)

| # | Type | Content | Grounded by |
|---|------|---------|-------------|
| 1 | `cover` | Field / asset, period | `time_range` |
| 2 | `metrics` | Wells, oil (bbl), gas (Mcf), boe with conversion in caption | `dataset_summary`, `filtered_total` |
| 3 | `two_column` | Type-curve image (log rate axis) + fit decisions (b bound, Dmin) | notebook PNG, manifest |
| 4 | `bar_chart` | Lost production by cause (bbl) | `column_distribution(value_col=...)` |
| 5 | `metrics` | Decline-analysis EUR P90/P50/P10 if computed | `tiles_from_facts` |
| 6 | `statement` | "These are technical forecasts, not reserves." | none |

## Emissions readout (sustainability or exec)

| # | Type | Content | Grounded by |
|---|------|---------|-------------|
| 1 | `cover` | Inventory year, boundary approach | none / manifest |
| 2 | `metrics` | Scope 1, Scope 2 location-based, Scope 2 market-based (tCO2e) | `filtered_total` |
| 3 | `bar_chart` | Scope 1 by source category | `column_distribution(value_col=...)` |
| 4 | `two_column` | Year-over-year bridge image + factor vintage, GWP set | notebook PNG, manifest |
| 5 | `metrics` | Intensity (kgCO2e/boe or tCO2e/MWh) | `tiles_from_facts` |
| 6 | `closing` | Data gaps, assurance status | none |

## Load forecast review (planning or rate case prep)

| # | Type | Content | Grounded by |
|---|------|---------|-------------|
| 1 | `cover` | Forecast vintage, horizon | manifest |
| 2 | `metrics` | Peak (MW), energy (MWh), backtest MAPE (%) | MLflow / `tiles_from_facts` |
| 3 | `two_column` | Load duration curve image + weather normalization decision | notebook PNG |
| 4 | `bullets` | Drivers: weather, EVs, DER, large loads | narrative only |
| 5 | `closing` | Open decisions for planners | none |

## Market exposure (trading or risk)

| # | Type | Content | Grounded by |
|---|------|---------|-------------|
| 1 | `cover` | ISO, nodes, period, settlement interval | `time_range` |
| 2 | `metrics` | Avg DA and RT LMP ($/MWh), hours at negative price | `numeric_summary`, `filtered_total` |
| 3 | `two_column` | LMP heatmap image (diverging, centred at 0) | notebook PNG |
| 4 | `bar_chart` | Congestion component by node ($/MWh) | `column_distribution(value_col=...)` |
| 5 | `closing` | Hedging questions | none |

## Wind / solar performance (asset management)

| # | Type | Content | Grounded by |
|---|------|---------|-------------|
| 1 | `cover` | Site, turbines/inverters, period | `dataset_summary`, `time_range` |
| 2 | `metrics` | Energy (MWh), availability (%), curtailment (MWh) | `filtered_total` |
| 3 | `two_column` | Power-curve scatter image vs. reference curve | notebook PNG |
| 4 | `bar_chart` | Lost energy by cause (MWh) | `column_distribution(value_col=...)` |
| 5 | `closing` | Underperforming units and next checks | none |
