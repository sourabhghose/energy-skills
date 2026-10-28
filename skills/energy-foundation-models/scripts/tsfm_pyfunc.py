"""MLflow PyFunc wrapper for energy time-series foundation models.

Log this FILE (not an instance) so the serving container imports it after
`code_paths` are on sys.path:

    mlflow.pyfunc.log_model(
        name="model",
        python_model="scripts/tsfm_pyfunc.py",            # file-based logging
        code_paths=["scripts/tsfm_contract.py", "scripts/tsfm_catalog.py"],
        artifacts={"manifest": "/tmp/manifest.json", "weights": "/tmp/weights"},
        input_example=example_request, pip_requirements=[...pinned...],
    )

`load_context` reads the manifest (decisions + provenance), loads the adapter for
`manifest["model_key"]` from local artifacts only (no network at request time), and
`predict` runs: normalize_request -> adapter.predict -> build_response.

Adapters wrap upstream inference APIs as documented on the pinned model cards.
Verify the call against the pinned code revision before registering; tests use a fake.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Protocol, Sequence

import numpy as np
import pandas as pd

try:  # The serving container and Databricks ML runtimes have MLflow; offline tests may not.
    from mlflow.pyfunc import PythonModel
except ImportError:  # pragma: no cover - exercised only where MLflow is absent
    PythonModel = object  # type: ignore[assignment,misc]

sys.path.insert(0, str(Path(__file__).resolve().parent))
from tsfm_contract import ContractError, ForecastSpec, build_response, normalize_request  # noqa: E402

MANIFEST_KEYS = ("model_key", "hf_repo", "hf_revision", "weights_license", "license_accepted_by",
                 "spec", "max_context", "skill_version")


class Adapter(Protocol):
    max_context: int

    def predict(self, contexts: Sequence[np.ndarray], horizon: int, quantiles: Sequence[float],
                covariates: Sequence[dict] | None = None) -> list[np.ndarray]:
        """Return one (horizon, len(quantiles)) array per context.

        covariates, when given, has one dict per series:
        {"names": tuple[str, ...], "past": (T, k) array, "future": (horizon, k) array | None}
        """
        ...


def _select(levels: Sequence[float], native: Sequence[float], values: np.ndarray) -> np.ndarray:
    """Pick requested quantile columns from a (horizon, n_native) array."""
    missing = [q for q in levels if q not in native]
    if missing:
        raise ContractError(f"quantiles {missing} are not emitted natively; choose from {list(native)}")
    return values[:, [list(native).index(q) for q in levels]]


def _reject_covariates(covariates, model: str) -> None:
    if covariates and any(c is not None for c in covariates):
        raise ContractError(f"{model} adapter does not take covariates; register a covariate-capable model")


class ChronosBoltAdapter:
    """amazon/chronos-bolt-*: pipeline.predict -> [n_series, 9 deciles, horizon]."""

    native = (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9)

    def __init__(self, weights_dir: str, device: str):
        import torch
        from chronos import BaseChronosPipeline

        self._torch = torch
        self.pipeline = BaseChronosPipeline.from_pretrained(weights_dir, device_map=device)
        self.max_context = 2048

    def predict(self, contexts, horizon, quantiles, covariates=None):
        _reject_covariates(covariates, "chronos-bolt")
        tensors = [self._torch.tensor(c, dtype=self._torch.float32) for c in contexts]
        out = self.pipeline.predict(context=tensors, prediction_length=horizon).cpu().numpy()
        return [_select(quantiles, self.native, out[i].T) for i in range(len(contexts))]


def _chronos2_inputs(contexts, covariates) -> list:
    if not covariates:
        return [np.asarray(c, dtype=np.float32) for c in contexts]
    items = []
    for ctx, cov in zip(contexts, covariates):
        item = {"target": np.asarray(ctx, dtype=np.float32),
                "past_covariates": {n: cov["past"][:, i] for i, n in enumerate(cov["names"])}}
        if cov.get("future") is not None:
            item["future_covariates"] = {n: cov["future"][:, i] for i, n in enumerate(cov["names"])}
        items.append(item)
    return items


class Chronos2Adapter:
    """amazon/chronos-2: predict_quantiles with optional past / known-future covariates."""

    def __init__(self, weights_dir: str, device: str):
        from chronos import Chronos2Pipeline

        self.pipeline = Chronos2Pipeline.from_pretrained(weights_dir, device_map=device)
        self.max_context = 8192

    def predict(self, contexts, horizon, quantiles, covariates=None):
        q, _mean = self.pipeline.predict_quantiles(
            _chronos2_inputs(contexts, covariates), prediction_length=horizon,
            quantile_levels=list(quantiles))
        # each element: (n_variates=1, horizon, n_quantiles)
        return [np.asarray(t.cpu().numpy())[0] for t in q]


class TimesFM25Adapter:
    """google/timesfm-2.5-200m-pytorch: forecast -> (n, h, 10): mean, then deciles."""

    native = (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9)

    def __init__(self, weights_dir: str, device: str, max_context: int, max_horizon: int):
        import timesfm

        self.model = timesfm.TimesFM_2p5_200M_torch.from_pretrained(weights_dir)
        self.model.compile(timesfm.ForecastConfig(
            max_context=max_context, max_horizon=max_horizon, normalize_inputs=True,
            use_continuous_quantile_head=True, fix_quantile_crossing=True,
        ))
        self.max_context = max_context

    def predict(self, contexts, horizon, quantiles, covariates=None):
        _reject_covariates(covariates, "timesfm-2.5 (XReg not wired)")
        _, qf = self.model.forecast(horizon=horizon, inputs=list(contexts))
        return [_select(quantiles, self.native, qf[i, :, 1:]) for i in range(len(contexts))]


ADAPTERS = {
    "chronos-bolt-base": lambda m, d: ChronosBoltAdapter(d, m.get("device", "cpu")),
    "chronos-2": lambda m, d: Chronos2Adapter(d, m.get("device", "cpu")),
    "timesfm-2.5-200m": lambda m, d: TimesFM25Adapter(
        d, m.get("device", "cpu"), m["max_context"], m["spec"]["horizon"]),
}


def spec_from_manifest(manifest: dict) -> ForecastSpec:
    s = manifest["spec"]
    return ForecastSpec(horizon=int(s["horizon"]), quantiles=tuple(s["quantiles"]), freq=s["freq"],
                        unit=s["unit"], non_negative=bool(s["non_negative"]),
                        gap_policy=s["gap_policy"], covariates=tuple(s.get("covariates", ())))


def validate_manifest(manifest: dict) -> None:
    missing = [k for k in MANIFEST_KEYS if k not in manifest]
    if missing:
        raise ContractError(f"manifest missing keys: {missing}")
    if not manifest["license_accepted_by"]:
        raise ContractError("manifest has no licence acceptance; refuse to load")
    if len(str(manifest["hf_revision"])) != 40:
        raise ContractError("hf_revision must be a full 40-character commit SHA")


def _covariate_payload(batch, spec: ForecastSpec) -> list[dict] | None:
    if not spec.covariates:
        return None
    return [{"names": spec.covariates, "past": past, "future": fut}
            for past, fut in zip(batch.past_covariates, batch.future_covariates)]


class EnergyTSFM(PythonModel):
    """PyFunc boundary. `adapter` can be injected (tests) instead of loaded from artifacts."""

    def __init__(self, adapter: Adapter | None = None, manifest: dict | None = None):
        self.adapter = adapter
        self.manifest = manifest
        self.spec = spec_from_manifest(manifest) if manifest else None

    def load_context(self, context) -> None:
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
        with open(context.artifacts["manifest"], encoding="utf-8") as fh:
            self.manifest = json.load(fh)
        validate_manifest(self.manifest)
        self.spec = spec_from_manifest(self.manifest)
        factory = ADAPTERS.get(self.manifest["model_key"])
        if factory is None:
            raise ContractError(f"no adapter for model_key {self.manifest['model_key']!r}")
        self.adapter = factory(self.manifest, context.artifacts["weights"])

    def predict(self, context, model_input: pd.DataFrame, params=None) -> pd.DataFrame:
        if self.adapter is None or self.spec is None:
            raise ContractError("model not initialized: call load_context or inject an adapter")
        batch = normalize_request(model_input, self.spec, max_context=self.adapter.max_context)
        raw = self.adapter.predict(list(batch.contexts), self.spec.horizon, self.spec.quantiles,
                                   _covariate_payload(batch, self.spec))
        return build_response(batch, raw, self.spec, model_name=self.manifest["model_key"],
                              model_revision=self.manifest["hf_revision"])


try:  # file-based logging hook; no-op when MLflow is absent
    import mlflow.models

    mlflow.models.set_model(EnergyTSFM())
except ImportError:  # pragma: no cover
    pass
