from src.tools.sql_parser import detect_change_type, extract_affected_objects, estimate_impact_level


def test_detect_change_type_mixed() -> None:
    sql = "create table t1(id int); update t1 set id = 2;"
    result = detect_change_type(sql)
    assert "DDL" in result
    assert "DML" in result


def test_extract_affected_objects() -> None:
    sql = "create table hr.emp(id int); update hr.emp set id = 1;"
    objects = extract_affected_objects(sql)
    assert "hr.emp" in objects


def test_estimate_impact_level_high() -> None:
    sql = "drop table hr.emp;"
    impact = estimate_impact_level(sql, ["hr.emp"])
    assert impact == "high"
