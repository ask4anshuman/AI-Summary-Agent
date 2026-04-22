from src.agents.orchestrator import SQLDocumentationOrchestrator
from src.local_batch import process_sql_directory


def test_orchestrator_run_returns_agent_result() -> None:
    orch = SQLDocumentationOrchestrator()
    result = orch.run(
        previous_sql="create table dept(id int);",
        current_sql="create table dept(id int, name varchar(50));"
    )
    assert result.summary
    assert result.change_type
    assert result.impact_level
    assert isinstance(result.affected_objects, list)
    assert isinstance(result.suggested_doc_updates, list)
    assert result.markdown.startswith("## SQL Change Summary")


def test_process_sql_directory_writes_output_files(tmp_path) -> None:
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    (input_dir / "sample.sql").write_text("create table demo(id int);", encoding="utf-8")

    written_files = process_sql_directory(input_dir=input_dir, output_dir=output_dir)

    assert len(written_files) == 1
    output_text = written_files[0].read_text(encoding="utf-8")
    assert '"input_file": "sample.sql"' in output_text
    assert '"summary":' in output_text
