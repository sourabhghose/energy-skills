# GHG Protocol scopes as implemented

Summarized in our own words. Primary sources:
- GHG Protocol Corporate Standard (revised edition): https://ghgprotocol.org/corporate-standard
- GHG Protocol Scope 2 Guidance (2015): https://ghgprotocol.org/scope-2-guidance
- GHG Protocol Scope 3 Standard and Technical Guidance: https://ghgprotocol.org/corporate-value-chain-scope-3-standard
- IPCC AR6 WG1 Chapter 7, Table 7.15 (GWP100): https://www.ipcc.ch/report/ar6/wg1/chapter/chapter-7/

## Organizational boundary (decision: `consolidation`)

Choose one approach and apply it to every facility:

| Approach | Rule | Typical user |
|---|---|---|
| `operational_control` | 100% of facilities you operate, 0% otherwise | Most O&G operators; aligns with EPA GHGRP facility reporting |
| `financial_control` | 100% where you direct financial and operating policies | Some utilities, financial reporting alignment |
| `equity_share` | Your % ownership of every facility | Non-operated JV portfolios; IOGP/IPIECA guidance discusses both |

A JV-heavy upstream portfolio can differ by 2x between approaches, so `preview_inventory` shows the total
under each approach for which the input has the column.

## Scope 1

Direct emissions from owned/controlled sources: stationary combustion, mobile combustion, flaring,
venting (pneumatics, tanks, compressor seals, blowdowns), fugitive (equipment leaks), process emissions.

## Scope 2 dual reporting

Companies with operations in markets that offer contractual instruments must report **both**:

- **Location-based**: grid-average emission rate for where electricity is consumed (US: eGRID subregion
  total-output rate).
- **Market-based**: rates from contractual instruments, in hierarchy order: energy attribute
  certificates (RECs, GOs) and PPAs with certificates → supplier-specific rates → residual mix → (if
  no residual mix exists) grid average, disclosed as such.

The skill always computes both. Decision `scope2_headline` only picks which one goes into the
`scope1_plus_scope2_*` headline; both appear in the summary. Decision `market_fallback` decides
whether a missing residual mix raises (`raise`) or falls back to the location rate with a FLAG note
(`location_fallback_flagged`).

Note: eGRID total-output rates exclude transmission and distribution losses (which belong to Scope 3
category 3). The subregion CO2 rates shipped here exclude CH4 and N2O; add CO2e rates as additional
factors if your program needs them.

## Scope 3 category 11 (use of sold products)

For oil and gas producers, category 11 is usually the single largest emissions category: the
combustion of the crude, gas, and NGLs that the company sells. Screening method here: sold volume ×
HHV × combustion CO2 factor. Decision `cat11_basis` records whether volumes are **sold** volumes
(standard) or **production** volumes (sometimes used when sales data is unavailable; can double count
fuel consumed or flared on site, already in Scope 1). Non-combusted uses (petrochemical feedstock,
asphalt, lubricants) should be removed before calculation; the skill does not guess that share.

## GWP set (decision: `gwp_set`)

| Set | CH4 | N2O | Notes |
|---|---|---|---|
| AR4 | 25 | 298 | EPA GHGRP through RY2023; many legacy baselines |
| AR5 | 28 | 265 | EPA GHGRP Table A-1 from 1 Jan 2025 (RY2024 reports onward) |
| AR6 | 29.8 (fossil) / 27.0 (non-fossil) | 273 | Latest IPCC; increasingly used by voluntary frameworks |

The skill uses AR6 fossil CH4 (29.8) because the sources here are fossil. Keep the GWP set constant
across a baseline and target year; restate the baseline if you change it.

Regulatory status note (verify before relying on it): in 2025 EPA proposed ending GHGRP reporting
for most source categories, including parts of Subpart W. Check the current rule status for your
reporting year.
