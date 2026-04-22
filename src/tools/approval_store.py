import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class ApprovalStateStore:
    def __init__(self, file_path: str) -> None:
        self._file_path = Path(file_path)

    def upsert_pr_analysis(
        self,
        owner: str,
        repo: str,
        pull_number: int,
        head_sha: str,
        modified_files: list[str],
        new_files: list[str],
        doc_payloads: list[dict[str, Any]],
    ) -> None:
        data = self._read_all()
        key = self._key(owner, repo, pull_number)
        previous = data["prs"].get(key, {})

        data["prs"][key] = {
            "owner": owner,
            "repo": repo,
            "pull_number": pull_number,
            "head_sha": head_sha,
            "modified_files": modified_files,
            "new_files": new_files,
            "doc_payloads": doc_payloads,
            "approval": previous.get("approval", {"approved": False}),
            "publication": previous.get("publication", {"published": False}),
            "updated_at": self._now_iso(),
        }
        self._write_all(data)

    def mark_approval(
        self,
        owner: str,
        repo: str,
        pull_number: int,
        approved: bool,
        source: str,
        actor: str,
        detail: str = "",
    ) -> None:
        data = self._read_all()
        key = self._key(owner, repo, pull_number)
        record = data["prs"].get(key)
        if record is None:
            record = {
                "owner": owner,
                "repo": repo,
                "pull_number": pull_number,
                "head_sha": "",
                "modified_files": [],
                "new_files": [],
                "doc_payloads": [],
                "approval": {"approved": False},
                "publication": {"published": False},
                "updated_at": self._now_iso(),
            }

        record["approval"] = {
            "approved": approved,
            "source": source,
            "actor": actor,
            "detail": detail,
            "updated_at": self._now_iso(),
        }
        record["updated_at"] = self._now_iso()

        data["prs"][key] = record
        self._write_all(data)

    def mark_publication(
        self,
        owner: str,
        repo: str,
        pull_number: int,
        published: bool,
        message: str,
        page_id: str = "",
        title: str = "",
    ) -> None:
        data = self._read_all()
        key = self._key(owner, repo, pull_number)
        record = data["prs"].get(key)
        if record is None:
            return

        record["publication"] = {
            "published": published,
            "message": message,
            "page_id": page_id,
            "title": title,
            "updated_at": self._now_iso(),
        }
        record["updated_at"] = self._now_iso()
        data["prs"][key] = record
        self._write_all(data)

    def get_pr_record(self, owner: str, repo: str, pull_number: int) -> dict[str, Any] | None:
        data = self._read_all()
        return data["prs"].get(self._key(owner, repo, pull_number))

    def _read_all(self) -> dict[str, Any]:
        if not self._file_path.exists():
            return {"prs": {}}

        try:
            payload = json.loads(self._file_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {"prs": {}}

        if not isinstance(payload, dict) or "prs" not in payload or not isinstance(payload["prs"], dict):
            return {"prs": {}}

        return payload

    def _write_all(self, payload: dict[str, Any]) -> None:
        self._file_path.parent.mkdir(parents=True, exist_ok=True)
        self._file_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    @staticmethod
    def _key(owner: str, repo: str, pull_number: int) -> str:
        return f"{owner}/{repo}#{pull_number}"

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()
