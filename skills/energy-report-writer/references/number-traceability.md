# Number Traceability: the Facts Ledger

Every number in an energy report must trace to a result table or run manifest. Reports go to
regulators, boards, auditors, and investors; an invented or mistyped figure causes real harm. The
skill therefore never lets the agent type a figure into prose.

## How it works

1. **Collect facts.** After the analysis, build a ledger from the result tables and run manifests
   the upstream skills wrote:

   ```python
   import sys; sys.path.append("<skill-dir>/scripts")
   from facts_ledger import build_ledger, records_from_rows, save_ledger

   rows = spark.table("main.reliability.annual_indices").toPandas().to_dict("records")
   ledger = build_ledger(
       records_from_rows(rows, id_key="metric_id", value_key="value", unit_key="unit",
                         source="main.reliability.annual_indices", prefix="y2025_")
       + [{"fact_id": "tmed_2025", "value": manifest["decisions"]["t_med_min"], "unit": "min",
           "source": f"manifest:{manifest['run_id']}"}]
   )
   save_ledger(ledger, "/Volumes/<catalog>/<schema>/reports/2025/facts.json")
   ```

   Each fact has an id, a value, a **unit** (`-` for counts), a **source**, and optional decimals.

2. **Draft with references.** The draft says `\fact{y2025_saidi_excl_med}` (LaTeX) or
   `{{fact:y2025_saidi_excl_med}}` (Markdown), never `132 min`.

3. **Check and render.**

   ```bash
   python scripts/check_report.py report.tex --ledger facts.json --report-type reliability-annual
   ```

   Fails on unknown fact ids, untraced numbers, or missing notices. On success writes
   `report.rendered.tex`, which is what gets compiled.

4. **Appendix.** `ledger_appendix(ledger, used_ids)` produces the Sources-of-Figures table.

## What counts as untraced

Any number in the document body except:

| Exempt | Example |
|---|---|
| Years 1900-2099 | "In 2025" |
| Names after a prefix word | Scope 2, IEEE 1366, EIA-923, Form 1, Table 3, Figure~2, Subpart W, AR6 |
| Compound adjectives | 15-minute, 5-year |
| LaTeX structure | `\label{}`, `\ref{}`, `\cite{}`, `\includegraphics[width=0.85\textwidth]{}`, `\fpath{}`, `\texttt{}`, comments |
| Markdown structure | headings, list numbering, inline code, link targets |

Everything else, including decision values in Methods ("b bounded at 1.2"), must be a fact. Put
decision values from the run manifest into the ledger.

## Derived numbers

A change, ratio, or share computed for the narrative (year-over-year %, share of customer
minutes) is computed **in code** from ledger facts and added as its own fact with
`source="derived: <expression>"`, e.g. `"derived: (saidi_2025 - saidi_2024) / saidi_2024"`.
Never compute it in prose.

## Rounding

`Fact.formatted()` rounds to 0 decimals at ≥ 100, 1 at ≥ 10, else 2, unless `decimals` is set.
Set `decimals` when a filing prescribes precision. Never round in the source table.
