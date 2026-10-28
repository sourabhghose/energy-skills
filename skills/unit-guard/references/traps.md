# Unit traps a general coding agent falls into

Each trap below is either handled by `units_core` or refused by it.

## 1. "M" means thousand, except when it doesn't

In oil & gas, `M` comes from the Roman numeral for thousand: **Mcf** is 1,000 scf, **MMcf**
is 10⁶, **Mbbl** is 1,000 bbl, **MMBtu** is 10⁶ Btu. SI uses `M` for mega: **MW**, **MSm³**
(10⁶ Sm³, the Norwegian convention), **Mt** (megatonne).

Refused as ambiguous: `MBtu` (thousand in US gas practice, read as million by others), `Mlb`,
`MT` / `mt`, `Mm3`, `MCM`. Write `kBtu`, `klb`, `t` or `Mt` instead.

## 2. Power is not energy

MW is a rate and MWh is an amount. Interval data in MW must be multiplied by the **actual**
interval length: 0.25 h for 15-minute data, 23 h or 25 h for days with a DST transition.
`power_to_energy` takes explicit hours. Adding MW to MWh raises `DimensionError`.

**MW-month** and **MW-day** are capacity products (resource adequacy, capacity markets). They
are not energy, and conversion to MWh is refused.

## 3. Standard gas volumes need a basis

`scf` → `Sm³` is not just × 0.0283168. The reference temperature changes from 60 °F to 15 °C
(≈0.2%), and the reference pressure may change too (14.73 vs 14.696 psia, ≈0.23%). Crossing
bases raises `DecisionRequired("scf_standard_conditions")`. Plain `m³` on a gas column is
flagged by the lint because it may be at line conditions.

## 4. boe is a convention, not a unit

`6 Mcf = 1 boe` is an approximate energy equivalence (≈5.8 MMBtu/bbl crude vs ≈1.0 MMBtu/Mcf
gas) used by SEC and SPE reporting. At a $75 oil and $3 gas price, value parity is closer to
25:1. NGLs are usually counted 1:1 by volume even though they hold ≈ 4 MMBtu/bbl. Every boe
figure must say which method produced it, and `boe_from_gas` requires the method.

## 5. HHV vs LHV

The two bases differ by about 10% for natural gas. A CCGT quoted at 60% LHV efficiency is
about 54% HHV. Heat-rate and efficiency functions carry the basis but never switch it.
Switching needs a fuel-specific `lhv_over_hhv`.

## 6. Tons

The short ton (907 kg), the long ton (1,016 kg) and the metric tonne (1,000 kg) differ by up
to 12%. US EPA reports metric tonnes (`MMT CO2e` = million metric tons). Some US utility fuel
data is in short tons. `ton` / `tons` are refused.

## 7. Gauge vs absolute pressure

`psig` + 14.696 (site-dependent) = `psia`. Plain `psi` and `bar` are refused. Gas-law
calculations and standard-volume corrections need absolute pressure.

## 8. Temperature is affine

60 °F is 15.56 °C. A temperature *difference* of 60 °F is 33.3 °C. Adding absolute
temperatures is refused.

## 9. Years

8,760 h vs 8,784 h (leap year), and 365 vs 365.25 days. Annual capacity factors and
annualized decline rates change by up to 0.3%. `yr` is refused as a unit; callers state the
day count.
