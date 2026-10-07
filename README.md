# Context Processor

A FastAPI backend that turns browser context (Bitbucket pull requests, Confluence pages, Outlook email) into AI output. Prompts run through the Codex CLI and are stored in PostgreSQL, so they can be edited without a redeploy.

## Layout

| Path | Purpose |
|------|---------|
| `main.py` | FastAPI app and routes |
| `PromptExecutor.py` | Runs operations (PR review, Confluence, email summary) by building prompts and calling Codex |
| `pr_manager.py`, `confluence_manager.py`, `email_manager.py` | Postgres persistence and external API access for each feature |
| `prompt_db.py` | Prompt storage (connection pool, list/get/update) |
| `ctx-senders/` | Browser scripts that send page context to the API (`pull-request.js`, `confluence.js`, plus `confluence.test.cjs`) |
| `templates/prompt_editor.html` | Web UI for editing prompts |
| `deploy/` | `docker-compose.yaml` (Postgres 16), `db_setup.sql`, `migrations/` |
| `start_environment.sh`, `stop_environment.sh`, `start_server.sh`, `Makefile` | Run and manage the local environment |
| `test_*.py`, `run.py` | Python tests |

## API

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Health check |
| POST | `/pullrequest` | Review a pull request from the posted payload |
| POST | `/confluence` | Confluence operation: `explain`, `rewrite`, `page_update` or `delete` (body: `operation`, `hostname`, `pathname`, `search`, `instruction`) |
| POST | `/emails/summary` | Summarize emails for `start_date`..`end_date` (`refresh` regenerates) |
| GET / DELETE | `/emails/summary/{folder}/{start_date}/{end_date}` | Fetch or delete a stored summary |
| PATCH | `/emails/summary/{folder}/{start_date}/{end_date}/todos/{todo_id}` | Mark a summary to-do completed or not |
| GET | `/prompts/editor` | Prompt editor UI |
| GET | `/prompts`, `/prompts/{key}` | List or read prompts |
| PUT | `/prompts/{key}` | Update a prompt |

Prompt failures return `502`. Invalid Confluence requests return `422`.

## Setup

Requires Python 3, Docker, and the Codex CLI.

```bash
pip install -r requirements.txt
make install-playwright        # Chromium for token capture
cp .env.example .env.local.conf   # then fill in values
make prereq                    # start the Postgres container (pr_postgres_container)
./start_server.sh              # uvicorn main:app on http://localhost:8000
```

Initialize the schema from `deploy/db_setup.sql`, then apply `deploy/migrations/`.

Prompt editor: http://localhost:8000/prompts/editor

### Configuration (`.env.local.conf`)

- `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`: Postgres connection
- `BITBUCKET_TOKEN`: Bitbucket access
- `PERSONAL_ACCESS_TOKEN`, `CONFLUENCE_URL`, `CONFLUENCE_PAGE_ID`: Confluence access
- `CODEX_TIMEOUT_SECONDS`: Codex run timeout (default 600)
- `EMAIL_READER_DIR`: location of the `sysapp/email-reader` program used to collect Outlook email (default `~/sysapp/email-reader`)

### Make targets

`prereq` (start Postgres), `restart` and `kill` (uvicorn), `install-playwright`.

## Browser scripts

The scripts in `ctx-senders/` are self-contained IIFEs. Load one on the matching Bitbucket or Confluence page; it collects the page context, posts it to the API and renders the Markdown response.
