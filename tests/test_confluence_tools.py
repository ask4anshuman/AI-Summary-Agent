from src.tools.confluence_tools import ConfluencePublisher


def test_publish_pr_record_creates_one_page_per_payload() -> None:
    publisher = ConfluencePublisher(
        base_url="https://example.atlassian.net/wiki",
        space_key="SPACE",
        username="user@example.com",
        api_token="token",
        parent_page_id="1",
    )

    created: list[tuple[str, str]] = []
    publisher._find_page_by_title = lambda title: None  # type: ignore[attr-defined]
    publisher._create_page = lambda title, body, parent_page_id="": created.append((title, body, parent_page_id)) or {"id": f"id-{len(created)}"}  # type: ignore[attr-defined]

    record = {
        "doc_payloads": [
            {
                "filename": "dml/insert_sample.sql",
                "full_summary": "Insert summary",
                "sql_description": "Insert description",
                "object_types": ["DML"],
                "table_details": ["employees"],
                "join_details": [],
                "filter_details": ["where employee_id = 1004"],
                "affected_objects": ["employees"],
            },
            {
                "filename": "dml/update_sample.sql",
                "full_summary": "Update summary",
                "sql_description": "Update description",
                "object_types": ["DML"],
                "table_details": ["employees"],
                "join_details": [],
                "filter_details": ["where employee_id = 1001"],
                "affected_objects": ["employees"],
            },
        ]
    }

    result = publisher.publish_pr_record(owner="team", repo="repo", pull_number=10, record=record)

    assert result["ok"] is True
    assert result["message"] == "Confluence pages published: 2"
    assert len(created) == 2
    assert created[0][0] == "Technical Summary for - insert_sample.sql"
    assert created[1][0] == "Technical Summary for - update_sample.sql"
    assert created[0][2] == "1"


def test_build_file_page_body_contains_detailed_sql_sections() -> None:
    publisher = ConfluencePublisher(
        base_url="https://example.atlassian.net/wiki",
        space_key="SPACE",
        username="user@example.com",
        api_token="token",
    )

    body = publisher._build_file_page_body(  # type: ignore[attr-defined]
        {
            "full_summary": "This is a full summary",
            "sql_description": "This is a SQL description",
            "object_types": ["FUNCTION"],
            "table_details": ["employees"],
            "join_details": ["inner join departments on employees.department_id = departments.id"],
            "filter_details": ["where employees.status = 'ACTIVE'"],
            "affected_objects": ["employees", "departments"],
        }
    )

    assert "<h2>Full Summary</h2>" in body
    assert "<h2>SQL Description</h2>" in body
    assert "<h2>Object Types</h2>" in body
    assert "<h2>Table Details</h2>" in body
    assert "<h2>Join Details</h2>" in body
    assert "<h2>Filter Details</h2>" in body
    assert "<h2>Affected Objects</h2>" in body
    assert "This is a full summary" in body
    assert "This is a SQL description" in body


def test_build_file_page_body_adds_deleted_heading_when_present() -> None:
    publisher = ConfluencePublisher(
        base_url="https://example.atlassian.net/wiki",
        space_key="SPACE",
        username="user@example.com",
        api_token="token",
    )

    body = publisher._build_file_page_body(  # type: ignore[attr-defined]
        {
            "page_heading": "Code moved or deleted",
            "full_summary": "The SQL file was deleted in an approved PR.",
            "sql_description": "Code moved or deleted.",
            "object_types": [],
            "table_details": [],
            "join_details": [],
            "filter_details": [],
            "affected_objects": [],
        }
    )

    assert "<h1>Code moved or deleted</h1>" in body
    assert "The SQL file was deleted in an approved PR." in body


def test_publish_pr_record_returns_error_without_payloads() -> None:
    publisher = ConfluencePublisher(
        base_url="https://example.atlassian.net/wiki",
        space_key="SPACE",
        username="user@example.com",
        api_token="token",
    )

    result = publisher.publish_pr_record(owner="team", repo="repo", pull_number=10, record={"doc_payloads": []})

    assert result["ok"] is False
    assert result["message"] == "No SQL documentation payload was captured"
