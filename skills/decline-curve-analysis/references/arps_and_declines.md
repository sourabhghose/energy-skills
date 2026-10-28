# Arps models, terminal decline, and decline-rate conventions

## Arps (1945) family

With `t` in years, `qi` the rate at the start of decline, `Di` the initial **nominal** decline
(1/yr), and `b` the hyperbolic exponent:

| Model | Rate q(t) | Cumulative Q(t) |
|-------|-----------|-----------------|
| Exponential (b = 0) | qi·e^(−Di·t) | (qi/Di)·(1 − e^(−Di·t)) |
| Harmonic (b = 1) | qi / (1 + Di·t) | (qi/Di)·ln(1 + Di·t) |
| Hyperbolic (0 < b, b ≠ 1) | qi / (1 + b·Di·t)^(1/b) | qi/((1−b)·Di) · [1 − (1 + b·Di·t)^((b−1)/b)] |

The instantaneous nominal decline is `D(t) = Di / (1 + b·Di·t)`, so it falls over time when
b > 0.

### Why b must be bounded

Arps derived the hyperbolic form for boundary-dominated flow, where `0 ≤ b ≤ 1`. Fits to
unconventional (multi-fractured horizontal) wells often give `b > 1` because the early
history is in **transient linear flow**, where b ≈ 2. That regime is temporary. If you
extrapolate b > 1 for decades, cumulative production keeps growing far longer than it
physically can, and for b ≥ 1 the cumulative has no finite limit unless you add an economic
limit. Practitioners therefore either:

1. bound b (commonly ≤ 1.0–1.5, by play and company policy), and/or
2. switch to a **terminal exponential decline** once D(t) falls to `D_min` (the
   *modified hyperbolic*, Robertson 1988), with `D_min` typically 5–10 %/yr effective.

Both are **engineering decisions**, often fixed by reserves-booking policy, so this skill
asks for them and never picks them.

## Modified hyperbolic

The switch happens at `t_sw = (Di/D_lim − 1)/(b·Di)`, when D(t) = D_lim. After the switch
the rate is `q_sw·e^(−D_lim·(t − t_sw))`. The terminal decline is usually quoted as an
**effective annual** fraction, which this skill converts with `D_lim = −ln(1 − D_min,eff)`.
For example, 8 %/yr effective gives 0.0834 /yr nominal.

## Three ways to quote "the decline"

| Form | Definition | Notes |
|------|-----------|-------|
| Nominal D | instantaneous −(dq/dt)/q, 1/yr | what the equations use |
| Tangent effective | 1 − e^(−D) | exact only for exponential decline |
| Secant effective | 1 − (1 + b·D)^(−1/b) | the actual first-year fractional drop for a hyperbolic; the SPEE-recommended way to quote hyperbolic declines |

These forms are not interchangeable. A "70 % first-year decline" with b = 1.5 is a nominal
Di of 3.39 /yr if it is secant, but 1.20 /yr if someone treats it as tangent. Plugging the
wrong one into the hyperbolic equation can shift EUR by tens of percent. `dca_models`
provides every conversion, and fitted output reports all three forms.

## Fitting

- Fit on **log rate**. Arithmetic least squares is dominated by the early high rates and
  under-weights the tail that controls EUR.
- For fixed (b, Di), the best log(qi) is closed-form, so `dca_fit` searches (b, log Di) on a
  bounded grid and then refines it. It never leaves the b-bounds, needs no initial guess,
  and is deterministic.
- Rates are assigned to **period midpoints**. A monthly volume divided by days gives an
  average rate, which is closest to the instantaneous rate mid-period.

## EUR

`EUR = cumulative to date (all history, including pre-peak) + ∫ forecast` from the end of
the last reported period to the earlier of:

- the time the rate reaches the **economic limit rate** (a decision, in volume/day), or
- **maximum life** from first production (a decision).

The output records which of the two ended the forecast. Reserves categories (1P/2P/3P) and
the economic test belong to PRMS / SEC rules and are out of scope. This skill produces
technical forecasts.

## Sources (summarized in our own words; consult the originals)

- Arps, J.J. (1945). *Analysis of Decline Curves*. Trans. AIME 160, SPE-945228-G. https://doi.org/10.2118/945228-G
- Robertson, S. (1988). *Generalized Hyperbolic Equation*. SPE-18731-MS. https://onepetro.org/
- SPEE Monograph 4 (2016). *Estimating Ultimate Recovery of Developed Wells in Low-Permeability Reservoirs*. https://spee.org/
- SPE PRMS (2018). *Petroleum Resources Management System*. https://www.spe.org/en/industry/petroleum-resources-management-system-2018/
- Fetkovich, M.J. (1980). *Decline Curve Analysis Using Type Curves*. JPT, SPE-4629-PA. https://doi.org/10.2118/4629-PA
