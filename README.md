# Context Processor

## Restart the server

Kill the running process and restart:

```bash
pkill -f "uvicorn main:app" ; cd /Users/ts-amar.vashishth/context_processor && ./start_server.sh
```

Or if you need the full environment (Rancher Desktop + Postgres + FastAPI):

```bash
pkill -f "uvicorn main:app" ; cd /Users/ts-amar.vashishth/context_processor && ./start_environment.sh
```

The API will be available at `http://localhost:8000` and the prompt editor at `http://localhost:8000/prompts/editor`.

## Confluence operation flow

The injected `ctx-senders/confluence.js` sends the operation and page URL fields
(`hostname`, `pathname`, `search`) to `/confluence`. The server fetches the current
page's storage body and version from the configured `CONFLUENCE_URL`.

| Button | Operation | Stored prompt | Inputs | Action |
| --- | --- | --- | --- | --- |
| Explain | `explain` | `confluence_explain` | `{confluence_content}` | Show Markdown; cache by page version and rendered prompt |
| Rewrite | `rewrite` | `confluence_rewrite` | `{confluence_content}` | Validate full storage XHTML, replace page body, reload |
| Send instruction | `page_update` | `confluence_page_update` | `{confluence_content}`, `{instruction}` | Apply targeted edit to full body, validate, replace, reload |
| Clear Cache | `delete` | None | Page ID | Clear generated results; leaves the Confluence page intact |

Rewrite and page updates always use the latest page and never reuse cached output.
Updates retain the page title and increment the fetched version; Confluence version
conflicts are returned as errors. Unchanged output does not create a new version.
Malformed model output and upstream failures return HTTP 502; invalid requests
return HTTP 422. The browser reloads only after a successful write operation.
XML validation checks structure; factual accuracy and preservation still depend on
the model's output and are not proven by parsing.

The prompt editor requires the inputs listed above to remain in each template.
Placeholder substitution runs once, preserving literal placeholders inside page
content or instructions. The startup SQL contains the revised prompts; existing
installations can apply only these three updates with
`deploy/migrations/20260929_confluence_prompts.sql` (back up customized prompts first).
Reinject the sender script after updating it.

Run the local regression checks with `python -m unittest discover -v` and
`node --test ctx-senders/confluence.test.cjs`. These mock model/Confluence calls and
do not publish changes to real pages.
