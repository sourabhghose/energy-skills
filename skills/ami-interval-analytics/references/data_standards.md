# Meter data standards and formats

| Standard | What it covers | Relevance |
|----------|----------------|-----------|
| ANSI C12.19 (Utility Industry End Device Data Tables) | Data tables inside the meter: registers, load profile, quality flags | Defines register vs load-profile (interval) data and status flags the head-end translates |
| ANSI C12.18 / C12.21 / C12.22 | Optical-port, modem, and network protocols for C12.19 tables | How reads leave the meter |
| ANSI C12.20 | Accuracy classes (0.1, 0.2, 0.5) for electricity meters | Bounds on expected measurement error |
| NAESB REQ.21 Energy Services Provider Interface (ESPI) — "Green Button" | XML/Atom schema for interval usage shared with customers and third parties | `IntervalBlock` / `IntervalReading` with `start` (epoch seconds, UTC) and `duration`: interval-beginning, UTC |
| IEC 61968-9 (CIM for meter reading and control) | Information model for meter readings, reading types, quality codes | Reading-type and quality-code semantics in many MDMs |

ANSI, IEC, and NAESB documents are paywalled; the notes above are our own summaries.

## Green Button note

ESPI `IntervalReading.timePeriod.start` is UTC epoch seconds for the interval start, and
`LocalTimeParameters` carries the DST rules. When ingesting Green Button files use
`timestamp_basis='utc'`, `interval_convention='beginning'`.

## Sources

- Green Button Alliance: https://www.greenbuttonalliance.org/
- NAESB REQ.21 ESPI: https://www.naesb.org/ESPI_Standards.asp
- ANSI C12 series (NEMA): https://www.nema.org/
- IEC 61968-9: https://webstore.iec.ch/
