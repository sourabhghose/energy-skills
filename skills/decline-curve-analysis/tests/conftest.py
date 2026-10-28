"""Put this skill's scripts/ on sys.path so tests import the vetted modules directly."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import pytest  # noqa: E402


def synth_well(qi=900.0, di=4.0, b=1.3, terminal=0.08, months=60, ramp=(300.0, 600.0),
               downtime=None, shut_in=(), spike=None, seed=None):
    """Monthly volumes from a known modified-hyperbolic curve, with optional artefacts."""
    from dca_models import modified_rate, terminal_effective_to_nominal

    dates = pd.date_range("2020-01-01", periods=months, freq="MS")
    start = len(ramp)
    t = ((dates - dates[start]).days + dates.days_in_month / 2) / 365.25
    d_lim = None if terminal is None else terminal_effective_to_nominal(terminal)
    rate = np.asarray(modified_rate(np.clip(t, 0, None), qi, di, b, d_lim), dtype=float)
    rate[:start] = ramp
    if seed is not None:
        rate = rate * np.exp(np.random.default_rng(seed).normal(0, 0.05, months))
    days_on = dates.days_in_month.to_numpy().astype(float)
    for idx, days in (downtime or {}).items():
        days_on[idx] = days
    volume = rate * days_on
    for idx in shut_in:
        volume[idx], days_on[idx] = 0.0, 0.0
    if spike is not None:
        volume[spike] *= 3.0
    return pd.DataFrame({"period_start": dates, "volume": volume, "days_on": days_on})


@pytest.fixture
def decisions():
    from dca_config import DcaDecisions

    return DcaDecisions.from_kwargs(rate_basis="producing_day", decline_start="peak", outlier_method="mad",
                                    b_bounds=(0.0, 2.0), terminal_decline_eff=0.08,
                                    econ_limit_rate=5.0, max_life_years=50.0)
