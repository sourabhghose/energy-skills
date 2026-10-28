"""Synthetic ISO price fixtures."""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))


def ercot_hour_ending(days=("2025-11-01", "2025-11-02", "2025-11-03"), nodes=("HB_NORTH", "RN_WIND1")):
    """ERCOT-style RT SPP: date, hour_ending 'HH:00', interval 1-4, DSTFlag; Nov 2 has a repeated HE2."""
    rows = []
    for node in nodes:
        for d in days:
            hours = list(range(1, 25)) + ([2] if d == "2025-11-02" else [])
            flags = ["N"] * 24 + (["Y"] if d == "2025-11-02" else [])
            for he, flag in zip(hours, flags):
                for i in range(1, 5):
                    price = 30 + he + (5 if node == "RN_WIND1" else 0) + (10 if flag == "Y" else 0)
                    rows.append({"node": node, "date": d, "hour_ending": f"{he:02d}:00", "interval": i,
                                 "dst_flag": flag, "lmp": float(price)})
    return pd.DataFrame(rows)


def pjm_utc(hours=48, start="2025-07-01T04:00:00Z"):
    """PJM-style 5-minute RT with components and interval-beginning UTC timestamps."""
    ts = pd.date_range(start, periods=hours * 12, freq="5min")
    rng = np.random.default_rng(3)
    frames = []
    for node in ("WESTERN HUB", "NODE_A"):
        energy = 40 + 10 * np.sin(np.arange(len(ts)) / 30)
        cong = rng.normal(0, 2, len(ts)) + (8 if node == "NODE_A" else 0)
        loss = rng.normal(0.5, 0.2, len(ts))
        frames.append(pd.DataFrame({"node": node, "timestamp": ts, "energy": energy, "congestion": cong,
                                    "loss": loss, "lmp": energy + cong + loss}))
    return pd.concat(frames, ignore_index=True)


@pytest.fixture
def ercot():
    return ercot_hour_ending()


@pytest.fixture
def pjm():
    return pjm_utc()
