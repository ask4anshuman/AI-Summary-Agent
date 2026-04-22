import hashlib
import hmac
import re
from typing import Any

import requests
from fastapi import APIRouter, HTTPException, Request

from src.agents.orchestrator import SQLDocumentationOrchestrator
from src.config import settings
from src.models import PRFileDocPayload, SummarizeRequest, SummarizeResponse, WebhookResponse
from src.tools.confluence_tools import ConfluencePublisher
from src.tools.git_tools import GithubPRSQLFileChange, fetch_bitbucket_pr_sql_patches, fetch_github_pr_sql_file_changes
from src.tools.approval_store import ApprovalStateStore

router = APIRouter()
orchestrator = SQLDocumentationOrchestrator()
approval_store = ApprovalStateStore(settings.approval_state_file)
confluence_publisher = ConfluencePublisher(
    base_url=settings.confluence_base_url,
    space_key=settings.confluence_space,
    username=settings.confluence_username,
    api_token=settings.confluence_api_token,
    parent_page_id=settings.confluence_parent_page_id,
)
STICKY_PR_COMMENT_MARKER = "<!-- ai-sql-summary-agent:sticky-pr-summary -->"


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/summarize", response_model=SummarizeResponse)
def summarize_sql(request: SummarizeRequest) -> SummarizeResponse:
    if not request.diff and not request.current_sql and not request.previous_sql:
        raise HTTPException(status_code=400, detail="Provide at least one of diff, current_sql, or previous_sql")

    result = orchestrator.run(previous_sql=request.previous_sql, current_sql=request.current_sql, diff=request.diff)
    return SummarizeResponse(result=result)


@router.post("/github-webhook", response_model=WebhookResponse)
async def github_webhook(request: Request) -> WebhookResponse:
    raw_body = await request.body()
    _validate_github_signature(request=request, raw_body=raw_body)

    payload = await request.json()
    event_name = request.headers.get("X-GitHub-Event", "pull_request")

    if event_name == "pull_request":
        return _handle_github_pull_request_event(payload)
    if event_name == "issue_comment":
        return _handle_github_issue_comment_event(payload)
    if event_name == "pull_request_review":
        return _handle_github_pull_request_review_event(payload)

    return WebhookResponse(ok=True, message=f"Ignored GitHub event: {event_name}")


def _handle_github_pull_request_event(payload: dict[str, Any]) -> WebhookResponse:
    action = str(payload.get("action", ""))
    owner, repo, pull_number = _extract_github_pr_identity(payload)

    if action == "closed":
        return _handle_github_pull_request_merge(payload=payload, owner=owner, repo=repo, pull_number=pull_number)

    if action in {"labeled", "unlabeled"}:
        label_name = str(payload.get("label", {}).get("name", "")).strip().lower()
        target_label = settings.github_approval_label.strip().lower()
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
    if settings.github_api_base_url and settings.github_token:
        sql_changes = fetch_github_pr_sql_file_changes(
            api_base_url=settings.github_api_base_url,
            token=settings.github_token,
            owner=owner,
            repo=repo,
            pull_number=pull_number,
        )

    if not sql_changes:
        return WebhookResponse(ok=True, message="No SQL changes found in GitHub PR")

    comment_markdown, doc_payloads = _build_github_pr_summary_comment(sql_changes)
    _store_pr_analysis(payload=payload, owner=owner, repo=repo, pull_number=pull_number, sql_changes=sql_changes, doc_payloads=doc_payloads)

    if not comment_markdown:
        return WebhookResponse(ok=True, message="No commentable SQL changes found in GitHub PR")

    _upsert_github_pr_comment(owner=owner, repo=repo, pull_number=pull_number, markdown=comment_markdown)
    return WebhookResponse(ok=True, message="GitHub webhook processed", markdown=comment_markdown)


def _handle_github_pull_request_merge(payload: dict[str, Any], owner: str, repo: str, pull_number: int) -> WebhookResponse:
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

    publish_result = confluence_publisher.publish_pr_record(
        owner=owner,
        repo=repo,
        pull_number=pull_number,
        record=record,
    )
    approval_store.mark_publication(
        owner=owner,
        repo=repo,
        pull_number=pull_number,
        published=bool(publish_result.get("ok", False)),
        message=str(publish_result.get("message", "")),
        page_id=str(publish_result.get("page_id", "")),
        title=str(publish_result.get("title", "")),
    )
    return WebhookResponse(ok=True, message=str(publish_result.get("message", "Confluence publish attempted")))


def _handle_github_issue_comment_event(payload: dict[str, Any]) -> WebhookResponse:
    issue = payload.get("issue", {})
    if "pull_request" not in issue:
        return WebhookResponse(ok=True, message="Ignored issue comment outside pull request")

    owner, repo, pull_number = _extract_github_issue_identity(payload)
    action = str(payload.get("action", ""))
    if action not in {"created", "edited"}:
        return WebhookResponse(ok=True, message=f"Ignored issue_comment action: {action}")

    body = str(payload.get("comment", {}).get("body", "")).strip().lower()
    command = settings.github_approval_command.strip().lower()
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


def _handle_github_pull_request_review_event(payload: dict[str, Any]) -> WebhookResponse:
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


def _post_github_pr_comment(owner: str, repo: str, pull_number: int, markdown: str) -> None:
    if not (settings.github_api_base_url and settings.github_token):
        return

    url = f"{settings.github_api_base_url.rstrip('/')}/repos/{owner}/{repo}/issues/{pull_number}/comments"
    headers = {"Authorization": f"Bearer {settings.github_token}", "Accept": "application/vnd.github+json"}
    body = {"body": markdown}
    try:
        requests.post(url, headers=headers, json=body, timeout=20)
    except requests.RequestException:
        return


def _upsert_github_pr_comment(owner: str, repo: str, pull_number: int, markdown: str) -> None:
    if not (settings.github_api_base_url and settings.github_token):
        return

    comments = _list_github_pr_comments(owner=owner, repo=repo, pull_number=pull_number)
    for comment in comments:
        if STICKY_PR_COMMENT_MARKER in str(comment.get("body", "")):
            _update_github_comment(owner=owner, repo=repo, comment_id=int(comment.get("id", 0)), markdown=markdown)
            return

    _post_github_pr_comment(owner=owner, repo=repo, pull_number=pull_number, markdown=markdown)


def _list_github_pr_comments(owner: str, repo: str, pull_number: int) -> list[dict[str, Any]]:
    if not (settings.github_api_base_url and settings.github_token):
        return []

    url = f"{settings.github_api_base_url.rstrip('/')}/repos/{owner}/{repo}/issues/{pull_number}/comments"
    headers = {"Authorization": f"Bearer {settings.github_token}", "Accept": "application/vnd.github+json"}
    try:
        response = requests.get(url, headers=headers, timeout=20)
        response.raise_for_status()
    except requests.RequestException:
        return []

    payload = response.json()
    return payload if isinstance(payload, list) else []


def _update_github_comment(owner: str, repo: str, comment_id: int, markdown: str) -> None:
    if not (settings.github_api_base_url and settings.github_token) or comment_id <= 0:
        return

    url = f"{settings.github_api_base_url.rstrip('/')}/repos/{owner}/{repo}/issues/comments/{comment_id}"
    headers = {"Authorization": f"Bearer {settings.github_token}", "Accept": "application/vnd.github+json"}
    body = {"body": markdown}
    try:
        requests.patch(url, headers=headers, json=body, timeout=20)
    except requests.RequestException:
        return


def _build_github_pr_summary_comment(sql_changes: list[GithubPRSQLFileChange]) -> tuple[str, list[dict[str, Any]]]:
    modified_changes = [change for change in sql_changes if change.status in {"modified", "renamed"}]
    added_changes = [change for change in sql_changes if change.status == "added"]
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

    if len(sections) == 2:
        return "", doc_payloads

    return "\n".join(sections), doc_payloads


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
    approval_store.upsert_pr_analysis(
        owner=owner,
        repo=repo,
        pull_number=pull_number,
        head_sha=head_sha,
        modified_files=modified_files,
        new_files=new_files,
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


def _validate_github_signature(request: Request, raw_body: bytes) -> None:
    if not settings.github_webhook_secret:
        return

    signature = request.headers.get("X-Hub-Signature-256", "")
    if not signature.startswith("sha256="):
        raise HTTPException(status_code=401, detail="Missing or invalid GitHub signature header")

    expected_signature = hmac.new(
        settings.github_webhook_secret.encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(signature, f"sha256={expected_signature}"):
        raise HTTPException(status_code=401, detail="GitHub webhook signature verification failed")
