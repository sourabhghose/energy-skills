# Operating states and condition features

## Steady running only

Condition signals are only comparable across time when the machine runs in a similar state.
Start-ups, coast-downs, and trips produce large, normal excursions that a naive anomaly
model flags as faults.

- **`running_definition`**:
  - `status_tag`: a run-status or breaker tag (RUN / STOP, 1 / 0). Preferred.
  - `threshold`: running when a measurement exceeds a value (for example motor current > 20 %
    of nameplate, or speed > 90 % of rated). Pass `threshold={"measurement": ..., "min": ...}`.
- **`transient_exclusion_minutes`**: running rows within N minutes after a start or before
  a stop are excluded. Typical ESP restarts need 30–120 min for intake pressure and motor
  temperature to settle. Gas turbines need longer for thermal soak. Use OEM guidance.

## Features (computed on steady rows only)

| Feature | Why |
|---|---|
| `<signal>_mean`, `_std` (rolling) | level and stability |
| `<signal>_slope_per_h` (rolling regression) | drift (bearing temperature creep, motor temperature rise) |
| `motor_current_cv` | ESP current instability: gas interference / gas lock shows as cycling amps |
| `motor_temp_rise` | motor temperature minus intake temperature: cooling loss, low flow past the motor |
| `vibration_zone` | ISO-style A/B/C/D zone from mean velocity RMS |

## ESP signatures (ammeter-chart lore, as features)

| Pattern | Feature signal | Typical cause |
|---|---|---|
| smooth, steady amps | low CV | normal |
| cycling amps | rising `motor_current_cv` | gas interference, gas lock |
| gradual amp decline + pump-off trips | falling current mean, intake pressure falling | pump-off / low inflow |
| amps rising with temperature rise | current slope +, `motor_temp_rise` + | wear, sand, scale, rising viscosity |
| frequent restarts | many start transitions | underload / overload protection trips |

## Vibration zones (ISO 10816-3 / 20816-3 style, summarized)

Velocity RMS (mm/s) zone boundaries for industrial machines measured on bearing housings:

| Machine group / foundation | A/B | B/C | C/D |
|---|---|---|---|
| Group 1 (large, > 300 kW), rigid | 2.3 | 4.5 | 7.1 |
| Group 1, flexible | 3.5 | 7.1 | 11.0 |
| Group 2 (15–300 kW), rigid | 1.4 | 2.8 | 4.5 |
| Group 2, flexible | 2.3 | 4.5 | 7.1 |

Zone A is newly commissioned. B is acceptable for long-term operation. C is unsatisfactory
for long-term operation. D is severe enough to cause damage. These are generic evaluation
guides. **Site or OEM alarm limits take precedence**: pass `site_vibration_limits=(ab, bc, cd)`.
Reciprocating compressors and machines with rolling-element bearings in special services need
their own criteria (ISO 10816-6 / 20816-8, API 618/670 practice).

## Sources

- ISO 10816-3:2009 / ISO 20816-3:2022, Mechanical vibration: evaluation of machine vibration
  by measurements on non-rotating parts: https://www.iso.org/search.html?q=ISO%2020816-3
- API 610 (centrifugal pumps) and API 617 (axial and centrifugal compressors) set
  vibration acceptance at shop test. Summarized only: https://www.api.org/products-and-services/standards
- Takacs, G., *Electrical Submersible Pumps Manual* (Gulf Professional Publishing), ammeter
  chart interpretation.
