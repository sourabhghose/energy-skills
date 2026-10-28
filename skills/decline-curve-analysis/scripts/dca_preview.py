"""Read-only DCA preview: data profile and EUR sensitivity to each decision point (pandas).

Shows the user, on THEIR wells, how much the choices move the answer before anything is
built. The EUR grid uses a provisional economic limit (2% of peak rate) and a 50-year life,
labelled as illustrative; the confirmed build requires the user's own values.

Usage:
    from dca_preview import preview_wells
    print(preview_wells({"42-123-45678": pdf}, period="monthly"))
"""

from __future__ import annotations

import logging

import pandas as pd

from dca_config import DcaDecisions
from dca_prep import condition_well
from dca_well import analyze_well

logger = logging.getLogger(__name__)

B_OPTIONS = ((0.0, 1.0), (0.0, 1.5), (0.0, 2.0))
TERMINAL_OPTIONS = ("none", 0.06, 0.10)


def _profile(well_id: str, pdf: pd.DataFrame, period: str) -> dict:
    has_days = "days_on" in pdf.columns and pdf["days_on"].notna().any()
    basis = "producing_day" if has_days else "calendar_day"
    cw = condition_well(pdf, period, basis, "peak", "none")
    cal = condition_well(pdf, period, "calendar_day", "peak", "none")
    frame = cw.frame
    downtime = int((frame["days_on"] < frame["calendar_days"] - 0.5).sum()) if has_days else None
    return {
        "well_id": well_id, "periods": len(frame),
        "first_production": cw.first_production.date().isoformat(),
        "peak_period": cw.decline_start.date().isoformat(),
        "periods_before_peak": int((frame["exclude_reason"] == "pre_decline").sum()),
        "shut_in_or_zero": int((frame["exclude_reason"] == "shut_in_or_zero").sum()),
        "periods_with_downtime": downtime,
        "peak_rate_calendar": float(cal.frame.loc[cal.frame["include"], "rate"].max()),
        "peak_rate_producing": float(frame.loc[frame["include"], "rate"].max()) if has_days else None,
        "cum_to_date": cw.cum_volume,
    }


def _eur_grid(pdf: pd.DataFrame, period: str, peak_rate: float, rate_basis: str) -> dict:
    grid = {}
    for b_bounds in B_OPTIONS:
        for terminal in TERMINAL_OPTIONS:
            decisions = DcaDecisions.from_kwargs(
                rate_basis=rate_basis, decline_start="peak", outlier_method="none", b_bounds=b_bounds,
                terminal_decline_eff=terminal, econ_limit_rate=0.02 * peak_rate, max_life_years=50.0)
            try:
                res = analyze_well(pdf, period, decisions)
            except ValueError as exc:
                logger.warning("preview fit failed for b=%s terminal=%s: %s", b_bounds, terminal, exc)
                continue
            if res.get("status") == "ok":
                grid[(b_bounds[1], terminal)] = (res["eur"], res["b"])
    return grid


def _format_grid(grid: dict, unit: str) -> list[str]:
    lines = ["    b_max \\ terminal   " + "".join(f"{str(t):>16s}" for t in TERMINAL_OPTIONS)]
    for _, b_max in B_OPTIONS:
        cells = [grid.get((b_max, t)) for t in TERMINAL_OPTIONS]
        text = "".join(f"{c[0]:>12,.0f} b={c[1]:.2f}" if c else f"{'n/a':>16s}" for c in cells)
        lines.append(f"    {b_max:<19.1f}{text}")
    lines.append(f"    (EUR in {unit}; provisional econ limit = 2% of peak rate, 50-yr life: ILLUSTRATIVE)")
    return lines


def preview_wells(wells: dict[str, pd.DataFrame], period: str, volume_unit: str = "bbl") -> str:
    """Text readout of profile + EUR sensitivity. Builds nothing."""
    lines = [f"DCA preview for {len(wells)} well(s). READ-ONLY: nothing was written.", ""]
    for well_id, pdf in wells.items():
        prof = _profile(well_id, pdf, period)
        basis = "producing_day" if prof["peak_rate_producing"] is not None else "calendar_day"
        lines += [f"Well {well_id}: {prof['periods']} {period} periods, first production {prof['first_production']}, "
                  f"peak {prof['peak_period']} ({prof['periods_before_peak']} periods before peak)",
                  f"  shut-in/zero periods: {prof['shut_in_or_zero']}; periods with downtime: "
                  f"{prof['periods_with_downtime']}",
                  f"  peak rate: calendar-day {prof['peak_rate_calendar']:,.1f}/d"
                  + (f", producing-day {prof['peak_rate_producing']:,.1f}/d" if prof["peak_rate_producing"] else ""),
                  f"  cumulative to date: {prof['cum_to_date']:,.0f} {volume_unit}",
                  f"  EUR sensitivity ({basis} rates):"]
        lines += _format_grid(_eur_grid(pdf, period, prof["peak_rate_calendar"], basis), volume_unit)
        lines.append("")
    lines += ["Decisions to confirm with the user before build_confirmed_dca:",
              "  rate_basis (calendar_day | producing_day), decline_start (peak | first_production),",
              "  outlier_method (none | mad), b_bounds, terminal_decline_eff (fraction or 'none'),",
              f"  econ_limit_rate ({volume_unit}/d), max_life_years."]
    return "\n".join(lines)
