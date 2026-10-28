"""Wide pivot with run-overlap policy, and the pure batch used by the runner."""

import numpy as np
import pandas as pd
import pytest
from conftest import decisions, make_parsed

from las_run import ingest_parsed
from las_wide import to_wide


def _two_runs():
    early = make_parsed(source="run1.las", log_date="2023-01-10", curves=[("DEPT", "F"), ("GR", "GAPI")],
                        data=np.array([[5000.0, 40.0], [5000.5, 41.0], [5001.0, 42.0]]))
    late = make_parsed(source="run2.las", log_date="2024-06-01", curves=[("DEPT", "F"), ("GR", "GAPI")],
                       data=np.array([[5001.0, 90.0], [5001.5, 91.0]]))
    return [early, late]


def test_overlap_policy_latest_vs_earliest():
    headers, _, long, errors = ingest_parsed(_two_runs(), decisions())
    assert errors == {}
    latest = to_wide(long, headers, "prefer_latest_run", 0.5).set_index("depth")["gr_gapi"]
    earliest = to_wide(long, headers, "prefer_earliest_run", 0.5).set_index("depth")["gr_gapi"]
    assert latest[5001.0] == 90.0 and earliest[5001.0] == 42.0
    assert latest[5000.0] == 40.0 and latest[5001.5] == 91.0


def test_skip_wide_and_invalid_policy():
    headers, _, long, _ = ingest_parsed(_two_runs(), decisions())
    assert to_wide(long, headers, "skip_wide", 0.5).empty
    with pytest.raises(ValueError):
        to_wide(long, headers, "average", 0.5)


def test_batch_skips_file_with_datum_problem():
    from las_parse import HeaderItem

    bad = make_parsed(source="bad.las", well_extra={"LMF": HeaderItem("LMF", "", "", "")})
    headers, _, _, errors = ingest_parsed([make_parsed(), bad], decisions(depth_datum="GL"))
    assert list(headers["source_file"]) == ["a.las"]
    assert "bad.las" in errors


def test_wide_has_unit_suffixes():
    headers, _, long, _ = ingest_parsed([make_parsed()], decisions())
    wide = to_wide(long, headers, "prefer_latest_run", 0.5)
    assert {"gr_gapi", "rhob_gcc", "nphi_vv", "rt_ohmm"} <= set(wide.columns)
    assert isinstance(wide, pd.DataFrame)
