---
name: presentation-builder
description: >-
  Presentation builder for energy analysis: turns a finished artifact in Unity Catalog
  (reliability indices, production and decline results, emissions inventory, load forecast,
  market prices, wind/solar performance) into a self-contained, shareable HTML deck on a frozen
  1920x1080 framework (keyboard/click nav, Save-as-PDF, Databricks branding). Grounds every
  figure with units via scripts/ground.py (counts, totals, distributions, summaries, each cited
  to its source table) or reuses the energy-report-writer facts ledger; never types a number by
  hand. Validated identifiers, parameterized filters, small-group suppression. Delegates
  customer-level and CEII protection to grid-data-guard, else asks the user. Run the vetted
  entrypoints in scripts/build_deck.py and scripts/ground.py; do not hand-write deck HTML. For
  written reports use energy-report-writer.
category: Others
summary: "Turn reliability, production, emissions, forecast, or market results into a grounded, unit-correct, shareable HTML deck."
version: 0.1.0
author: Sourabh Ghose
license: Databricks License
---

<!-- Adapted from databricks-industry-solutions/vital-skills (skills/presentation-builder/SKILL.md); modified for the energy industry. -->

# Presentation Builder — Grounded Energy Decks

## Overview

Turns a finished energy artifact into a **self-contained HTML presentation** a stakeholder can open in any browser and share: no server, no login, no PowerPoint. The deck renders onto a frozen design framework (fixed 1920×1080 canvas scaled to fit, keyboard/click navigation, one-slide-per-page Save as PDF, Databricks branding), so the author only supplies a *slide spec* and figures. Every number on a data slide is **grounded**: pulled by `ground.py` with its unit and cited to its source table, or taken from the facts ledger `energy-report-writer` built, so a deck and its report never disagree.

It runs on the execution model: Genie Code calls the vetted entrypoints and reports their output. It does not hand-write the deck shell (frozen in `scripts/deck_framework.py`) and does not invent figures.

## When to Use

- "Make a deck of our 2025 reliability results for the operations review"
- "Present the Permian decline-curve results to the asset team"
- "Turn the Scope 1 and 2 inventory into slides for the sustainability committee"
- "Share the load-forecast backtest as a short presentation"
- "Build slides on wind-farm underperformance and curtailment for asset management"
- "I need a readout of nodal price exposure for the trading desk, grounded in the real numbers"
- "Export the summary as slides so I can Save as PDF"

## Prerequisites

- **Compute**: Python-enabled compute (serverless or a cluster), not a SQL-only warehouse. `ground.py` runs SQL on a warehouse through the Databricks SDK (auto-selected, or `warehouse_id=`). Rendering needs no warehouse.
- **Inputs**: a UC table or view (`catalog.schema.table`) produced by an upstream skill, and/or a `facts.json` ledger from `energy-report-writer`, and/or MLflow run metrics. Images (PNG) for charts the bar layout cannot draw.
- **No external services** to render; an optional Google Fonts link degrades to system fonts offline.

## Quick Start

```python
import sys; sys.path.insert(0, "<this-skill-dir>/scripts")
import ground, build_deck

TABLE = "<catalog.schema.reliability_interruptions_2025>"
tiles = ground.tiles_from_facts("<path>/facts.json",
                                ["y2025_saidi_excl_med", "y2025_saidi_incl_med"],
                                labels={"y2025_saidi_excl_med": "SAIDI excl. MED",
                                        "y2025_saidi_incl_med": "SAIDI incl. MED"})
causes = ground.column_distribution(TABLE, "cause_category", value_col="customer_minutes",
                                    unit="customer-min")
spec = {"title": "Reliability 2025", "footer_left": "Databricks · Energy", "slides": [
    {"type": "cover", "theme": "dark", "title": "2025 [[reliability]] readout"},
    {"type": "metrics", "title": "Headline indices", "tiles": tiles},
    {"type": "bar_chart", "title": "What drove customer minutes",
     "chart": {"heading": "Customer-minutes by cause", "unit": causes["unit"], "bars": causes["bars"]},
     "notes": causes["source"]},
]}
print(build_deck.build_deck(spec, "<output_dir>/reliability_2025.html"))
```

## Workflow

**⛔ EXECUTE, DO NOT REIMPLEMENT.** Ground with `scripts/ground.py`, build with `scripts/build_deck.py`. Do not hand-write deck HTML, type figures, or edit `deck_framework.py`.

### Step 1: Identify the artifact, audience, and story

Confirm what is presented and to whom (operations, engineering, board, regulator-facing staff, trading). Pick a storyline from `references/storylines.md` and 5-8 slides, one idea each.

### Step 2: Protect sensitive data before you present

This skill does not de-identify. If the source holds **customer meter-level rows, customer identifiers, or locations of critical assets (CEII)**:

1. Run the **`grid-data-guard`** skill and ground from its governed, aggregated view.
2. If `grid-data-guard` is not available, stop and ask the user: *"`<table>` has customer-level or critical-asset data and grid-data-guard isn't available. Should I (a) include it as-is (you confirm it's cleared for this audience), or (b) present aggregates only, with small groups suppressed and no asset coordinates?"* Build only after they choose. For (b), use `suppress_below` on every distribution.

Aggregated, non-sensitive sources (system-level indices, model metrics, emissions totals) go straight to Step 3.

### Step 3: Ground every figure

| Helper | Returns | Use on slide |
|--------|---------|--------------|
| `tiles_from_facts(facts.json, ids)` | tiles with unit-bearing values | `metrics` |
| `dataset_summary(table, id_col)` | `n_rows`, `n_entities` | `metrics` / `cover` |
| `time_range(table, ts_col)` | first / last timestamp | `cover` |
| `numeric_summary(table, col, unit)` | stats + `display` strings | `metrics` |
| `filtered_total(table, col, unit, where)` | SUM with parameterized filters | `metrics` |
| `column_distribution(table, col, ...)` | `bars`, `unit` | `bar_chart` |

Put each `source` in the tile `caption` or slide `notes`. SQL details: `references/grounding_recipes.md`.

```python
s2_mkt = ground.filtered_total("<catalog.schema.inventory>", "co2e_t", unit="tCO2e",
                               where={"scope": "2", "method": "market"})
tile = {"value": s2_mkt["display"], "label": "Scope 2 (market-based)", "caption": s2_mkt["source"]}
```

### Step 4: Assemble the slide spec

Layout types: `cover`, `statement`, `bullets`, `cards`, `metrics`, `bar_chart`, `two_column`, `architecture`, `closing` (`references/deck_framework.md`). Inline markup: `[[x]]` accent, `**x**` bold; all content is HTML-escaped. Charts the bar layout can't draw (log-axis decline curves, load duration curves, heatmaps, negative prices) go in as PNG on a `two_column` slide.

### Step 5: Build and verify

```python
build_deck.build_deck(spec, "<output_dir>/deck.html")   # -> {path, slides, bytes, titles}
```

Open the file; navigate with ← / → / space / click; `R` resets. Save as PDF from the browser print dialog (one slide per page).

### Step 6: Deliver

Hand over the `.html`. Tell the recipient which tables or facts ledger it is grounded in, and how sensitive data was handled (grid-data-guard view, aggregates with suppression, or user-approved).

## Decision Points

| Decision | Options | What changes |
|----------|---------|--------------|
| Audience | operations / engineering / executive / board / regulator-facing staff / trading | Storyline, depth, what can be shown |
| Sensitive data | grid-data-guard view / aggregates with suppression / include as-is (user confirms) | Source table and `suppress_below` |
| Suppression threshold | none / k rows (e.g. 10, or the utility's own privacy rule) | Small groups folded into "(suppressed)" |
| Reliability basis | MED-excluded / MED-included / both | Which tiles appear; both is the safe default to propose |
| Scope 2 method | location- and market-based (both) / one headlined | Tiles and notes |
| Number source | facts ledger (matches report) / live grounding | `tiles_from_facts` vs. `ground.*` |

## Key Parameters

| Parameter | Where | Meaning |
|-----------|-------|---------|
| `spec["slides"]` | `build_deck` | Slides, each a layout dict |
| `spec["accent"]` | `build_deck` | Optional `#hex` accent override (default `#ff3621`) |
| `theme` | per slide | `"light"` (default) or `"dark"` |
| `unit` | `numeric_summary`, `filtered_total`, `column_distribution(value_col=...)` | Required; no inference |
| `top` | `column_distribution` | Top-N groups (default 8) |
| `suppress_below` | `column_distribution` | Fold groups with fewer rows into "(suppressed)" |
| `profile`, `warehouse_id` | `ground.*` | CLI profile / warehouse for grounding queries |

## Expected Outputs

- One self-contained `.html` at `out_path` (open anywhere, email, host)
- `build_deck.build_deck(...)` returns `{path, slides, bytes, titles}`
- `ground.*` helpers return figures with units, display strings, and `source` captions
- Navigation and browser Save as PDF (one slide per page) work out of the box

## Troubleshooting

| Problem | Cause | Solution |
|---------|-------|----------|
| `ValueError: unit is required` | Numeric helper called without a unit | Pass the unit from the column name/comment or upstream manifest; ask if unclear |
| `Expected a fully-qualified catalog.schema.table` | Short or unsafe table name | Use the full three-part name |
| A category is missing from a distribution | Only top `top` groups returned, or suppressed | Raise `top`; check `suppress_below` |
| Negative values show as empty bars | Bar layout clamps to 0 | Use a notebook PNG on a `two_column` slide |
| Mean looks absurd | Rollover, null sentinel, or price cap in the data | Check `min`/`max`; prefer median; filter upstream |
| `unknown type` / `theme must be ...` | Spec uses an unsupported layout or theme | See `references/deck_framework.md` |
| Fonts look like system default | Offline; webfont not loaded | Expected; the deck is still self-contained |

## Guardrails

1. **No hand-entered figures.** Numbers on `metrics` / `bar_chart` slides come from `ground.py` or the facts ledger. Ungrounded numbers are assumptions, labelled on a `statement` slide.
2. **Every number shows its unit.** Use the `display` strings; never strip units to save space.
3. **Sanity-check before showing a mean**: look at min/max first.
4. **Protect sensitive data upstream; never ship it silently.** Customer-level and CEII data go through `grid-data-guard`, or the user explicitly chooses.
5. **No reserves language** for decline outputs: "decline-analysis EUR" or "technical forecast", not proved/2P/reserves.
6. **No editing the frozen framework.** Styling changes go in `layouts.COMPONENT_CSS` or the spec.
7. **No hardcoded paths, hosts, or warehouse IDs.**

## Related Skills

- `energy-report-writer`: the written report; share its `facts.json` so figures match
- `grid-data-guard`: aggregate / mask customer and CEII data before presenting
- `reliability-metrics`, `decline-curve-analysis`, `ghg-emissions-calculator`, `load-forecaster`, `iso-market-data`, `wind-solar-performance`: produce the artifacts presented
- `energy-semantic-builder`: governed metric views to ground from
- `skill-eval`: present with/without-skill results

## Bundled Resources

| Path | What it is |
|------|-----------|
| `scripts/build_deck.py` | Entrypoint: validate spec → render → write self-contained `.html` |
| `scripts/deck_framework.py` | **Frozen** deck shell (CSS, navigation runtime, print, protocol) |
| `scripts/layouts.py` | Pure slide renderers + editable component CSS |
| `scripts/ground.py` | Grounded reads with units, validated identifiers, parameters, suppression, facts bridge |
| `references/deck_framework.md` | Deck-spec contract and layout vocabulary |
| `references/grounding_recipes.md` | SQL behind each helper and energy recipes |
| `references/storylines.md` | Slide-by-slide storylines for six energy readouts |
| `tests/` | Offline unit tests (framework emission, renderer safety, grounding) |

## References

- [Vital Skills presentation-builder](https://github.com/databricks-industry-solutions/vital-skills/tree/main/skills/presentation-builder): the HLS original this skill adapts; its design framework is adapted from the OpenDesign deck runtime (open-design.ai)
- [Databricks SQL Statement Execution API](https://docs.databricks.com/aws/en/dev-tools/sql-execution-tutorial): parameterized statements used by `ground.Q`
- [IEEE Std 1366](https://standards.ieee.org/ieee/1366/7243/): reliability index definitions shown in reliability decks
- [GHG Protocol Scope 2 Guidance](https://ghgprotocol.org/scope_2_guidance): location- vs. market-based reporting
