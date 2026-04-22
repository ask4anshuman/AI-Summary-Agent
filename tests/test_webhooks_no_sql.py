import hashlib
import hmac

from fastapi.testclient import TestClient

from src.api import routes
from src.tools.git_tools import GithubPRSQLFileChange


def _github_signature(secret: str, payload: bytes) -> str:
    digest = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def _set_github_webhook_secret(secret: str) -> None:
    object.__setattr__(routes.settings, "github_webhook_secret", secret)


def _set_github_api_config(base_url: str, token: str) -> None:
    object.__setattr__(routes.settings, "github_api_base_url", base_url)
    object.__setattr__(routes.settings, "github_token", token)


def test_github_webhook_no_sql_changes_without_provider_config(client: TestClient) -> None:
    original_fetcher = routes.fetch_github_pr_sql_file_changes
    original_store = routes.approval_store.upsert_pr_analysis
    routes.fetch_github_pr_sql_file_changes = lambda **_: []
    routes.approval_store.upsert_pr_analysis = lambda **_: None
    payload = {
        "action": "opened",
        "pull_request": {"number": 123},
        "repository": {"full_name": "team/repo"}
    }
    try:
        response = client.post("/github-webhook", json=payload)
    finally:
        routes.fetch_github_pr_sql_file_changes = original_fetcher
        routes.approval_store.upsert_pr_analysis = original_store

    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_github_webhook_rejects_missing_signature_when_secret_configured(client: TestClient) -> None:
    _set_github_webhook_secret("topsecret")
    payload = {
        "action": "opened",
        "pull_request": {"number": 123},
        "repository": {"full_name": "team/repo"}
    }

    try:
        response = client.post("/github-webhook", json=payload)
    finally:
        _set_github_webhook_secret("")

    assert response.status_code == 401
    assert response.json()["detail"] == "Missing or invalid GitHub signature header"


def test_github_webhook_rejects_invalid_signature(client: TestClient) -> None:
    _set_github_webhook_secret("topsecret")
    payload = b'{"action":"opened","pull_request":{"number":123},"repository":{"full_name":"team/repo"}}'

    try:
        response = client.post(
            "/github-webhook",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "X-Hub-Signature-256": "sha256=invalid",
            },
        )
    finally:
        _set_github_webhook_secret("")

    assert response.status_code == 401
    assert response.json()["detail"] == "GitHub webhook signature verification failed"


def test_github_webhook_accepts_valid_signature(client: TestClient) -> None:
    secret = "topsecret"
    original_fetcher = routes.fetch_github_pr_sql_file_changes
    original_store = routes.approval_store.upsert_pr_analysis
    routes.fetch_github_pr_sql_file_changes = lambda **_: []
    routes.approval_store.upsert_pr_analysis = lambda **_: None
    _set_github_webhook_secret(secret)
    payload = b'{"action":"opened","pull_request":{"number":123},"repository":{"full_name":"team/repo"}}'

    try:
        response = client.post(
            "/github-webhook",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "X-Hub-Signature-256": _github_signature(secret, payload),
            },
        )
    finally:
        _set_github_webhook_secret("")
        routes.fetch_github_pr_sql_file_changes = original_fetcher
        routes.approval_store.upsert_pr_analysis = original_store

    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_github_webhook_creates_sticky_summary_for_modified_sql(client: TestClient) -> None:
    original_fetcher = routes.fetch_github_pr_sql_file_changes
    original_upsert = routes._upsert_github_pr_comment
    original_run = routes.orchestrator.run
    original_store = routes.approval_store.upsert_pr_analysis
    captured: dict[str, str] = {}
    stored: dict[str, object] = {}

    routes.fetch_github_pr_sql_file_changes = lambda **_: [
        GithubPRSQLFileChange(
            filename="db/orders.sql",
            status="modified",
            patch="@@ -1 +1 @@\n-select * from orders\n+select order_id, total_amount from orders",
        )
    ]
    routes.orchestrator.run = lambda **_: type(
        "Result",
        (),
        {
            "summary": "The query now selects explicit order columns for reporting. " * 20,
            "markdown": "## SQL Change Summary\nExample",
            "change_type": "DML",
            "impact_level": "medium",
            "affected_objects": ["orders"],
            "suggested_doc_updates": ["Release notes"],
            "rationale": "Columns changed",
        },
    )()
    routes._upsert_github_pr_comment = lambda **kwargs: captured.update({"markdown": kwargs["markdown"]})
    routes.approval_store.upsert_pr_analysis = lambda **kwargs: stored.update(kwargs)

    payload = {
        "action": "opened",
        "pull_request": {"number": 123},
        "repository": {"full_name": "team/repo"}
    }

    try:
        response = client.post("/github-webhook", json=payload)
    finally:
        routes.fetch_github_pr_sql_file_changes = original_fetcher
        routes._upsert_github_pr_comment = original_upsert
        routes.orchestrator.run = original_run
        routes.approval_store.upsert_pr_analysis = original_store

    assert response.status_code == 200
    assert "## SQL PR Summary" in captured["markdown"]
    assert "db/orders.sql" in captured["markdown"]
    assert "explicit order columns" in captured["markdown"].lower()
    assert "..." in captured["markdown"]
    assert stored["modified_files"] == ["db/orders.sql"]
    assert isinstance(stored["doc_payloads"], list)
    assert len(stored["doc_payloads"]) == 1


def test_github_webhook_posts_merge_note_for_new_sql_files(client: TestClient) -> None:
    original_fetcher = routes.fetch_github_pr_sql_file_changes
    original_upsert = routes._upsert_github_pr_comment
    original_run = routes.orchestrator.run
    original_store = routes.approval_store.upsert_pr_analysis
    captured: dict[str, str] = {}
    called = {"run": 0}
    stored: dict[str, object] = {}

    routes.fetch_github_pr_sql_file_changes = lambda **_: [
        GithubPRSQLFileChange(
            filename="db/new_feature.sql",
            status="added",
            patch="@@ -0,0 +1 @@\n+create table new_feature(id int)",
        )
    ]
    routes.orchestrator.run = lambda **_: called.__setitem__("run", called["run"] + 1)
    routes._upsert_github_pr_comment = lambda **kwargs: captured.update({"markdown": kwargs["markdown"]})
    routes.approval_store.upsert_pr_analysis = lambda **kwargs: stored.update(kwargs)

    payload = {
        "action": "opened",
        "pull_request": {"number": 123},
        "repository": {"full_name": "team/repo"}
    }

    try:
        response = client.post("/github-webhook", json=payload)
    finally:
        routes.fetch_github_pr_sql_file_changes = original_fetcher
        routes._upsert_github_pr_comment = original_upsert
        routes.orchestrator.run = original_run
        routes.approval_store.upsert_pr_analysis = original_store

    assert response.status_code == 200
    assert called["run"] == 0
    assert "Documentation will be published after PR merge" in captured["markdown"]
    assert stored["new_files"] == ["db/new_feature.sql"]


def test_upsert_github_pr_comment_updates_existing_sticky_comment() -> None:
    original_list = routes._list_github_pr_comments
    original_update = routes._update_github_comment
    original_post = routes._post_github_pr_comment
    captured: dict[str, object] = {}

    _set_github_api_config("https://api.github.com", "token")
    routes._list_github_pr_comments = lambda **_: [{"id": 42, "body": f"old\n{routes.STICKY_PR_COMMENT_MARKER}"}]
    routes._update_github_comment = lambda **kwargs: captured.update(kwargs)
    routes._post_github_pr_comment = lambda **kwargs: captured.update({"posted": True, **kwargs})

    try:
        routes._upsert_github_pr_comment(owner="team", repo="repo", pull_number=123, markdown="new body")
    finally:
        _set_github_api_config("", "")
        routes._list_github_pr_comments = original_list
        routes._update_github_comment = original_update
        routes._post_github_pr_comment = original_post

    assert captured["owner"] == "team"
    assert captured["repo"] == "repo"
    assert captured["comment_id"] == 42
    assert captured["markdown"] == "new body"
    assert "posted" not in captured


def test_github_issue_comment_approval_command_marks_approved(client: TestClient) -> None:
    original_mark = routes.approval_store.mark_approval
    captured: dict[str, object] = {}
    routes.approval_store.mark_approval = lambda **kwargs: captured.update(kwargs)

    payload = {
        "action": "created",
        "repository": {"full_name": "team/repo"},
        "issue": {"number": 123, "pull_request": {"url": "https://api.github.com/repos/team/repo/pulls/123"}},
        "comment": {"body": "Looks good /approve-sql-doc"},
        "sender": {"login": "alice"},
    }

    try:
        response = client.post("/github-webhook", json=payload, headers={"X-GitHub-Event": "issue_comment"})
    finally:
        routes.approval_store.mark_approval = original_mark

    assert response.status_code == 200
    assert captured["approved"] is True
    assert captured["source"] == "command"
    assert captured["actor"] == "alice"


def test_github_pr_label_marks_approved(client: TestClient) -> None:
    original_mark = routes.approval_store.mark_approval
    captured: dict[str, object] = {}
    routes.approval_store.mark_approval = lambda **kwargs: captured.update(kwargs)

    payload = {
        "action": "labeled",
        "repository": {"full_name": "team/repo"},
        "pull_request": {"number": 123},
        "label": {"name": "sql-doc-approved"},
        "sender": {"login": "bob"},
    }

    try:
        response = client.post("/github-webhook", json=payload, headers={"X-GitHub-Event": "pull_request"})
    finally:
        routes.approval_store.mark_approval = original_mark

    assert response.status_code == 200
    assert captured["approved"] is True
    assert captured["source"] == "label"
    assert captured["actor"] == "bob"


def test_github_review_approved_marks_approved(client: TestClient) -> None:
    original_mark = routes.approval_store.mark_approval
    captured: dict[str, object] = {}
    routes.approval_store.mark_approval = lambda **kwargs: captured.update(kwargs)

    payload = {
        "action": "submitted",
        "repository": {"full_name": "team/repo"},
        "pull_request": {"number": 123},
        "review": {"state": "approved"},
        "sender": {"login": "charlie"},
    }

    try:
        response = client.post("/github-webhook", json=payload, headers={"X-GitHub-Event": "pull_request_review"})
    finally:
        routes.approval_store.mark_approval = original_mark

    assert response.status_code == 200
    assert captured["approved"] is True
    assert captured["source"] == "review"
    assert captured["detail"] == "approved"


def test_github_merge_skips_when_not_approved(client: TestClient) -> None:
    original_get = routes.approval_store.get_pr_record
    original_publish = routes.confluence_publisher.publish_pr_record
    original_mark_publication = routes.approval_store.mark_publication
    called = {"publish": 0, "mark_publication": 0}

    routes.approval_store.get_pr_record = lambda **_: {
        "head_sha": "abc123",
        "approval": {"approved": False},
        "doc_payloads": [],
    }
    routes.confluence_publisher.publish_pr_record = lambda **_: called.__setitem__("publish", called["publish"] + 1)
    routes.approval_store.mark_publication = lambda **_: called.__setitem__("mark_publication", called["mark_publication"] + 1)

    payload = {
        "action": "closed",
        "repository": {"full_name": "team/repo"},
        "pull_request": {"number": 123, "merged": True, "head": {"sha": "abc123"}},
    }

    try:
        response = client.post("/github-webhook", json=payload, headers={"X-GitHub-Event": "pull_request"})
    finally:
        routes.approval_store.get_pr_record = original_get
        routes.confluence_publisher.publish_pr_record = original_publish
        routes.approval_store.mark_publication = original_mark_publication

    assert response.status_code == 200
    assert "without approval" in response.json()["message"]
    assert called["publish"] == 0
    assert called["mark_publication"] == 0


def test_github_merge_skips_when_sha_mismatch(client: TestClient) -> None:
    original_get = routes.approval_store.get_pr_record
    original_publish = routes.confluence_publisher.publish_pr_record
    called = {"publish": 0}

    routes.approval_store.get_pr_record = lambda **_: {
        "head_sha": "oldsha",
        "approval": {"approved": True},
        "doc_payloads": [],
    }
    routes.confluence_publisher.publish_pr_record = lambda **_: called.__setitem__("publish", called["publish"] + 1)

    payload = {
        "action": "closed",
        "repository": {"full_name": "team/repo"},
        "pull_request": {"number": 123, "merged": True, "head": {"sha": "newsha"}},
    }

    try:
        response = client.post("/github-webhook", json=payload, headers={"X-GitHub-Event": "pull_request"})
    finally:
        routes.approval_store.get_pr_record = original_get
        routes.confluence_publisher.publish_pr_record = original_publish

    assert response.status_code == 200
    assert "does not match" in response.json()["message"]
    assert called["publish"] == 0


def test_github_merge_publishes_to_confluence_when_approved_and_sha_matches(client: TestClient) -> None:
    original_get = routes.approval_store.get_pr_record
    original_publish = routes.confluence_publisher.publish_pr_record
    original_mark_publication = routes.approval_store.mark_publication
    captured: dict[str, object] = {}

    routes.approval_store.get_pr_record = lambda **_: {
        "head_sha": "abc123",
        "approval": {"approved": True},
        "doc_payloads": [{"filename": "db/orders.sql", "summary": "changed"}],
    }
    routes.confluence_publisher.publish_pr_record = lambda **kwargs: {
        "ok": True,
        "message": "Confluence page updated",
        "page_id": "99",
        "title": "repo PR-123 SQL Summary",
        "owner": kwargs["owner"],
    }
    routes.approval_store.mark_publication = lambda **kwargs: captured.update(kwargs)

    payload = {
        "action": "closed",
        "repository": {"full_name": "team/repo"},
        "pull_request": {"number": 123, "merged": True, "head": {"sha": "abc123"}},
    }

    try:
        response = client.post("/github-webhook", json=payload, headers={"X-GitHub-Event": "pull_request"})
    finally:
        routes.approval_store.get_pr_record = original_get
        routes.confluence_publisher.publish_pr_record = original_publish
        routes.approval_store.mark_publication = original_mark_publication

    assert response.status_code == 200
    assert response.json()["message"] == "Confluence page updated"
    assert captured["published"] is True
    assert captured["page_id"] == "99"
    assert captured["title"] == "repo PR-123 SQL Summary"


def test_bitbucket_webhook_no_sql_changes(client: TestClient) -> None:
    payload = {
        "pullrequest": {
            "links": {
                "diff": {"href": ""}
            }
        }
    }
    response = client.post("/bitbucket-webhook", json=payload)
    assert response.status_code == 200
    assert response.json()["ok"] is True
