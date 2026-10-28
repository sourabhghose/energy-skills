"""Entrypoints the agent calls: read-only preview, then confirmed build.

Purpose
    preview_reliability_options  READ-ONLY. Profiles the data and shows how SAIDI /
                                 SAIFI / CAIDI move under every decision-point option.
    build_confirmed_reliability  Requires every decision explicitly. Returns indices with
                                 AND without MEDs, the MED list, cause breakdown, and a
                                 reproducible run manifest.

Usage
    import sys; sys.path.append("<skill-dir>/scripts")
    from reliability_api import preview_reliability_options, build_confirmed_reliability
"""

from __future__ import annotations

import itertools
import json
from datetime import datetime, timezone

import pandas as pd

from reliability_core import (
    DENOMINATOR_OPTIONS,
    MED_OPTIONS,
    PLANNED_OPTIONS,
    SUSTAINED_THRESHOLD_OPTIONS,
    Decisions,
    cause_breakdown,
    classify_steps,
    compute_indices,
    customer_level_indices,
    customers_served_for,
    daily_saidi,
    group_momentary_events,
    major_event_days,
    med_threshold,
    require_decisions,
    summarize_events,
    validate_steps,
)

SKILL_NAME = "reliability-metrics"
SKILL_VERSION = "0.1.0"
STANDARD = "IEEE Std 1366-2022 (2.5 beta MED method)"


def _events_for(steps: pd.DataFrame, threshold: int, tz: str, planned: str) -> pd.DataFrame:
    events = summarize_events(classify_steps(steps, threshold), tz)
    if planned == "exclude_planned":
        return events.loc[~events["is_planned"].astype(bool)]
    return events


def _med_context(events: pd.DataFrame, customers_served: pd.DataFrame, basis: str,
                 reporting_year: int) -> tuple[dict, list]:
    daily = daily_saidi(events, customers_served, basis)
    stats = med_threshold(daily, reporting_year)
    meds = major_event_days(daily, reporting_year, stats["t_med_minutes"])
    return stats, meds


def _scenario(steps, customers_served, reporting_year, tz, d: Decisions) -> dict:
    events = _events_for(steps, d.sustained_threshold_min, tz, d.planned_handling)
    n_t = customers_served_for(customers_served, reporting_year, d.denominator_basis)
    year_events = events.loc[events["year"] == reporting_year]
    meds: list = []
    if d.med_method == "ieee_2_5_beta":
        _, meds = _med_context(events, customers_served, d.denominator_basis, reporting_year)
        year_events = year_events.loc[~year_events["event_date"].isin(meds)]
    idx = compute_indices(year_events, n_t, reporting_year)
    return {**d.as_dict(), "med_days": len(meds), "saidi_min": idx["saidi_min"],
            "saifi": idx["saifi"], "caidi_min": idx["caidi_min"]}


def preview_reliability_options(steps: pd.DataFrame, customers_served: pd.DataFrame,
                                reporting_year: int, tz: str) -> dict:
    """READ-ONLY: profile data and tabulate indices for every decision combination.

    Builds nothing. Show `readout` to the user and ask them to choose each decision.
    """
    problems = validate_steps(steps)
    if problems:
        return {"ok": False, "problems": problems, "readout": "\n".join(problems)}
    grid = itertools.product(SUSTAINED_THRESHOLD_OPTIONS, DENOMINATOR_OPTIONS,
                             PLANNED_OPTIONS, MED_OPTIONS)
    rows = [_scenario(steps, customers_served, reporting_year, tz, Decisions(*combo))
            for combo in grid]
    table = pd.DataFrame(rows)
    planned_share = float(steps["is_planned"].astype(bool).mean())
    readout = _preview_readout(table, steps, reporting_year, planned_share)
    return {"ok": True, "scenarios": table, "readout": readout}


def _preview_readout(table: pd.DataFrame, steps: pd.DataFrame, year: int,
                     planned_share: float) -> str:
    lo, hi = table["saidi_min"].min(), table["saidi_min"].max()
    lines = [
        f"Reliability preview for {year} — READ-ONLY, nothing built.",
        f"  restoration steps: {len(steps):,}   events: {steps['event_id'].nunique():,}"
        f"   planned share of steps: {planned_share:.1%}",
        f"  SAIDI ranges from {lo:.1f} to {hi:.1f} min depending on the decisions below.",
        "",
        "Decisions needed (no defaults):",
        "  1. sustained_threshold_min: 5 (IEEE 1366) or 1 (some state rules)",
        "  2. denominator_basis: 'average' or 'year_end' customers served",
        "  3. planned_handling: 'exclude_planned' or 'include_planned'",
        "  4. med_method: 'ieee_2_5_beta' (exclude Major Event Days) or 'none'",
        "",
        table.to_string(index=False, float_format=lambda v: f"{v:,.3f}"),
    ]
    return "\n".join(lines)


def build_confirmed_reliability(steps: pd.DataFrame, customers_served: pd.DataFrame,
                                reporting_year: int, tz: str, *,
                                sustained_threshold_min, denominator_basis,
                                planned_handling, med_method,
                                momentary_ops: pd.DataFrame | None = None,
                                customer_events: pd.DataFrame | None = None,
                                source_tables: dict | None = None) -> dict:
    """Compute indices under the user's confirmed decisions (all required, no defaults)."""
    d = require_decisions(sustained_threshold_min, denominator_basis, planned_handling,
                          med_method)
    events = _events_for(steps, d.sustained_threshold_min, tz, d.planned_handling)
    n_t = customers_served_for(customers_served, reporting_year, d.denominator_basis)
    year_events = events.loc[events["year"] == reporting_year]
    med_stats, meds = ({}, [])
    if d.med_method == "ieee_2_5_beta":
        med_stats, meds = _med_context(events, customers_served, d.denominator_basis,
                                       reporting_year)
    momentary = group_momentary_events(momentary_ops) if momentary_ops is not None else None
    all_days = compute_indices(year_events, n_t, reporting_year, momentary)
    normal = year_events.loc[~year_events["event_date"].isin(meds)]
    excl = compute_indices(normal, n_t, reporting_year, momentary)
    extra = customer_level_indices(customer_events, n_t) if customer_events is not None else {}
    manifest = build_manifest(d, reporting_year, tz, steps, med_stats, meds, source_tables)
    headline = excl if d.med_method == "ieee_2_5_beta" else all_days
    return {
        "headline": {**headline, **extra},
        "all_days": all_days,
        "excluding_med": excl,
        "major_event_days": meds,
        "med_stats": med_stats,
        "cause_breakdown": cause_breakdown(normal),
        "manifest": manifest,
        "readout": _build_readout(d, reporting_year, all_days, excl, meds, med_stats),
    }


def build_manifest(d: Decisions, year: int, tz: str, steps: pd.DataFrame, med_stats: dict,
                   meds: list, source_tables: dict | None) -> dict:
    """Reproducible definition of this run (inputs, decisions, standard, version)."""
    return {
        "skill": SKILL_NAME, "skill_version": SKILL_VERSION, "standard": STANDARD,
        "run_at_utc": datetime.now(timezone.utc).isoformat(),
        "reporting_year": year, "timezone": tz,
        "decisions": d.as_dict(),
        "inputs": {**(source_tables or {}), "restoration_steps": int(len(steps))},
        "t_med_minutes": med_stats.get("t_med_minutes"),
        "med_history_years": med_stats.get("history_years"),
        "major_event_days": [str(x) for x in meds],
    }


def _build_readout(d: Decisions, year: int, all_days: dict, excl: dict, meds: list,
                   med_stats: dict) -> str:
    def row(label: str, r: dict) -> str:
        return (f"  {label:<22} SAIDI {r['saidi_min']:8.2f} min  SAIFI {r['saifi']:.3f}"
                f"  CAIDI {r['caidi_min']:7.2f} min  ASAI {r['asai']:.6f}")

    lines = [f"Reliability indices {year} ({STANDARD})",
             f"  decisions: {json.dumps(d.as_dict())}",
             row("all days", all_days), row("excluding MEDs", excl)]
    if med_stats:
        lines.append(f"  T_MED = {med_stats['t_med_minutes']:.3f} min "
                     f"(alpha {med_stats['alpha']:.3f}, beta {med_stats['beta']:.3f}, "
                     f"history {med_stats['history_years']}); MEDs: {[str(m) for m in meds]}")
        lines.extend(f"  WARNING: {w}" for w in med_stats["warnings"])
    return "\n".join(lines)
