from src.tools.config_loader import get_nested_config_value, load_yaml_config


def test_load_yaml_config_returns_mapping(tmp_path) -> None:
    cfg = tmp_path / "agent.yml"
    cfg.write_text(
        """
llm:
  model: gpt-4o-mini
github:
  approval:
    command: /approve-sql-doc
confluence:
  space: DATA
""".strip(),
        encoding="utf-8",
    )

    loaded = load_yaml_config(str(cfg))

    assert loaded["llm"]["model"] == "gpt-4o-mini"
    assert loaded["github"]["approval"]["command"] == "/approve-sql-doc"
    assert loaded["confluence"]["space"] == "DATA"


def test_get_nested_config_value_reads_dotted_paths() -> None:
    config = {
        "llm": {"temperature": 0.2, "pr_summary_max_chars": 250},
        "github": {"approval": {"label": "sql-doc-approved"}},
    }

    assert get_nested_config_value(config, "llm.temperature", 0.1) == 0.2
    assert get_nested_config_value(config, "llm.pr_summary_max_chars", 280) == 250
    assert get_nested_config_value(config, "github.approval.label", "") == "sql-doc-approved"
    assert get_nested_config_value(config, "confluence.space", "DATA") == "DATA"
