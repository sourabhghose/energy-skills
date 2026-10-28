"""PyFunc wrapper contract with an injected fake adapter, manifest rules, runner helpers."""

from __future__ import annotations

import json
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from conftest import FakeForecaster, feeder_load, request_frame

import tsfm_pyfunc
from tsfm_catalog import CATALOG, fit_report
from tsfm_contract import ContractError, DecisionRequired, ForecastSpec
from tsfm_pyfunc import EnergyTSFM, _select, validate_manifest
from tsfm_run import (
    build_confirmed_deployment,
    build_manifest,
    check_pins,
    profile_frame,
    validate_identifier,
)


def _manifest(spec: ForecastSpec, **overrides) -> dict:
    base = build_manifest("chronos-2", spec, "Test Owner, 2026-10-28", "CPU", "main.grid.load", 100)
    return {**base, **overrides}


def test_wrapper_predict_with_fake_adapter(spec):
    model = EnergyTSFM(adapter=FakeForecaster(season=48), manifest=_manifest(spec))
    df = pd.concat([request_frame(feeder_load(7), "2026-01-01", "30min", "f1"),
                    request_frame(feeder_load(7, seed=3), "2026-01-01", "30min", "f2")],
                   ignore_index=True)
    out = model.predict(None, df)
    assert out.groupby("series_id").size().to_dict() == {"f1": 48, "f2": 48}
    assert (out["model_revision"] == CATALOG["chronos-2"].hf_revision).all()
    assert (out[["q0.1", "q0.5", "q0.9"]].to_numpy() >= 0).all()


def test_wrapper_passes_covariates_to_adapter():
    spec = ForecastSpec(horizon=4, quantiles=(0.5,), freq="1h", unit="mwh", non_negative=True,
                        gap_policy="reject", covariates=("temp_c",))
    fake = FakeForecaster(season=24)
    model = EnergyTSFM(adapter=fake, manifest=_manifest(spec))
    hist = request_frame(np.arange(72.0), "2026-01-01", "1h").assign(temp_c=1.0)
    fut = request_frame(np.full(4, np.nan), "2026-01-04", "1h").assign(temp_c=2.0)
    model.predict(None, pd.concat([hist, fut], ignore_index=True))
    cov = fake.calls[-1]["covariates"][0]
    assert cov["names"] == ("temp_c",)
    assert cov["past"].shape == (72, 1) and cov["future"].shape == (4, 1)


def test_wrapper_uninitialized_fails(spec):
    with pytest.raises(ContractError, match="not initialized"):
        EnergyTSFM().predict(None, request_frame(feeder_load(2), "2026-01-01", "30min"))


def test_load_context_reads_manifest_and_uses_registered_adapter(tmp_path, spec, monkeypatch):
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(_manifest(spec)), encoding="utf-8")
    monkeypatch.setitem(tsfm_pyfunc.ADAPTERS, "chronos-2", lambda m, d: FakeForecaster(season=48))
    model = EnergyTSFM()
    model.load_context(SimpleNamespace(artifacts={"manifest": str(path), "weights": str(tmp_path)}))
    out = model.predict(None, request_frame(feeder_load(7), "2026-01-01", "30min"))
    assert len(out) == 48


@pytest.mark.parametrize("override,match", [
    ({"license_accepted_by": ""}, "licence acceptance"),
    ({"hf_revision": "main"}, "40-character"),
])
def test_manifest_guards(spec, override, match):
    with pytest.raises(ContractError, match=match):
        validate_manifest(_manifest(spec, **override))


def test_select_rejects_non_native_quantile():
    with pytest.raises(ContractError, match="not emitted natively"):
        _select((0.05,), (0.1, 0.5, 0.9), np.zeros((2, 3)))


def test_build_manifest_requires_licence_acceptance(spec):
    with pytest.raises(DecisionRequired, match="license_accepted_by"):
        build_manifest("chronos-2", spec, "", "CPU", "main.grid.load", 1)


def test_build_confirmed_requires_every_decision(tmp_path):
    with pytest.raises(DecisionRequired, match="model_key"):
        build_confirmed_deployment("main.grid.load", "main.models.m", str(tmp_path),
                                   model_key=None, compute="CPU", license_accepted_by="x",
                                   horizon=4, quantiles=(0.5,), non_negative=True,
                                   gap_policy="reject", unit="mwh", freq="1h",
                                   pip_requirements=["torch==2.5.1"])


def test_build_confirmed_blocks_without_passing_validation(tmp_path):
    failed = SimpleNamespace(passed=False, reasons=("MASE ratio 1.2 >= gate 1.0",))
    with pytest.raises(RuntimeError, match="MASE ratio"):
        build_confirmed_deployment("main.grid.load", "main.models.m", str(tmp_path),
                                   model_key="chronos-2", compute="CPU", license_accepted_by="x",
                                   horizon=4, quantiles=(0.5,), non_negative=True,
                                   gap_policy="reject", unit="mwh", freq="1h",
                                   pip_requirements=["torch==2.5.1"], validation_report=failed)


def test_pins_must_be_exact():
    assert check_pins(["torch==2.5.1"]) == ["torch==2.5.1"]
    with pytest.raises(ValueError, match="unpinned"):
        check_pins(["transformers>=4.40"])


@pytest.mark.parametrize("bad", ["main.grid.load; DROP TABLE x", "a.b.c.d", "", "main.`x`"])
def test_identifier_validation(bad):
    with pytest.raises(ValueError):
        validate_identifier(bad)


def test_profile_frame_flags_naive_timestamps_and_negatives():
    df = request_frame(np.array([1.0, -2.0, 3.0, 4.0]), "2026-01-01", "1h").assign(
        timestamp=lambda d: pd.to_datetime(d["timestamp"]).dt.tz_localize(None).astype(str))
    prof = profile_frame(df, "series_id", "timestamp", "target")
    assert prof["dst_risk"] is True
    assert prof["negative_share"] == 0.25
    assert prof["inferred_step"] == str(pd.Timedelta("1h"))


def test_fit_report_blocks_non_commercial_and_short_horizon_models():
    rows = {r["model"]: r for r in fit_report(horizon=96, context=5000, freq="30min",
                                              needs_future_covariates=True, commercial_use=True,
                                              quantiles=(0.1, 0.5, 0.9))}
    assert rows["chronos-2"]["usable"]
    assert not rows["moirai-2.0-small"]["usable"]
    assert any("non-commercial" in b for b in rows["moirai-2.0-small"]["blockers"])
    assert any("horizon 96 > max 64" in b for b in rows["chronos-bolt-base"]["blockers"])
    assert not rows["granite-ttm-r2"]["usable"]
