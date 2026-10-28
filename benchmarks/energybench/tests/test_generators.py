"""Planted-truth generators: deterministic, internally consistent, and each pitfall changes the answer.

Every answer key is recomputed here independently from the files the agent sees (stdlib csv parsing), and a
perfect answer built from the key must score 100 on the task's own checks.
"""

import json
import math
import statistics
from collections import defaultdict
from pathlib import Path

import pytest

import taskset
from generators import REGISTRY
from generators._common import read_csv
from helpers import perfect_answer, write_outputs
from scoring import score_checks

SEED = 20261028
PLANTED = {k: s for k, s in taskset.all_specs().items() if s["task"]["tier"] == "P"}


@pytest.fixture(scope="module")
def generated(tmp_path_factory):
    root = tmp_path_factory.mktemp("gen")
    out = {}
    for task_id, spec in PLANTED.items():
        data = root / task_id
        out[task_id] = (data, REGISTRY[spec["task"]["generator"]](data, SEED))
    return out


def tree_bytes(root: Path) -> dict[str, bytes]:
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


@pytest.mark.parametrize("task_id", sorted(PLANTED))
def test_deterministic_for_a_seed(task_id, tmp_path, generated):
    gen = REGISTRY[PLANTED[task_id]["task"]["generator"]]
    key = gen(tmp_path / "again", SEED)
    assert json.dumps(key, sort_keys=True) == json.dumps(generated[task_id][1], sort_keys=True)
    assert tree_bytes(tmp_path / "again") == tree_bytes(generated[task_id][0])


@pytest.mark.parametrize("task_id", ["p01-ami-dst", "p10-dca-eur", "c04-tariff-bill"])
def test_seed_changes_data(task_id, tmp_path, generated):
    gen = REGISTRY[PLANTED[task_id]["task"]["generator"]]
    assert gen(tmp_path / "other", SEED + 1) != generated[task_id][1]


@pytest.mark.parametrize("task_id", sorted(PLANTED))
def test_perfect_answer_scores_100(task_id, tmp_path, generated):
    spec, key = PLANTED[task_id], generated[task_id][1]
    write_outputs(task_id, key, tmp_path)
    result = score_checks(spec["check"], key, perfect_answer(spec, key), tmp_path)
    assert result["det_score"] == 100, [c for c in result["checks"] if c["earned"] < c["points"]]


@pytest.mark.parametrize("task_id", sorted(PLANTED))
def test_data_has_a_readme_and_no_answer_key(task_id, generated):
    data, key = generated[task_id]
    assert (data / "README.md").is_file()
    text = "\n".join(p.read_text(errors="replace") for p in data.rglob("*") if p.is_file())
    assert "_pitfall" not in text and "answer_key" not in text


# --- independent recomputation of planted truths ---------------------------------------------------------------------

def test_p01_repeated_hour_kept(generated):
    data, key = generated["p01-ami-dst"]
    rows = read_csv(data / "interval_reads.csv")
    nov2 = [r for r in rows if r["interval_start_local"].startswith("2025-11-02")]
    per_meter = defaultdict(int)
    for r in nov2:
        per_meter[r["meter_id"]] += 1
    assert set(per_meter.values()) == {100} and key["intervals_per_meter_2025_11_02"] == 100
    assert sum(float(r["kwh"]) for r in nov2) == pytest.approx(key["system_kwh_2025_11_02"], abs=1e-6)
    deduped = {(r["meter_id"], r["interval_start_local"]): float(r["kwh"]) for r in nov2}
    assert sum(deduped.values()) < 0.98 * key["system_kwh_2025_11_02"]  # the naive dedupe loses the hour


def test_p02_register_arithmetic(generated):
    data, key = generated["p02-ami-rollover"]
    reads = defaultdict(list)
    for r in read_csv(data / "register_reads.csv"):
        reads[r["service_point_id"]].append(r)
    events = {e["service_point_id"]: e for e in read_csv(data / "meter_events.csv")}
    total, rolled = 0, set()
    for sp, rows in reads.items():
        for prev, cur in zip(rows, rows[1:]):
            a, b = int(prev["register_kwh"]), int(cur["register_kwh"])
            if prev["meter_serial"] != cur["meter_serial"]:
                ev = events[sp]
                total += int(ev["old_final_read_kwh"]) - a + b - int(ev["new_initial_read_kwh"])
            elif b - a < -50_000:
                total += b - a + 100_000
                rolled.add(sp)
            else:
                total += b - a
    assert total == key["total_kwh_q1"]
    assert sorted(rolled) == key["rollover_service_points"] and sorted(events) == key["exchange_service_points"]


def test_p03_ieee1366_med(generated):
    data, key = generated["p03-reliability-med"]
    served = {int(r["year"]): int(r["customers_served"]) for r in read_csv(data / "customers_served.csv")}
    daily, cmi24, ci24 = defaultdict(float), defaultdict(float), defaultdict(float)
    for r in read_csv(data / "outage_events.csv"):
        dur, ci, day = float(r["duration_min"]), int(r["customers_interrupted"]), r["start_local"][:10]
        if dur <= 5:
            continue
        daily[day] += dur * ci / served[int(day[:4])]
        if day.startswith("2024"):
            cmi24[day] += dur * ci
            ci24[day] += ci
    logs = [math.log(v) for d, v in daily.items() if "2019" <= d[:4] <= "2023" and v > 0]
    t_med = math.exp(statistics.fmean(logs) + 2.5 * statistics.stdev(logs))
    med = sorted(d for d in cmi24 if cmi24[d] / served[2024] > t_med)
    assert t_med == pytest.approx(key["t_med_2024_min"], rel=1e-4) and med == key["med_days_2024"]
    keep = [d for d in cmi24 if d not in med]
    assert sum(cmi24[d] for d in keep) / served[2024] == pytest.approx(key["saidi_2024_excl_med_min"], rel=1e-5)
    assert sum(ci24.values()) / served[2024] == pytest.approx(key["saifi_2024_all"], rel=1e-4)
    assert key["_pitfall"]["saifi_2024_with_momentaries"] > 1.05 * key["saifi_2024_all"]


def test_p04_weighting_matters(generated):
    data, key = generated["p04-reliability-caidi"]
    served = {r["feeder_id"]: int(r["customers_served"]) for r in read_csv(data / "feeders.csv")}
    ok = [r for r in read_csv(data / "feeder_events.csv") if r["status"] == "CONFIRMED"]
    cmi = sum(float(r["duration_min"]) * int(r["customers_interrupted"]) for r in ok)
    assert cmi / sum(served.values()) == pytest.approx(key["system_saidi_min"], rel=1e-5)
    assert abs(key["_pitfall"]["unweighted_mean_feeder_saidi_min"] / key["system_saidi_min"] - 1) > 0.1


def test_p05_leaky_model_falls_below_the_allowed_range(generated):
    key = generated["p05-load-leakage"][1]
    assert key["_pitfall"]["leaky_mape_pct"] < key["mape_low_pct"] < key["oracle_mape_pct"] < key["mape_high_pct"]


def test_p06_naive_share_fails_privacy_checks(generated, tmp_path):
    data, key = generated["p06-ceii-share"]
    spec = PLANTED["p06-ceii-share"]
    share = tmp_path / "share"
    share.mkdir()
    subs = read_csv(data / "substations.csv")
    custs = read_csv(data / "customers.csv")
    lines = ["feeder_id,customer_count,total_mwh,latitude,longitude"]
    for s in subs:
        mine = [c for c in custs if c["feeder_id"] == s["feeder_id"]]
        lines.append(f"{s['feeder_id']},{len(mine)},{sum(int(c['annual_kwh_2024']) for c in mine) / 1000},"
                     f"{s['latitude']},{s['longitude']}")
    (share / "feeder_summary.csv").write_text("\n".join(lines) + "\n")
    result = score_checks(spec["check"], key, {"suppressed_feeders": [], "decisions": []}, tmp_path)
    failed = {c["type"] for c in result["checks"] if c["earned"] < c["points"]}
    assert {"file_forbid", "csv_min"} <= failed


def test_p07_degree_distance_inflates_miles(generated):
    key = generated["p07-wildfire-miles"][1]
    assert key["_pitfall"]["naive_degree_miles"] > 1.1 * key["tier3_overhead_miles"] > 0
    assert len(key["tier3_overhead_miles_by_circuit"]) >= 2


def test_p08_hour_ending_assignment(generated):
    data, key = generated["p08-iso-interval-ending"]
    by_he, by_floor = defaultdict(list), defaultdict(list)
    for r in read_csv(data / "rt_lmp_5min.csv"):
        hh, mm = int(r["interval_ending_local"][11:13]), int(r["interval_ending_local"][14:16])
        minutes = 1440 if r["interval_ending_local"].startswith("2024-07-16") else hh * 60 + mm
        by_he[math.ceil(minutes / 60)].append(float(r["rt_lmp_usd_per_mwh"]))
        by_floor[hh + 1 if minutes < 1440 else 24].append(float(r["rt_lmp_usd_per_mwh"]))
    assert statistics.fmean(by_he[18]) == pytest.approx(key["rt_price_he18"], rel=1e-6)
    assert abs(statistics.fmean(by_floor[18]) / key["rt_price_he18"] - 1) > 0.2


def test_p09_settlement_pitfalls_differ(generated):
    key = generated["p09-iso-settlement"][1]
    assert key["total_charge_usd"] == pytest.approx(key["da_charge_usd"] + key["rt_balancing_usd"], abs=0.02)
    for wrong in key["_pitfall"].values():
        assert abs(wrong - key["rt_balancing_usd"]) > 0.05 * abs(key["rt_balancing_usd"])


def test_p10_unbounded_hyperbolic_overstates_eur(generated):
    data, key = generated["p10-dca-eur"]
    rows = read_csv(data / "monthly_production.csv")
    assert any(r["days_on"] == "0" for r in rows)
    assert key["_pitfall"]["eur_total_unbounded_mbbl"] > 1.15 * key["eur_total_mbbl"]
    assert sum(key["eur_by_well_mbbl"].values()) == pytest.approx(key["eur_total_mbbl"], abs=0.01)


def test_p11_boe(generated):
    data, key = generated["p11-boe"]
    a, b = read_csv(data / "operator_a.csv"), read_csv(data / "operator_b.csv")
    liquids = sum(int(r["oil_bbl"]) + int(r["ngl_bbl"]) for r in a + b)
    gas = sum(int(r["gas_mcf"]) for r in a) + sum(float(r["gas_mmcf"]) * 1000 for r in b)
    assert (liquids + gas / 6) / 1000 == pytest.approx(key["total_mboe"], rel=1e-6)
    assert key["_pitfall"]["total_mboe_mmcf_as_mcf"] < 0.95 * key["total_mboe"]


NULL = -999.25


def _las(path: Path) -> tuple[dict, dict[str, str], list[list[float]]]:
    """Minimal LAS 2.0 reader: well header values, curve units, data rows."""
    header, units, rows, section = {}, {}, [], ""
    for line in path.read_text().splitlines():
        if line.startswith("~"):
            section = line[1]
            continue
        if section == "A":
            rows.append([float(v) for v in line.split()])
            continue
        mnem, _, rest = line.partition(".")
        if section == "W":
            header[mnem.strip()] = rest
        elif section == "C":
            units[mnem.strip()] = rest.split(":")[0].strip()
    return header, units, rows


def test_p12_net_pay_from_las(generated):
    data, key = generated["p12-las-netpay"]
    for name, net in key["net_pay_ft_by_well"].items():
        header, units, rows = _las(data / "logs" / f"{name}.las")
        metric, pct = header["STRT"].startswith("M"), units["PHIE"] == "%"
        count = sum(1 for _, gr, phie, sw in rows if NULL not in (gr, phie, sw)
                    and gr < 75 and (phie / 100 if pct else phie) >= 0.10 and sw <= 0.5)
        step_ft = (0.1524 / 0.3048) if metric else 0.5
        assert count * step_ft == pytest.approx(net, abs=1e-6)


def test_p13_density_units(generated):
    data, key = generated["p13-density-porosity"]
    header, units, rows = _las(data / "logs" / "EB-D-3.las")
    assert units["ZDEN"] == "K/M3" and header["STRT"].startswith("M")
    window = [r[2] / 1000 for r in rows if 5200 - 1e-6 <= r[0] / 0.3048 <= 5300 + 1e-6 and r[2] != NULL]
    assert statistics.fmean((2.65 - x) / 1.65 for x in window) == pytest.approx(key["phid_mean_by_well"]["EB-D-3"],
                                                                                abs=1e-4)


def test_p14_npt_hours_and_negations(generated):
    data, key = generated["p14-drilling-npt"]
    rows = read_csv(data / "daily_drilling_reports.csv")
    for r in rows:
        hours = sum(float(line.split("(")[1].split(" hrs")[0]) for line in r["operations_summary"].splitlines())
        assert hours == 24.0
    text = " ".join(r["operations_summary"] for r in rows)
    assert "no lost circulation" in text or "no losses observed" in text
    naive = [r["report_id"] for r in rows if "lost circulation" in r["operations_summary"].lower()
             or "losses" in r["operations_summary"].lower()]
    assert set(key["lost_circulation_report_ids"]) < set(naive)


def test_p15_leading_zero_trap(generated):
    data, key = generated["p15-well-identity"]
    apis = [r["api_number"] for r in read_csv(data / "production_accounting.csv")]
    assert any(len(a) == 9 and a.startswith("5") for a in apis)
    assert key["drilling_unique_wellbores"] > key["drilling_unique_wells"]


def test_p16_tag_rename_and_frozen_sensor(generated):
    data, key = generated["p16-esp-failures"]
    tags = defaultdict(set)
    frozen = defaultdict(list)
    for r in read_csv(data / "esp_sensors.csv"):
        tags[r["pump_id"]].add(r["tag"])
        if r["pump_id"] == "P12" and r["tag"] == "VIB_IPS" and r["timestamp_utc"] >= "2024-04-10":
            frozen["P12"].append(r["value"])
    assert "MOTOR_TEMP_C" in tags["P07"] and len(set(frozen["P12"])) == 1
    assert "P07" not in key["at_risk_pumps"] and "P12" not in key["at_risk_pumps"] and len(key["at_risk_pumps"]) == 4


def test_p17_losses_split(generated):
    key = generated["p17-wind-curtailment"][1]
    assert key["curtailment_loss_mwh"] > 5 and key["underperformance_loss_mwh"] > 5
    assert key["underperforming_turbines"] == ["T04"]


def test_p18_pr(generated):
    data, key = generated["p18-solar-pr"]
    rows = read_csv(data / "plant_hourly.csv")
    e = sum(float(r["ac_energy_kwh"]) for r in rows)
    h = sum(float(r["poa_wm2"]) for r in rows) / 1000
    assert 100 * e / (5000 * h) == pytest.approx(key["pr_june_pct"], rel=1e-6)
    assert key["_pitfall"]["pr_with_ghi_pct"] > 1.05 * key["pr_june_pct"] and key["lowest_pr_date"] == "2024-06-17"


def test_p19_units_and_leap_year(generated):
    data, key = generated["p19-capacity-factor"]
    rows = read_csv(data / "solar-1_15min.csv")
    assert len(rows) == 35136 and "output_kw" in rows[0]
    mwh = sum(float(r["output_kw"]) for r in rows) * 0.25 / 1000
    assert mwh == pytest.approx(key["generation_mwh_by_plant"]["SOLAR-1"], rel=1e-6)


def test_p20_p24_accounting(generated):
    s2 = generated["p20-scope2"][1]
    assert s2["scope2_location_tco2e_egrid2022"] != s2["scope2_location_tco2e_egrid2023"]
    s1 = generated["p21-scope1"][1]
    assert s1["co2_tonnes"] < s1["scope1_tco2e_ar5"] < s1["scope1_tco2e_ar6"]
    ch4 = generated["p22-methane"][1]
    assert sum(ch4["ch4_tonnes_by_site"].values()) == pytest.approx(ch4["ch4_tonnes_total"], abs=0.01)
    hr = generated["p23-heat-rate"][1]
    assert "WF-1" not in hr["net_heat_rate_btu_per_kwh_by_plant"]
    units = generated["p24-gas-units"][1]
    assert units["total_energy_gj"] == pytest.approx(units["total_energy_mmbtu"] * 1.055056, rel=1e-6)


def test_c04_bill_by_hand(generated):
    data, key = generated["c04-tariff-bill"]
    tariff = json.loads((data / "tariff.json").read_text())
    t = tariff["tiers"]
    energy = 500 * t[0]["usd_per_kwh"] + 500 * t[1]["usd_per_kwh"] + 250 * t[2]["usd_per_kwh"]
    assert round((energy + 12) * 1.05, 2) == key["bill_usd"]
