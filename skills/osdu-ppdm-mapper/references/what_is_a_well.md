# "What is a well?": well, wellbore, completion, wellhead stream

Upstream systems disagree about what one row represents, and that is the most common source
of wrong joins: production double-counted across sidetracks, or a wellbore's TD attached to
its parent well. Decide what level each source table is at *before* mapping.

## Hierarchy (PPDM "What Is A Well" and OSDU)

| Level | Meaning | US API digits | OSDU | PPDM 3.9-style |
|---|---|---|---|---|
| Well origin / well | surface location where drilling started | API-10 (state 2 + county 3 + unique 5) | `master-data--Well` | `WELL` (well-level UWI) |
| Wellbore | one drilled path: original hole, sidetrack, lateral | API-12 (+ 2-digit sidetrack code, 00 = original) | `master-data--Wellbore` (links `WellID`) | `WELL` component with a parent UWI |
| Wellbore segment / lateral | part of a multilateral | operator-specific | `Wellbore` with `KickOffWellbore` | segment tables |
| Completion | interval connected to the reservoir | API-14 (+ 2-digit event/completion code) | completion work-product / reporting entity | `WELL_COMPLETION` |
| Wellhead stream / reporting entity | what is metered and reported | lease or unit IDs (for example Texas RRC oil by lease) | not a core WKS | `PDEN` (production entity) |

## Decisions this skill asks for

- **`source_identifier_level`**: the level the source ID column is at (`well`, `wellbore`,
  `completion`, or `lease` for production). The preview shows the digit-length mix and the
  number of distinct API-10/12/14 prefixes.
  - Finer → coarser (API-14 source → wellbore table) truncates and collapses rows. Rows that
    disagree on attributes (two TDs for one wellbore) are rejected as `conflicting_duplicate`,
    never picked arbitrarily.
  - Coarser → finer (API-10 source → wellbore table) is not knowable from the data. See
    `api_padding`.
- **`api_padding`**: `pad_zeros` asserts every well-level row is the original hole (`00`);
  `leave_null` rejects those rows. Pad only if you know there are no sidetracks.

## API number quirks

- Separators vary (`42-301-12345-00-00`, `4230112345`).
- Numeric ingestion drops the leading zero of states 01–09 (Alabama 01 to Colorado 05 …) and
  appends `.0`. The skill restores a single leading zero for 9/11/13-digit values and reports
  it as `leading_zero_restored`.
- The API standard (API Bulletin D12A) is maintained by the PPDM Association since 2013 as
  the "US Well Number" standard (2nd edition introduced 12-digit well numbers with different
  semantics). Check which edition your source follows.

## Sources

- PPDM Association, "What Is A Well" and the PPDM 3.9 data model: https://ppdm.org/
- PPDM, US Well Number Standard (successor to API Bulletin D12A), listed under Standards at https://ppdm.org/
- OSDU data definitions (well-known schemas): https://community.opengroup.org/osdu/data/data-definitions
