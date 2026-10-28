import pytest

from ami_decisions import DecisionRequired
from ami_run import _select_sql, build_confirmed_vee


def test_select_sql_quotes_identifiers_and_samples_meters():
    sql = _select_sql("main.ami.reads", {"meter_id": "mtr", "read_ts": "ts", "value": "kwh",
                                         "quality": None}, 50)
    assert "`main`.`ami`.`reads`" in sql and "LIMIT 50" in sql and "quality" not in sql


@pytest.mark.parametrize("bad", ["main.ami", "main.ami.reads; DROP TABLE x", "a.b.c.d"])
def test_bad_table_names_are_rejected(bad):
    with pytest.raises(ValueError):
        _select_sql(bad, {"meter_id": "m", "read_ts": "t", "value": "v"}, None)


def test_build_refuses_before_touching_spark_when_a_decision_is_missing():
    with pytest.raises(DecisionRequired, match="interval_minutes"):
        build_confirmed_vee("main.ami.reads", "main.ami.vee")
