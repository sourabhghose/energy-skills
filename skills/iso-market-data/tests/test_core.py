from datetime import date

import pandas as pd
import pytest

from iso_core import (DecisionRequired, from_hour_ending, from_utc, ground_nodes, interval_grid_report,
                      iso_convention, nerc_holidays, peak_mask)


def test_registry_has_all_isos_and_marks_status():
    for iso in ("CAISO", "ERCOT", "PJM", "MISO", "NYISO", "ISONE", "SPP"):
        c = iso_convention(iso)
        assert c["status"] == "verify_before_use" and c["timezone"]
    assert iso_convention("NYISO")["congestion_sign"] == -1
    assert iso_convention("MISO")["observes_dst"] is False
    with pytest.raises(DecisionRequired):
        iso_convention("AESO")


def test_ercot_repeated_hour_is_distinct(ercot):
    out = from_hour_ending(ercot, "America/Chicago", repeated_col="dst_flag", interval_col="interval",
                           interval_minutes=15)
    nov2 = out[(out.node == "HB_NORTH") & (out.date == "2025-11-02")]
    assert len(nov2) == 100  # 25 hours x 4 intervals
    assert nov2.interval_start_utc.is_unique
    rep = nov2[nov2.dst_flag == "Y"].interval_start_utc.min()
    first = nov2[(nov2.hour_ending == "02:00") & (nov2.dst_flag == "N")].interval_start_utc.min()
    assert rep - first == pd.Timedelta(hours=1)
    assert first == pd.Timestamp("2025-11-02T06:00:00Z")


def test_unflagged_repeated_hour_rejected(ercot):
    with pytest.raises(ValueError, match="repeated DST hour"):
        from_hour_ending(ercot.assign(dst_flag="N"), "America/Chicago", repeated_col="dst_flag",
                         interval_col="interval", interval_minutes=15)


def test_isone_02x_label():
    df = pd.DataFrame({"node": "H", "date": "2025-11-02", "hour_ending": ["01", "02", "02X", "03"], "lmp": 1.0})
    out = from_hour_ending(df, "America/New_York")
    assert out.interval_start_utc.is_unique and len(out) == 4


def test_spring_forward_nonexistent_hour_rejected():
    df = pd.DataFrame({"node": "H", "date": "2025-03-09", "hour_ending": ["02", "03"], "lmp": 1.0})
    with pytest.raises(ValueError, match="do not exist"):
        from_hour_ending(df, "America/Chicago")


def test_miso_est_has_no_dst():
    df = pd.DataFrame({"node": "M", "date": ["2025-07-01"], "hour_ending": ["1"], "lmp": 1.0})
    out = from_hour_ending(df, iso_convention("MISO")["timezone"])
    assert out.interval_start_utc.iloc[0] == pd.Timestamp("2025-07-01T05:00:00Z")


def test_interval_ending_shifts_start(pjm):
    beg = from_utc(pjm, "timestamp", "interval_beginning", 5)
    end = from_utc(pjm, "timestamp", "interval_ending", 5)
    assert (beg.interval_start_utc - end.interval_start_utc == pd.Timedelta(minutes=5)).all()
    with pytest.raises(DecisionRequired):
        from_utc(pjm, "timestamp", None, 5)


def test_grid_report_knows_25_hour_day(ercot):
    out = from_hour_ending(ercot, "America/Chicago", repeated_col="dst_flag", interval_col="interval",
                           interval_minutes=15)
    g = interval_grid_report(out, "America/Chicago").set_index(["node", "local_date"])
    assert g.loc[("HB_NORTH", date(2025, 11, 2)), "expected"] == 100
    assert g.complete.all()


def test_nerc_holidays_2027_christmas_saturday_not_moved():
    h = nerc_holidays(2027)
    assert date(2027, 12, 25) in h and date(2027, 12, 24) not in h and date(2027, 12, 27) not in h


def test_nerc_holidays_sunday_moves_to_monday():
    assert date(2023, 1, 2) in nerc_holidays(2023)  # Jan 1 2023 was a Sunday
    assert date(2025, 11, 27) in nerc_holidays(2025)  # Thanksgiving
    assert date(2025, 5, 26) in nerc_holidays(2025)   # Memorial Day


def test_peak_blocks_partition_the_week():
    hours = pd.Series(pd.date_range("2025-07-01", periods=24 * 14, freq="h", tz="UTC"))
    m = {b: peak_mask(hours, b, "America/New_York") for b in ("5x16", "2x16", "7x8")}
    total = m["5x16"].astype(int) + m["2x16"].astype(int) + m["7x8"].astype(int)
    assert (total == 1).all()
    assert m["5x16"].sum() == 16 * 9  # 10 weekdays minus July 4th
    july4_noon = pd.Timestamp("2025-07-04T16:00:00Z")
    assert not m["5x16"][hours == july4_noon].iloc[0] and m["2x16"][hours == july4_noon].iloc[0]


def test_ground_nodes_never_substitutes():
    g = ground_nodes(["HB_NORTH", "HB_NROTH"], ["HB_NORTH", "HB_SOUTH"])
    assert g["found"] == ["HB_NORTH"] and "HB_NORTH" in g["missing"]["HB_NROTH"]
