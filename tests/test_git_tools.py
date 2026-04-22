from src.tools.git_tools import extract_sql_file_changes_from_github_pr_files, generate_unified_diff, parse_sql_diff


def test_generate_and_parse_diff() -> None:
    previous_sql = "create table t(id int);\n"
    current_sql = "create table t(id int, name varchar(30));\n"
    diff = generate_unified_diff(previous_sql, current_sql)
    parts = parse_sql_diff(diff)
    assert isinstance(parts["added"], list)
    assert isinstance(parts["removed"], list)
    assert any("name" in line for line in parts["added"])


def test_extract_sql_file_changes_from_github_pr_files_filters_and_classifies() -> None:
    payload = [
        {"filename": "db/changed.sql", "status": "modified", "patch": "@@ -1 +1 @@\n-select 1\n+select 2"},
        {"filename": "db/new_file.sql", "status": "added", "patch": "@@ -0,0 +1 @@\n+create table demo(id int);"},
        {"filename": "docs/readme.md", "status": "modified", "patch": "@@ -1 +1 @@"},
    ]

    changes = extract_sql_file_changes_from_github_pr_files(payload)

    assert [change.filename for change in changes] == ["db/changed.sql", "db/new_file.sql"]
    assert [change.status for change in changes] == ["modified", "added"]
