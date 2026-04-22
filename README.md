AI SQL Summary Agent

Overview
This project analyzes SQL and PL/SQL changes, generates natural language summaries, and suggests documentation updates. It can run manually through API calls or through GitHub and Bitbucket pull request webhooks.

Project Structure
src/main.py
src/api/routes.py
src/agents/orchestrator.py
src/agents/sql_summarizer.py
src/agents/doc_suggester.py
src/tools/sql_parser.py
src/tools/git_tools.py
src/tools/llm_tools.py
src/models.py
src/config.py
tests/

Environment Variables
OPENAI_API_KEY
OPENAI_MODEL
OPENAI_TEMPERATURE
PR_SUMMARY_MAX_CHARS
APP_CONFIG_FILE
GITHUB_API_BASE_URL
GITHUB_TOKEN
GITHUB_WEBHOOK_SECRET
GITHUB_APPROVAL_COMMAND
GITHUB_APPROVAL_LABEL
APPROVAL_STATE_FILE
BITBUCKET_API_BASE_URL
BITBUCKET_TOKEN
CONFLUENCE_BASE_URL
CONFLUENCE_SPACE
CONFLUENCE_PARENT_PAGE_ID
CONFLUENCE_USERNAME
CONFLUENCE_API_TOKEN
APP_HOST
APP_PORT

Local Run
1. Create and activate a virtual environment
2. Install dependencies
   pip install -r requirements.txt
3. Start the API
   uvicorn src.main:app --host 0.0.0.0 --port 8000
4. Open docs
   http://localhost:8000/docs

Quick API Test
POST /summarize
Body example:
{
  "previous_sql": "create table emp(id int);",
  "current_sql": "create table emp(id int, name varchar(100));"
}

GitHub Webhook Validation
1. Set `GITHUB_WEBHOOK_SECRET` to the same secret configured in the GitHub webhook.
2. GitHub requests to `/github-webhook` are verified with the `X-Hub-Signature-256` HMAC signature.
3. If no webhook secret is configured, signature validation is skipped.

GitHub Approval Tracking
1. PR open/sync/reopen events generate sticky SQL summary comments for modified SQL files.
2. New SQL files get a note: documentation will be published after merge.
3. Approval is recorded when any one of the following occurs:
   - PR comment contains `GITHUB_APPROVAL_COMMAND` (default `/approve-sql-doc`)
   - PR is labeled with `GITHUB_APPROVAL_LABEL` (default `sql-doc-approved`)
   - PR review is submitted with state `approved`
4. Approval state and rich doc payload are stored in `APPROVAL_STATE_FILE`.

Merge + Confluence Publish
1. On `pull_request` action `closed`, the app checks if the PR is merged.
2. If merged, it checks approval state and verifies analyzed `head_sha` matches final PR `head.sha`.
3. If both checks pass, it creates or updates a Confluence page with SQL documentation payload.
4. Publish status is persisted into `APPROVAL_STATE_FILE` for audit and downstream steps.

YAML Config Loader
1. The app reads YAML mappings from `APP_CONFIG_FILE` (default `config/agent.yml`).
2. Supported mapping sections: `llm`, `github`, `confluence`, `bitbucket`, `app`.
3. Environment variables still work and override YAML values when both are set.
4. Example mapped keys:
   - `llm.model`, `llm.temperature`, `llm.pr_summary_max_chars`
   - `github.api_base_url`, `github.token`, `github.approval.command`, `github.approval.label`
   - `confluence.base_url`, `confluence.space`, `confluence.parent_page_id`, `confluence.username`, `confluence.api_token`

Local Sample Run
1. Put `.sql` files in `sample_input`
2. Ensure `OPENAI_API_KEY` is set if you want live LLM output
3. If you use `OPENAI_BASE_URL`, set it to the API root such as `https://api.openai.com/v1`, not the `/chat/completions` endpoint
4. Run `python -m src.local_batch`
5. Review generated `.json` files in `sample_output`

Run Tests
pytest -q
