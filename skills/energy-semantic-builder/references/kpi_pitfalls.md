# Energy KPI pitfalls the catalog prevents

Every rate below is a **ratio of sums** (composite measure, `MEASURE(a) / MEASURE(b)`), so
it stays correct at any roll-up. Averaging per-well, per-unit, per-plant or per-day ratios is
the most common error in energy dashboards.

| KPI | Correct | Common mistake |
|-----|---------|----------------|
| boe/d | total boe ÷ calendar days in the slice | average of per-well rates; dividing by well-days |
| boe | oil + NGL + gas ÷ **confirmed** Mcf-per-boe | silent 6:1; price-parity ratio in a volume KPI |
| Water cut | water ÷ (oil + water) | water ÷ oil (that is WOR); average of well water cuts |
| GOR | 1000 × Mcf ÷ bbl (scf/bbl) | Mcf/bbl labelled scf/bbl |
| LOE $/boe | LOE ÷ boe on the **same** monthly grain | daily volumes joined to monthly cost (fan-out) |
| Capacity factor | net MWh ÷ (capacity × hours) | mixing nameplate and net capacity; 8760 h in a leap year |
| Net heat rate | fuel Btu ÷ **net** kWh | gross kWh; LHV fuel vs. HHV benchmark |
| EAF | (AH − (EUDH + EPDH + ESEDH)) ÷ PH | ignoring derates (that is AF) |
| EFOR | (FOH + EFDH) ÷ (FOH + SH + EFDHRS) | calling it EFORd (needs demand factors) |
| Fleet GADS indexes | unweighted **or** MW-weighted, as decided | mixing the two across reports |
| Line losses | (received − delivered) ÷ received | cycle-billed sales vs. calendar-month sendout |
| SAIDI / SAIFI | CMI ÷ N_T over a complete daily grid | averaging circuit SAIDI; incomplete day grid |
| CAIDI | CMI ÷ CI | average of circuit CAIDIs |
| Performance ratio | Σ energy ÷ Σ (POA insolation × kWp) | GHI instead of POA; average of daily PR |
| Emissions intensity | Σ tCO2e ÷ Σ net MWh (or boe) | average of plant intensities |
| ¢/kWh | 100 × Σ revenue ÷ Σ kWh | average of per-bill ¢/kWh |

## Sources

- NERC GADS Data Reporting Instructions (Appendix F, performance indexes) —
  https://www.nerc.com/programs/reliability-assessment--performance-analysis/generating-availability-data-system/gads-conventional/data-reporting-instructions--templates
  (Appendix F: https://www.nerc.com/globalassets/programs/rapa/gads/conventional/appendix_f_equations_2026.pdf).
  Pooled MW-weighted statistics multiply **each term** by NMC before summing; they are not
  NMC-weighted averages of unit indexes.
- EIA-923 / EIA-860 / EIA-861 — https://www.eia.gov/electricity/data.php
- IEC 61724-1 (PV system performance monitoring; purchase required) — https://webstore.iec.ch/
- IEEE 1366 — https://standards.ieee.org/ieee/1366/7243/
- SEC Regulation S-X Rule 4-10 (oil and gas reporting) — https://www.ecfr.gov/current/title-17/section-210.4-10
- Databricks metric views — https://docs.databricks.com/aws/en/metric-views/
