# Conversion factors and their sources

All factors live in `scripts/units_registry.py`. This page explains where each comes from.
Exact values are exact by definition. Derived values are computed from exact ones.

## Exact definitions

| Quantity | Value | Source |
|----------|-------|--------|
| 1 international foot | 0.3048 m | NIST SP 811, Appendix B |
| 1 ft³ | 0.028316846592 m³ | (0.3048)³ |
| 1 US gallon | 3.785411784 L | NIST SP 811 |
| 1 barrel (petroleum) | 42 US gal = 0.158987294928 m³ | API MPMS Ch. 1; NIST SP 811 |
| 1 avoirdupois pound | 0.45359237 kg | NIST SP 811 |
| 1 short ton | 2000 lb = 907.18474 kg | NIST SP 811 |
| 1 long ton | 2240 lb = 1016.0469088 kg | NIST SP 811 |
| 1 Btu (International Table) | 1055.05585262 J | NIST SP 811 |
| 1 kWh | 3.6 × 10⁶ J | SI |
| 1 standard atmosphere | 101.325 kPa | SI / ISO 13443 |
| 1 psi | 6.894757293168 kPa | derived from lbf and inch |

## Derived values worth memorising

| Conversion | Value |
|------------|-------|
| 1 MWh | 3.412141633 MMBtu |
| 1 MMBtu | 1.05505585262 GJ = 0.29307107 MWh |
| 1 therm | 100,000 Btu = 0.1 MMBtu; 1 Dth (dekatherm) = 1 MMBtu |
| 100 % efficiency | 3412.14 Btu/kWh = 3600 kJ/kWh heat rate |
| 1 scf (60 °F, 14.696 psia) | 0.0282623 Sm³ (15 °C, 101.325 kPa) |
| 1 Sm³ (15 °C) | 35.383 scf (60 °F, 14.696 psia); *not* 35.3147, which ignores the temperature change |

## Standard conditions for gas

Standard volumes describe an amount of gas, not a physical volume, so every one carries a
reference temperature and pressure. Under the ideal-gas approximation used here, converting
between bases scales by `(P₁/P₂) × (T₂/T₁)`. For custody transfer, the real-gas compressibility
(AGA Report No. 8 / ISO 12213) can matter. This skill does not apply it; the contract governs.

| Basis | T | P | Where used |
|-------|---|---|-----------|
| `60F_14.696psia` | 60 °F | 14.696 psia | SPE, ISO 13443 imperial, many operators |
| `60F_14.73psia` | 60 °F | 14.73 psia | AGA, US federal royalty reporting (ONRR / BLM) |
| `60F_14.65psia` | 60 °F | 14.65 psia | some US state agencies and older contracts |
| `Sm3_15C` | 15 °C | 101.325 kPa | ISO 13443 metric, North Sea, most of the world |
| `Nm3_0C` | 0 °C | 101.325 kPa | "normal" m³, European industrial gas, emissions permits |

Switching from 14.73 to 14.65 psia changes reported volumes by 0.55%. On a 100 MMcf/d field
that is about 0.55 MMcf/d, which is material for royalties.

## Heating value

The heating value of natural gas varies by field and by processing. EIA's US average is about
1,036–1,038 Btu/scf (HHV). Use the measured value from the gas analysis when you have it.
Natural gas LHV is about 90% of HHV; for coal, LHV is about 95–97% of HHV. US utility heat
rates are HHV; IEA and European statistics are LHV.

## GWP sets (100-year)

| Gas | AR4 | AR5 | AR6 |
|-----|-----|-----|-----|
| CH₄ | 25 | 28 | 29.8 (fossil) / 27.0 (non-fossil) |
| N₂O | 298 | 265 | 273 |
| SF₆ | 22,800 | 23,500 | 25,200 |
| NF₃ | 17,200 | 16,100 | 17,400 |

AR5 values shown are without climate-carbon feedbacks, which is the convention used by UNFCCC
inventories. Each reporting regime fixes its own set (US EPA GHGRP pins its values in 40 CFR
Part 98 Table A-1), so always confirm the regime before choosing.

## Sources

- NIST SP 811, *Guide for the Use of the International System of Units*: https://www.nist.gov/pml/special-publication-811
- EIA, *Energy conversion calculators and heat content*: https://www.eia.gov/energyexplained/units-and-calculators/
- EIA, *Natural gas heat content*: https://www.eia.gov/dnav/ng/ng_cons_heat_a_EPG0_VGTH_btucf_a.htm
- ISO 13443, *Natural gas: standard reference conditions*: https://www.iso.org/standard/20461.html
- SPE, *Metric standard / unit conventions*: https://www.spe.org/en/industry/units-standards/
- IPCC AR4 WG1 Ch. 2 Table 2.14: https://www.ipcc.ch/report/ar4/wg1/
- IPCC AR5 WG1 Ch. 8 Appendix 8.A: https://www.ipcc.ch/report/ar5/wg1/
- IPCC AR6 WG1 Ch. 7 Table 7.15: https://www.ipcc.ch/report/ar6/wg1/
- 40 CFR Part 98 Table A-1 (GHGRP GWPs): https://www.ecfr.gov/current/title-40/chapter-I/subchapter-C/part-98
- SEC Regulation S-K Item 1200-series (boe disclosure): https://www.ecfr.gov/current/title-17/chapter-II/part-229
