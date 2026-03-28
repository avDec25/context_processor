# Context Processor - Changes Summary

## Overview

Your FastAPI application has been significantly improved with two major enhancements:

1. **Concurrent Request Handling** - Can now process multiple requests simultaneously
2. **Database-Driven Prompts** - Large prompt templates moved to PostgreSQL

---

## 1. Concurrent Request Handling

### Problem
The application could only handle **one request at a time** because blocking operations (subprocess calls, HTTP requests) were blocking the entire event loop.

### Solution
All blocking I/O operations now run in thread pools using `asyncio.run_in_executor()`, allowing the event loop to handle multiple requests concurrently.

### Changes Made

#### Modified Files:
- **PromptExecutor.py**:
  - `run_codex()` → async, runs subprocess in thread pool
  - `pull_request_data()` → async, runs HTTP requests in thread pool
  - `pull_request_operation()` → async
  - `confluence_operation()` → async
  - `get_confluence_data()` → async with thread pool executors

- **main.py**:
  - Updated endpoints to `await` async operations
  - Added shutdown handler for cleanup

### Benefits
✅ Multiple concurrent requests
✅ Better resource utilization
✅ Improved throughput
✅ Same functionality, just async

---

## 2. Database-Driven Prompts

### Problem
Massive prompt templates (500+ lines each) were hardcoded in PromptExecutor.py, making the code:
- Hard to read and maintain
- Difficult to update without redeploying
- Cluttered with huge multi-line strings

### Solution
Prompts are now stored in a PostgreSQL database with intelligent keys, fetched asynchronously when needed.

### Changes Made

#### New Files:
1. **`init_prompts_db.py`** - Database initialization script
   - Creates `prompts` table
   - Populates with all 5 prompts
   - Uses UPSERT for safe re-runs

2. **`prompt_db.py`** - Database connection module
   - Connection pooling (2-10 connections)
   - Async prompt retrieval
   - Template formatting with data

3. **`requirements.txt`** - Python dependencies
   - FastAPI, uvicorn, requests, psycopg2-binary

4. **`.env.example`** - Environment variables template

5. **`DATABASE_SETUP.md`** - Complete setup guide

#### Modified Files:
- **PromptExecutor.py**:
  - Removed 5 hardcoded prompts (~2000 lines total)
  - Added `from prompt_db import get_prompt_with_data`
  - Replaced prompt strings with database calls:
    ```python
    # Before:
    prompt = f"""...huge prompt..."""

    # After:
    prompt = await get_prompt_with_data('pr_review', pr_data=pr_data['diffs'])
    ```

- **main.py**:
  - Added shutdown handler to close DB connections

### Prompt Keys (Intelligent Naming)

| Key | Operation | Endpoint |
|-----|-----------|----------|
| `pr_review` | Code review with security focus | POST /pullrequest?operation=review |
| `pr_test_checklist` | Risk-based test checklist | POST /pullrequest?operation=test_checklist |
| `pr_explain` | Explain changes to managers | POST /pullrequest?operation=explain |
| `confluence_explain` | Summarize Confluence doc | POST /confluence?operation=explain |
| `confluence_rewrite` | Rewrite/improve Confluence doc | POST /confluence?operation=rewrite |

### Benefits
✅ Cleaner, more readable code
✅ Update prompts without redeploying
✅ Centralized prompt management
✅ Connection pooling for efficiency
✅ Easy to version control prompts

---

## Setup Instructions

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Setup Database

```bash
# Create PostgreSQL database
psql -U postgres -c "CREATE DATABASE context_processor;"

# Initialize schema and prompts
python init_prompts_db.py
```

Expected output:
```
✓ Connected to database: context_processor
✓ Prompts table created successfully
✓ Inserted/Updated 5 prompts
✓ Database initialization completed successfully!
```

### 3. Configure Environment (Optional)

Copy `.env.example` to `.env` and update if needed:
```bash
cp .env.example .env
# Edit .env with your database credentials
```

### 4. Run Application

```bash
# Development
uvicorn main:app --reload

# Production
uvicorn main:app --host 0.0.0.0 --port 8000 --workers 4
```

---

## File Structure

```
context_processor/
├── main.py                    # FastAPI app (modified)
├── PromptExecutor.py          # Core logic (refactored)
├── prompt_db.py               # NEW: Database module
├── init_prompts_db.py         # NEW: DB initialization
├── pr_manager.py              # Existing
├── confluence_manager.py      # Existing
├── requirements.txt           # NEW: Dependencies
├── .env.example               # NEW: Config template
├── DATABASE_SETUP.md          # NEW: Database guide
└── CHANGES_SUMMARY.md         # This file
```

---

## Environment Variables

```bash
# Database (defaults shown)
DB_HOST=localhost
DB_PORT=5432
DB_NAME=context_processor
DB_USER=postgres
DB_PASSWORD=postgres

# API Tokens (keep secret!)
BITBUCKET_TOKEN=<your_token>
PERSONAL_ACCESS_TOKEN=<your_token>
CONFLUENCE_URL=https://confluence.rakuten-it.com/confluence
```

---

## Testing

### Test Concurrent Requests

```bash
# Terminal 1
curl -X POST http://localhost:8000/pullrequest \
  -H "Content-Type: application/json" \
  -d '{"operation":"review","hostname":"bitbucket.example.com","pathname":"/projects/X/repos/Y/pull-requests/1/diff"}'

# Terminal 2 (immediately after)
curl -X POST http://localhost:8000/pullrequest \
  -H "Content-Type: application/json" \
  -d '{"operation":"explain","hostname":"bitbucket.example.com","pathname":"/projects/X/repos/Y/pull-requests/2/diff"}'
```

Both requests will now process simultaneously instead of one waiting for the other!

### Verify Database Connection

```bash
# Check prompts in database
python -c "
from prompt_db import get_prompt
import asyncio
async def test():
    prompt = await get_prompt('pr_review')
    print(f'✓ Retrieved prompt: {len(prompt)} characters')
asyncio.run(test())
"
```

---

## Performance Impact

### Before:
- ⏱️ Sequential processing (1 request at a time)
- 🐌 Each request blocks others
- ❌ Poor resource utilization
- 📝 2000+ lines of prompt strings in code

### After:
- ⚡ Concurrent processing (multiple requests)
- 🚀 Non-blocking I/O with thread pools
- ✅ Efficient resource utilization
- 🗄️ Clean code with database-backed prompts
- 📈 Connection pooling (2-10 connections)

---

## Maintenance

### Updating Prompts

1. **Edit prompts in `init_prompts_db.py`**
2. **Re-run initialization**:
   ```bash
   python init_prompts_db.py
   ```
3. **No restart needed** - changes take effect on next request

### Or update directly in database:

```sql
UPDATE prompts
SET prompt_text = 'new prompt...',
    updated_at = CURRENT_TIMESTAMP
WHERE key = 'pr_review';
```

### Monitoring

```sql
-- Check active connections
SELECT * FROM pg_stat_activity WHERE datname = 'context_processor';

-- View all prompts
SELECT key, LENGTH(prompt_text), description FROM prompts;
```

---

## Rollback Plan

If issues arise:

1. **Revert concurrent changes**: The async changes are minimal and safe
2. **Use hardcoded prompts**: Prompts are preserved in `init_prompts_db.py`
3. **Database issues**: App will error on startup - check DB connection

---

## Security Notes

⚠️ **IMPORTANT**: I noticed API tokens hardcoded in `PromptExecutor.py`:
- `BITBUCKET_TOKEN` (line 9)
- `PERSONAL_ACCESS_TOKEN` (line 11)

**Recommendation**: Move these to environment variables:

```python
import os

BITBUCKET_TOKEN = os.getenv('BITBUCKET_TOKEN')
CONFLUENCE_URL = os.getenv('CONFLUENCE_URL', 'https://confluence.rakuten-it.com/confluence')
PERSONAL_ACCESS_TOKEN = os.getenv('PERSONAL_ACCESS_TOKEN')
```

---

## Next Steps

Consider:
- [ ] Move API tokens to environment variables
- [ ] Add prompt versioning (history table)
- [ ] Implement prompt caching for frequently used prompts
- [ ] Add metrics/logging for monitoring
- [ ] Build prompt management UI
- [ ] Add automated tests

---

## Questions?

- **Database setup**: See `DATABASE_SETUP.md`
- **Concurrent behavior**: All blocking I/O now runs in thread pools
- **Prompt updates**: Re-run `init_prompts_db.py` or update DB directly
- **Performance**: Connection pooling + async I/O = efficient concurrency

Enjoy your upgraded FastAPI application! 🚀
