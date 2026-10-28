# Energy Figures for Reports and Decks

Chart conventions energy readers expect. Shared with `presentation-builder`. Every axis label
carries a unit; every time axis states its timezone.

| Chart | Use for | Conventions |
|---|---|---|
| **Load duration curve** | Capacity planning, peak exposure | Hours (0-8,760, or 8,784 in a leap year) on x, load (MW) on y, sorted descending; mark the top 1% hours |
| **Daily load profile / heatmap** | Shape, DST effects, EV or solar impacts | Hour-of-day × date heatmap, local time, interval-ending label stated; diverging colour only for deltas |
| **Decline curve** | Well or type-curve performance | Rate (bbl/d or Mcf/d) on a **log** y-axis vs. time (months) or cumulative production on x; observed points + fitted line + forecast in a distinct style; mark terminal-decline switch |
| **Lost-production waterfall** | Production losses by cause | Start at potential, steps for downtime categories, end at actual; units bbl or boe with the conversion stated |
| **Reliability trend** | SAIDI / SAIFI over years | Bars or lines for MED-excluded, separate marker or panel for MED-included; never stack the two |
| **Cause Pareto** | Outage or NPT drivers | Sorted bars of customer-minutes (or hours) + cumulative % line |
| **Emissions bridge** | Year-over-year Scope 1/2 change | Waterfall from prior year to current by driver; market- and location-based Scope 2 shown separately |
| **Power curve scatter** | Wind turbine performance | Hub-height wind speed (m/s) vs. power (kW), density-corrected; reference curve overlaid; curtailed points in a separate colour |
| **Solar performance ratio** | PV underperformance | PR (%) by month, weather-corrected; irradiance-weighted |
| **LMP heatmap / price duration** | Market exposure | Node × hour heatmap ($/MWh), negative prices visible (diverging scale centred at 0) |
| **Map with H3 cells** | Wildfire / asset risk | Aggregated cells only in shareable outputs; never exact coordinates of critical assets (CEII) |

## Export

```python
fig.savefig(f"{out}/{name}.pdf", bbox_inches="tight")
fig.savefig(f"{out}/{name}.png", dpi=300, bbox_inches="tight")
```

For scatter plots with > 5,000 points (power curves, interval data), set `rasterized=True` on the
scatter so the PDF keeps vector axes with rasterized points.

## Captions

"What is plotted, axes with units, the takeaway." Example: *"Load duration curve for 2025
(MW, hourly, America/Chicago). The top 88 hours exceed 90% of annual peak."* The numbers in a
caption are facts too: use `\fact{}`.
