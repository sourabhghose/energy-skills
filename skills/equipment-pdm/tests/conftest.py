"""Put this skill's scripts/ on sys.path and build a small synthetic ESP fleet."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))
for _mod in ("uc_io", "pdm_taxonomy", "tags", "resample", "features", "modeling", "pdm_pipeline", "pdm_run"):
    sys.modules.pop(_mod, None)

START = pd.Timestamp("2026-03-01", tz="UTC")
FAIL_AT = START + pd.Timedelta(days=25)  # after the time-split embargo


def _asset_rows(asset: str, rng: np.random.Generator, degrade: bool) -> list[dict]:
    ts = START + pd.to_timedelta(np.arange(0, 28 * 24 * 60, 10), unit="min")
    hours_to_fail = (FAIL_AT - ts).total_seconds() / 3600.0
    ramp = np.clip(1 - hours_to_fail / 72.0, 0, 1) if degrade else np.zeros(len(ts))
    running = ~((ts >= START + pd.Timedelta(days=5)) & (ts < START + pd.Timedelta(days=5, hours=4)))
    if degrade:
        running &= ~((ts >= FAIL_AT) & (ts < FAIL_AT + pd.Timedelta(days=2)))
    amps = np.where(running, 42 + rng.normal(0, 0.4, len(ts)) + ramp * rng.normal(0, 6, len(ts)), 0.0)
    temp_f = np.where(running, 230 + rng.normal(0, 1, len(ts)) + 40 * ramp, 120.0)
    pip_psi = np.where(running, 850 + rng.normal(0, 5, len(ts)), 1200.0)
    rows = []
    for i, t in enumerate(ts):
        rows += [{"tag": f"{asset}.MTR_AMPS", "ts": t, "value": f"{amps[i]:.3f}"},
                 {"tag": f"{asset}.MTR_TEMP", "ts": t, "value": f"{temp_f[i]:.3f}"},
                 {"tag": f"{asset}.PIP", "ts": t, "value": f"{pip_psi[i]:.3f}"},
                 {"tag": f"{asset}.RUN", "ts": t, "value": "RUN" if running[i] else "STOP"}]
    rows.append({"tag": f"{asset}.MTR_AMPS", "ts": START + pd.Timedelta(days=3, minutes=5), "value": "I/O Timeout"})
    rows.append({"tag": f"{asset}.SPARE1", "ts": START, "value": "1"})
    return rows


@pytest.fixture(scope="session")
def fleet():
    rng = np.random.default_rng(3)
    rows = [r for a, deg in (("ESP-101", True), ("ESP-102", False), ("ESP-103", False))
            for r in _asset_rows(a, rng, deg)]
    historian = pd.DataFrame(rows)
    tag_map = pd.DataFrame([
        {"tag": f"{a}.{suffix}", "asset_id": a, "equipment_class": "esp", "measurement": m, "unit": u}
        for a in ("ESP-101", "ESP-102", "ESP-103")
        for suffix, m, u in (("MTR_AMPS", "motor_current", "A"), ("MTR_TEMP", "motor_temperature", "degF"),
                             ("PIP", "intake_pressure", "psi"), ("RUN", "run_status", "state"))
    ] + [{"tag": "ESP-104.MTR_AMPS", "asset_id": "ESP-104", "equipment_class": "esp",
          "measurement": "motor_current", "unit": "A"},
         {"tag": "ESP-101.PIP", "asset_id": "ESP-101", "equipment_class": "esp",
          "measurement": "intake_pressure", "unit": "furlongs"}][:1])
    work_orders = pd.DataFrame([
        {"asset_id": "ESP-101", "wo_id": "WO-1", "failure_mode": "ELF", "failure_start": FAIL_AT,
         "restored": FAIL_AT + pd.Timedelta(days=2)},
        {"asset_id": "ESP-102", "wo_id": "WO-2", "failure_mode": "OTH", "failure_start": START + pd.Timedelta(days=10),
         "restored": START + pd.Timedelta(days=10, hours=2)},
    ])
    return historian, tag_map, work_orders


DECISIONS = dict(analog_interpolation="linear", running_definition="status_tag", transient_exclusion_minutes=60,
                 failure_modes=["ELF", "BRD"], label_horizon_hours=72, split_strategy="time",
                 anomaly_method="robust_z")
