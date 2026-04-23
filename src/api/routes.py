import hashlib
import hmac
import json
import re
from dataclasses import dataclass
from typing import Any

import requests
from fastapi import APIRouter, HTTPException, Request

from src.agents.orchestrator import SQLDocumentationOrchestrator
from src.config import settings
from src.models import (
    PRFileDocPayload,
    PublishedSQLDocPayload,
    RepoRegistrationRequest,
    RepoRegistrationResponse,
    SummarizeRequest,
    SummarizeResponse,
    WebhookResponse,
)
from src.tools.repo_registry import RepoRegistryStore
from src.tools.confluence_tools import ConfluencePublisher
from src.tools.git_tools import (
    GithubPRSQLFileChange,
    fetch_bitbucket_pr_sql_patches,
    fetch_github_file_content,
    fetch_github_file_content_with_sha,
    fetch_github_pr_sql_file_changes,
    update_github_file_content,
)
from src.tools.llm_tools import LLMClient, build_publish_doc_prompt
from src.tools.approval_store import ApprovalStateStore
from src.tools.sql_parser import (
    detect_change_type,
    extract_affected_objects,
    extract_filter_details,
    extract_join_details,
    extract_object_types,
    extract_table_details,
)

router = APIRouter()
orchestrator = SQLDocumentationOrchestrator()
publish_llm_client = LLMClient()
approval_store = ApprovalStateStore(settings.approval_state_file)
repo_registry = RepoRegistryStore(settings.repo_registry_file)
confluence_publisher = ConfluencePublisher(
    base_url=settings.confluence_base_url,
    space_key=settings.confluence_space,
    username=settings.confluence_username,
    api_token=settings.confluence_api_token,
    parent_page_id=settings.confluence_parent_page_id,
)
STICKY_PR_COMMENT_MARKER = "<!-- ai-sql-summary-agent:sticky-pr-summary -->"


@dataclass(frozen=True)
class RuntimeConfig:
    github_api_base_url: str
    github_token: str
    github_webhook_secret: str
    github_approval_command: str
    github_approval_label: str
    confluence: ConfluencePublisher


def _default_runtime_config() -> RuntimeConfig:
    return RuntimeConfig(
        github_api_base_url=settings.github_api_base_url,
        github_token=settings.github_token,
        github_webhook_secret=settings.github_webhook_secret,
        github_approval_command=settings.github_approval_command,
        github_approval_label=settings.github_approval_label,
        confluence=confluence_publisher,
    )


def _build_runtime_config(payload: dict[str, Any]) -> RuntimeConfig:
    runtime = _default_runtime_config()
    repository = payload.get("repository", {})
    full_name = str(repository.get("full_name", "")).strip().lower()
    if not full_name or "/" not in full_name:
        return runtime

    repo_config = repo_registry.get_repo(full_name)
    if not repo_config:
        return runtime

    github_cfg = repo_config.get("github", {}) if isinstance(repo_config.get("github", {}), dict) else {}
    confluence_cfg = repo_config.get("confluence", {}) if isinstance(repo_config.get("confluence", {}), dict) else {}

    confluence_runtime = ConfluencePublisher(
        base_url=str(confluence_cfg.get("base_url", runtime.confluence.base_url)).strip(),
        space_key=str(confluence_cfg.get("space", runtime.confluence.space_key)).strip(),
        username=str(confluence_cfg.get("username", runtime.confluence.username)).strip(),
        api_token=str(confluence_cfg.get("api_token", runtime.confluence.api_token)).strip(),
        parent_page_id=str(confluence_cfg.get("default_parent_page_id", runtime.confluence.parent_page_id)).strip(),
        path_mappings=confluence_cfg.get("path_mappings", []) if isinstance(confluence_cfg.get("path_mappings", []), list) else [],
    )

    return RuntimeConfig(
        github_api_base_url=str(github_cfg.get("api_base_url", runtime.github_api_base_url)).strip(),
        github_token=str(github_cfg.get("token", runtime.github_token)).strip(),
        github_webhook_secret=str(github_cfg.get("webhook_secret", runtime.github_webhook_secret)).strip(),
        github_approval_command=str(github_cfg.get("approval_command", runtime.github_approval_command)).strip() or runtime.github_approval_command,
        github_approval_label=str(github_cfg.get("approval_label", runtime.github_approval_label)).strip() or runtime.github_approval_label,
        confluence=confluence_runtime,
    )


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/repos/register", response_model=RepoRegistrationResponse)
def register_repo(request: RepoRegistrationRequest) -> RepoRegistrationResponse:
    owner = request.github.owner.strip()
    name = request.github.name.strip()
    if not owner or not name:
        raise HTTPException(status_code=400, detail="github.owner and github.name are required")

    full_name = f"{owner}/{name}".lower()
    record = {
        "repo": full_name,
        "github": {
            "owner": owner,
            "name": name,
            "token": request.github.token,
            "api_base_url": request.github.api_base_url,
            "webhook_secret": request.github.webhook_secret,
            "approval_command": request.github.approval_command,
            "approval_label": request.github.approval_label,
        },
        "llm": request.llm.model_dump(),
        "confluence": {
            "base_url": request.confluence.base_url,
            "space": request.confluence.space,
            "username": request.confluence.username,
            "api_token": request.confluence.api_token,
            "default_parent_page_id": request.confluence.default_parent_page_id,
            "path_mappings": [item.model_dump() for item in request.confluence.path_mappings],
        },
    }
    repo_registry.upsert_repo(full_name, record)
    return RepoRegistrationResponse(ok=True, message="Repository registered", repo=full_name)


@router.get("/repos/{owner}/{repo}")
def get_repo_registration(owner: str, repo: str) -> dict[str, Any]:
    full_name = f"{owner}/{repo}".lower()
    record = repo_registry.get_repo(full_name)
    if not record:
        raise HTTPException(status_code=404, detail="Repository registration not found")
    return {"ok": True, "repo": full_name, "config": record}


@router.put("/repos/{owner}/{repo}", response_model=RepoRegistrationResponse)
def update_repo_registration(owner: str, repo: str, request: RepoRegistrationRequest) -> RepoRegistrationResponse:
    full_name = f"{owner}/{repo}".lower()
    existing = repo_registry.get_repo(full_name)
    if not existing:
        raise HTTPException(status_code=404, detail="Repository registration not found")
    requested_full_name = f"{request.github.owner.strip()}/{request.github.name.strip()}".lower()
    if requested_full_name != full_name:
        raise HTTPException(status_code=400, detail="Path owner/repo must match payload github.owner/github.name")
    return register_repo(request)


@router.delete("/repos/{owner}/{repo}")
def delete_repo_registration(owner: str, repo: str) -> dict[str, Any]:
    full_name = f"{owner}/{repo}".lower()
    deleted = repo_registry.delete_repo(full_name)
    if not deleted:
        raise HTTPException(status_code=404, detail="Repository registration not found")
    return {"ok": True, "message": "Repository registration deleted", "repo": full_name}


@router.post("/summarize", response_model=SummarizeResponse)
def summarize_sql(request: SummarizeRequest) -> SummarizeResponse:
    if not request.diff and not request.current_sql and not request.previous_sql:
        raise HTTPException(status_code=400, detail="Provide at least one of diff, current_sql, or previous_sql")

    result = orchestrator.run(previous_sql=request.previous_sql, current_sql=request.current_sql, diff=request.diff)
    return SummarizeResponse(result=result)


@router.post("/github-webhook", response_model=WebhookResponse)
async def github_webhook(request: Request) -> WebhookResponse:
    raw_body = await request.body()
    try:
        payload = json.loads(raw_body.decode("utf-8") or "{}")
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON payload") from exc

    runtime = _build_runtime_config(payload)
    _validate_github_signature(request=request, raw_body=raw_body, webhook_secret=runtime.github_webhook_secret)

    event_name = request.headers.get("X-GitHub-Event", "pull_request")

    if event_name == "pull_request":
        return _handle_github_pull_request_event(payload, runtime=runtime)
    if event_name == "issue_comment":
        return _handle_github_issue_comment_event(payload, runtime=runtime)
    if event_name == "pull_request_review":
        return _handle_github_pull_request_review_event(payload, runtime=runtime)

    return WebhookResponse(ok=True, message=f"Ignored GitHub event: {event_name}")


def _handle_github_pull_request_event(payload: dict[str, Any], runtime: RuntimeConfig | None = None) -> WebhookResponse:
    runtime = runtime or _default_runtime_config()
    action = str(payload.get("action", ""))
    owner, repo, pull_number = _extract_github_pr_identity(payload)

    if action == "closed":
        return _handle_github_pull_request_merge(payload=payload, owner=owner, repo=repo, pull_number=pull_number, runtime=runtime)

    if action in {"labeled", "unlabeled"}:
        label_name = str(payload.get("label", {}).get("name", "")).strip().lower()
        target_label = runtime.github_approval_label.strip().lower()
        if label_name == target_label:
            approved = action == "labeled"
            approval_store.mark_approval(
                owner=owner,
                repo=repo,
                pull_number=pull_number,
                approved=approved,
                source="label",
                actor=_extract_github_actor(payload),
                detail=label_name,
            )
            state = "approved" if approved else "revoked"
            return WebhookResponse(ok=True, message=f"Approval {state} via PR label")

    if action not in {"opened", "synchronize", "reopened"}:
        return WebhookResponse(ok=True, message=f"Ignored GitHub action: {action}")

    sql_changes: list[GithubPRSQLFileChange] = []
    if runtime.github_api_base_url and runtime.github_token:
        sql_changes = fetch_github_pr_sql_file_changes(
            api_base_url=runtime.github_api_base_url,
            token=runtime.github_token,
            owner=owner,
            repo=repo,
            pull_number=pull_number,
        )

    if not sql_changes:
        return WebhookResponse(ok=True, message="No SQL changes found in GitHub PR")

    comment_markdown, doc_payloads = _build_github_pr_summary_comment(sql_changes, confluence=runtime.confluence)
    _store_pr_analysis(payload=payload, owner=owner, repo=repo, pull_number=pull_number, sql_changes=sql_changes, doc_payloads=doc_payloads)

    if not comment_markdown:
        return WebhookResponse(ok=True, message="No commentable SQL changes found in GitHub PR")

    _upsert_github_pr_comment(
        owner=owner,
        repo=repo,
        pull_number=pull_number,
        markdown=comment_markdown,
        api_base_url=runtime.github_api_base_url,
        token=runtime.github_token,
    )
    return WebhookResponse(ok=True, message="GitHub webhook processed", markdown=comment_markdown)


def _handle_github_pull_request_merge(
    payload: dict[str, Any],
    owner: str,
    repo: str,
    pull_number: int,
    runtime: RuntimeConfig | None = None,
) -> WebhookResponse:
    runtime = runtime or _default_runtime_config()
    pull_request = payload.get("pull_request", {})
    merged = bool(pull_request.get("merged", False))
    if not merged:
        return WebhookResponse(ok=True, message="PR closed without merge; publish skipped")

    record = approval_store.get_pr_record(owner=owner, repo=repo, pull_number=pull_number)
    if not record:
        return WebhookResponse(ok=True, message="No stored PR analysis found; publish skipped")

    approval = record.get("approval", {})
    if not bool(approval.get("approved", False)):
        return WebhookResponse(ok=True, message="PR merged without approval; publish skipped")

    merged_head_sha = str(pull_request.get("head", {}).get("sha", ""))
    analyzed_head_sha = str(record.get("head_sha", ""))
    if analyzed_head_sha and merged_head_sha and analyzed_head_sha != merged_head_sha:
        return WebhookResponse(
            ok=True,
            message="PR merged but analyzed SHA does not match final PR SHA; publish skipped",
        )

    publish_record = _build_publish_record_from_merged_sql(payload=payload, owner=owner, repo=repo, record=record, runtime=runtime)

    publish_result = runtime.confluence.publish_pr_record(
        owner=owner,
        repo=repo,
        pull_number=pull_number,
        record=publish_record,
    )
    _sync_confluence_links_into_sql_files(
        payload=payload,
        owner=owner,
        repo=repo,
        record=record,
        publication_pages=publish_result.get("pages", []),
        confluence=runtime.confluence,
        runtime=runtime,
    )
    approval_store.mark_publication(
        owner=owner,
        repo=repo,
        pull_number=pull_number,
        published=bool(publish_result.get("ok", False)),
        message=str(publish_result.get("message", "")),
        page_id=str(publish_result.get("page_id", "")),
        title=str(publish_result.get("title", "")),
        pages=publish_result.get("pages", []),
    )
    _refresh_pr_comment_after_publication(owner=owner, repo=repo, pull_number=pull_number, runtime=runtime)
    return WebhookResponse(ok=True, message=str(publish_result.get("message", "Confluence publish attempted")))


def _handle_github_issue_comment_event(payload: dict[str, Any], runtime: RuntimeConfig | None = None) -> WebhookResponse:
    runtime = runtime or _default_runtime_config()
    issue = payload.get("issue", {})
    if "pull_request" not in issue:
        return WebhookResponse(ok=True, message="Ignored issue comment outside pull request")

    owner, repo, pull_number = _extract_github_issue_identity(payload)
    action = str(payload.get("action", ""))
    if action not in {"created", "edited"}:
        return WebhookResponse(ok=True, message=f"Ignored issue_comment action: {action}")

    body = str(payload.get("comment", {}).get("body", "")).strip().lower()
    command = runtime.github_approval_command.strip().lower()
    if command and command in body:
        approval_store.mark_approval(
            owner=owner,
            repo=repo,
            pull_number=pull_number,
            approved=True,
            source="command",
            actor=_extract_github_actor(payload),
            detail=command,
        )
        return WebhookResponse(ok=True, message="Approval recorded from PR comment command")

    return WebhookResponse(ok=True, message="No approval command detected in PR comment")


def _handle_github_pull_request_review_event(payload: dict[str, Any], runtime: RuntimeConfig | None = None) -> WebhookResponse:
    _ = runtime or _default_runtime_config()
    action = str(payload.get("action", ""))
    if action != "submitted":
        return WebhookResponse(ok=True, message=f"Ignored pull_request_review action: {action}")

    state = str(payload.get("review", {}).get("state", "")).strip().lower()
    if state not in {"approved", "changes_requested"}:
        return WebhookResponse(ok=True, message=f"Ignored pull_request_review state: {state}")

    owner, repo, pull_number = _extract_github_pr_identity(payload)
    approval_store.mark_approval(
        owner=owner,
        repo=repo,
        pull_number=pull_number,
        approved=state == "approved",
        source="review",
        actor=_extract_github_actor(payload),
        detail=state,
    )
    return WebhookResponse(ok=True, message="Approval state updated from PR review")


@router.post("/bitbucket-webhook", response_model=WebhookResponse)
def bitbucket_webhook(payload: dict[str, Any]) -> WebhookResponse:
    pull_request = payload.get("pullrequest", {})
    links = pull_request.get("links", {})
    diff_url = links.get("diff", {}).get("href", "")

    patches: list[str] = []
    if diff_url and settings.bitbucket_token:
        patches = fetch_bitbucket_pr_sql_patches(
            api_base_url=settings.bitbucket_api_base_url,
            token=settings.bitbucket_token,
            pr_url=diff_url,
        )

    if not patches:
        return WebhookResponse(ok=True, message="No SQL changes found in Bitbucket PR")

    combined_diff = "\n\n".join(patches)
    result = orchestrator.run(diff=combined_diff)

    _post_bitbucket_pr_comment(payload=payload, markdown=result.markdown)
    return WebhookResponse(ok=True, message="Bitbucket webhook processed", markdown=result.markdown)


@router.post("/demo")
async def demo_from_raw_request(request: Request) -> dict[str, Any]:
    payload = await request.json()
    previous_sql = str(payload.get("previous_sql", ""))
    current_sql = str(payload.get("current_sql", ""))
    diff = str(payload.get("diff", ""))

    result = orchestrator.run(previous_sql=previous_sql, current_sql=current_sql, diff=diff)
    return {"ok": True, "markdown": result.markdown, "result": result.model_dump()}


def _post_github_pr_comment(
    owner: str,
    repo: str,
    pull_number: int,
    markdown: str,
    api_base_url: str = "",
    token: str = "",
) -> None:
    effective_api_base_url = api_base_url or settings.github_api_base_url
    effective_token = token or settings.github_token
    if not (effective_api_base_url and effective_token):
        return

    url = f"{effective_api_base_url.rstrip('/')}/repos/{owner}/{repo}/issues/{pull_number}/comments"
    headers = {"Authorization": f"Bearer {effective_token}", "Accept": "application/vnd.github+json"}
    body = {"body": markdown}
    try:
        requests.post(url, headers=headers, json=body, timeout=20)
    except requests.RequestException:
        return


def _upsert_github_pr_comment(
    owner: str,
    repo: str,
    pull_number: int,
    markdown: str,
    api_base_url: str = "",
    token: str = "",
) -> None:
    effective_api_base_url = api_base_url or settings.github_api_base_url
    effective_token = token or settings.github_token
    if not (effective_api_base_url and effective_token):
        return

    comments = _list_github_pr_comments(
        owner=owner,
        repo=repo,
        pull_number=pull_number,
        api_base_url=effective_api_base_url,
        token=effective_token,
    )
    for comment in comments:
        if STICKY_PR_COMMENT_MARKER in str(comment.get("body", "")):
            _update_github_comment(
                owner=owner,
                repo=repo,
                comment_id=int(comment.get("id", 0)),
                markdown=markdown,
                api_base_url=effective_api_base_url,
                token=effective_token,
            )
            return

    _post_github_pr_comment(
        owner=owner,
        repo=repo,
        pull_number=pull_number,
        markdown=markdown,
        api_base_url=effective_api_base_url,
        token=effective_token,
    )


def _list_github_pr_comments(
    owner: str,
    repo: str,
    pull_number: int,
    api_base_url: str = "",
    token: str = "",
) -> list[dict[str, Any]]:
    effective_api_base_url = api_base_url or settings.github_api_base_url
    effective_token = token or settings.github_token
    if not (effective_api_base_url and effective_token):
        return []

    url = f"{effective_api_base_url.rstrip('/')}/repos/{owner}/{repo}/issues/{pull_number}/comments"
    headers = {"Authorization": f"Bearer {effective_token}", "Accept": "application/vnd.github+json"}
    try:
        response = requests.get(url, headers=headers, timeout=20)
        response.raise_for_status()
    except requests.RequestException:
        return []

    payload = response.json()
    return payload if isinstance(payload, list) else []


def _get_existing_sticky_pr_comment(
    owner: str,
    repo: str,
    pull_number: int,
    api_base_url: str = "",
    token: str = "",
) -> str:
    comments = _list_github_pr_comments(
        owner=owner,
        repo=repo,
        pull_number=pull_number,
        api_base_url=api_base_url,
        token=token,
    )
    for comment in comments:
        body = str(comment.get("body", ""))
        if STICKY_PR_COMMENT_MARKER in body:
            return body
    return ""


def _update_github_comment(
    owner: str,
    repo: str,
    comment_id: int,
    markdown: str,
    api_base_url: str = "",
    token: str = "",
) -> None:
    effective_api_base_url = api_base_url or settings.github_api_base_url
    effective_token = token or settings.github_token
    if not (effective_api_base_url and effective_token) or comment_id <= 0:
        return

    url = f"{effective_api_base_url.rstrip('/')}/repos/{owner}/{repo}/issues/comments/{comment_id}"
    headers = {"Authorization": f"Bearer {effective_token}", "Accept": "application/vnd.github+json"}
    body = {"body": markdown}
    try:
        requests.patch(url, headers=headers, json=body, timeout=20)
    except requests.RequestException:
        return


def _build_github_pr_summary_comment(
    sql_changes: list[GithubPRSQLFileChange],
    confluence: ConfluencePublisher = confluence_publisher,
) -> tuple[str, list[dict[str, Any]]]:
    modified_changes = [change for change in sql_changes if change.status in {"modified", "renamed"}]
    added_changes = [change for change in sql_changes if change.status == "added"]
    deleted_changes = [change for change in sql_changes if change.status in {"deleted", "removed"}]
    doc_payloads: list[dict[str, Any]] = []

    sections: list[str] = [STICKY_PR_COMMENT_MARKER, "## SQL PR Summary"]

    if modified_changes:
        sections.append("### Modified SQL Files")
        for change in modified_changes:
            summary, doc_payload = _summarize_github_sql_change(change)
            doc_payloads.append(doc_payload.model_dump())
            sections.append(f"- **{change.filename}**: {summary}")

    if added_changes:
        sections.append("### New SQL Files")
        for change in added_changes:
            sections.append(
                f"- **{change.filename}**: New SQL file detected. Documentation will be published after PR merge."
            )

    if deleted_changes:
        sections.append("### Deleted SQL Files")
        for change in deleted_changes:
            existing_page = confluence.find_page_for_filename(change.filename) if confluence.enabled else None
            page_url = str(existing_page.get("url", "")) if existing_page else ""
            if page_url:
                sections.append(
                    f"- **{change.filename}**: This SQL file is being deleted in this PR. [Confluence]({page_url}) (Deleted or moved will be added after Published.)"
                )
            else:
                sections.append(
                    f"- **{change.filename}**: This SQL file is being deleted in this PR. Existing documentation will be marked as Code moved or deleted after PR merge. (Deleted or moved will be added after Published.)"
                )

    status_lines = _build_pr_file_status_lines(sql_changes, confluence=confluence)
    if status_lines:
        sections.append("### Documentation Status")
        sections.extend(status_lines)

    if len(sections) == 2:
        return "", doc_payloads

    return "\n".join(sections), doc_payloads


def _build_pr_file_status_lines(
    sql_changes: list[GithubPRSQLFileChange],
    publication_pages: list[dict[str, Any]] | None = None,
    confluence: ConfluencePublisher = confluence_publisher,
) -> list[str]:
    publication_pages = publication_pages or []
    published_by_filename = {
        str(page.get("filename", "")): page for page in publication_pages if str(page.get("filename", ""))
    }

    lines: list[str] = []
    for change in sql_changes:
        published_page = published_by_filename.get(change.filename)
        if published_page:
            lines.append(_format_status_line(change.filename, "Published", str(published_page.get("url", ""))))
            continue

        if change.status in {"deleted", "removed"}:
            existing_page = confluence.find_page_for_filename(change.filename) if confluence.enabled else None
            if existing_page and existing_page.get("url"):
                lines.append(_format_status_line(change.filename, "Will mark as Code moved or deleted after merge", existing_page["url"]))
            else:
                lines.append(_format_status_line(change.filename, "Will mark as Code moved or deleted after merge"))
            continue

        existing_page = confluence.find_page_for_filename(change.filename) if confluence.enabled else None
        if existing_page and existing_page.get("url"):
            lines.append(_format_status_line(change.filename, "Publish after merged", existing_page["url"]))
        else:
            lines.append(_format_status_line(change.filename, "Publish after merged"))

    return lines


def _format_status_line(filename: str, status: str, url: str = "") -> str:
    if url:
        return f"- **{filename}**: {status} - [Confluence]({url})"
    return f"- **{filename}**: {status}"


def _replace_documentation_status_section(markdown: str, status_lines: list[str]) -> str:
    if not status_lines:
        return markdown.strip()

    status_section = "\n".join(["### Documentation Status", *status_lines])
    stripped_markdown = markdown.strip()
    if not stripped_markdown:
        return "\n".join([STICKY_PR_COMMENT_MARKER, "## SQL PR Summary", status_section])

    marker = "\n### Documentation Status\n"
    if marker in stripped_markdown:
        prefix, _ = stripped_markdown.split(marker, 1)
        return "\n".join([prefix.rstrip(), status_section])

    return "\n\n".join([stripped_markdown, status_section])


def _refresh_pr_comment_after_publication(
    owner: str,
    repo: str,
    pull_number: int,
    runtime: RuntimeConfig | None = None,
) -> None:
    runtime = runtime or _default_runtime_config()
    record = approval_store.get_pr_record(owner=owner, repo=repo, pull_number=pull_number)
    if not record:
        return

    sql_changes = [
        GithubPRSQLFileChange(filename=path, status="modified", patch="")
        for path in record.get("modified_files", [])
    ] + [
        GithubPRSQLFileChange(filename=path, status="added", patch="")
        for path in record.get("new_files", [])
    ] + [
        GithubPRSQLFileChange(filename=path, status="deleted", patch="")
        for path in record.get("deleted_files", [])
    ]
    if not sql_changes:
        return

    publication_pages = record.get("publication", {}).get("pages", [])
    status_lines = _build_pr_file_status_lines(sql_changes, publication_pages=publication_pages, confluence=runtime.confluence)
    existing_comment_markdown = _get_existing_sticky_pr_comment(
        owner=owner,
        repo=repo,
        pull_number=pull_number,
        api_base_url=runtime.github_api_base_url,
        token=runtime.github_token,
    )
    if existing_comment_markdown:
        comment_markdown = _replace_documentation_status_section(existing_comment_markdown, status_lines)
    else:
        comment_markdown, _ = _build_github_pr_summary_comment(sql_changes, confluence=runtime.confluence)
        comment_markdown = _replace_documentation_status_section(comment_markdown, status_lines)

    _upsert_github_pr_comment(
        owner=owner,
        repo=repo,
        pull_number=pull_number,
        markdown=comment_markdown,
        api_base_url=runtime.github_api_base_url,
        token=runtime.github_token,
    )


def _summarize_github_sql_change(change: GithubPRSQLFileChange) -> tuple[str, PRFileDocPayload]:
    if not change.patch:
        fallback = "SQL file changed in this PR, but GitHub did not provide a patch for summarization."
        doc_payload = PRFileDocPayload(
            filename=change.filename,
            summary=fallback,
            markdown=fallback,
            change_type="UNKNOWN",
            impact_level="medium",
            affected_objects=[],
            suggested_doc_updates=[],
            rationale="Patch omitted by GitHub API payload.",
        )
        return fallback, doc_payload

    diff = f"# File: {change.filename}\n{change.patch}"
    result = orchestrator.run(diff=diff)
    short_summary = _to_pr_safe_summary(result.summary)
    doc_payload = PRFileDocPayload(
        filename=change.filename,
        summary=result.summary,
        markdown=result.markdown,
        change_type=result.change_type,
        impact_level=result.impact_level,
        affected_objects=result.affected_objects,
        suggested_doc_updates=result.suggested_doc_updates,
        rationale=result.rationale,
    )
    return short_summary, doc_payload


def _to_pr_safe_summary(summary: str, max_len: int | None = None) -> str:
    max_chars = max_len if max_len is not None else settings.pr_summary_max_chars
    cleaned = re.sub(r"\s+", " ", summary).strip()
    if len(cleaned) <= max_chars:
        return cleaned
    return f"{cleaned[: max_chars - 3].rstrip()}..."


def _build_publish_record_from_merged_sql(
    payload: dict[str, Any],
    owner: str,
    repo: str,
    record: dict[str, Any],
    runtime: RuntimeConfig | None = None,
) -> dict[str, Any]:
    runtime = runtime or _default_runtime_config()
    if not (runtime.github_api_base_url and runtime.github_token):
        return record

    pull_request = payload.get("pull_request", {})
    ref = str(pull_request.get("merge_commit_sha", "")).strip() or str(pull_request.get("base", {}).get("ref", "")).strip()
    final_paths = sorted(set([*record.get("modified_files", []), *record.get("new_files", [])]))
    deleted_paths = sorted(set(record.get("deleted_files", [])))
    if not final_paths and not deleted_paths:
        return record

    publish_payloads: list[dict[str, Any]] = []
    for path in final_paths:
        try:
            sql_text = fetch_github_file_content(
                api_base_url=runtime.github_api_base_url,
                token=runtime.github_token,
                owner=owner,
                repo=repo,
                path=path,
                ref=ref,
            )
        except requests.RequestException:
            continue

        if not sql_text.strip():
            continue

        publish_payloads.append(_generate_publish_sql_doc(path, sql_text).model_dump())

    for path in deleted_paths:
        publish_payloads.append(_generate_deleted_sql_doc(path).model_dump())

    if not publish_payloads:
        return record

    updated_record = dict(record)
    updated_record["doc_payloads"] = publish_payloads
    return updated_record


def _sync_confluence_links_into_sql_files(
    payload: dict[str, Any],
    owner: str,
    repo: str,
    record: dict[str, Any],
    publication_pages: list[dict[str, Any]],
    confluence: ConfluencePublisher = confluence_publisher,
    runtime: RuntimeConfig | None = None,
) -> None:
    runtime = runtime or _default_runtime_config()
    if not (runtime.github_api_base_url and runtime.github_token):
        return

    pull_request = payload.get("pull_request", {})
    base_ref = str(pull_request.get("base", {}).get("ref", "")).strip()
    if not base_ref:
        return

    file_paths = sorted(set([*record.get("modified_files", []), *record.get("new_files", [])]))
    if not file_paths:
        return

    page_by_filename = {
        str(page.get("filename", "")): str(page.get("url", ""))
        for page in publication_pages
        if str(page.get("filename", "")) and str(page.get("url", ""))
    }

    for path in file_paths:
        page_url = page_by_filename.get(path, "")
        if not page_url and confluence.enabled:
            existing_page = confluence.find_page_for_filename(path)
            page_url = str(existing_page.get("url", "")) if existing_page else ""

        if not page_url:
            continue

        try:
            current_sql, current_sha = fetch_github_file_content_with_sha(
                api_base_url=runtime.github_api_base_url,
                token=runtime.github_token,
                owner=owner,
                repo=repo,
                path=path,
                ref=base_ref,
            )
        except requests.RequestException:
            continue

        if not current_sql.strip() or not current_sha:
            continue

        updated_sql = _ensure_confluence_link_at_fourth_line(current_sql, page_url)
        if updated_sql == current_sql:
            continue

        try:
            update_github_file_content(
                api_base_url=runtime.github_api_base_url,
                token=runtime.github_token,
                owner=owner,
                repo=repo,
                path=path,
                content=updated_sql,
                message=f"chore(sql-doc): add confluence link to {path}",
                branch=base_ref,
                sha=current_sha,
            )
        except requests.RequestException:
            continue


def _ensure_confluence_link_at_fourth_line(sql_text: str, confluence_url: str) -> str:
    newline = "\r\n" if "\r\n" in sql_text else "\n"
    trailing_newline = sql_text.endswith("\n") or sql_text.endswith("\r")
    lines = sql_text.splitlines()
    confluence_line = f"-- Confluence: {confluence_url}"

    while len(lines) < 3:
        lines.append("")

    if len(lines) >= 4 and lines[3].strip().lower().startswith("-- confluence:"):
        lines[3] = confluence_line
    elif len(lines) >= 4 and lines[3].strip() == confluence_line:
        pass
    else:
        lines.insert(3, confluence_line)

    rebuilt = newline.join(lines)
    if trailing_newline and not rebuilt.endswith(newline):
        rebuilt += newline
    return rebuilt


def _generate_publish_sql_doc(filename: str, sql_text: str) -> PublishedSQLDocPayload:
    change_type = detect_change_type(sql_text)
    affected_objects = extract_affected_objects(sql_text)
    object_types = extract_object_types(sql_text)
    table_details = extract_table_details(sql_text)
    join_details = extract_join_details(sql_text)
    filter_details = extract_filter_details(sql_text)

    fallback = {
        "full_summary": _build_publish_summary_fallback(change_type, table_details, join_details, filter_details),
        "sql_description": _build_publish_description_fallback(object_types, table_details, join_details, filter_details, affected_objects),
        "object_types": object_types,
        "table_details": table_details,
        "join_details": join_details,
        "filter_details": filter_details,
        "affected_objects": affected_objects,
    }

    response = publish_llm_client.request_json(
        prompt=build_publish_doc_prompt(sql_text=sql_text, change_type=change_type, affected_objects=affected_objects),
        fallback=fallback,
    )

    return PublishedSQLDocPayload(
        filename=filename,
        full_summary=str(response.get("full_summary", fallback["full_summary"])),
        sql_description=str(response.get("sql_description", fallback["sql_description"])),
        object_types=[str(item) for item in response.get("object_types", object_types)],
        table_details=[str(item) for item in response.get("table_details", table_details)],
        join_details=[str(item) for item in response.get("join_details", join_details)],
        filter_details=[str(item) for item in response.get("filter_details", filter_details)],
        affected_objects=[str(item) for item in response.get("affected_objects", affected_objects)],
        page_heading=str(response.get("page_heading", "")),
    )


def _generate_deleted_sql_doc(filename: str) -> PublishedSQLDocPayload:
    return PublishedSQLDocPayload(
        filename=filename,
        full_summary="This SQL file was removed from the repository by an approved pull request. The documentation page is retained for traceability.",
        sql_description="Code moved or deleted.",
        object_types=[],
        table_details=[],
        join_details=[],
        filter_details=[],
        affected_objects=[],
        page_heading="Code moved or deleted",
    )


def _build_publish_summary_fallback(
    change_type: str,
    table_details: list[str],
    join_details: list[str],
    filter_details: list[str],
) -> str:
    tables = ", ".join(table_details[:5]) if table_details else "no clearly parsed tables"
    joins = f" It uses {len(join_details)} join clause(s)." if join_details else ""
    filters = f" It applies {len(filter_details)} filter clause(s)." if filter_details else ""
    return f"This final merged SQL file is classified as {change_type} and works with {tables}.{joins}{filters}".strip()


def _build_publish_description_fallback(
    object_types: list[str],
    table_details: list[str],
    join_details: list[str],
    filter_details: list[str],
    affected_objects: list[str],
) -> str:
    type_text = ", ".join(object_types) if object_types else "UNKNOWN"
    table_text = ", ".join(table_details[:8]) if table_details else "No table references detected"
    join_text = "; ".join(join_details[:5]) if join_details else "No explicit joins detected"
    filter_text = "; ".join(filter_details[:5]) if filter_details else "No explicit filters detected"
    object_text = ", ".join(affected_objects[:8]) if affected_objects else "No affected objects detected"
    return (
        f"Object types: {type_text}. Tables or primary objects: {table_text}. "
        f"Join details: {join_text}. Filter details: {filter_text}. Affected objects: {object_text}."
    )


def _store_pr_analysis(
    payload: dict[str, Any],
    owner: str,
    repo: str,
    pull_number: int,
    sql_changes: list[GithubPRSQLFileChange],
    doc_payloads: list[dict[str, Any]],
) -> None:
    pull_request = payload.get("pull_request", {})
    head_sha = str(pull_request.get("head", {}).get("sha", ""))
    modified_files = [change.filename for change in sql_changes if change.status in {"modified", "renamed"}]
    new_files = [change.filename for change in sql_changes if change.status == "added"]
    deleted_files = [change.filename for change in sql_changes if change.status in {"deleted", "removed"}]
    approval_store.upsert_pr_analysis(
        owner=owner,
        repo=repo,
        pull_number=pull_number,
        head_sha=head_sha,
        modified_files=modified_files,
        new_files=new_files,
        deleted_files=deleted_files,
        doc_payloads=doc_payloads,
    )


def _extract_github_pr_identity(payload: dict[str, Any]) -> tuple[str, str, int]:
    repository = payload.get("repository", {})
    full_name = str(repository.get("full_name", ""))
    if "/" not in full_name:
        raise HTTPException(status_code=400, detail="Invalid GitHub repository full_name")

    owner, repo = full_name.split("/", 1)
    pull_request = payload.get("pull_request", {})
    pull_number = int(pull_request.get("number", 0))
    if pull_number <= 0:
        raise HTTPException(status_code=400, detail="Invalid GitHub pull request number")

    return owner, repo, pull_number


def _extract_github_issue_identity(payload: dict[str, Any]) -> tuple[str, str, int]:
    repository = payload.get("repository", {})
    full_name = str(repository.get("full_name", ""))
    if "/" not in full_name:
        raise HTTPException(status_code=400, detail="Invalid GitHub repository full_name")

    owner, repo = full_name.split("/", 1)
    issue = payload.get("issue", {})
    pull_number = int(issue.get("number", 0))
    if pull_number <= 0:
        raise HTTPException(status_code=400, detail="Invalid GitHub pull request number")

    return owner, repo, pull_number


def _extract_github_actor(payload: dict[str, Any]) -> str:
    login = str(payload.get("sender", {}).get("login", "")).strip()
    return login or "unknown"


def _post_bitbucket_pr_comment(payload: dict[str, Any], markdown: str) -> None:
    if not settings.bitbucket_token:
        return

    links = payload.get("pullrequest", {}).get("links", {})
    comments_url = links.get("comments", {}).get("href", "")
    if not comments_url:
        return

    headers = {"Authorization": f"Bearer {settings.bitbucket_token}", "Content-Type": "application/json"}
    body = {"content": {"raw": markdown}}
    try:
        requests.post(comments_url, headers=headers, json=body, timeout=20)
    except requests.RequestException:
        return


def _validate_github_signature(request: Request, raw_body: bytes, webhook_secret: str = "") -> None:
    effective_secret = webhook_secret or settings.github_webhook_secret
    if not effective_secret:
        return

    signature = request.headers.get("X-Hub-Signature-256", "")
    if not signature.startswith("sha256="):
        raise HTTPException(status_code=401, detail="Missing or invalid GitHub signature header")

    expected_signature = hmac.new(
        effective_secret.encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(signature, f"sha256={expected_signature}"):
        raise HTTPException(status_code=401, detail="GitHub webhook signature verification failed")
