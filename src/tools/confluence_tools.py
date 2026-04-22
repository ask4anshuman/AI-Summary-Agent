from typing import Any

import requests


class ConfluencePublisher:
    def __init__(
        self,
        base_url: str,
        space_key: str,
        username: str,
        api_token: str,
        parent_page_id: str = "",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.space_key = space_key
        self.username = username
        self.api_token = api_token
        self.parent_page_id = parent_page_id

    @property
    def enabled(self) -> bool:
        return bool(self.base_url and self.space_key and self.username and self.api_token)

    def publish_pr_record(self, owner: str, repo: str, pull_number: int, record: dict[str, Any]) -> dict[str, Any]:
        if not self.enabled:
            return {"ok": False, "message": "Confluence publisher not configured"}

        title = f"{repo} PR-{pull_number} SQL Summary"
        body = self._build_page_body(owner=owner, repo=repo, pull_number=pull_number, record=record)

        existing = self._find_page_by_title(title)
        if existing is None:
            created = self._create_page(title=title, body=body)
            if not created:
                return {"ok": False, "message": "Failed to create Confluence page"}
            return {
                "ok": True,
                "message": "Confluence page created",
                "page_id": str(created.get("id", "")),
                "title": title,
            }

        updated = self._update_page(page=existing, title=title, body=body)
        if not updated:
            return {"ok": False, "message": "Failed to update Confluence page"}

        return {
            "ok": True,
            "message": "Confluence page updated",
            "page_id": str(existing.get("id", "")),
            "title": title,
        }

    def _build_page_body(self, owner: str, repo: str, pull_number: int, record: dict[str, Any]) -> str:
        approval = record.get("approval", {})
        modified_files = record.get("modified_files", [])
        new_files = record.get("new_files", [])
        doc_payloads = record.get("doc_payloads", [])

        sections: list[str] = [
            f"<h2>PR Context</h2>",
            f"<p><strong>Repository:</strong> {owner}/{repo}</p>",
            f"<p><strong>PR Number:</strong> {pull_number}</p>",
            f"<p><strong>Head SHA:</strong> {record.get('head_sha', '')}</p>",
            f"<p><strong>Approved:</strong> {approval.get('approved', False)}</p>",
            f"<p><strong>Approval Source:</strong> {approval.get('source', '')}</p>",
            f"<p><strong>Approval Actor:</strong> {approval.get('actor', '')}</p>",
            "<h2>Modified SQL Files</h2>",
            self._to_html_list([str(item) for item in modified_files]) or "<p>None</p>",
            "<h2>New SQL Files</h2>",
            self._to_html_list([str(item) for item in new_files]) or "<p>None</p>",
            "<h2>SQL Change Documentation</h2>",
        ]

        if not doc_payloads:
            sections.append("<p>No SQL documentation payload was captured.</p>")
            return "\n".join(sections)

        for payload in doc_payloads:
            filename = str(payload.get("filename", "unknown.sql"))
            summary = str(payload.get("summary", ""))
            change_type = str(payload.get("change_type", "UNKNOWN"))
            impact_level = str(payload.get("impact_level", "medium"))
            rationale = str(payload.get("rationale", ""))
            affected_objects = [str(item) for item in payload.get("affected_objects", [])]
            suggested_doc_updates = [str(item) for item in payload.get("suggested_doc_updates", [])]

            sections.append(f"<h3>{filename}</h3>")
            sections.append(f"<p><strong>Summary:</strong> {summary}</p>")
            sections.append(f"<p><strong>Change Type:</strong> {change_type}</p>")
            sections.append(f"<p><strong>Impact Level:</strong> {impact_level}</p>")
            sections.append(f"<p><strong>Rationale:</strong> {rationale}</p>")
            sections.append("<p><strong>Affected Objects:</strong></p>")
            sections.append(self._to_html_list(affected_objects) or "<p>None</p>")
            sections.append("<p><strong>Suggested Documentation Updates:</strong></p>")
            sections.append(self._to_html_list(suggested_doc_updates) or "<p>None</p>")

        return "\n".join(sections)

    @staticmethod
    def _to_html_list(items: list[str]) -> str:
        if not items:
            return ""
        rows = "".join(f"<li>{item}</li>" for item in items)
        return f"<ul>{rows}</ul>"

    def _find_page_by_title(self, title: str) -> dict[str, Any] | None:
        url = f"{self.base_url}/rest/api/content"
        params = {"spaceKey": self.space_key, "title": title, "expand": "version"}
        try:
            response = requests.get(url, params=params, auth=(self.username, self.api_token), timeout=20)
            response.raise_for_status()
        except requests.RequestException:
            return None

        payload = response.json()
        results = payload.get("results", []) if isinstance(payload, dict) else []
        if not results:
            return None
        return results[0]

    def _create_page(self, title: str, body: str) -> dict[str, Any] | None:
        url = f"{self.base_url}/rest/api/content"
        payload: dict[str, Any] = {
            "type": "page",
            "title": title,
            "space": {"key": self.space_key},
            "body": {"storage": {"value": body, "representation": "storage"}},
        }
        if self.parent_page_id:
            payload["ancestors"] = [{"id": self.parent_page_id}]

        try:
            response = requests.post(url, json=payload, auth=(self.username, self.api_token), timeout=20)
            response.raise_for_status()
        except requests.RequestException:
            return None

        parsed = response.json()
        return parsed if isinstance(parsed, dict) else None

    def _update_page(self, page: dict[str, Any], title: str, body: str) -> bool:
        page_id = str(page.get("id", ""))
        version_number = int(page.get("version", {}).get("number", 1))
        if not page_id:
            return False

        url = f"{self.base_url}/rest/api/content/{page_id}"
        payload = {
            "id": page_id,
            "type": "page",
            "title": title,
            "version": {"number": version_number + 1},
            "body": {"storage": {"value": body, "representation": "storage"}},
        }

        try:
            response = requests.put(url, json=payload, auth=(self.username, self.api_token), timeout=20)
            response.raise_for_status()
        except requests.RequestException:
            return False

        return True
