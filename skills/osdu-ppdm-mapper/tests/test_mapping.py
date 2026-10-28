"""Profile -> propose -> preview -> build contract."""

from __future__ import annotations

import copy

import pytest

from mapping_apply import DecisionRequired, build_canonical, preview_mapping
from mapping_spec import load_spec, propose_mapping, propose_value_map, spec_to_yaml
from osdu_records import to_osdu_records

DECISIONS = dict(source_identifier_level="completion", api_padding="leave_null",
                 source_crs="column:DATUM", target_standard="both")


def test_propose_maps_obvious_columns(header):
    spec = propose_mapping(header, "wellbore", "main.raw.header")
    f = spec["fields"]
    assert spec["status"] == "proposed"
    assert f["wellbore_uwi"]["source"] == "API_NO" and f["well_uwi"]["source"] == "API_NO"
    assert f["total_depth_md"]["source"] == "TD" and f["total_depth_md"]["uom"] is None
    assert spec["coordinates"] == {}  # wellbore entity has no surface coords
    assert "DATUM" in spec["datum_columns_in_source"]


def test_well_entity_proposes_coordinates(header):
    spec = propose_mapping(header, "well", "t")
    assert spec["coordinates"]["surface"] == {"lat": "SURF_LAT", "lon": "SURF_LONG", "crs": None}
    assert spec["fields"]["well_status"]["value_map"] == {"P&A": "PLUGGED_AND_ABANDONED", "PR": "PRODUCING",
                                                         "SI": "SHUT_IN"}


def test_value_map_leaves_unknown_values_null():
    import pandas as pd
    assert propose_value_map(pd.Series(["PR", "ZZZ"]), "status") == {"PR": "PRODUCING", "ZZZ": None}


def test_yaml_roundtrip(header):
    spec = propose_mapping(header, "well", "t")
    assert load_spec(spec_to_yaml(spec))["fields"].keys() == spec["fields"].keys()


def test_preview_lists_review_items(header):
    spec = propose_mapping(header, "wellbore", "t")
    rep = preview_mapping(header, spec)
    assert rep["depth_fields_missing_uom"] == ["total_depth_md"]
    assert rep["identifier_levels"]["wellbore_uwi"]["implied_level"] == "completion"
    assert rep["datum_values_in_source"]["DATUM"] == ["NAD27", "NAD83"]


def test_build_requires_reviewed_spec(header):
    spec = propose_mapping(header, "wellbore", "t")
    with pytest.raises(DecisionRequired, match="reviewed"):
        build_canonical(header, spec, **DECISIONS)


@pytest.mark.parametrize("missing", list(DECISIONS))
def test_build_requires_each_decision(header, reviewed_spec, missing):
    with pytest.raises(DecisionRequired, match=missing):
        build_canonical(header, reviewed_spec, **{**DECISIONS, missing: None})


def test_build_requires_depth_uom(header, reviewed_spec):
    spec = copy.deepcopy(reviewed_spec)
    spec["fields"]["total_depth_md"]["uom"] = None
    with pytest.raises(DecisionRequired, match="uom"):
        build_canonical(header, spec, **DECISIONS)


def test_declared_level_finer_than_data_fails(header, reviewed_spec):
    short = header.assign(API_NO=["4230112345"] * 5)
    with pytest.raises(ValueError, match="needs 14-digit"):
        build_canonical(short, reviewed_spec, **DECISIONS)


def test_build_wellbore_from_completion_rows(header, reviewed_spec):
    out = build_canonical(header, reviewed_spec, **DECISIONS)
    canon = out["canonical"].set_index("wellbore_uwi")
    # 5 completion rows -> 3 wellbores; the exact duplicate BROWN 3 rows collapse
    assert sorted(canon.index) == ["423011234500", "423011234601", "423011234700"]
    assert canon.loc["423011234601", "well_uwi"] == "4230112346"
    assert canon.loc["423011234500", "total_depth_md_uom"] == "ft"
    assert len(out["rejects"]) == 0
    assert set(out["lineage"]["canonical_field"]) >= {"wellbore_uwi", "well_uwi", "total_depth_md"}
    assert "WELL.UWI (wellbore component)" in out["ppdm"].columns


def test_conflicting_duplicates_rejected(header, reviewed_spec):
    conflict = header.assign(TD=[18500, 18600, 17900, 9800, 9800])
    out = build_canonical(conflict, reviewed_spec, **DECISIONS)
    assert set(out["rejects"]["reject_reason"]) == {"conflicting_duplicate"}
    assert "423011234500" not in set(out["canonical"]["wellbore_uwi"])


def test_padding_policy(header):
    spec = propose_mapping(header, "wellbore", "t")
    spec = {**spec, "status": "reviewed",
            "fields": {**spec["fields"], "total_depth_md": {**spec["fields"]["total_depth_md"], "uom": "ft"}}}
    ten = header.assign(API_NO=["4230112345", "4230112345", "4230112346", "4230112347", "4230112347"])
    left = build_canonical(ten, spec, **{**DECISIONS, "source_identifier_level": "well"})
    padded = build_canonical(ten, spec, **{**DECISIONS, "source_identifier_level": "well", "api_padding": "pad_zeros"})
    assert left["canonical"].empty and set(left["rejects"]["reject_reason"]) == {"null_wellbore_uwi;"}
    assert set(padded["canonical"]["wellbore_uwi"]) == {"423011234500", "423011234600", "423011234700"}


def test_per_row_datum_and_osdu_records(header):
    spec = propose_mapping(header, "well", "t")
    spec = {**spec, "status": "reviewed",
            "fields": {**spec["fields"], "elevation_value": {**spec["fields"]["elevation_value"], "source": None}}}
    out = build_canonical(header, spec, **{**DECISIONS, "source_identifier_level": "completion"})
    canon = out["canonical"].set_index("well_uwi")
    assert canon.loc["4230112345", "source_crs"] == "EPSG:4267"
    assert canon.loc["4230112347", "source_crs"] == "EPSG:4269"
    with pytest.raises(ValueError):
        to_osdu_records(out["canonical"], "well", kind="", namespace="ns", acl={}, legal={})
    recs = to_osdu_records(out["canonical"], "well", kind="osdu:wks:master-data--Well:1.2.0", namespace="opendes",
                           acl={"owners": ["o"], "viewers": ["v"]}, legal={"legaltags": ["t"]})
    first = recs[0]
    assert first["id"].startswith("opendes:master-data--Well:")
    crs = first["data"]["SpatialLocation"]["AsIngestedCoordinates"]["CoordinateReferenceSystemID"]
    assert crs in ("EPSG:4267", "EPSG:4269")
