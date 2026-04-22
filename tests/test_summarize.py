from fastapi.testclient import TestClient


def test_summarize_with_current_and_previous_sql(client: TestClient) -> None:
    payload = {
        "previous_sql": "create table emp(id int);",
        "current_sql": "create table emp(id int, name varchar(100));"
    }
    response = client.post("/summarize", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert "result" in data
    assert "markdown" in data["result"]


def test_summarize_rejects_empty_payload(client: TestClient) -> None:
    response = client.post("/summarize", json={})
    assert response.status_code == 400
