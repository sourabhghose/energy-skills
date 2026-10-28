# LAS format notes for ingestion

Summarized from the Canadian Well Logging Society (CWLS) LAS specifications, in our own words.

## Versions

| Version | Status | Notes |
|---------|--------|-------|
| LAS 1.2 | legacy, still common | same section layout as 2.0; looser rules |
| LAS 2.0 | most common | `~V`, `~W`, `~C`, `~P`, `~O`, `~A` sections; one depth-indexed data table |
| LAS 3.0 | rare | multiple data sections (`~Log_Data`, `~Core_Data`, …), typed columns; **lasio reads only the first data section**, and the profile warns |

## Sections

- `~Version`: `VERS` (1.2 / 2.0 / 3.0) and `WRAP` (YES means a depth step's values span
  several lines; lasio unwraps them).
- `~Well`: `STRT`, `STOP`, `STEP` (with depth unit), `NULL`, `COMP`, `WELL`, `FLD`, `LOC`,
  `CTRY`/`PROV`/`STAT`, `SRVC`, `DATE`, `API` or `UWI`, and often `LATI`/`LONG`.
- `~Parameter`: elevations (`EKB`, `EDF`, `EGL`), `LMF` (log measured from), `DMF`
  (drilling measured from), `PDAT` (permanent datum), mud and run parameters. Many writers
  put elevations in `~Well` instead, so the skill reads both sections.
- `~Curve`: one line per column: `MNEM.UNIT  API_CODE : DESCRIPTION`. The first curve is
  the index (depth or time).
- `~ASCII` / `~A`: whitespace-delimited data.

## Nulls and sentinels

`NULL` in `~Well` declares the missing-value marker (usually −999.25). lasio replaces it
with NaN. Files from multiple vendors or processing steps often contain **other** markers
(−999, −9999, −99999, −999.2500). Whether those are nulls or real data is a decision
(`sentinel_policy`). An SP or a computed curve can legitimately reach −999 mV only in
corrupted data, but don't assume: the preview counts them per curve.

## Depth reference

Log depths are **measured depth (MD)** along the borehole from the datum in `LMF`
(usually KB, the kelly bushing). Converting to a different datum:

```
depth_below_target = depth_below_logged − (elevation_logged − elevation_target)
```

For example, KB 5,125 ft and GL 5,100 ft: 5,000 ft below KB is 4,975 ft below GL. Requirements:

- `LMF` must be present, or the conversion is refused for that file.
- Both elevations must be present, in a known unit (ft or m).
- **TVD / TVDSS need a deviation survey.** MD minus KB elevation is *not* subsea depth in
  a deviated or horizontal well. This skill never produces TVDSS. Join a directional
  survey downstream (see `osdu-ppdm-mapper`).

## Duplicate curves and runs

- Within one file, lasio renames repeated mnemonics `GR:1`, `GR:2`. The family conflict
  policy keeps all of them, or the first listed.
- Across files (logging runs of the same well), runs often overlap in depth. The long table
  keeps every run with `source_file`. The wide table resolves overlaps by
  `overlap_policy` (latest or earliest `DATE`, then file order).

## DLIS

DLIS (RP66 v1) is the binary format used for full-fidelity logs, including array data,
images, and multiple frames. Read it with [dlisio](https://github.com/equinor/dlisio)
(Equinor, LGPL). It is not implemented here. Convert the frames to the same tidy long
schema (`api14, source_file, depth, family, mnemonic, value, unit`) and reuse `las_core`'s
mnemonic and unit tables.

## Sources

- CWLS LAS standards: https://www.cwls.org/products/#products-las
- lasio documentation: https://lasio.readthedocs.io/
- dlisio: https://dlisio.readthedocs.io/
