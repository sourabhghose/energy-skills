"""Synthetic wind SCADA and PV data with planted truth."""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

RATED = 2000.0


def warranted_curve() -> pd.DataFrame:
    ws = np.arange(0, 25.5, 0.5)
    p = np.where(ws < 3, 0, np.where(ws >= 12, RATED, RATED * ((ws - 3) / 9) ** 3))
    p = np.where(ws > 25, 0, p)
    return pd.DataFrame({"ws_ms": ws, "power_kw": p})


def make_scada(days: int = 30, seed: int = 1) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    ts = pd.date_range("2025-03-01", periods=days * 144, freq="10min", tz="UTC")
    curve = warranted_curve()
    frames = []
    for tid, perf, yaw in (("T1", 1.0, 0.0), ("T2", 0.95, 8.0)):
        ws = np.clip(rng.weibull(2.0, len(ts)) * 8.0, 0, 30)
        temp = 15.0 + rng.normal(0, 1, len(ts))
        p_hpa = np.full(len(ts), 1013.25)
        rho = p_hpa * 100 / (287.05 * (temp + 273.15))
        ws_norm = ws * (rho / 1.225) ** (1 / 3)
        power = np.interp(ws_norm, curve.ws_ms, curve.power_kw) * perf
        df = pd.DataFrame({"turbine_id": tid, "timestamp": ts, "wind_speed_ms": ws.round(2), "power_kw": power,
                           "ambient_temp_c": temp, "pressure_hpa": p_hpa, "state": "running",
                           "setpoint_kw": RATED, "vane_rel_deg": rng.normal(yaw, 2.0, len(ts))})
        frames.append(df)
    df = pd.concat(frames, ignore_index=True)
    t1 = df.index[df.turbine_id == "T1"]
    df.loc[t1[100:244], "state"] = "fault"               # 1 day turbine fault
    df.loc[t1[100:244], "power_kw"] = 0.0
    df.loc[t1[500:644], "state"] = "grid_outage"         # 1 day external
    df.loc[t1[500:644], "power_kw"] = 0.0
    df.loc[t1[1000:1144], "state"] = "curtailed"         # 1 day curtailed to 500 kW
    df.loc[t1[1000:1144], "setpoint_kw"] = 500.0
    df.loc[t1[1000:1144], "power_kw"] = np.minimum(df.loc[t1[1000:1144], "power_kw"], 500.0)
    df.loc[t1[2000:2012], "wind_speed_ms"] = 7.31       # stuck anemometer, 2 h
    return df


def make_pv(days: int = 400, seed: int = 2, rd_pct: float = -0.8, pr: float = 0.82,
            gamma: float = -0.004, dc_kwp: float = 1000.0, ac_kw: float = 750.0,
            start: str = "2024-01-01") -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    ts = pd.date_range(start, periods=days * 96, freq="15min", tz="America/Denver")
    hour = ts.hour + ts.minute / 60
    clear = np.clip(np.sin(np.pi * (hour - 6) / 12), 0, None) * 1050
    cloud = np.repeat(rng.uniform(0.6, 1.0, days), 96)
    poa = clear * cloud
    t_amb = 15 + 10 * np.sin(2 * np.pi * (ts.dayofyear - 100) / 365)
    t_mod = poa * np.exp(-3.56 - 0.075 * 2.0) + t_amb
    t_cell = t_mod + poa / 1000 * 3
    years = (ts - ts[0]).days / 365.25
    dc = dc_kwp * poa / 1000 * (1 + gamma * (t_cell - 25)) * pr * (1 + rd_pct / 100) ** years
    ac = np.minimum(dc, ac_kw)
    return pd.DataFrame({"timestamp": ts, "poa_wm2": poa, "ac_power_kw": ac, "module_temp_c": t_mod,
                         "inverter_id": "INV1", "inverter_status": "ok", "setpoint_kw": ac_kw})


@pytest.fixture
def scada():
    return make_scada()


@pytest.fixture
def curve():
    return warranted_curve()


@pytest.fixture(scope="session")
def pv():
    return make_pv()
