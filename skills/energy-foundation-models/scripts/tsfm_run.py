"""Databricks runner: preview, then validate -> register -> deploy an energy TSFM.

Two entrypoints, per the Energy Skill Contract:

    preview_deployment_options(table, ...)   READ-ONLY. Profiles the series in a UC table
        (frequency, length, gaps, negatives, timezone) and returns which catalog models fit
        the requested horizon / covariates / licence posture, with the decisions to make.
    build_confirmed_deployment(table, ..., model_key=..., compute=..., ...)
        Requires every decision explicitly (no defaults). Writes the manifest, backtests
        against seasonal naive, refuses to register if the gate fails, then logs the
        file-based PyFunc to Unity Catalog and (optionally) creates a Model Serving endpoint
        with AI Gateway inference tables and usage tracking.

Spark / MLflow / Databricks SDK are imported lazily inside functions so this module
imports offline; the pure helpers (`profile_frame`, `build_manifest`,
`validate_identifier`) are unit-tested.

Usage (in a Databricks notebook on serverless or ML runtime):
    import sys; sys.path.append("<skill-dir>/scripts")
    from tsfm_run import preview_deployment_options, build_confirmed_deployment
    print(preview_deployment_options("main.grid.feeder_load_30min", horizon=96,
                                     needs_future_covariates=True, commercial_use=True))
"""

from __future__ import annotations

import datetime as dt
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from tsfm_catalog import CATALOG, fit_report  # noqa: E402
from tsfm_contract import GAP_POLICIES, ForecastSpec, require_decision  # noqa: E402

SKILL_VERSION = "0.1.0"
IDENTIFIER = re.compile(r"^[A-Za-z0-9_]+(\.[A-Za-z0-9_]+){0,2}$")
COMPUTE_OPTIONS = ("CPU", "GPU_SMALL", "GPU_MEDIUM", "GPU_LARGE", "BATCH_JOB_ONLY")


def validate_identifier(name: str) -> str:
    """Return name back-quoted per part, or raise for anything that is not catalog.schema.table."""
    if not IDENTIFIER.match(name or ""):
        raise ValueError(f"invalid Unity Catalog identifier: {name!r}")
    return ".".join(f"`{part}`" for part in name.split("."))


def profile_frame(df: pd.DataFrame, series_col: str, ts_col: str, target_col: str) -> dict:
    """Pure profile of a long-format frame: frequency, lengths, gaps, negatives, timezone."""
    ts = pd.to_datetime(df[ts_col], format="ISO8601")
    tz_aware = getattr(ts.dt, "tz", None) is not None
    utc = ts.dt.tz_convert("UTC") if tz_aware else ts
    frame = pd.DataFrame({"sid": df[series_col].astype(str), "ts": utc, "y": df[target_col]})
    steps = frame.sort_values(["sid", "ts"]).groupby("sid")["ts"].diff().dropna()
    freq = steps.mode().iat[0] if not steps.empty else None
    lengths = frame.groupby("sid").size()
    gap_share = float((steps > freq).mean()) if freq is not None else float("nan")
    return {
        "n_series": int(lengths.size),
        "min_length": int(lengths.min()), "median_length": int(lengths.median()),
        "inferred_step": str(freq) if freq is not None else None,
        "gap_share": round(gap_share, 4),
        "null_target_share": round(float(frame["y"].isna().mean()), 4),
        "negative_share": round(float((frame["y"] < 0).mean()), 4),
        "timezone_aware": tz_aware,
        "dst_risk": not tz_aware,
    }


def _read_profile(table: str, series_col: str, ts_col: str, target_col: str, limit: int) -> dict:
    from pyspark.sql import SparkSession

    spark = SparkSession.getActiveSession()
    if spark is None:
        raise RuntimeError("no active Spark session; run inside a Databricks notebook or job")
    cols = [series_col, ts_col, target_col]
    for c in cols:
        if not re.match(r"^[A-Za-z0-9_]+$", c):
            raise ValueError(f"invalid column name {c!r}")
    pdf = spark.table(validate_identifier(table)).select(*cols).limit(limit).toPandas()
    return profile_frame(pdf, series_col, ts_col, target_col)


def preview_deployment_options(table: str, horizon: int, needs_future_covariates: bool,
                               commercial_use: bool, series_col: str = "series_id",
                               ts_col: str = "timestamp", target_col: str = "target",
                               sample_rows: int = 500_000) -> str:
    """READ-ONLY readout: data profile, model fit table, and the decisions still open."""
    prof = _read_profile(table, series_col, ts_col, target_col, sample_rows)
    freq = pd.tseries.frequencies.to_offset(pd.Timedelta(prof["inferred_step"])).freqstr
    rows = fit_report(horizon, prof["median_length"], freq, needs_future_covariates, commercial_use)
    lines = [f"Profile of {table}: {json.dumps(prof)}", "", "| model | usable | blockers / notes |",
             "|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['model']} | {'yes' if r['usable'] else 'no'} | "
                     f"{'; '.join(r['blockers'] + r['notes']) or '-'} |")
    lines += ["", "Decisions for the user (build_confirmed_deployment needs all of them):",
              "  model_key, compute " + str(COMPUTE_OPTIONS), "  license_accepted_by (name/role)",
              "  horizon, quantiles, non_negative (False for prices), gap_policy " + str(GAP_POLICIES),
              "  unit (e.g. mwh, mw, usd_per_mwh, bbl_per_day)"]
    if prof["dst_risk"]:
        lines.append("WARNING: timestamps are timezone-naive; resolve to UTC before deploying.")
    return "\n".join(lines)


def build_manifest(model_key: str, spec: ForecastSpec, license_accepted_by: str, compute: str,
                   source_table: str, n_rows: int) -> dict:
    """Pure manifest builder; every decision and provenance field in one JSON document."""
    entry = CATALOG.get(model_key)
    if entry is None:
        raise ValueError(f"unknown model_key {model_key!r}; choose from {sorted(CATALOG)}")
    require_decision(license_accepted_by or None, "license_accepted_by",
                     f"name/role accepting {entry.weights_license}")
    if compute not in COMPUTE_OPTIONS:
        raise ValueError(f"compute must be one of {COMPUTE_OPTIONS}")
    return {
        "model_key": model_key, "hf_repo": entry.hf_repo, "hf_revision": entry.hf_revision,
        "code_repo": entry.code_repo, "weights_license": entry.weights_license,
        "commercial_use_permitted": entry.commercial_use, "license_accepted_by": license_accepted_by,
        "compute": compute, "device": "cpu" if compute in ("CPU", "BATCH_JOB_ONLY") else "cuda",
        "max_context": entry.max_context,
        "spec": {"horizon": spec.horizon, "quantiles": list(spec.quantiles), "freq": spec.freq,
                 "unit": spec.unit, "non_negative": spec.non_negative,
                 "gap_policy": spec.gap_policy, "covariates": list(spec.covariates)},
        "inputs": {"table": source_table, "rows": n_rows},
        "skill_version": SKILL_VERSION,
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
    }


def _check_decisions(model_key, compute, license_accepted_by, horizon, quantiles,
                     non_negative, gap_policy, unit, freq) -> None:
    for name, value, options in (
        ("model_key", model_key, sorted(CATALOG)), ("compute", compute, COMPUTE_OPTIONS),
        ("license_accepted_by", license_accepted_by, "name/role"), ("horizon", horizon, "steps"),
        ("quantiles", quantiles, "e.g. (0.1, 0.5, 0.9)"), ("non_negative", non_negative, (True, False)),
        ("gap_policy", gap_policy, GAP_POLICIES), ("unit", unit, "mwh, mw, usd_per_mwh, ..."),
        ("freq", freq, "pandas alias, e.g. 15min, 30min, 1h"),
    ):
        require_decision(value, name, options)


def check_pins(requirements: list[str]) -> list[str]:
    """Every requirement must be pinned exactly (==) or to an immutable git commit (@<sha>)."""
    loose = [r for r in requirements
             if "==" not in r and not re.search(r"@\s*git\+\S+@[0-9a-f]{40}$", r)]
    if not requirements or loose:
        raise ValueError(f"unpinned requirements (serving resolves the latest and breaks): {loose}")
    return list(requirements)


def _endpoint_config(registered_name: str, version: str, compute: str, endpoint: str):
    from databricks.sdk.service.serving import (
        AiGatewayConfig, AiGatewayInferenceTableConfig, AiGatewayUsageTrackingConfig,
        EndpointCoreConfigInput, ServedEntityInput, ServingModelWorkloadType,
    )

    catalog, schema, _ = registered_name.split(".")
    entity = ServedEntityInput(entity_name=registered_name, entity_version=version,
                               workload_size="Small", scale_to_zero_enabled=True,
                               workload_type=ServingModelWorkloadType[compute])
    gateway = AiGatewayConfig(
        inference_table_config=AiGatewayInferenceTableConfig(
            catalog_name=catalog, schema_name=schema, enabled=True,
            table_name_prefix=f"{endpoint}_{dt.datetime.now():%Y%m%d%H%M}"),
        usage_tracking_config=AiGatewayUsageTrackingConfig(enabled=True))
    return EndpointCoreConfigInput(name=endpoint, served_entities=[entity]), gateway


def deploy_endpoint(registered_name: str, version: str, compute: str, endpoint: str) -> str:
    """Create a serving endpoint (inference tables on). Not used for BATCH_JOB_ONLY."""
    from databricks.sdk import WorkspaceClient

    if compute == "BATCH_JOB_ONLY":
        raise ValueError("compute=BATCH_JOB_ONLY: score with mlflow.pyfunc.spark_udf in a Job instead")
    config, gateway = _endpoint_config(registered_name, version, compute, endpoint)
    w = WorkspaceClient()
    w.serving_endpoints.create(name=endpoint, config=config, ai_gateway=gateway)
    return endpoint


def build_confirmed_deployment(table: str, registered_name: str, weights_dir: str, *,
                               model_key: str | None, compute: str | None,
                               license_accepted_by: str | None, horizon: int | None,
                               quantiles: tuple[float, ...] | None, non_negative: bool | None,
                               gap_policy: str | None, unit: str | None, freq: str | None,
                               pip_requirements: list[str] | None,
                               validation_report=None, endpoint: str | None = None) -> dict:
    """Register (and optionally deploy) after the user confirmed every decision.

    validation_report: a tsfm_validation.BacktestReport from the held-out backtest. A failed
    or missing report blocks registration — a model that loses to seasonal naive is not shipped.
    pip_requirements: exact pins read from the model's own pyproject / requirements at the
    pinned code revision (e.g. "chronos-forecasting==<x.y.z>", "torch==<x.y.z>").
    """
    _check_decisions(model_key, compute, license_accepted_by, horizon, quantiles,
                     non_negative, gap_policy, unit, freq)
    pins = check_pins(require_decision(pip_requirements, "pip_requirements",
                                       "exact pins from the model's pyproject at the pinned commit"))
    validate_identifier(table)
    validate_identifier(registered_name)
    if validation_report is None or not validation_report.passed:
        reasons = getattr(validation_report, "reasons", ("no validation report supplied",))
        raise RuntimeError(f"validation gate not passed: {list(reasons)}")
    spec = ForecastSpec(horizon=int(horizon), quantiles=tuple(quantiles), freq=freq, unit=unit,
                        non_negative=bool(non_negative), gap_policy=gap_policy)
    manifest = build_manifest(model_key, spec, license_accepted_by, compute, table, n_rows=-1)
    manifest = {**manifest, "validation": {"mase_ratio": validation_report.mase_ratio,
                                           "coverage": validation_report.coverage,
                                           "n_origins": validation_report.n_origins}}
    version = _log_and_register({**manifest, "pip_requirements": pins}, registered_name, weights_dir)
    deployed = deploy_endpoint(registered_name, version, compute, endpoint) if endpoint else None
    return {"registered_name": registered_name, "version": version, "endpoint": deployed,
            "manifest": manifest}


def _example_request(spec: ForecastSpec) -> pd.DataFrame:
    idx = pd.date_range("2026-01-05T00:00:00Z", periods=4 * 24, freq=spec.freq)
    y = 100 + 10 * np.sin(np.arange(len(idx)) * 2 * np.pi / 24)
    covs = {c: np.zeros(len(idx)) for c in spec.covariates}
    return pd.DataFrame({"series_id": "feeder_001", "timestamp": idx.strftime("%Y-%m-%dT%H:%M:%SZ"),
                         "target": y, **covs})


def _log_and_register(manifest: dict, registered_name: str, weights_dir: str) -> str:
    import mlflow

    scripts = Path(__file__).resolve().parent
    manifest_path = Path("/tmp") / f"tsfm_manifest_{manifest['model_key']}.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    mlflow.set_registry_uri("databricks-uc")
    spec = ForecastSpec(**{**manifest["spec"], "quantiles": tuple(manifest["spec"]["quantiles"]),
                           "covariates": tuple(manifest["spec"]["covariates"])})
    with mlflow.start_run(run_name=f"energy-tsfm-{manifest['model_key']}"):
        mlflow.log_dict(manifest, "manifest.json")
        info = mlflow.pyfunc.log_model(
            name="model", python_model=str(scripts / "tsfm_pyfunc.py"),
            code_paths=[str(scripts / "tsfm_contract.py"), str(scripts / "tsfm_catalog.py")],
            artifacts={"manifest": str(manifest_path), "weights": weights_dir},
            input_example=_example_request(spec), registered_model_name=registered_name,
            pip_requirements=manifest["pip_requirements"],
        )
    return str(info.registered_model_version)
