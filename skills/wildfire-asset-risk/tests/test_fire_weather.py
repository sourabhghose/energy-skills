"""Fosberg FFWI and equilibrium moisture content."""

import numpy as np
import pytest

from fire_weather import equilibrium_moisture, fosberg_ffwi


def test_ffwi_reference_value():
    # T=80F, RH=10%, U=25 mph -> m=2.646, eta=0.835, FFWI ~ 69.6
    assert float(fosberg_ffwi(80, 10, 25)) == pytest.approx(69.6, abs=0.3)


def test_ffwi_calm_humid_is_low_and_capped():
    assert float(fosberg_ffwi(50, 90, 0)) < 5
    assert float(fosberg_ffwi(100, 2, 120)) == 100.0


def test_ffwi_increases_with_wind_and_dryness():
    winds = fosberg_ffwi(80, 15, np.array([5, 15, 30]))
    assert np.all(np.diff(winds) > 0)
    assert fosberg_ffwi(80, 10, 20) > fosberg_ffwi(80, 40, 20)


def test_emc_branches():
    m = equilibrium_moisture(np.array([70, 70, 70]), np.array([5, 30, 70]))
    assert m[0] < m[1] < m[2]


@pytest.mark.parametrize("args", [(80, 120, 10), (80, 20, -1), (300, 20, 10)])
def test_ffwi_rejects_bad_units(args):
    with pytest.raises(ValueError):
        fosberg_ffwi(*args)
