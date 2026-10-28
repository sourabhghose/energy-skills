"""Offline tests for column-name unit lint."""

from units_lint import lint_column, lint_columns


def _issues(column):
    return [(f.severity, f.issue) for f in lint_column(column)]


def test_clean_columns_have_no_findings():
    assert lint_columns(["oil_bbl", "well_id", "date", "generation_mwh"]) == []


def test_ambiguous_tons():
    assert any(sev == "error" and "tons" in issue for sev, issue in _issues("co2_tons"))


def test_mw_on_energy_column():
    assert any("MWh" in f.suggestion for f in lint_column("daily_generation_mw"))


def test_gas_in_actual_m3():
    assert any("Sm3" in f.suggestion for f in lint_column("gas_m3"))


def test_missing_unit():
    assert [f.severity for f in lint_column("gas_volume")] == ["warn"]


def test_scf_basis_and_hhv_info():
    issues = _issues("gas_mmbtu")
    assert any("HHV" in i for _, i in issues)
    assert any("reference pressure" in i for _, i in _issues("gas_mcf"))


def test_camel_case_and_mbtu():
    assert any(sev == "error" for sev, _ in _issues("fuelMBtu"))
