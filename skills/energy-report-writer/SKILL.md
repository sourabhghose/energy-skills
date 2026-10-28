---
name: energy-report-writer
description: Energy report writing from Databricks notebook analysis. Engineering studies, reliability annual report narrative (IEEE 1366), rate-case exhibit narrative support, EIA/FERC form variance commentary, ESG/climate disclosure sections (GHG Protocol, IFRS S2), and production/decline summaries, as LaTeX (compiled to PDF with Tectonic) or Markdown. Every number is a fact traced to a result table or run manifest via a facts ledger; check_report.py blocks untraced numbers, missing notices, and reserves-classification terms. For slides use presentation-builder; for computing the numbers use the domain skills (reliability-metrics, ghg-emissions-calculator, decline-curve-analysis).
category: Others
summary: "Draft energy reports (engineering study, reliability, rate-case, EIA/FERC, ESG, production) where every number traces to a table; LaTeX/PDF or Markdown."
version: 0.1.0
author: Sourabh Ghose
license: Databricks License
---

<!-- Adapted from databricks-industry-solutions/vital-skills (skills/report-builder/SKILL.md); modified for the energy industry. -->

# Energy Report Writer

## Overview

Turns notebook analysis into a structured energy document: a technical study, internal brief, or Markdown brief, shaped for one of seven report types (engineering study, internal brief, reliability annual report, rate-case exhibit narrative, regulatory form commentary, ESG disclosure, reserves/production summary). The agent writes a thorough Methods section, light Results, and bullet-form Discussion for the engineer or analyst to expand. **No number is typed by the agent**: every figure is a `\fact{id}` reference resolved from a facts ledger built from result tables and run manifests. LaTeX output compiles to PDF inside Databricks with Tectonic.

## When to Use

- "Write up the 2025 reliability results for the annual report" (SAIDI/SAIFI/CAIDI with and without MEDs)
- "Draft the narrative for the load-forecast exhibit in our rate case"
- "Explain the year-over-year variance on our EIA-923 / FERC Form 1 numbers"
- "Draft the Scope 1 and 2 section of our sustainability disclosure from the emissions tables"
- "Summarize production and decline-curve results for the Delaware Basin wells"
- "Turn this wind-farm underperformance notebook into an engineering study PDF"
- "Compile this .tex file to PDF in Databricks" or "give me a Markdown brief instead"

## Prerequisites

- **Compute**: serverless (Python) or a cluster for building the ledger; Genie Code `executeCode` chat compute for Tectonic
- **Inputs**: the analysis notebook, its result tables (UC), and run manifests written by upstream skills
- **Tectonic** (PDF only): ~21 MB binary downloaded from GitHub to `/tmp`, only with the user's **typed** authorization
- **Optional**: a `.bib` file for references

## Quick Start

```python
import sys; sys.path.append("<this-skill-dir>/scripts")
from facts_ledger import build_ledger, records_from_rows, save_ledger, ledger_appendix

rows = spark.table("<catalog.schema.result_table>").toPandas().to_dict("records")
ledger = build_ledger(records_from_rows(rows, id_key="metric_id", value_key="value",
                                        unit_key="unit", source="<catalog.schema.result_table>"))
save_ledger(ledger, "<output_dir>/facts.json")
# Draft report.tex from references/latex-templates.md using \fact{<id>} for every number, then:
#   python scripts/check_report.py report.tex --ledger facts.json --report-type reliability-annual
# Compile report.rendered.tex with Tectonic (Step 6).
```

## Workflow

**⛔ EXECUTE, DO NOT REIMPLEMENT.** Build the ledger with `scripts/facts_ledger.py`, check with `scripts/check_report.py`, install Tectonic with `scripts/ensure_tectonic.py`. Never type a figure into the draft, never round or derive numbers in prose, and never pick the report type, audience, or disclosure framework yourself.

### Step 1: Gather context and ask

Read the source notebook and upstream run manifests. Identify data sources, decisions, result tables, and figures. Then ask the user, in one message:

1. **Report type and audience** (see Decision Points).
2. **Output format and location**: LaTeX/PDF or Markdown; workspace or UC Volume path.
3. **Jurisdiction / framework** where relevant (state PUC, EIA/FERC form, IFRS S2 / CSRD / CDP).
4. **`.bib` file** or skip bibliography.
5. **Tectonic authorization** (PDF only), in plain chat text, not a button: *"To compile to PDF I need to download the Tectonic LaTeX engine (~21 MB) from github.com/tectonic-typesetting/tectonic, install it to /tmp, and run it. Please reply in your own words if you authorize me to download, install, and run it."*

### Step 2: Build the facts ledger

Collect every number the report will state (indices, volumes, emissions, decision values like T_MED or b-factor bound, derived changes) into the ledger. Derived numbers are computed in code and added with `source="derived: <expression>"`. Details: `references/number-traceability.md`.

```python
ledger = build_ledger(records_from_rows(rows, id_key="metric_id", value_key="value",
                                        unit_key="unit", source="main.reliability.annual_indices",
                                        prefix="y2025_")
                      + [{"fact_id": "tmed_2025", "value": manifest["decisions"]["t_med_min"],
                          "unit": "min", "source": f"manifest:{manifest['run_id']}"}])
```

### Step 3: Draft from the template

Start from `references/latex-templates.md` (Technical study, Internal brief, or Markdown brief) and the outline for the chosen type in `references/energy-report-types.md`. Fill `<<PLACEHOLDERS>>` with content from the notebook; numbers only as `\fact{id}` / `{{fact:id}}`. Include the required notice box with the type's extra notice. Methods states every decision from the manifest with its standard. Figures follow `references/energy-figures.md`. Escape prose with `latex_utils.latex_escape()`; long paths with `latex_utils.fpath()`.

### Step 4: Check and render

```bash
python scripts/check_report.py report.tex --ledger facts.json --report-type reliability-annual
```

Fix every problem it lists (unknown fact, untraced number, missing notice, reserves term) by adding facts or rewording, then re-run. On success it writes `report.rendered.tex`. Add the Sources-of-Figures appendix with `ledger_appendix(ledger, used_ids)`.

### Step 5: Ensure Tectonic (PDF only)

Only after typed authorization. Run **three separate** `executeCode` calls (the platform blocks download + extract + execute in one cell):

```python
import sys; sys.path.append("<this-skill-dir>/scripts"); import ensure_tectonic as et
print(et.download())   # call 1
print(et.extract())    # call 2
print(et.verify())     # call 3
```

If the safety judge blocks the download, ask the user to type the authorization and retry. For any other failure, skip to Step 7 and deliver the `.tex`.

### Step 6: Compile

```python
import subprocess
r = subprocess.run(["/tmp/tectonic-bin/tectonic", "-X", "compile", "report.rendered.tex"],
                   capture_output=True, text=True, cwd=build_dir, timeout=300)
print("PDF compiled" if r.returncode == 0 else r.stderr[-2000:])
```

Copy figures (PDF + PNG) and any `.bib` into `build_dir` first. At most 2 fix-and-retry rounds.

### Step 7: Deliver

Copy `.pdf` (if compiled), `.tex` source, rendered `.tex`, `facts.json`, and figures to the user's output path. Tell the user exactly what was saved, which checks passed, and that the document is a draft for review by a qualified person.

## Decision Points

Ask; do not choose for the user.

| Decision | Options | What changes |
|----------|---------|--------------|
| Report type | `engineering-study`, `internal-brief`, `reliability-annual`, `rate-case-exhibit`, `regulatory-form-commentary`, `esg-disclosure`, `reserves-production-summary` | Outline, required notices, forbidden terms |
| Audience | internal team / executive / regulator / investor / public | Depth of Methods, tone, what can be shown (CEII, customer data) |
| Format | Technical study (LaTeX) / Internal brief (LaTeX) / Markdown brief | Template |
| Jurisdiction or framework | state PUC, EIA/FERC form, IFRS S2, CSRD ESRS E1, CDP, internal | Which sections and definitions apply; the user confirms current requirements |
| Reliability basis | MED-excluded only / both included and excluded | Default outline reports both; the user decides what is headlined |
| Scope 2 presentation | location-based and market-based (both) / one headlined | Both must appear; the user picks the headline |
| Rounding / precision | auto / prescribed decimals per fact | `decimals` field on facts |

## Key Parameters

| Parameter | Default | Range / Options | Effect |
|-----------|---------|-----------------|--------|
| `--report-type` | none (required) | 7 types above | Notices and forbidden terms checked |
| `--syntax` | from file extension | `latex`, `markdown` | Fact reference syntax |
| `Fact.decimals` | auto (0 at ≥100, 1 at ≥10, else 2) | int | Display precision |
| `TECTONIC_VERSION` | `0.15.0` | pinned | Compiler version (x86_64 Linux) |
| compile retries | 2 | ≤ 2 | Then deliver `.tex` and explain |

## Common Recipes

### Recipe: Reliability year-over-year change as a derived fact

```python
change = (ledger["y2025_saidi_excl_med"].value - ledger["y2024_saidi_excl_med"].value)
ledger = {**ledger, **build_ledger([{"fact_id": "saidi_yoy_change", "value": change, "unit": "min",
          "source": "derived: y2025_saidi_excl_med - y2024_saidi_excl_med"}])}
```

### Recipe: Markdown brief for a dashboard or email

```bash
python scripts/check_report.py brief.md --ledger facts.json --report-type internal-brief
# brief.rendered.md is ready to paste; no Tectonic needed
```

### Recipe: Production summary without reserves language

Use `--report-type reserves-production-summary`. The checker requires the "not a reserves report" notice and fails on proved / 2P / PUD / reserves / contingent resources. Describe volumes as "decline-analysis EUR" or "technical forecast".

## Expected Outputs

- `report.tex` (source with `\fact{}` references) and `report.rendered.tex` (values substituted)
- `report.pdf` when Tectonic is authorized and compiles
- `facts.json` ledger and a Sources-of-Figures appendix listing each fact's source
- Figures as PDF + PNG in the build/output folder
- A short delivery note: files saved, checks passed, open TODOs

## Troubleshooting

| Problem | Cause | Solution |
|---------|-------|----------|
| `untraced number` from check_report | A figure typed into prose | Add it to the ledger and reference it; or reword if it is a name (use a prefix like "Table 3") |
| `fact not in ledger` | Typo or fact never collected | Fix the id or add the fact from its source table |
| `missing required notice` | Notice box edited or omitted | Paste the notice from `latex-templates.md` with the type's extra text |
| `term not allowed` in production summary | Reserves classification words | Replace with "decline-analysis EUR" / "technical forecast"; reserves need a qualified evaluator |
| Safety judge blocks Tectonic download | Consent missing or given by button | Ask the user to type the authorization; retry `download()` |
| Compilation fails on notebook text | Unescaped `_ % & # $` | `latex_escape()`; table names via `\texttt{}` or `fpath()` |
| `\fact` shows as red TODO in PDF | Compiled the unrendered source | Compile `report.rendered.tex` |

## Guardrails

1. **Never invent, round, or derive a number in prose.** Every figure is a ledger fact with a source; `check_report.py` must pass before delivery.
2. **Not legal, regulatory, or investment advice.** The notice box is mandatory; the draft requires review by a qualified person.
3. **No reserves classification.** Never label volumes proved / probable / possible / 1P-3P / reserves / contingent resources; that requires a qualified reserves evaluator under SPE-PRMS or SEC rules.
4. **No testimony or legal argument.** Rate-case drafts support witness narrative; they do not argue the case or characterize precedent.
5. **Protect sensitive data.** No CEII asset locations or customer-level data in shareable documents; aggregate or route to `grid-data-guard`.
6. **Tectonic only with typed consent**, to `/tmp` only, three separate calls; no alternative compilers or improvised PDF generation (no matplotlib/HTML-to-PDF). If compilation fails, deliver the `.tex`.
7. **No hardcoded paths.** Ask for or derive catalog, schema, volume, and workspace paths.
8. **Max 2 compile-fix retries**, then save the source and explain.

## Related Skills

- `presentation-builder`: slides from the same facts and figures
- `reliability-metrics`, `ghg-emissions-calculator`, `decline-curve-analysis`, `load-forecaster`, `wind-solar-performance`, `iso-market-data`: compute the numbers and write the manifests
- `energy-semantic-builder`: governed metric views the ledger can read from
- `unit-guard`: convert units before facts enter the ledger
- `grid-data-guard`: de-identify or aggregate sensitive data before it is shared

## Bundled Resources

- `references/latex-templates.md`: Technical study, Internal brief, and Markdown templates; notice wording; section guidance
- `references/energy-report-types.md`: outlines, must-state and must-not lists for the seven report types, with sources
- `references/number-traceability.md`: facts ledger workflow, exemptions, derived numbers, rounding
- `references/energy-figures.md`: energy chart conventions (load duration, decline, waterfall, power curve, ...)
- `scripts/facts_ledger.py`: build / save / load ledger, render facts, find untraced numbers, appendix
- `scripts/check_report.py`: pre-delivery check and render CLI
- `scripts/latex_utils.py`: `latex_escape`, `fpath`, `unit_label`
- `scripts/ensure_tectonic.py`: `download()`, `extract()`, `verify()` for Tectonic

## References

- [Tectonic](https://github.com/tectonic-typesetting/tectonic): LaTeX engine (pinned 0.15.0)
- [IEEE Std 1366](https://standards.ieee.org/ieee/1366/7243/): distribution reliability indices
- [GHG Protocol standards](https://ghgprotocol.org/standards): corporate inventory, Scope 2 guidance
- [IFRS S2](https://www.ifrs.org/issued-standards/ifrs-sustainability-standards-navigator/ifrs-s2-climate-related-disclosures/): climate-related disclosures
- [SPE-PRMS](https://www.spe.org/en/industry/reserves/): petroleum resources classification
- [SEC Regulation S-K Subpart 1200](https://www.ecfr.gov/current/title-17/chapter-II/part-229/subpart-229.1200): oil and gas disclosure
- [EIA survey forms](https://www.eia.gov/survey/) and [FERC Form 1](https://www.ferc.gov/general-information-0/electric-industry-forms/form-1-electric-utility-annual-report)
- [Vital Skills report-builder](https://github.com/databricks-industry-solutions/vital-skills/tree/main/skills/report-builder): the HLS original this skill adapts
