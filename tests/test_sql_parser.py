from src.tools.sql_parser import (
    detect_change_type,
    extract_affected_objects,
    extract_filter_details,
    extract_join_details,
    extract_object_types,
    extract_table_details,
    estimate_impact_level,
)


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


def test_extract_publish_details() -> None:
    sql = """
    select e.id, d.name
    from hr.emp e
    inner join hr.dept d on e.dept_id = d.id
    where e.status = 'ACTIVE'
    having count(*) > 1;
    """

    assert "DML" in extract_object_types(sql)
    assert "hr.emp" in extract_table_details(sql)
    assert any("join hr.dept" in item.lower() for item in extract_join_details(sql))
    assert any(item.lower().startswith("where ") for item in extract_filter_details(sql))
