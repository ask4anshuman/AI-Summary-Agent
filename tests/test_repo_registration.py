from fastapi.testclient import TestClient

from src.api import routes


def test_register_get_delete_repo(client: TestClient) -> None:
    original_registry = routes.repo_registry

    class _MemRegistry:
        def __init__(self) -> None:
            self.data: dict[str, dict] = {}

        def upsert_repo(self, full_name: str, config: dict) -> dict:
            self.data[full_name] = config
            return config

        def get_repo(self, full_name: str):
            return self.data.get(full_name)

        def delete_repo(self, full_name: str) -> bool:
            return self.data.pop(full_name, None) is not None

    routes.repo_registry = _MemRegistry()

    payload = {
        "github": {
            "owner": "team",
            "name": "repo",
            "token": "gh-token",
            "api_base_url": "https://api.github.com",
            "webhook_secret": "secret",
            "approval_command": "/approve-sql-doc",
            "approval_label": "sql-doc-approved",
        },
        "llm": {
            "api_key": "",
            "base_url": "",
            "model": "gpt-4o-mini",
            "temperature": 0.1,
        },
        "confluence": {
            "base_url": "https://example.atlassian.net/wiki",
            "space": "SPACE",
            "username": "user@example.com",
            "api_token": "token",
            "default_parent_page_id": "123",
            "path_mappings": [
                {"sql_path_prefix": "dml/", "parent_page_id": "456"}
            ],
        },
    }

    try:
        register_resp = client.post("/repos/register", json=payload)
        assert register_resp.status_code == 200
        assert register_resp.json()["repo"] == "team/repo"

        get_resp = client.get("/repos/team/repo")
        assert get_resp.status_code == 200
        assert get_resp.json()["config"]["confluence"]["path_mappings"][0]["sql_path_prefix"] == "dml/"

        delete_resp = client.delete("/repos/team/repo")
        assert delete_resp.status_code == 200

        missing_resp = client.get("/repos/team/repo")
        assert missing_resp.status_code == 404
    finally:
        routes.repo_registry = original_registry
