# IEEE 1366 index definitions (summary in our own words)

IEEE Std 1366 ("Guide for Electric Power Distribution Reliability Indices", current edition
2022) defines the reliability indices most North American regulators use. The standard is
paywalled; this note restates the definitions. Check your copy and your regulator's rules
before filing.

## Terms

| Term | Meaning |
|------|---------|
| Sustained interruption | Customer loses service for **more than 5 minutes** (older editions and some state rules: > 1 min). |
| Momentary interruption | Loss of service lasting **5 minutes or less**, typically recloser operations. |
| Momentary interruption *event* | All reclosing operations within one sequence (≤ 5 min) count as one event (MAIFI_E). If the sequence ends in lockout, the customers get a sustained interruption instead. |
| N_T | Total customers served in the area for the reporting period. The averaging basis (average of monthly counts vs. year-end count) differs by utility and regulator. |
| CI | Customers interrupted (sustained). |
| CMI | Customer-minutes interrupted (sustained), i.e. Σ customers × restoration minutes. |
| Step restoration | An outage restored in stages. Each stage contributes its own customers × minutes since the outage began; customers restored within 5 minutes are momentary. |

## Indices

| Index | Formula | Unit |
|-------|---------|------|
| SAIDI | CMI / N_T | minutes per customer |
| SAIFI | CI / N_T | interruptions per customer |
| CAIDI | SAIDI / SAIFI = CMI / CI | minutes per interruption |
| CAIFI | CI / (distinct customers who had ≥ 1 sustained interruption) | interruptions per affected customer |
| ASAI | 1 − CMI / (N_T × minutes in period) | fraction (8,784 h in a leap year) |
| MAIFI | momentary customer interruptions / N_T | per customer |
| MAIFI_E | momentary customer interruption *events* / N_T | per customer |
| CEMI_n | customers with **more than n** sustained interruptions / N_T | fraction |
| CELID_s(t) | customers whose **single longest** interruption ≥ t hours / N_T | fraction |
| CELID_t(t) | customers whose **total** interruption duration ≥ t hours / N_T | fraction |

## Common mistakes this skill prevents

- **Counting a stepped outage at its final restoration time.** CMI must be summed per step.
- **Counting the whole event as sustained** when some customers came back within 5 minutes.
- **Averaging CAIDI across circuits.** CAIDI must be recomputed as CMI/CI over the roll-up.
- **Using 525,600 minutes for ASAI in a leap year.** 2024 has 527,040 minutes.
- **Dating events in UTC.** Events belong to the local calendar day the interruption began.
- **Computing SAIDI from incomplete daily data.** A daily fact table must contain zero-outage
  days for every circuit, or the N_T average is wrong.

## Sources

- IEEE Std 1366-2022 — https://standards.ieee.org/ieee/1366/7243/ (purchase required)
- IEEE DRWG benchmarking and MED background — https://cmte.ieee.org/pes-drwg/
- EIA-861 reliability data (SAIDI/SAIFI with and without MED by utility) —
  https://www.eia.gov/electricity/data/eia861/
