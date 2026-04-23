from src.tools.repo_registry import RepoRegistryStore


def test_repo_registry_store_updates_yaml_without_dropping_existing_keys(tmp_path) -> None:
    config_file = tmp_path / "agent.yml"
    config_file.write_text(
        "\n".join(
            [
                "llm:",
                "  model: gpt-4o-mini",
                "confluence:",
                "  parent_page_id: \"123\"",
                "app:",
                "  repo_registry_file: config/agent.yml",
            ]
        ),
        encoding="utf-8",
    )

    store = RepoRegistryStore(str(config_file))
    store.upsert_repo("team/repo", {"repo": "team/repo", "github": {"owner": "team", "name": "repo"}})

    loaded = store.get_repo("team/repo")
    assert loaded is not None
    assert loaded["repo"] == "team/repo"

    full_text = config_file.read_text(encoding="utf-8")
    assert "llm:" in full_text
    assert "confluence:" in full_text
    assert "repos:" in full_text
