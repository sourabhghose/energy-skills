"""Offline tests for the runner's pure planning layer (no Spark needed)."""

import pytest

from uc_io import validate_identifier, validate_volume_path
from units_core import DecisionRequired
from units_run import _validate_conversions, plan_conversions


def test_plan_requires_decision():
    convs = [{"column": "gas_mcf", "from_unit": "Mcf", "to_unit": "MSm3", "new_column": "gas_msm3"}]
    with pytest.raises(DecisionRequired):
        plan_conversions(convs, {})
    plan = plan_conversions(convs, {"scf_standard_conditions": "60F_14.696psia"})
    assert plan[0]["scale"] == pytest.approx(2.82623e-2 * 1e-3, rel=1e-5)


def test_validate_conversions_rejects_bad_columns():
    with pytest.raises(ValueError):
        _validate_conversions([{"column": "x; drop", "from_unit": "bbl", "to_unit": "m3"}], ["x; drop"])
    with pytest.raises(ValueError, match="not in table"):
        _validate_conversions([{"column": "oil", "from_unit": "bbl", "to_unit": "m3"}], ["gas"])


@pytest.mark.parametrize("bad", ["a.b.c.d", "main.x;DROP", "", "a b"])
def test_identifier_validation(bad):
    with pytest.raises(ValueError):
        validate_identifier(bad)


def test_volume_path_validation():
    assert validate_volume_path("/Volumes/main/energy/raw/las/a.las")
    with pytest.raises(ValueError):
        validate_volume_path("/Volumes/main/energy/raw/../../etc")
