# AI SQL Summary Agent

Analyze SQL and PL/SQL changes, generate natural language summaries, suggest documentation updates, and publish to Confluence. Deploy as a service with GitHub/Bitbucket webhooks, or use via API.

**✨ Key Features:** Multi-tenant setup, per-repo custom prompts (zero code changes), LangChain + OpenAI integration, automatic PR comments, GitHub approval workflow, Confluence publishing.

---

## Quick Start

### 1. Prerequisites
- Python 3.10+
- OpenAI API key (or compatible LLM endpoint)
- GitHub/Bitbucket (for webhook integration)
- Confluence (for documentation publishing)

### 2. Setup
```bash
# Install dependencies
pip install -r requirements.txt

# Set environment variables
export OPENAI_API_KEY="sk-..."
export OPENAI_MODEL="gpt-4"

# Start the API
uvicorn src.main:app --host 0.0.0.0 --port 8000

# Open docs
http://localhost:8000/docs
```

### 3. Test Endpoint
```bash
curl -X POST http://localhost:8000/summarize \
  -H "Content-Type: application/json" \
  -d '{
    "previous_sql": "create table emp(id int);",
    "current_sql": "create table emp(id int, name varchar(100));"
  }'
```

---

## Multi-Repo Registration

### Register a Repository

```bash
curl -X POST http://localhost:8000/repos/register \
  -H "Content-Type: application/json" \
  -d '{
    "github": {
      "owner": "myorg",
      "name": "my-sql-repo",
      "token": "ghp_...",
      "webhook_secret": "my-webhook-secret"
    },
    "llm": {
      "api_key": "sk-...",
      "model": "gpt-4",
      "temperature": 0.1,
      "prompt_set": "default"
    },
    "confluence": {
      "base_url": "https://myorg.atlassian.net/wiki",
      "space": "SQLDB",
      "username": "bot@myorg.com",
      "api_token": "ATATT...",
      "default_parent_page_id": "123456"
    }
  }'
```

### CRUD Operations
- **POST** `/repos/register` - Register new repo
- **GET** `/repos/{owner}/{repo}` - View registration
- **PUT** `/repos/{owner}/{repo}` - Update full registration
- **DELETE** `/repos/{owner}/{repo}` - Delete registration

Registrations are stored in `config/agent.yml` under `repos:` section.

---

## Custom Prompts (No Code Changes!)

### Problem Solved
Before: Custom prompts required editing `config/prompts.yml` and redeploying code.  
After: Custom prompts are provided during registration, stored per-repo in `config/agent.yml`.

### Register with Custom Prompts

```bash
curl -X POST http://localhost:8000/repos/register \
  -H "Content-Type: application/json" \
  -d '{
    "github": {...},
    "llm": {"prompt_set": "analytics-specialized", ...},
    "confluence": {...},
    "prompts": {
      "analytics-specialized": {
        "summary": {
          "system": "You are an analytics SQL expert.",
          "user": "Analyze this SQL change.\n{format_instructions}\n{sql_diff}"
        },
        "doc_suggestion": {
          "system": "You document analytics changes.",
          "user": "Suggest doc updates.\n{format_instructions}\n{summary}\n{sql_diff}"
        },
        "pr_comment": {
          "system": "You comment on analytics PRs.",
          "user": "Summarize briefly.\n{format_instructions}\n{filename}\n{sql_diff}"
        },
        "publish": {
          "system": "You create analytics documentation.",
          "user": "Document this query.\n{format_instructions}\n{pr_summary}\n{sql_diff}"
        }
      }
    }
  }'
```

### Update Prompts Anytime

```bash
curl -X PUT http://localhost:8000/repos/myorg/my-repo/prompts \
  -H "Content-Type: application/json" \
  -d '{
    "v2-improved": {
      "summary": {...},
      "doc_suggestion": {...},
      "pr_comment": {...},
      "publish": {...}
    }
  }'
```

### Prompt Set Structure

Each prompt set requires **4 prompt types**: `summary`, `doc_suggestion`, `pr_comment`, `publish`.

#### 1. `summary` - SQL Diff Analysis
**Variables:** `{sql_diff}`, `{change_type}`, `{affected_objects}`, `{format_instructions}`  
**Output:** JSON with `summary` (string), `change_type` (string), `impact_level` (string)

#### 2. `doc_suggestion` - Documentation Updates
**Variables:** `{summary}`, `{sql_diff}`, `{format_instructions}`  
**Output:** JSON with `suggested_doc_updates` (list), `rationale` (string)

#### 3. `pr_comment` - GitHub PR Comment
**Variables:** `{filename}`, `{status}`, `{sql_diff}`, `{format_instructions}`  
**Output:** JSON with `summary` (string)

#### 4. `publish` - Confluence Documentation
**Variables:** `{pr_summary}`, `{change_type}`, `{affected_objects}`, `{sql_diff}`, `{format_instructions}`  
**Output:** JSON with `full_summary`, `sql_description`, `object_types`, `table_details`, `join_details`, `filter_details`, `affected_objects`, `page_heading`

### Prompt Resolution

```
1. Check repo-specific prompts (from config/agent.yml)
2. If found → use that
3. If not found → fall back to default prompts (from config/prompts.yml)
4. If still not found → raise error
```

### Best Practices

✅ Keep prompts focused (one purpose per prompt)  
✅ Use specific domain knowledge in system messages  
✅ Validate all `{variable}` references exist  
✅ Always include `{format_instructions}` for JSON output  
✅ Test custom prompts before production  

---

## GitHub Webhook Setup

### 1. Set Webhook Secret
```bash
export GITHUB_WEBHOOK_SECRET="your-webhook-secret"
```

### 2. Configure GitHub
In repository Settings > Webhooks:
- **Payload URL:** `https://your-domain.com/github-webhook`
- **Content type:** `application/json`
- **Secret:** Same as `GITHUB_WEBHOOK_SECRET`
- **Events:** Pull requests, Push, Issue comments, Pull request reviews

### 3. How It Works

**On PR Open/Sync:**
- Analyzes SQL file changes
- Posts sticky summary comment to PR
- Shows change type, impact level, affected objects

**On Comment with Approval Command:**
- Records approval when comment contains `/approve-sql-doc`
- Updates PR comment to reflect approval

**On PR Merge:**
- Verifies approval and SHA match
- Creates/updates Confluence page with full SQL documentation
- Stores publish status in `APPROVAL_STATE_FILE`

### GitHub Approval Tracking
Approval is recorded via any of:
- PR comment containing `/approve-sql-doc` (configurable)
- PR label `sql-doc-approved` (configurable)
- PR review submitted with state `approved`

---

## Confluence Integration

### Path Mappings
Define which SQL files go to which parent page:

```yaml
confluence:
  base_url: https://company.atlassian.net/wiki
  space: SQLDB
  path_mappings:
    - sql_path_prefix: ddl/
      parent_page_id: '111111'
    - sql_path_prefix: dml/
      parent_page_id: '222222'
    - sql_path_prefix: soft/
      parent_page_id: '333333'
```

On publish, the longest matching prefix determines the parent page. If no match, uses `default_parent_page_id`.

---

## Local Batch Processing

Test without webhooks:

```bash
# 1. Place .sql files in sample_input/
# 2. Set OPENAI_API_KEY
# 3. Run:
python -m src.local_batch

# 4. Review results in sample_output/
```

---

## Project Structure

```
src/
  main.py                 # FastAPI app
  config.py              # Settings & YAML loading
  models.py              # Pydantic schemas
  api/
    routes.py            # HTTP endpoints & webhook handlers
  agents/
    orchestrator.py      # SQL analysis orchestrator
    sql_summarizer.py    # SQL diff analysis
    doc_suggester.py     # Documentation suggestions
  tools/
    llm_tools.py         # LangChain LLM service (ChatOpenAI)
    prompt_store.py      # Prompt registry (repo + defaults)
    sql_parser.py        # SQL parsing & analysis
    git_tools.py         # GitHub/Bitbucket API helpers
    confluence_tools.py  # Confluence publishing
    repo_registry.py     # YAML-based repo storage
    approval_store.py    # Approval state tracking
config/
  agent.yml              # Repo registrations
  prompts.yml            # Default prompt templates
tests/                   # pytest test suite (38 tests, all passing)
```

---

## API Reference

### POST /repos/register
Register repository with GitHub, LLM, Confluence, and optional custom prompts.

**Response:**
```json
{
  "ok": true,
  "message": "Repository registered",
  "repo": "owner/repo"
}
```

---

### PUT /repos/{owner}/{repo}/prompts
Add or update custom prompt sets.

**Request:**
```json
{
  "prompt-set-name": {
    "summary": {"system": "...", "user": "..."},
    "doc_suggestion": {"system": "...", "user": "..."},
    "pr_comment": {"system": "...", "user": "..."},
    "publish": {"system": "...", "user": "..."}
  }
}
```

**Response:**
```json
{
  "ok": true,
  "message": "Repository prompts updated",
  "repo": "owner/repo",
  "prompts": {...}
}
```

---

### POST /summarize
Analyze SQL manually (no webhook).

**Request:**
```json
{
  "previous_sql": "...",
  "current_sql": "...",
  "diff": "..." (optional)
}
```

**Response:**
```json
{
  "ok": true,
  "result": {
    "summary": "...",
    "change_type": "...",
    "impact_level": "...",
    "affected_objects": [...],
    "suggested_doc_updates": [...],
    "markdown": "..."
  }
}
```

---

### POST /github-webhook
GitHub webhook handler (auto-called by GitHub).

---

## Environment Variables

### LLM Configuration
```
OPENAI_API_KEY              # Required
OPENAI_BASE_URL             # Default: https://api.openai.com/v1
OPENAI_MODEL                # Default: gpt-4o-mini
OPENAI_TEMPERATURE          # Default: 0.1
OPENAI_PROMPT_SET           # Default: default
```

### GitHub
```
GITHUB_API_BASE_URL         # Default: https://api.github.com
GITHUB_TOKEN                # Personal access token
GITHUB_WEBHOOK_SECRET       # Webhook secret (optional)
GITHUB_APPROVAL_COMMAND     # Default: /approve-sql-doc
GITHUB_APPROVAL_LABEL       # Default: sql-doc-approved
```

### Confluence
```
CONFLUENCE_BASE_URL         # Wiki instance URL
CONFLUENCE_SPACE            # Space key or ID
CONFLUENCE_PARENT_PAGE_ID   # Default parent page
CONFLUENCE_USERNAME         # Bot username
CONFLUENCE_API_TOKEN        # Confluence API token
```

### Bitbucket (optional)
```
BITBUCKET_API_BASE_URL      # Default: https://api.bitbucket.org/2.0
BITBUCKET_TOKEN             # Personal access token
```

### App Configuration
```
APP_HOST                    # Default: 0.0.0.0
APP_PORT                    # Default: 8000
APP_CONFIG_FILE             # Default: config/agent.yml
PROMPTS_FILE                # Default: config/prompts.yml
APPROVAL_STATE_FILE         # Default: .ai_sql_agent/approval_state.json
REPO_REGISTRY_FILE          # Default: config/agent.yml
```

---

## Configuration Files

### config/agent.yml
YAML registry of repositories:
```yaml
repos:
  owner/repo-name:
    github:
      owner: owner
      name: repo-name
      token: ${GITHUB_TOKEN_...}
      webhook_secret: secret
    llm:
      api_key: ${LLM_API_KEY_...}
      model: gpt-4
      prompt_set: default
    confluence:
      base_url: https://...
      space: SQLDB
    prompts:                           # Optional custom prompts
      custom-set:
        summary: {...}
        doc_suggestion: {...}
        pr_comment: {...}
        publish: {...}
```

### config/prompts.yml
Default prompt templates (fallback):
```yaml
prompt_sets:
  default:
    summary:
      system: "..."
      user: "..."
    doc_suggestion:
      system: "..."
      user: "..."
    pr_comment:
      system: "..."
      user: "..."
    publish:
      system: "..."
      user: "..."
```

---

## Testing

Run all tests:
```bash
pytest -v          # Verbose output
pytest -q          # Quiet output
```

**Coverage:** 38 tests, all passing ✅

**Key scenarios:**
- Default prompt resolution
- Repo-specific prompt resolution
- LLM client initialization
- Runtime config building
- GitHub webhook validation
- Confluence publishing
- Approval tracking

---

## Architecture Highlights

### Multi-Tenant Design
- Per-repo GitHub, LLM, Confluence settings
- Per-repo custom prompts (no code changes)
- Runtime config resolution from webhook payload

### LLM Integration
- LangChain + ChatOpenAI (type-safe, structured output)
- Pydantic models enforce output validation
- Strict mode: fails fast on misconfiguration

### Prompt System
- Resolution: repo-specific → defaults
- All 4 prompt types in one custom set
- Variable interpolation at runtime

### Data Storage
- YAML-based repo registry
- Approval state stored per-repo
- No database required

---

## Troubleshooting

### Prompt Set Not Found
**Error:** `Prompt set not found: custom-set`

**Solution:** Verify `llm.prompt_set` matches the key in `prompts` object exactly.

### Custom Prompts Not Being Used
1. Check repo is registered with custom `prompt_set`
2. Verify `config/agent.yml` has `prompts` section
3. Ensure all 4 prompt types defined: summary, doc_suggestion, pr_comment, publish
4. Check for typos in variable names: `{sql_diff}`, `{format_instructions}`, etc.

### LLM API Errors
1. Verify `OPENAI_API_KEY` is set and valid
2. Check `OPENAI_MODEL` exists
3. If using custom endpoint, verify `OPENAI_BASE_URL` format (e.g., `https://api.openai.com/v1`, not `/chat/completions`)

### Webhook Not Triggering
1. Verify GitHub webhook URL points to `/github-webhook` endpoint
2. Check `GITHUB_WEBHOOK_SECRET` matches GitHub webhook secret
3. Confirm repo is registered in `config/agent.yml`

---

## Next Steps

1. **Register your first repo** via `POST /repos/register`
2. **Create a GitHub webhook** pointing to `/github-webhook`
3. **Open a PR** with SQL changes to test
4. **Monitor PR comments** for auto-generated summaries
5. **Approve the merge** to publish to Confluence
6. **Customize prompts** via `PUT /repos/{owner}/{repo}/prompts` as needed

---

## License & Support

For issues, questions, or contributions, see the project repository.
