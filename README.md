# context_processor

Browser-side scripts (in `ctx-senders/`) that capture page/API context and render it with `marked` (and `DOMPurify` for Confluence).

- `ctx-senders/confluence.js` – Confluence page context sender
- `ctx-senders/pull-request.js` – Pull request context sender
- `ctx-senders/confluence.test.cjs` – tests for the Confluence sender

Each script is a self-contained IIFE; load it in the page (e.g. via a userscript or console).
