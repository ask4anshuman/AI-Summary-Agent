import difflib
from dataclasses import dataclass
from typing import Any

import requests


SQL_EXTENSIONS = {".sql", ".pls", ".pkb", ".pks", ".prc", ".fnc", ".trg"}


@dataclass(frozen=True)
class GithubPRSQLFileChange:
    filename: str
    status: str
    patch: str
    previous_filename: str = ""


def generate_unified_diff(previous_sql: str, current_sql: str, from_name: str = "previous.sql", to_name: str = "current.sql") -> str:
    previous_lines = previous_sql.splitlines(keepends=True)
    current_lines = current_sql.splitlines(keepends=True)
    diff = difflib.unified_diff(previous_lines, current_lines, fromfile=from_name, tofile=to_name)
    return "".join(diff)


def parse_sql_diff(diff_text: str) -> dict[str, list[str]]:
    added: list[str] = []
    removed: list[str] = []

    for line in diff_text.splitlines():
        if line.startswith("+++") or line.startswith("---") or line.startswith("@@"):
            continue
        if line.startswith("+"):
            added.append(line[1:])
        elif line.startswith("-"):
            removed.append(line[1:])

    return {"added": added, "removed": removed}


def _looks_like_sql_file(path: str) -> bool:
    path_lower = path.lower()
    return any(path_lower.endswith(ext) for ext in SQL_EXTENSIONS)


def extract_sql_patches_from_github_pr_files(pr_files_payload: list[dict[str, Any]]) -> list[str]:
    patches: list[str] = []
    for file_item in pr_files_payload:
        filename = file_item.get("filename", "")
        patch = file_item.get("patch", "")
        if _looks_like_sql_file(filename) and patch:
            patches.append(f"# File: {filename}\n{patch}")
    return patches


def extract_sql_file_changes_from_github_pr_files(pr_files_payload: list[dict[str, Any]]) -> list[GithubPRSQLFileChange]:
    changes: list[GithubPRSQLFileChange] = []
    for file_item in pr_files_payload:
        filename = str(file_item.get("filename", ""))
        previous_filename = str(file_item.get("previous_filename", ""))
        path_for_detection = filename or previous_filename
        if not _looks_like_sql_file(path_for_detection):
            continue

        changes.append(
            GithubPRSQLFileChange(
                filename=filename or previous_filename,
                status=str(file_item.get("status", "")).lower(),
                patch=str(file_item.get("patch", "")),
                previous_filename=previous_filename,
            )
        )

    return changes


def fetch_github_pr_sql_file_changes(
    api_base_url: str,
    token: str,
    owner: str,
    repo: str,
    pull_number: int,
    timeout: int = 20,
) -> list[GithubPRSQLFileChange]:
    url = f"{api_base_url.rstrip('/')}/repos/{owner}/{repo}/pulls/{pull_number}/files"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    response = requests.get(url, headers=headers, timeout=timeout)
    response.raise_for_status()
    files_payload = response.json()
    return extract_sql_file_changes_from_github_pr_files(files_payload)


def fetch_github_pr_sql_patches(
    api_base_url: str,
    token: str,
    owner: str,
    repo: str,
    pull_number: int,
    timeout: int = 20,
) -> list[str]:
    file_changes = fetch_github_pr_sql_file_changes(
        api_base_url=api_base_url,
        token=token,
        owner=owner,
        repo=repo,
        pull_number=pull_number,
        timeout=timeout,
    )
    return [f"# File: {change.filename}\n{change.patch}" for change in file_changes if change.patch]


def fetch_bitbucket_pr_sql_patches(api_base_url: str, token: str, pr_url: str, timeout: int = 20) -> list[str]:
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.get(pr_url, headers=headers, timeout=timeout)
    response.raise_for_status()
    payload = response.json()

    values = payload.get("values", [])
    patches: list[str] = []
    for item in values:
        old_path = item.get("old", {}).get("path", "")
        new_path = item.get("new", {}).get("path", "")
        path = new_path or old_path
        if not _looks_like_sql_file(path):
            continue

        diff_link = item.get("links", {}).get("diff", {}).get("href", "")
        if not diff_link:
            continue

        diff_resp = requests.get(diff_link, headers=headers, timeout=timeout)
        diff_resp.raise_for_status()
        patches.append(f"# File: {path}\n{diff_resp.text}")

    return patches
