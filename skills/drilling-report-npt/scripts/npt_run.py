"""Databricks runner for drilling-report-npt: read-only preview, then confirmed build.

Purpose: Genie Code calls these two entrypoints instead of writing NPT SQL by hand.
  * preview_npt_options(...)  READ-ONLY. Profiles the time log, shows how each decision
    changes NPT hours on this data, and builds nothing.
  * build_confirmed_npt(...)  Requires every decision explicitly; classifies remarks with
    ai_query (span-grounded), reconciles hours, writes UC tables + a run manifest.

Usage (Python compute, e.g. serverless notebook):
    import sys; sys.path.append("<skill-dir>/scripts")
    from npt_run import preview_npt_options, build_confirmed_npt
    print(preview_npt_options("main.drilling.ddr_time_log", endpoint="databricks-claude-sonnet-4-5"))
"""

from __future__ import annotations

import logging

import pandas as pd

from npt_core import aggregate_npt, compute_ilt, evidence_table, flag_npt, normalize_ops, reconcile_hours
from npt_taxonomy import COMBINE_MODES, DecisionRequired, require_decisions, resolve_code_map
from npt_text import PROMPT_TAIL, PROMPT_VERSION, events_from_responses, primary_text_category, prompt_head
from uc_io import build_manifest, markdown, run_sql, validate_endpoint, validate_fqn, write_manifest, write_table

LOG = logging.getLogger(__name__)
SKILL, VERSION = "drilling-report-npt", "0.1.0"
TEXT_MODES = ("text_only", "union", "intersection")


def _read_ops(table: str, limit: int, warehouse_id, profile) -> pd.DataFrame:
    return run_sql("SELECT * FROM {t} LIMIT :n", {"n": int(limit)}, tables={"t": validate_fqn(table)},
                   warehouse_id=warehouse_id, profile=profile)


def _read_ops_with_llm(table: str, endpoint: str, limit: int, warehouse_id, profile) -> pd.DataFrame:
    ep = validate_endpoint(endpoint)
    sql = (f"SELECT *, CASE WHEN remarks IS NULL OR trim(remarks) = '' THEN NULL "
           f"ELSE ai_query('{ep}', concat(:head, remarks, :tail)) END AS npt_response "
           "FROM {t} LIMIT :n")
    return run_sql(sql, {"head": prompt_head(), "tail": PROMPT_TAIL, "n": int(limit)},
                   tables={"t": validate_fqn(table)}, warehouse_id=warehouse_id, profile=profile)


def _text_categories(ops: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    if "npt_response" not in ops.columns:
        empty = pd.DataFrame(columns=["row_id", "text_category", "text_quote", "equipment_owner",
                                      "multi_category"])
        return empty, pd.DataFrame()
    events = events_from_responses(ops, ops["npt_response"])
    return primary_text_category(events), events


def _mode_table(ops: pd.DataFrame, text_cats: pd.DataFrame, code_map: dict, has_text: bool) -> str:
    lines = ["| combine_mode | NPT h (weather=npt) | NPT h (weather excluded) |", "|---|---|---|"]
    for mode in COMBINE_MODES if has_text else ("code_only",):
        hours = [flag_npt(ops, text_cats, code_map, mode, wp).query("is_npt")["duration_hr"].sum()
                 for wp in ("npt", "exclude")]
        lines.append(f"| {mode} | {hours[0]:.1f} | {hours[1]:.1f} |")
    return "\n".join(lines)


def _recon_line(raw: pd.DataFrame, start_hour: int) -> str:
    ops = normalize_ops(raw, start_hour)
    recon = reconcile_hours(ops, start_hour)
    bad = recon[recon["status"] != "ok"] if len(recon) else recon
    return (f"| {start_hour:02d}:00 | {len(recon)} | {len(bad)} | "
            f"{', '.join(sorted(set(bad['status']))) if len(bad) else '-'} |")


def preview_npt_options(ops_table: str, endpoint: str | None = None, sample_rows: int = 500,
                        warehouse_id: str | None = None, profile: str | None = None) -> str:
    """READ-ONLY. Show decision options and their effect on a sample of the time log."""
    raw = (_read_ops_with_llm(ops_table, endpoint, sample_rows, warehouse_id, profile) if endpoint
           else _read_ops(ops_table, sample_rows, warehouse_id, profile))
    ops = normalize_ops(raw, 0)
    code_map = resolve_code_map("iadc_style")
    text_cats, events = _text_categories(ops)
    unmapped = sorted(set(ops["activity_code"].dropna()) - set(code_map))
    dropped = events[~events["kept"]]["drop_reason"].value_counts().to_dict() if len(events) else {}
    multi = int(text_cats["multi_category"].sum()) if len(text_cats) else 0
    return "\n".join([
        f"# NPT preview — {ops_table} (sample {len(ops)} rows, READ-ONLY, nothing written)",
        f"Wells: {ops['well_id'].nunique()}  Rigs: {ops['rig_id'].nunique()}  "
        f"Logged hours: {ops['duration_hr'].sum():.1f}",
        f"Activity codes not in the IADC-style map (decision code_taxonomy): {unmapped or 'none'}",
        "\n## Reporting-day start (decision report_day_start_hour)",
        "| start | well-days | flagged days | issues |", "|---|---|---|---|",
        _recon_line(raw, 0), _recon_line(raw, 6),
        "\n## NPT hours by combine mode and weather policy (iadc_style codes)",
        _mode_table(ops, text_cats, code_map, endpoint is not None),
        f"\nText events dropped by grounding/negation/subject filters: {dropped or 'none'}",
        f"Rows with >1 text NPT category (review): {multi}",
        "\nDecisions needed for build_confirmed_npt: code_taxonomy, combine_mode, "
        "weather_policy, report_day_start_hour, ilt_benchmark.",
    ])


def _check_text_endpoint(combine_mode: str, endpoint: str | None) -> None:
    if combine_mode in TEXT_MODES and not endpoint:
        raise DecisionRequired(f"combine_mode={combine_mode!r} reads remark text: pass endpoint=")


def _outputs(flagged: pd.DataFrame, recon: pd.DataFrame, ilt: pd.DataFrame, weather_policy: str) -> dict:
    return {
        "npt_by_category": aggregate_npt(flagged, ["npt_category"], weather_policy),
        "npt_by_well": aggregate_npt(flagged, ["well_id", "npt_category"], weather_policy),
        "npt_by_rig": aggregate_npt(flagged, ["rig_id", "contractor", "npt_category"], weather_policy),
        "npt_evidence": evidence_table(flagged),
        "hours_recon": recon,
        "ilt_rows": ilt,
    }


def _persist(outputs: dict, output_prefix: str, manifest: dict) -> list[str]:
    comment = f"{SKILL} v{VERSION}; decisions={manifest['decisions']}"
    written = [write_table(df.astype({c: "string" for c in df.columns if df[c].dtype == object}),
                           f"{output_prefix}_{name}", comment) for name, df in outputs.items()]
    write_manifest(manifest, f"{output_prefix}_run_manifest")
    return written


def build_confirmed_npt(ops_table: str, output_prefix: str, *, code_taxonomy, combine_mode,
                        weather_policy, report_day_start_hour, ilt_benchmark,
                        endpoint: str | None = None, ilt_group_cols: tuple = ("activity_code",),
                        max_rows: int = 200_000, warehouse_id: str | None = None,
                        profile: str | None = None, write: bool = True) -> dict:
    """Build NPT outputs. Every decision is keyword-only with no default (DecisionRequired)."""
    decisions = require_decisions(code_taxonomy=code_taxonomy, combine_mode=combine_mode,
                                  weather_policy=weather_policy, report_day_start_hour=report_day_start_hour,
                                  ilt_benchmark=ilt_benchmark)
    _check_text_endpoint(combine_mode, endpoint)
    validate_fqn(ops_table)
    validate_fqn(output_prefix)
    use_text = combine_mode in TEXT_MODES
    raw = (_read_ops_with_llm(ops_table, endpoint, max_rows, warehouse_id, profile) if use_text
           else _read_ops(ops_table, max_rows, warehouse_id, profile))
    ops = normalize_ops(raw, report_day_start_hour)
    text_cats, events = _text_categories(ops)
    flagged = flag_npt(ops, text_cats, resolve_code_map(code_taxonomy), combine_mode, weather_policy)
    outputs = _outputs(flagged, reconcile_hours(ops, report_day_start_hour),
                       compute_ilt(flagged, ilt_benchmark, list(ilt_group_cols)), weather_policy)
    manifest = build_manifest(SKILL, VERSION, {"ops_table": ops_table, "rows": len(ops),
                                               "truncated_at_max_rows": len(ops) >= max_rows},
                              {**decisions, "code_taxonomy": str(code_taxonomy)},
                              {"endpoint": endpoint, "prompt_version": PROMPT_VERSION,
                               "ilt_group_cols": list(ilt_group_cols),
                               "text_events_dropped": int((~events["kept"]).sum()) if len(events) else 0})
    if write:
        manifest = {**manifest, "tables": _persist(outputs, output_prefix, manifest)}
    return {"manifest": manifest, **outputs}


def format_result(result: dict) -> str:
    """Analyst-facing readout of build_confirmed_npt output."""
    cat = result["npt_by_category"]
    recon = result["hours_recon"]
    bad = int((recon["status"] != "ok").sum()) if len(recon) else 0
    ilt = result["ilt_rows"]["ilt_hr"].sum(skipna=True) if "ilt_hr" in result["ilt_rows"] else 0.0
    return "\n".join([
        "# NPT result", f"Decisions: {result['manifest']['decisions']}",
        markdown(cat),
        f"\nWell-days failing 24-hour reconciliation: {bad} of {len(recon)}",
        f"Invisible lost time (benchmarked rows): {ilt:.1f} h",
        f"Evidence rows (verbatim quotes): {len(result['npt_evidence'])}",
    ])
