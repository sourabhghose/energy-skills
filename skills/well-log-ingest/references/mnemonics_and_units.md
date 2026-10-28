# Curve families, units, and identifiers

The alias table lives in `scripts/mnemonics.py`. This page explains the rules.

## Families

| Family | Canonical unit | Typical aliases | Plausible range |
|--------|----------------|-----------------|-----------------|
| GR (gamma ray) | gAPI | GR, GRC, GR_EDTC, SGR, ECGR, HGR | 0–1,500 |
| CGR (computed GR, no uranium) | gAPI | CGR, HCGR | 0–1,500 |
| RHOB (bulk density) | g/cm³ | RHOB, RHOZ, ZDEN, DEN, RHO8 | 1.0–3.5 |
| NPHI (neutron porosity) | v/v | NPHI, TNPH, NPOR, CNC, NPHS, NPHL | −0.15–1.0 |
| DT (compressional slowness) | µs/ft | DT, DTC, DTCO, AC, DT24 | 30–250 |
| DTS (shear slowness) | µs/ft | DTS, DTSM, DTSH | 50–800 |
| RT (deep resistivity) | ohm·m | ILD, LLD, AT90, AF90, HDRS, RD | 0.01–100,000 |
| RM (medium resistivity) | ohm·m | ILM, AT30, HMRS | 0.01–100,000 |
| RS (shallow / Rxo) | ohm·m | LLS, SFL, MSFL, RXOZ, AT10 | 0.01–100,000 |
| CALI (caliper) | in | CALI, CAL, HCAL, C1, C2 | 2–40 |
| SP | mV | SP, SPBR, SSP | −500–500 |
| PEF | b/e | PEF, PE, PEFZ | 0–20 |

Vendor tool codes change over time. Unmapped mnemonics are kept with family `UNMAPPED` and
their declared unit, and they are listed in the catalog. Add aliases with a test rather
than guessing.

Neutron porosity matrix: `NPHS` (sandstone), `NPHL` (limestone), and `NPHD` (dolomite)
differ by matrix calibration. They map to the same family, but the catalog keeps the
original mnemonic so petrophysics can apply the right matrix.

## Unit traps

| Trap | Example | Handling |
|------|---------|----------|
| Neutron in % vs v/v | TNPH median 22 with unit `V/V` | `implausible_range`; proposes `PU`; user confirms |
| Density in kg/m³ | RHOZ `K/M3` 2,450 | scaled ×0.001 to 2.45 g/cm³ |
| Sonic in µs/m | DT `US/M` 260 | scaled ×0.3048 to 79 µs/ft |
| Missing unit | `TNPH.` with blank unit | `ambiguous_unit`; value-based proposal only |
| `MS/FT` | "milliseconds per foot" is almost always a mislabel for µs/ft | treated as ambiguous |
| Caliper in mm | CALI `MM` 216 | scaled to 8.5 in |
| Depth in metres | `STRT.M` | converted when `depth_unit` differs |

Proposals from values are never applied automatically. Each needs an entry in
`unit_resolution`, keyed by `"file::MNEMONIC"` or by `"MNEMONIC"` to apply to all files.

## US API well number (US Well Number)

Format `SS-CCC-UUUUU-DD-EE`, which gives 10, 12, or 14 digits:

- `SS`: API state code. This is an alphabetical numbering (01 Alabama … 42 Texas … 49
  Wyoming, 50 Alaska, 51 Hawaii; 55/56/60/61 offshore), **not** FIPS.
- `CCC`: county code. `UUUUU`: unique well within the county.
- `DD`: directional sidetrack code. `EE`: event sequence (completion / recompletion).

The skill normalizes to 14 digits, padding a 10-digit API with `0000`. The most common
defect is a **lost leading zero**: states 01–09 stored as integers become 9, 11, or 13
digits. These are reported as `leading_zero_lost` and fixed only when `api_zero_pad="pad"`.

Canadian wells use the DLS UWI (`100/06-12-034-05W5/00`) or NTS grid identifiers. DLS is
recognized and kept as-is.

## Sources

- PPDM, *US Well Number Standard* (2013, successor to API Bulletin D12A): https://ppdm.org/ppdm/PPDM/Standards/US_Well_Number_Standard/PPDM/Standards/US_Well_Number_Standard.aspx
- CWLS LAS 2.0 specification: https://www.cwls.org/products/#products-las
- SPWLA mnemonic resources: https://www.spwla.org/
- Schlumberger (SLB) curve mnemonic dictionary: https://www.apps.slb.com/cmd/
