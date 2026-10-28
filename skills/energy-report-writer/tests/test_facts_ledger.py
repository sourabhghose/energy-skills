"""Unit tests for scripts/facts_ledger.py, check_report.py, and latex_utils.py."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from check_report import check, main, missing_notices  # noqa: E402
from facts_ledger import (  # noqa: E402
    Fact,
    UnknownFact,
    build_ledger,
    find_untraced_numbers,
    ledger_appendix,
    load_ledger,
    records_from_rows,
    render,
    save_ledger,
)
from latex_utils import fpath, latex_escape, unit_label  # noqa: E402

RECORDS = [
    {"fact_id": "saidi_2025_excl_med", "value": 132.44, "unit": "min", "source": "main.rel.saidi_annual"},
    {"fact_id": "saifi_2025_excl_med", "value": 1.0812, "unit": "interruptions", "source": "main.rel.saidi_annual"},
    {"fact_id": "customers_served", "value": 412345, "unit": "-", "source": "main.rel.customers"},
    {"fact_id": "loss_share", "value": 4.25, "unit": "%", "source": "manifest:run-17"},
]
NOTICES = ("This draft requires review by a qualified engineer. It is not legal, regulatory, "
           "or investment advice.")


@pytest.fixture
def ledger():
    return build_ledger(RECORDS)


def test_formatting_rules(ledger):
    assert ledger["saidi_2025_excl_med"].formatted() == "132 min"
    assert ledger["saifi_2025_excl_med"].formatted() == "1.08 interruptions"
    assert ledger["customers_served"].formatted() == "412,345"
    assert Fact("x", 12.345, "MW", "t", decimals=2).formatted() == "12.35 MW"


@pytest.mark.parametrize("bad, match", [
    ({"fact_id": "Bad Id", "value": 1, "unit": "MW", "source": "t"}, "fact_id"),
    ({"fact_id": "a", "value": "n/a", "unit": "MW", "source": "t"}, "numeric"),
    ({"fact_id": "a", "value": float("nan"), "unit": "MW", "source": "t"}, "finite"),
    ({"fact_id": "a", "value": 1, "unit": "", "source": "t"}, "unit"),
    ({"fact_id": "a", "value": 1, "unit": "MW", "source": ""}, "source"),
])
def test_invalid_records_rejected(bad, match):
    with pytest.raises(ValueError, match=match):
        build_ledger([bad])


def test_duplicate_fact_rejected():
    with pytest.raises(ValueError, match="duplicate"):
        build_ledger([RECORDS[0], RECORDS[0]])


def test_records_from_rows_and_roundtrip(tmp_path):
    rows = [{"metric": "SAIDI", "value": 120.0, "unit": "min"}]
    ledger = build_ledger(records_from_rows(rows, id_key="metric", value_key="value",
                                            unit_key="unit", source="t", prefix="y2025_"))
    assert "y2025_saidi" in ledger
    path = tmp_path / "facts.json"
    save_ledger(ledger, path)
    assert load_ledger(path) == ledger


def test_render_latex_and_markdown(ledger):
    tex = r"SAIDI was \fact{saidi_2025_excl_med}; losses \fact{loss_share}."
    assert render(tex, ledger) == r"SAIDI was 132 min; losses 4.25 \%."
    md = "SAIDI was {{fact:saidi_2025_excl_med}}."
    assert render(md, ledger, syntax="markdown") == "SAIDI was 132 min."


def test_render_unknown_fact_raises(ledger):
    with pytest.raises(UnknownFact, match="saidi_2024"):
        render(r"\fact{saidi_2024}", ledger)


def test_untraced_numbers_found():
    text = "\\begin{document}\nSAIDI fell to 128.3 minutes from \\fact{x}.\n\\end{document}"
    found = find_untraced_numbers(text)
    assert [n.token for n in found] == ["128.3"]
    assert found[0].line == 2


@pytest.mark.parametrize("line", [
    "In 2025 the utility reported Scope 2 emissions per IEEE 1366 and EIA-923.",
    r"See Figure~3 and Table 2. \label{fig:a1} \ref{tab:2} \cite{eia2024}",
    r"\includegraphics[width=0.85\textwidth]{load_duration_2025.pdf}",
    "We used 15-minute intervals and a 5-year baseline. % 99 in a comment",
    r"Volumes at \fpath{/Volumes/main/s1/v2} via \fact{saidi_2025_excl_med}.",
])
def test_exempt_numbers(line):
    assert find_untraced_numbers(line) == []


def test_markdown_exemptions():
    md = "## 3. Results\n1. Loads `table_v2` see [link](http://x/1)\nPeak was 912 MW."
    assert [n.token for n in find_untraced_numbers(md, syntax="markdown")] == ["912"]


def test_appendix_lists_used_facts(ledger):
    tex = ledger_appendix(ledger, ["saidi_2025_excl_med", "saidi_2025_excl_med"])
    assert tex.count(r"\\") == 2  # header + one row
    assert r"saidi\_2025\_excl\_med" in tex
    md = ledger_appendix(ledger, ["loss_share"], syntax="markdown")
    assert "| `loss_share` | 4.25 % | `manifest:run-17` |" in md


def test_missing_notices_by_type():
    assert missing_notices(NOTICES, "reliability-annual") == []
    assert missing_notices(NOTICES, "reserves-production-summary") == ["not a reserves report"]
    with pytest.raises(ValueError):
        missing_notices(NOTICES, "press-release")


def test_check_combines_problems(ledger):
    draft = NOTICES + "\nSAIDI {{fact:saidi_2024}} vs 140 min."
    problems = check(draft, ledger, "reliability-annual", "markdown")
    assert any("not in ledger" in p for p in problems)
    assert any("'140'" in p for p in problems)


def test_cli_renders_on_success(tmp_path, ledger):
    save_ledger(ledger, tmp_path / "facts.json")
    draft = tmp_path / "brief.md"
    draft.write_text(NOTICES + "\nSAIDI was {{fact:saidi_2025_excl_med}}.", encoding="utf-8")
    args = [str(draft), "--ledger", str(tmp_path / "facts.json"), "--report-type", "internal-brief"]
    assert main(args) == 0
    assert "132 min" in (tmp_path / "brief.rendered.md").read_text(encoding="utf-8")
    draft.write_text("Peak load 912 MW.", encoding="utf-8")
    assert main(args) == 1


def test_latex_utils():
    assert latex_escape("O&M 5% capex_total #1") == r"O\&M 5\% capex\_total \#1"
    assert fpath("/Volumes/a_b").startswith(r"\fpath{/\allowbreak Volumes/\allowbreak a\_\allowbreak b")
    assert unit_label("Emissions", "tCO2e") == r"Emissions (tCO$_2$e)"
    assert unit_label("Load", "MW") == "Load (MW)"


def test_reserves_terms_blocked_only_in_reserves_summary(ledger):
    notice = NOTICES + (" This is not a reserves report. Volume classification requires a "
                        "qualified reserves evaluator.")
    clean = notice + "\nDecline-analysis EUR is {{fact:saidi_2025_excl_med}}."
    assert check(clean, ledger, "reserves-production-summary", "markdown") == []
    dirty = notice + "\nProved reserves (1P) and 2P volumes rose."
    problems = check(dirty, ledger, "reserves-production-summary", "markdown")
    assert {"'Proved'", "'reserves'", "'1P'", "'2P'"} <= {p.split(": ")[1].split(" ")[0] for p in problems}
    assert check(NOTICES + "\nProbable cause was vegetation.", ledger, "reliability-annual", "markdown") == []
    benign = notice + "\nWhere possible, the probable cause of shut-ins is noted."
    assert check(benign, ledger, "reserves-production-summary", "markdown") == []
