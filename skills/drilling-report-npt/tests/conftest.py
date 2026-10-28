"""Put this skill's scripts/ on sys.path and provide synthetic time-log fixtures."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))
for _mod in ("uc_io", "npt_core", "npt_text", "npt_taxonomy", "npt_run"):
    sys.modules.pop(_mod, None)


def _row(i, well, start, end, code, remark, rig="R1", contractor="Acme Drilling", footage=None):
    return {"row_id": f"r{i}", "well_id": well, "rig_id": rig, "contractor": contractor,
            "start_time": start, "end_time": end, "activity_code": code, "remarks": remark,
            "footage_ft": footage}


@pytest.fixture
def ops_raw() -> pd.DataFrame:
    """Two report days on one well (00:00 start). Day 2 has a 1-hour gap."""
    d1, d2 = "2026-03-01", "2026-03-02"
    rows = [
        _row(1, "W-1", f"{d1} 00:00", f"{d1} 06:00", "2", "Drilled 8-1/2in hole 5000-5600 ft. No losses observed.", footage=600),
        _row(2, "W-1", f"{d1} 06:00", f"{d1} 10:00", "8", "Repair top drive hydraulic leak."),
        _row(3, "W-1", f"{d1} 10:00", f"{d1} 16:00", "5", "Partial losses 40 bbl/hr while circulating. Pumped LCM pill."),
        _row(4, "W-1", f"{d1} 16:00", f"{d2} 00:00", "21", "Waiting on weather, lightning in area, operations suspended."),
        _row(5, "W-1", f"{d2} 00:00", f"{d2} 05:00", "2", "Drilled ahead 5600-6100 ft. Offset well had stuck pipe at this depth.", footage=500),
        _row(6, "W-1", f"{d2} 06:00", "2026-03-03 00:00", "6", "POOH to change BHA, precaution for possible stuck pipe."),
    ]
    return pd.DataFrame(rows)


FAKE_EVENTS = {
    "No losses": '{"events": [{"category": "LOST_CIRCULATION", "quote": "losses observed", "negated": false, "subject": "this_well", "equipment_owner": null}]}',
    "top drive": '{"events": [{"category": "EQUIPMENT_RIG", "quote": "Repair top drive hydraulic leak", "negated": false, "subject": "this_well", "equipment_owner": "rig"}]}',
    "Partial losses": 'Here you go: {"events": [{"category": "LOST_CIRCULATION", "quote": "Partial losses 40 bbl/hr", "negated": false, "subject": "this_well", "equipment_owner": null}]}',
    "weather": '{"events": [{"category": "WAIT_WEATHER", "quote": "Waiting on weather", "negated": false, "subject": "this_well", "equipment_owner": null}]}',
    "Offset well": '{"events": [{"category": "STUCK_PIPE", "quote": "stuck pipe at this depth", "negated": false, "subject": "this_well", "equipment_owner": null}]}',
    "precaution": '{"events": [{"category": "STUCK_PIPE", "quote": "possible stuck pipe", "negated": false, "subject": "this_well", "equipment_owner": null}]}',
}


def fake_llm(prompt: str) -> str:
    """Deterministic stand-in for ai_query that makes deliberate model mistakes."""
    remark = prompt.rsplit("<<<", 1)[-1]
    for key, response in FAKE_EVENTS.items():
        if key in remark:
            return response
    return '{"events": []}'


@pytest.fixture
def llm():
    return fake_llm
