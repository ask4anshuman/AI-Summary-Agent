# Purpose : CLI entry point for running SQL documentation generation locally without a GitHub webhook.
#           Reads .sql files from an input directory, runs the orchestrator on each file, and writes
#           JSON summaries to an output directory.
# Called by: `python -m src.local_batch` from the command line (manual / CI batch runs).
#            tests/test_orchestrator.py calls process_sql_directory() directly in unit tests.

import argparse
import json
from pathlib import Path

from src.agents.orchestrator import SQLDocumentationOrchestrator
from src.tools.llm_tools import LLMClient


def process_sql_directory(input_dir: Path, output_dir: Path) -> list[Path]:
    orchestrator = SQLDocumentationOrchestrator(llm_client=LLMClient())
    output_dir.mkdir(parents=True, exist_ok=True)

    written_files: list[Path] = []
    for sql_file in sorted(input_dir.glob("*.sql")):
        sql_text = sql_file.read_text(encoding="utf-8")
        result = orchestrator.run(current_sql=sql_text)

        output_path = output_dir / f"{sql_file.stem}.json"
        output_payload = {
            "input_file": sql_file.name,
            "llm_enabled": orchestrator.summarizer.llm_client.enabled,
            "result": result.model_dump(),
        }
        output_path.write_text(json.dumps(output_payload, indent=2), encoding="utf-8")
        written_files.append(output_path)

    return written_files


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Process local SQL samples and persist summaries.")
    parser.add_argument(
        "--input-dir",
        default="sample_input",
        help="Directory containing .sql files to summarize.",
    )
    parser.add_argument(
        "--output-dir",
        default="sample_output",
        help="Directory where natural-language summaries will be stored.",
    )
    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)

    if not input_dir.exists():
        raise FileNotFoundError(f"Input directory not found: {input_dir}")

    written_files = process_sql_directory(input_dir=input_dir, output_dir=output_dir)
    print(f"Processed {len(written_files)} SQL file(s) into {output_dir}")
    for path in written_files:
        print(path)


if __name__ == "__main__":
    main()