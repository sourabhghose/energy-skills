"""Fire-weather indices for wildfire-asset-risk (vectorized numpy).

Purpose
    equilibrium_moisture(temp_f, rh_pct)  Simard (1968) equilibrium moisture content (%)
    fosberg_ffwi(temp_f, rh_pct, wind_mph) Fosberg Fire Weather Index (0-100)
    Inputs are Fahrenheit, percent RH, and wind speed in mph. Convert first: passing
    Celsius or km/h silently produces a wrong index, so the functions range-check.

Usage
    from fire_weather import fosberg_ffwi
    ffwi = fosberg_ffwi(df["temp_f"], df["rh_pct"], df["wind_mph"])
"""

from __future__ import annotations

import numpy as np

FFWI_MAX = 100.0


def _as_array(x) -> np.ndarray:
    return np.asarray(x, dtype=float)


def _check_ranges(temp_f: np.ndarray, rh: np.ndarray, wind: np.ndarray) -> None:
    if np.any((rh < 0) | (rh > 100)):
        raise ValueError("rh_pct must be in [0, 100]")
    if np.any(wind < 0):
        raise ValueError("wind_mph must be >= 0")
    if np.any((temp_f < -60) | (temp_f > 140)):
        raise ValueError("temp_f out of range: are temperatures in Celsius or Kelvin?")


def equilibrium_moisture(temp_f, rh_pct) -> np.ndarray:
    """Equilibrium moisture content (%) of fine dead fuel."""
    t, h = _as_array(temp_f), _as_array(rh_pct)
    low = 0.03229 + 0.281073 * h - 0.000578 * h * t
    mid = 2.22749 + 0.160107 * h - 0.01478 * t
    high = 21.0606 + 0.005565 * h ** 2 - 0.00035 * h * t - 0.483199 * h
    return np.where(h < 10, low, np.where(h < 50, mid, high))


def fosberg_ffwi(temp_f, rh_pct, wind_mph) -> np.ndarray:
    """Fosberg Fire Weather Index, capped at 100.

    FFWI = eta * sqrt(1 + U^2) / 0.3002, with eta the moisture damping coefficient
    1 - 2(m/30) + 1.5(m/30)^2 - 0.5(m/30)^3 and m the equilibrium moisture content.
    """
    t, h, u = _as_array(temp_f), _as_array(rh_pct), _as_array(wind_mph)
    _check_ranges(t, h, u)
    m = np.clip(equilibrium_moisture(t, h), 0.0, 30.0) / 30.0
    eta = 1.0 - 2.0 * m + 1.5 * m ** 2 - 0.5 * m ** 3
    return np.minimum(eta * np.sqrt(1.0 + u ** 2) / 0.3002, FFWI_MAX)
