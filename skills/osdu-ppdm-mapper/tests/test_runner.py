"""Runner entrypoints offline (reads monkeypatched, writes disabled)."""

from __future__ import annotations

import pytest

import mapping_run


@pytest.fixture
def patched(monkeypatch, header):
    monkeypatch.setattr(mapping_run, "_read", lambda *a, **k: header)
    monkeypatch.setattr(mapping_run, "write_table", lambda *a, **k: pytest.fail("unexpected write"))


def test_propose_writes_spec_file(patched, tmp_path):
    path = tmp_path / "spec.yaml"
    text = mapping_run.propose_mapping_spec("main.raw.header", "wellbore", str(path))
    assert path.exists() and "status: proposed" in path.read_text()
    assert "API_NO" in text


def test_preview_read_only(patched, reviewed_spec):
    text = mapping_run.preview_mapping_options("main.raw.header", reviewed_spec)
    assert "READ-ONLY" in text and "source_identifier_level" in text


def test_build_offline(patched, reviewed_spec, tmp_path):
    res = mapping_run.build_confirmed_mapping(
        "main.raw.header", reviewed_spec, "main.canon.wb", source_identifier_level="completion",
        api_padding="leave_null", source_crs="not_applicable", target_standard="osdu", write=False)
    assert res["manifest"]["canonical_rows"] == 3 and res["ppdm"] is None
    assert "Mapping result" in mapping_run.format_result(res)


def test_bad_output_prefix(patched, reviewed_spec):
    with pytest.raises(ValueError):
        mapping_run.build_confirmed_mapping("main.raw.header", reviewed_spec, "x;drop", source_identifier_level="well",
                                            api_padding="leave_null", source_crs="NAD27", target_standard="osdu",
                                            write=False)
