"""Profiling and normalization on hand-built ParsedLas fixtures (no lasio needed)."""

import numpy as np
import pytest
from conftest import decisions, make_parsed

from las_core import DecisionRequired, IngestDecisions, normalize_las, profile_las
from mnemonics import family_of, resolve_unit


def test_family_aliases():
    assert family_of("RHOZ") == "RHOB"
    assert family_of("TNPH") == "NPHI"
    assert family_of("AT90") == "RT"
    assert family_of("GR:1") == "GR"
    assert family_of("XYZ") == "UNMAPPED"


def test_unit_resolution_rules():
    assert resolve_unit("RHOB", "K/M3") == ("g/cm3", 0.001)
    assert resolve_unit("NPHI", "PU") == ("v/v", 0.01)
    assert resolve_unit("DT", "US/M") == ("us/ft", 0.3048)
    assert resolve_unit("RHOB", "US/F") is None       # incompatible
    assert resolve_unit("NPHI", "") is None            # missing


def test_profile_flags_ambiguous_and_sentinels():
    prof = profile_las(make_parsed())
    status = {c.mnemonic: c for c in prof.curves}
    assert status["TNPH"].status == "ambiguous_unit"
    assert status["TNPH"].proposed_unit == "PU"        # median ~21 -> percent
    assert status["RHOZ"].status == "ok"
    assert status["GR"].n_sentinel == 1
    assert prof.api["status"] == "ok"
    needed = prof.decisions_needed()
    assert "unit_resolution[a.las::TNPH]" in needed and "sentinel_policy" in needed


def test_declared_unit_contradicted_by_values():
    p = make_parsed(curves=[("DEPT", "F"), ("NPHI", "V/V")], data=np.array([[1.0, 22.0], [2.0, 25.0], [3.0, 28.0]]))
    cp = profile_las(p).curves[0]
    assert cp.status == "implausible_range" and cp.proposed_unit == "PU"


def test_normalize_requires_unit_resolution():
    with pytest.raises(DecisionRequired, match="TNPH"):
        normalize_las(make_parsed(), decisions(unit_resolution={}))


def test_normalize_converts_units_and_sentinels():
    norm = normalize_las(make_parsed(), decisions())
    long = norm.long
    rhob = long[long.family == "RHOB"]["value"]
    nphi = long[long.family == "NPHI"]["value"]
    assert rhob.between(2.4, 2.5).all() and (long[long.family == "RHOB"]["unit"] == "g/cm3").all()
    assert nphi.max() == pytest.approx(0.24)
    gr = long[long.family == "GR"]
    assert -9999.0 not in gr["value"].to_list() and len(gr) == 3
    cat = norm.catalog.set_index("mnemonic")
    assert cat.loc["GR", "n_sentinel_replaced"] == 1


def test_header_null_only_keeps_sentinel():
    norm = normalize_las(make_parsed(), decisions(sentinel_policy="header_null_only"))
    assert -9999.0 in norm.long[norm.long.family == "GR"]["value"].to_list()


def test_depth_datum_and_unit_conversion():
    as_logged = normalize_las(make_parsed(), decisions()).long["depth"].min()
    gl = normalize_las(make_parsed(), decisions(depth_datum="GL")).long["depth"].min()
    assert as_logged == pytest.approx(5000.0)
    assert gl == pytest.approx(4975.0)                 # KB is 25 ft above GL
    metres = normalize_las(make_parsed(), decisions(depth_unit="m", depth_datum="GL")).long["depth"].min()
    assert metres == pytest.approx(4975.0 * 0.3048)


def test_datum_conversion_without_lmf_fails_clearly():
    from las_parse import HeaderItem

    p = make_parsed(well_extra={"LMF": HeaderItem("LMF", "", "", "")})
    with pytest.raises(ValueError, match="LMF"):
        normalize_las(p, decisions(depth_datum="GL"))


def test_api_leading_zero_needs_decision():
    p = make_parsed(api="512345678")
    with pytest.raises(DecisionRequired, match="api_zero_pad"):
        normalize_las(p, decisions(api_zero_pad=None))
    assert normalize_las(p, decisions()).header["api14"] == "05123456780000"


def test_family_conflict_policy():
    curves = [("DEPT", "F"), ("GR", "GAPI"), ("GR:1", "GAPI")]
    data = np.array([[1.0, 50.0, 51.0], [2.0, 60.0, 61.0]])
    p = make_parsed(curves=curves, data=data)
    assert profile_las(p).family_conflicts == {"GR": ["GR", "GR:1"]}
    first = normalize_las(p, decisions(family_conflict_policy="first_listed")).long
    assert set(first["mnemonic"]) == {"GR"}
    both = normalize_las(p, decisions()).long
    assert set(both["mnemonic"]) == {"GR", "GR:1"}


@pytest.mark.parametrize("missing", ["sentinel_policy", "depth_unit", "depth_datum", "family_conflict_policy",
                                     "unit_resolution"])
def test_decisions_are_required(missing):
    kw = dict(sentinel_policy="common_sentinels", depth_unit="ft", depth_datum="KB",
              family_conflict_policy="keep_all", unit_resolution={})
    kw.pop(missing)
    with pytest.raises(DecisionRequired):
        IngestDecisions.from_kwargs(**kw)


def test_unmapped_curve_kept_raw():
    p = make_parsed(curves=[("DEPT", "F"), ("XYZ", "WEIRD")], data=np.array([[1.0, 3.0], [2.0, 4.0]]))
    norm = normalize_las(p, decisions())
    assert set(norm.long["family"]) == {"UNMAPPED"} and set(norm.long["unit"]) == {"WEIRD"}
