"""Build a perfect answer for a tier-P task from its answer key, so scorers can be tested end to end."""

from __future__ import annotations

import csv
from pathlib import Path


def _value(check: dict, key: dict) -> object:
    if check["type"] == "numeric_any":
        return key[check["expected_any"][0]]
    if check["type"] == "numeric_range":
        return (float(key[check["low"]]) + float(key[check["high"]])) / 2
    if check["type"] == "forbid_in_list":
        return ["temp_forecast_f", "hour_local", "day_of_week", "is_holiday", "load_lag_168h"]
    return key[check.get("expected", check["key"])]


def perfect_answer(spec: dict, key: dict) -> dict:
    answer: dict = {"decisions": [], "summary": "ok"}
    for check in spec["check"]:
        if check["type"] == "decision":
            answer["decisions"].append({"decision": check["example"], "options": [], "chosen": "", "impact": ""})
        elif "key" in check:
            answer[check["key"]] = _value(check, key)
    return answer


def write_outputs(task_id: str, key: dict, workdir: Path) -> None:
    """Output files some tasks ask for, written the way a careful agent would."""
    if task_id == "p06-ceii-share":
        share = workdir / "share"
        share.mkdir(parents=True, exist_ok=True)
        with open(share / "feeder_summary.csv", "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["feeder_id", "customer_count", "total_mwh", "region"])
            w.writerow(["ALL_OTHER", 1000, key["total_mwh_all"], "North Bay"])
    if task_id == "c02-price-plot":
        (workdir / "figures").mkdir(parents=True, exist_ok=True)
        (workdir / "figures" / "retail_prices.png").write_bytes(b"\x89PNG fake")
    if task_id == "p05-load-leakage":
        (workdir / "forecast.csv").write_text("timestamp_utc,forecast_mw\n2024-10-03T04:00:00Z,1000\n")
