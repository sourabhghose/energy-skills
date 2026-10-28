# Energy Report Types

Section outlines that slot into the templates in `report-structure.md`. Each type lists what the
draft must state, what it must not do, and which upstream skills usually supply the facts.

Regulatory requirements vary by jurisdiction (state PUC, provincial regulator, national agency)
and change over time. The outlines are a starting structure, not a compliance checklist. Ask the
user which jurisdiction and filing the narrative supports, and have them confirm the current
requirement.

---

## `engineering-study`

Technical study for an engineering question: interconnection or hosting-capacity screening,
load-forecast update, decline-curve type-curve study, wind/solar underperformance investigation.

| Section | Must state |
|---|---|
| Scope | Question, assets, period, decision the study informs |
| Data | Sources, units as received, timezone, interval convention, quality flags |
| Methods | Every decision from the run manifest; standard used (IEC 61400-12, Arps / modified hyperbolic, etc.) |
| Results | Findings with facts; sensitivity to the key decision (e.g. b-factor bound, weather year) |
| Limitations | Data gaps, extrapolation range, what would change the conclusion |

Upstream skills: `load-forecaster`, `decline-curve-analysis`, `wind-solar-performance`,
`equipment-pdm`, `wildfire-asset-risk`.

## `reliability-annual`

Narrative support for an annual reliability report to a regulator or board.

| Section | Must state |
|---|---|
| Indices | SAIDI, SAIFI, CAIDI (and MAIFI if momentary data exist) with units, **both including and excluding Major Event Days** |
| MED method | IEEE 1366 2.5β method, years used for the threshold, T_MED value, number and dates of MEDs |
| Trend | Five-year trend on a consistent basis (same MED treatment each year) |
| Drivers | Cause categories (vegetation, equipment, weather, animal, public) with customer-minutes share |
| Worst-performing circuits | Ranking method as defined by the jurisdiction, if required |
| Customer count basis | Customers served at year end vs. average |

Must not: mix MED-included and MED-excluded values in one trend; restate a prior year's index
without saying its basis changed.

Upstream: `reliability-metrics`, `energy-semantic-builder`.

## `rate-case-exhibit`

Narrative support for exhibits a witness will sponsor (load forecast, reliability investment,
O&M variance, capital plan).

| Section | Must state |
|---|---|
| Exhibit purpose | What the exhibit shows and which witness's testimony it supports |
| Test year | Historical vs. forecast test year and any normalizations (weather, out-of-period items) |
| Method | Forecast or normalization method with decisions and data vintages |
| Reconciliation | How exhibit figures tie to the filed schedules (table ids) |

Must not: write testimony in a witness's voice, argue the case, or characterize regulatory
precedent. The draft supports the narrative; counsel and witnesses own it.

Upstream: `load-forecaster`, `reliability-metrics`, `energy-semantic-builder`.

## `regulatory-form-commentary`

Variance commentary for recurring forms (for example EIA-861, EIA-923, EIA-930 data questions,
FERC Form 1 schedules, or national equivalents).

| Section | Must state |
|---|---|
| Form and period | Form id, schedule or line, reporting period |
| Variance | Current vs. prior value with facts, absolute and % change |
| Explanation | Driver traceable to a table (new generation online, outage, reclassification) |
| Data notes | Unit and definition used (net vs. gross generation, MWh vs. MW, fuel heat content) |

Must not: state a filed value that is not in the ledger; guess at the form's line definitions.
Ask the user for the form instructions when a definition matters.

Upstream: `iso-market-data`, `ami-interval-analytics`, `ghg-emissions-calculator`,
`energy-semantic-builder`.

## `esg-disclosure`

Draft section for a climate or sustainability disclosure (GHG Protocol inventory, and frameworks
such as ISSB IFRS S2, TCFD-aligned reports, CSRD ESRS E1, CDP responses).

| Section | Must state |
|---|---|
| Boundary | Organizational boundary approach (equity share / financial control / operational control) |
| Scope 1 | Total and by source category; methane quantification approach (e.g. OGMP 2.0 level) where relevant |
| Scope 2 | **Both location-based and market-based** totals, and the instruments used for market-based |
| Scope 3 | Categories included and excluded, with reasons |
| Factors | Emission-factor sources **with versions/years**, GWP set (AR5 or AR6), and any changes vs. prior year |
| Intensity | Numerator and denominator with units (e.g. tCO$_2$e/MWh, kgCO$_2$e/boe) |
| Assurance | Assurance status (none / limited / reasonable); default is "not assured" |

Must not: call a target "on track" or make forward-looking claims; mix factor vintages across
years without a restatement note; drop market-based Scope 2.

Which frameworks apply, and whether a regulatory climate disclosure rule is in force, depends on
jurisdiction and changes over time. Ask the user; don't assert it.

Upstream: `ghg-emissions-calculator`, `energy-semantic-builder`.

## `reserves-production-summary`

Production performance and decline-analysis summary for an asset or field. **Not** a reserves
report.

| Section | Must state |
|---|---|
| Production | Gross and net (if working-interest data exist) volumes by product with units (bbl, Mcf, NGL bbl), and boe with the conversion factor stated |
| Decline analysis | Model (Arps / modified hyperbolic), b-factor bound, terminal decline, fit window, wells excluded |
| Forecast | Technical forecast volumes and EUR **labelled as decline-analysis estimates** |
| Uncertainty | Range (e.g. P90/P50/P10 from type-curve spread) if computed, and how |

Must not:
- label any volume "proved", "probable", "possible", "1P/2P/3P", "reserves", or "contingent
  resources". Classification under SPE-PRMS or SEC Regulation S-X Rule 4-10 / Regulation S-K
  Items 1200-1208 requires a qualified reserves evaluator, economic limits, and
  reasonable-certainty criteria the skill does not apply;
- combine oil and gas into boe without stating the conversion and that it is energy-based,
  not value-based.

`check_report.py` requires the `not a reserves report` notice for this type and fails on
classification terms (proved, probable/possible reserves, 1P/2P/3P, PDP, PUD, reserves, contingent or
prospective resources). The phrases "reserves report" and "reserves evaluator" are allowed.

Upstream: `decline-curve-analysis`, `well-log-ingest`, `osdu-ppdm-mapper`, `unit-guard`.

---

## Sources

- IEEE Std 1366, *Guide for Electric Power Distribution Reliability Indices*: https://standards.ieee.org/ieee/1366/7243/
- EIA survey forms (EIA-861, EIA-923, EIA-930): https://www.eia.gov/survey/
- FERC Form 1: https://www.ferc.gov/general-information-0/electric-industry-forms/form-1-electric-utility-annual-report
- GHG Protocol Corporate Standard and Scope 2 Guidance: https://ghgprotocol.org/standards
- IFRS S2 Climate-related Disclosures: https://www.ifrs.org/issued-standards/ifrs-sustainability-standards-navigator/ifrs-s2-climate-related-disclosures/
- OGMP 2.0 framework: https://www.ogmpartnership.com/
- SPE Petroleum Resources Management System (PRMS): https://www.spe.org/en/industry/reserves/
- SEC Regulation S-K Subpart 1200 (oil and gas disclosure): https://www.ecfr.gov/current/title-17/chapter-II/part-229/subpart-229.1200
