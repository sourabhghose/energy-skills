"""Subsurface and drilling planted-truth generators: LAS net pay, density-porosity mnemonics, NPT from DDR text."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from ._common import readme, rng_for, write_csv, write_text

NULL = -999.25
FT_PER_M = 1 / 0.3048
CUTOFFS = {"gr_max": 75.0, "phie_min": 0.10, "sw_max": 0.50}
FACIES = {
    "shale": ((90, 130), (0.02, 0.07), (0.70, 1.00)),
    "pay": ((35, 65), (0.12, 0.24), (0.15, 0.45)),
    "wet": ((35, 65), (0.12, 0.24), (0.60, 0.95)),
    "tight": ((40, 65), (0.02, 0.08), (0.30, 0.90)),
}


def las_text(well: str, unit: str, depths: list[float], curves: list[tuple], rows: list[list], params: list) -> str:
    """LAS 2.0, unwrapped. curves: (mnemonic, unit, description); rows: values per depth, NULL for missing."""
    step = round(depths[1] - depths[0], 4)
    head = [
        "~VERSION INFORMATION", " VERS.   2.0 : CWLS LOG ASCII STANDARD - VERSION 2.0",
        " WRAP.   NO  : ONE LINE PER DEPTH STEP", "~WELL INFORMATION",
        f" STRT.{unit} {depths[0]:.4f} : START DEPTH", f" STOP.{unit} {depths[-1]:.4f} : STOP DEPTH",
        f" STEP.{unit} {step:.4f} : STEP", f" NULL.  {NULL:.2f} : NULL VALUE", f" WELL.  {well} : WELL NAME",
        *[f" {m}.{u} {v} : {d}" for m, u, v, d in params],
        "~CURVE INFORMATION", f" DEPT.{unit} : MEASURED DEPTH",
        *[f" {m}.{u} : {d}" for m, u, d in curves], "~A",
    ]
    body = [" ".join(f"{v:.4f}" for v in [dep, *vals]) for dep, vals in zip(depths, rows)]
    return "\n".join(head + body) + "\n"


def _beds(rng, n: int) -> list[str]:
    out = []
    while len(out) < n:
        facies = rng.choice(["shale", "shale", "pay", "wet", "tight"])
        out += [facies] * rng.randint(8, 60)
    return out[:n]


def _sample(rng, facies: str) -> tuple[float, float, float]:
    gr, phie, sw = FACIES[facies]
    return round(rng.uniform(*gr), 2), round(rng.uniform(*phie), 4), round(rng.uniform(*sw), 4)


def _is_pay(gr: float, phie: float, sw: float) -> bool:
    if NULL in (gr, phie, sw):
        return False
    return gr < CUTOFFS["gr_max"] and phie >= CUTOFFS["phie_min"] and sw <= CUTOFFS["sw_max"]


def _p12_well(rng, name: str, metric: bool, phie_pct: bool, null_sw: bool) -> tuple[str, float]:
    n = 1201
    depths = [round(1524.0 + k * 0.1524, 4) if metric else 5000.0 + k * 0.5 for k in range(n)]
    samples = [_sample(rng, f) for f in _beds(rng, n)]
    if null_sw:
        pays = [k for k, s in enumerate(samples) if _is_pay(*s)]
        start = pays[len(pays) // 2]
        samples = [(g, p, NULL) if start <= k < start + 40 else (g, p, s) for k, (g, p, s) in enumerate(samples)]
    net_ft = 0.5 * sum(_is_pay(*s) for s in samples)
    rows = [[g, round(p * 100, 2) if phie_pct else p, s] for g, p, s in samples]
    curves = [("GR", "GAPI", "GAMMA RAY"), ("PHIE", "%" if phie_pct else "V/V", "EFFECTIVE POROSITY"),
              ("SW", "V/V", "WATER SATURATION")]
    params = [("EKB", "M" if metric else "FT", 381.0 if metric else 1250.0, "KELLY BUSHING ELEVATION")]
    return las_text(name, "M" if metric else "FT", depths, curves, rows, params), net_ft


def p12_las_netpay(out: Path, seed: int) -> dict:
    rng = rng_for("p12", seed)
    specs = [("EB-A-1", False, False, False), ("EB-B-2", True, True, False), ("EB-C-3", False, False, True)]
    truth = {}
    for name, metric, pct, null_sw in specs:
        text, net = _p12_well(rng, name, metric, pct, null_sw)
        write_text(out / "logs" / f"{name}.las", text)
        truth[name] = net
    readme(out, "Petrophysical logs from three wells (LAS 2.0)", [
        "logs/*.las: interpreted curves GR, PHIE (effective porosity) and SW (water saturation), one file per "
        "well, as delivered by different service companies.",
    ])
    return {"net_pay_ft_by_well": truth, "total_net_pay_ft": sum(truth.values())}


# --- p13: density porosity across mnemonic and unit variants -----------------------------------------------------------

def _p13_density(rng, n: int) -> list[float]:
    rho, out = 2.45, []
    for _ in range(n):
        rho = min(2.62, max(2.20, rho + rng.gauss(0, 0.02)))
        out.append(round(rho, 4))
    return out


def p13_density_porosity(out: Path, seed: int) -> dict:
    rng = rng_for("p13", seed)
    specs = [("EB-D-1", "RHOB", "G/CC", 1.0, False), ("EB-D-2", "DEN", "G/CM3", 1.0, False),
             ("EB-D-3", "ZDEN", "K/M3", 1000.0, True), ("EB-D-4", "RHOZ", "G/C3", 1.0, False)]
    truth = {}
    for name, mnem, unit, scale, metric in specs:
        n = 1001
        rho = _p13_density(rng, n)
        if name == "EB-D-4":
            rho = [NULL if 450 <= k < 460 else r for k, r in enumerate(rho)]
        ft = [5000.0 + 0.5 * k for k in range(n)]
        depths = [round(1524.0 + 0.1524 * k, 4) for k in range(n)] if metric else ft
        rows = [[round(rng.uniform(40, 120), 2), r if r == NULL else round(r * scale, 4)] for r in rho]
        curves = [(rng.choice(["GR", "GRC", "SGR"]), "GAPI", "GAMMA RAY"), (mnem, unit, "BULK DENSITY")]
        write_text(out / "logs" / f"{name}.las", las_text(name, "M" if metric else "FT", depths, curves, rows, []))
        window = [r for d, r in zip(ft, rho) if 5200.0 <= d <= 5300.0 and r != NULL]
        truth[name] = round(sum((2.65 - r) / 1.65 for r in window) / len(window), 5)
    readme(out, "Bulk density logs from four wells (LAS 2.0)", [
        "logs/*.las: raw curves from four vendors; mnemonics and units follow each vendor's convention.",
    ])
    return {"phid_mean_by_well": truth}


# --- p14: NPT from free-text daily drilling reports ------------------------------------------------------------------

PRODUCTIVE = [
    "Drilled 8-1/2 in. hole from {d:,} ft to {d2:,} ft MD", "Circulated bottoms up and conditioned mud",
    "Tripped out of hole for bit change", "Made up BHA #4 and tripped in hole",
    "Performed BOP test to 5,000 psi - good test", "Ran 7 in. casing to {d:,} ft",
]
DISTRACTORS = [
    "Drilled ahead from {d:,} ft to {d2:,} ft, no losses observed",
    "Monitored well on trip tank - static, no lost circulation",
    "Pre-tour safety meeting: reviewed offset well 23-B stuck pipe incident",
    "Wiper trip to shoe; hole in good condition, no tight spots, pipe not stuck",
    "Reviewed weather forecast - no weather standby expected",
]
NPT = {
    "lost_circulation": ["Lost circulation at {d:,} ft, losses 60 bbl/hr; pumped LCM pill and waited on losses to heal",
                         "Partial losses (35 bbl/hr) at {d:,} ft; spotted LCM pill, regained full returns"],
    "stuck_pipe": ["Pipe stuck at {d:,} ft while making connection; worked pipe and jarred free",
                   "Differentially stuck at {d:,} ft; spotted pipe-lax pill and jarred free"],
    "waiting_on_weather": ["WOW - wind gusts above 45 mph, suspended crane and pipe handling",
                           "Waiting on weather: lightning within 5 miles, rig floor evacuated"],
    "equipment_repair": ["Repaired top drive hydraulic leak, rig on downtime",
                         "Mud pump #2 liner washout; repaired pump, rig on downtime"],
}


def _p14_activities(rng, depth: int) -> list[tuple[float, str, str | None]]:
    acts: list[tuple[float, str, str | None]] = []
    for cat in [c for c in NPT if rng.random() < 0.18][:2]:  # at most two NPT events keeps the log within 24 h
        acts.append((rng.randint(2, 12) / 2, rng.choice(NPT[cat]), cat))
    if rng.random() < 0.45:
        acts.append((rng.randint(2, 8) / 2, rng.choice(DISTRACTORS), None))
    while sum(a[0] for a in acts) < 24:
        hours = min(rng.randint(2, 12) / 2, 24 - sum(a[0] for a in acts))
        acts.append((hours, rng.choice(PRODUCTIVE), None))
    rng.shuffle(acts)
    return [(h, text.format(d=depth, d2=depth + int(h * 55)), cat) for h, text, cat in acts]


def _p14_remarks(acts: list[tuple]) -> str:
    t, lines = datetime(2024, 1, 1, 6), []
    for hours, text, _ in acts:
        end = t + timedelta(hours=hours)
        lines.append(f"{t:%H:%M}-{end:%H:%M} ({hours:.1f} hrs) {text}")
        t = end
    return "\n".join(lines)


def p14_drilling_npt(out: Path, seed: int) -> dict:
    rng = rng_for("p14", seed)
    rows, hours, lc_ids = [], {c: 0.0 for c in NPT}, []
    for k in range(40):
        rid, well = f"DDR-{k + 1:04d}", "EB-21H" if k < 20 else "EB-22H"
        acts = _p14_activities(rng, 6_000 + 180 * (k % 20))
        for h, _, cat in acts:
            if cat:
                hours[cat] += h
        if any(cat == "lost_circulation" for _, _, cat in acts):
            lc_ids.append(rid)
        date = (datetime(2024, 3, 1) + timedelta(days=k % 20)).strftime("%Y-%m-%d")
        rows.append([rid, well, date, _p14_remarks(acts)])
    write_csv(out / "daily_drilling_reports.csv", ["report_id", "well_id", "report_date", "operations_summary"],
              rows)
    readme(out, "Daily drilling reports (DDR), two wells, March 2024", [
        "daily_drilling_reports.csv: one report per well per day; operations_summary holds the 24-hour time log "
        "(06:00 to 06:00) as free text, one activity per line with its duration.",
    ])
    return {"npt_hours_by_category": hours, "total_npt_hours": sum(hours.values()),
            "lost_circulation_report_ids": lc_ids}
