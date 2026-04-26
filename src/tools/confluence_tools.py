# Purpose : Confluence REST API client. Creates and updates Confluence pages with SQL documentation,
#           searches for existing pages by title, resolves the target parent page using per-repo
#           folder-to-page path mappings (longest-prefix match), and returns page URLs.
# Called by: src/api/routes.py (_build_runtime_config constructs ConfluencePublisher per request;
#            used in _handle_github_pull_request_event for publish-on-merge).

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
        path_mappings: list[dict[str, str]] | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.space_key = space_key
        self.username = username
        self.api_token = api_token
        self.parent_page_id = parent_page_id
        self.path_mappings = sorted(
            [
                {
                    "sql_path_prefix": str(item.get("sql_path_prefix", "")).strip().lstrip("/"),
                    "parent_page_id": str(item.get("parent_page_id", "")).strip(),
                }
                for item in (path_mappings or [])
                if str(item.get("sql_path_prefix", "")).strip() and str(item.get("parent_page_id", "")).strip()
            ],
            key=lambda item: len(item["sql_path_prefix"]),
            reverse=True,
        )

    @property
    def enabled(self) -> bool:
        return bool(self.base_url and self.space_key and self.username and self.api_token)

    def find_page_for_filename(self, filename: str) -> dict[str, str] | None:
        title = self._build_file_page_title(repo="", pull_number=0, payload={"filename": filename})
        page = self._find_page_by_title(title)
        if page is None:
            return None

        page_id = str(page.get("id", ""))
        return {
            "filename": filename,
            "title": title,
            "page_id": page_id,
            "url": self._build_page_url(page_id),
        }

    def publish_pr_record(self, owner: str, repo: str, pull_number: int, record: dict[str, Any]) -> dict[str, Any]:
        if not self.enabled:
            return {"ok": False, "message": "Confluence publisher not configured"}

        doc_payloads = record.get("doc_payloads", [])
        if not doc_payloads:
            return {"ok": False, "message": "No SQL documentation payload was captured"}

        published_pages: list[dict[str, str]] = []
        for payload in doc_payloads:
            filename = str(payload.get("filename", "unknown.sql"))
            title = self._build_file_page_title(repo=repo, pull_number=pull_number, payload=payload)
            body = self._build_file_page_body(payload=payload)
            target_parent_page_id = self._resolve_parent_page_id(filename)

            existing = self._find_page_by_title(title)
            if existing is None:
                created = self._create_page(title=title, body=body, parent_page_id=target_parent_page_id)
                if not created:
                    return {"ok": False, "message": f"Failed to create Confluence page for {title}"}
                page_id = str(created.get("id", ""))
                published_pages.append({
                    "filename": filename,
                    "page_id": page_id,
                    "title": title,
                    "url": self._build_page_url(page_id),
                })
                continue

            updated = self._update_page(page=existing, title=title, body=body, parent_page_id=target_parent_page_id)
            if not updated:
                return {"ok": False, "message": f"Failed to update Confluence page for {title}"}
            page_id = str(existing.get("id", ""))
            published_pages.append({
                "filename": filename,
                "page_id": page_id,
                "title": title,
                "url": self._build_page_url(page_id),
            })

        primary = published_pages[0] if published_pages else {"page_id": "", "title": ""}
        return {
            "ok": True,
            "message": f"Confluence pages published: {len(published_pages)}",
            "page_id": primary["page_id"],
            "title": primary["title"],
            "pages": published_pages,
        }

    def _build_file_page_title(self, repo: str, pull_number: int, payload: dict[str, Any]) -> str:
        filename = str(payload.get("filename", "unknown.sql"))
        base_name = filename.split("/")[-1].split("\\")[-1]
        return f"Technical Summary for - {base_name}"

    def _build_page_url(self, page_id: str) -> str:
        if not page_id:
            return ""
        return f"{self.base_url}/pages/viewpage.action?pageId={page_id}"

    def _resolve_parent_page_id(self, filename: str) -> str:
        normalized = filename.strip().lstrip("/")
        for mapping in self.path_mappings:
            prefix = mapping["sql_path_prefix"]
            if normalized.startswith(prefix):
                return mapping["parent_page_id"]
        return self.parent_page_id

    def _build_file_page_body(self, payload: dict[str, Any]) -> str:
        page_heading = str(payload.get("page_heading", "")).strip()
        full_summary = str(payload.get("full_summary", "")).strip() or "No summary generated."
        sql_description = str(payload.get("sql_description", "")).strip() or "No SQL description generated."
        object_types = [str(item) for item in payload.get("object_types", [])]
        table_details = [str(item) for item in payload.get("table_details", [])]
        join_details = [str(item) for item in payload.get("join_details", [])]
        filter_details = [str(item) for item in payload.get("filter_details", [])]
        affected_objects = [str(item) for item in payload.get("affected_objects", [])]

        sections: list[str] = []
        if page_heading:
            sections.extend([f"<h1>{page_heading}</h1>", f"<p>{sql_description}</p>"])

        sections.extend(
            [
                "<h2>Full Summary</h2>",
                f"<p>{full_summary}</p>",
                "<h2>SQL Description</h2>",
                f"<p>{sql_description}</p>",
            ]
        )

        if object_types:
            sections.extend(["<h2>Object Types</h2>", self._to_html_list(object_types)])
        if table_details:
            sections.extend(["<h2>Table Details</h2>", self._to_html_list(table_details)])
        if join_details:
            sections.extend(["<h2>Join Details</h2>", self._to_html_list(join_details)])
        if filter_details:
            sections.extend(["<h2>Filter Details</h2>", self._to_html_list(filter_details)])
        if affected_objects:
            sections.extend(["<h2>Affected Objects</h2>", self._to_html_list(affected_objects)])

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

    def _create_page(self, title: str, body: str, parent_page_id: str = "") -> dict[str, Any] | None:
        url = f"{self.base_url}/rest/api/content"
        payload: dict[str, Any] = {
            "type": "page",
            "title": title,
            "space": {"key": self.space_key},
            "body": {"storage": {"value": body, "representation": "storage"}},
        }
        ancestor_id = parent_page_id or self.parent_page_id
        if ancestor_id:
            payload["ancestors"] = [{"id": ancestor_id}]

        try:
            response = requests.post(url, json=payload, auth=(self.username, self.api_token), timeout=20)
            response.raise_for_status()
        except requests.RequestException:
            return None

        parsed = response.json()
        return parsed if isinstance(parsed, dict) else None

    def _update_page(self, page: dict[str, Any], title: str, body: str, parent_page_id: str = "") -> bool:
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
        ancestor_id = parent_page_id or self.parent_page_id
        if ancestor_id:
            payload["ancestors"] = [{"id": ancestor_id}]

        try:
            response = requests.put(url, json=payload, auth=(self.username, self.api_token), timeout=20)
            response.raise_for_status()
        except requests.RequestException:
            return False

        return True
