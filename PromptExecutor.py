import subprocess
import requests
from pr_manager import read_pr_ai_response, write_pr_ai_response, delete_pr_ai_response
from confluence_manager import read_confluence_ai_response, write_confluence_ai_response, delete_confluence_ai_response
import json

BITBUCKET_TOKEN = "REDACTED"
CONFLUENCE_URL = "https://confluence.rakuten-it.com/confluence"
PERSONAL_ACCESS_TOKEN = "REDACTED"
headers = {
    "Authorization": f"Bearer {PERSONAL_ACCESS_TOKEN}",
    "Accept": "application/json",
    "Content-Type": "application/json"  # Required for PUT requests with JSON body
}


def run_codex(prompt: str):
    print(f"\n\n--> Running codex...")
    result = subprocess.run(
        ["codex", "exec", prompt],
        check=True,
        text=True,
        capture_output=True,
    )
    return result.stdout


def pull_request_data(hostname, pathname):
    url = f"https://{hostname}/rest/api/latest{pathname}"
    response = requests.get(url, headers={
        "Authorization": f"Bearer {BITBUCKET_TOKEN}",
        "Accept": "application/json"
    })
    return response.json()


def get_pr_id(pathname: str) -> str:
    pr_id_data = pathname.split('/')
    pr_id = f"{pr_id_data[2]}__{pr_id_data[4]}__{pr_id_data[6]}"
    return pr_id


def pull_request_operation(payload: dict) -> str:
    operation = payload.get('operation')
    if operation in ['explain', 'review', 'delete', 'test_checklist']:
        pr_id = get_pr_id(payload.get('pathname'))

        if payload['operation'] == "delete":
            if delete_pr_ai_response(pr_id):
                return f"Success: Deleted entry {pr_id}"
            else:
                return "Failed: None Deleted"

        response = read_pr_ai_response(pr_id) or {}
        if response.get(operation):
            return response[operation]

        pr_data = pull_request_data(payload['hostname'], payload['pathname'])
        print(pr_data)
        prompt = None
        if payload['operation'] == "review":
            prompt = f"""
You are a Pull Request Review Assistant (Senior Software/Security Engineer).
Review ONLY the changes shown in the provided git diff. Your priorities are:
1) Security (prevent vulnerabilities and data exposure)
2) Stability/Correctness (avoid regressions, breaking changes, edge cases)
3) Maintainability (readability, consistency, best practices)
4) Performance (only when meaningful or clearly impacted)

Context:
- You may not have full repository context. If something is unclear, state assumptions
  and ask targeted follow-up questions rather than guessing.
- Do not invent repository policies, APIs, or files that are not visible in the diff.
- Do not suggest large refactors unless necessary for security/stability.

What to look for (non-exhaustive):
Security:
- Injection: SQL/NoSQL/LDAP/command/template injection
- AuthN/AuthZ: missing checks, privilege escalation, insecure direct object references
- Data handling: secrets in code/logs, PII leakage, improper logging, weak encryption
- Input validation: path traversal, SSRF, deserialization, file upload risks
- Web risks: XSS, CSRF, CORS misconfig, open redirects, session/cookie flags
- Dependency/config changes: vulnerable packages, unsafe defaults, debug enabled
- Supply chain: scripts in CI, build steps, downloaded binaries, signature verification

Stability/Correctness:
- Breaking changes: public API changes, schema/migration issues, config changes
- Error handling: swallowed exceptions, wrong retries/timeouts, inconsistent behavior
- Concurrency: races, deadlocks, shared mutable state, async misuse
- Resource mgmt: leaks (files/sockets/db connections), unbounded memory growth
- Backwards compatibility: wire formats, serialization changes, feature flags

Maintainability/Quality:
- Coding standards and readability, duplication, unclear naming, missing docs/comments
- Test coverage: missing/weak tests for risky logic; suggest concrete tests
- Observability: meaningful logs/metrics without leaking sensitive info

How to respond:
- Be concrete and reference specific files/lines/hunks from the diff when possible.
- Prefer actionable recommendations: what to change and why.
- If you propose a fix, show a minimal patch snippet (pseudo-diff is fine).
- If you cite standards/docs, prefer widely accepted sources (e.g., OWASP ASVS, OWASP
  Top 10, CWE). Do not fabricate links; if unsure, name the standard without a URL.

Severity model:
- Critical: likely exploitable security issue or data loss; should block merge
- High: serious bug/security weakness; should be fixed before merge
- Medium: important but not immediately dangerous; fix soon
- Low: minor improvement; optional
- Nit: style/readability; non-blocking

Output format (Markdown):
1) Executive Summary (2-5 bullets)
2) Risk Table (Finding | Severity | Location | Impact | Recommendation)
3) Detailed Findings
   - Group by file, include hunk context and reasoning
4) Suggested Patches (only for the highest-impact issues)
5) Tests & Verification
   - Specific tests to add/update
   - How to validate (commands/checks conceptually; do not claim you ran anything)
6) Breaking Changes / Migration Notes (if any)
7) Questions / Missing Context (only if needed to proceed safely)

PR Diff (git diff):
```diff
{pr_data['diffs']}
"""

        elif payload['operation'] == "test_checklist":
            prompt = f"""
Act as a Senior Quality Assurance Engineer. You are an expert at deriving *risk-based* test checklists from a git diff only.

Input (ONLY source of truth):
- Git diff:
{pr_data['diffs']}

Your task:
Generate a prioritized, actionable checklist of tests to run before merging this PR, based strictly on what changed in the diff.

How to analyze (follow this order):
1) Parse the diff and identify:
   - Files changed (added/modified/deleted/renamed if visible).
   - Key functions/classes/endpoints/configs touched (use names present in the diff).
   - Data shape/contract changes (request/response fields, schemas, models, DTOs).
   - Control-flow and behavior changes (conditionals, validation, error handling, retries).
   - Non-functional risk indicators (auth/permissions, logging/metrics, caching, concurrency, performance, migrations).

2) Infer impacted behaviors conservatively:
   - If the user-facing intent is unclear from the diff, do NOT guess; instead produce “Open Questions”.

Output requirements (Markdown):
### 1) Change Summary (from diff)
- Bullet list of the most important behavioral changes.
- Reference file paths (and function/class names when present).

### 2) Test Checklist (prioritized)
Use priority tags:
- P0 = must-test before merge (security, data integrity, breaking contract, core flows, high regression risk)
- P1 = should-test (important edges, error paths, key regressions)
- P2 = good-to-test (lower risk, polish, rare conditions)

For EACH checklist item, use this exact structure:
- [Px] <specific test to perform>
  - Area: <API/UI/DB/Auth/Config/Job/Integration/Other>
  - Why (risk): <brief risk statement tied to the change>
  - Evidence: <file path + symbol/line context from diff that triggered this item>
  - Expected: <clear expected result>

Checklist content rules:
- Be concrete and verifiable. Avoid generic items like “test everything”, “run all tests”, “ensure it works”.
- Include at least:
  - Happy-path tests for changed behavior
  - Negative/invalid-input tests if validation/parsing changed
  - Error-handling tests if exceptions/returns/logging changed
  - Backward-compat/contract tests if data/API shapes changed
  - Regression tests for adjacent functionality implied by the diff

### 3) Open Questions (if any)
- List any unknowns that prevent precise test design, explicitly stating what information is missing and why.

Quality bar:
- Prefer a shorter checklist of high-value tests over a long generic list.
- Every item must trace back to something that actually changed in the diff (via “Evidence”).
"""

        elif payload['operation'] == "explain":
            prompt = f"""
You are a Senior Software Engineer reviewing a Pull Request.

Audience: an engineering manager who does not know this codebase.
Goal: explain what changed and what it means for the product/runtime behavior.

Input (git diff):
{pr_data['diffs']}

Write a SHORT Markdown summary with these sections:

## Overview (1–3 bullets)
- What this PR does in plain English (focus on user/system behavior).

## Key Changes
- Bullet list of the most important changes, grouped by file/module if helpful.
- Mention new/removed functionality, API/contract changes, data flow changes, and noteworthy refactors.

## Breaking / Risky Changes (if any)
- Call out anything that could break runtime behavior, integrations, configs, deployments, DB/schema, or backwards compatibility.
- If none are evident, explicitly say: "No breaking changes identified from the diff."

Rules:
- Prioritize explaining functionality and impact over implementation details.
- Be concise; do not paste the diff or line-by-line commentary.
- If something cannot be determined from the diff, state that clearly rather than guessing.
"""
        if prompt:
            ai_response = run_codex(prompt)
            write_pr_ai_response(pr_id, {
                payload['operation']: ai_response,
            })
            return ai_response

    return "Operation is not recognized"


def get_confluence_id(pathname: str) -> str:
    return pathname.split('/')[5]


def confluence_operation(payload: dict) -> str:
    operation = payload.get('operation')
    if operation in ['rewrite', 'explain', 'delete']:
        confluence_id = get_confluence_id(payload.get('pathname'))

        if payload['operation'] == "delete":
            if delete_confluence_ai_response(confluence_id):
                return f"Success: Deleted entry {confluence_id}"
            else:
                return "Failed: None Deleted"

        response = read_confluence_ai_response(confluence_id) or {}
        if response.get(operation):
            return response[operation]

        current_content, current_version, page_id, page_title = get_confluence_data(payload['hostname'],
                                                                                    payload['pathname'])
        prompt = None

        if payload['operation'] == "explain":
            prompt = f"""
### Role
Act as a **Senior Technical Architect** and **Expert Technical Writer** with strong depth in:
- Computer Science fundamentals (data structures, algorithms, complexity)
- Software Engineering patterns (SOLID, DDD, CQRS, eventing, reliability)
- System Design (scalability, consistency, observability, security)

### Objective
You will be given raw **Atlassian Confluence document content**. Produce a **brief technical summary** in **Markdown**, after carefully analyzing the document end-to-end.

### Method (mandatory)
1. **Deeply analyze the full document first** (do not start writing until you have a coherent mental model).
2. Identify: purpose, scope, key components/services, flows, decisions, constraints, dependencies, risks, and open questions.
3. Prefer **explicit facts from the text**. If you must infer, label it clearly as *Inference* and only when strongly supported.
4. If a requested item is absent, write **“Not specified”** (do not guess).

> Important: Do your reasoning privately. Output **only** the Markdown summary described below.

### Hard Constraints (must follow)
- **Output must be valid Markdown only** (no HTML).
- **Be concise**: maximum **150–200 words** total.
- **No filler** (no preamble, no “In summary”, no meta commentary).
- Avoid hallucinations; keep wording precise and checkable.

### Output Format (Markdown; use exactly these headings)
### Brief Summary
- (3–6 bullets capturing the most important points)

### Key Facts
- (2–6 bullets; include names, numbers, endpoints, configs only if explicitly present; otherwise omit)

### Risks / Gaps
- (1–4 bullets; use “Not specified” where appropriate)

### Open Questions
- (1–4 bullets; only questions that a reader would need answered to implement/operate)

### Input
**Confluence Document Content:**
{current_content}
"""
            ai_response = run_codex(prompt)
            write_confluence_ai_response(confluence_id, {
                payload['operation']: ai_response,
            })
            return ai_response

        elif payload['operation'] == "rewrite":
            prompt = f"""
### Role
Act as a **Principal Software Architect + Technical Documentation Lead** with strong expertise in **Distributed Systems**, **Security**, **Performance Engineering**, and **Atlassian Confluence (Storage Format / XHTML)**.

### Goal
Transform the provided Confluence page content into a **single, coherent, non-redundant, technically rigorous** document that engineering teams can rely on.
This is not a light copy-edit: you will **deduplicate**, **restructure**, and **selectively augment** the content.

---

## Phase 0 — Parse & Build a Mental Model (do NOT output this phase)
1. Identify the page’s purpose, target audience, and implied system context.
2. Extract a tentative outline (sections/subsections).
3. Detect duplicated or near-duplicated information and decide a **single canonical location** for each concept.

---

## Phase 1 — Deduplication & Single-Source-of-Truth Refactor (CRITICAL)
Your top priority is to remove repeated information while preserving meaning.

### Dedup Rules
1. **Collapse duplicates:** If two sections explain the same thing, keep the best-written/most complete version and delete the rest.
2. **Merge partial overlaps:** If sections overlap but each contains unique details, merge into one canonical section.
3. **Replace repetition with references:**
   - When a concept must be mentioned in multiple places, keep one canonical explanation and elsewhere add a short pointer like:
     “See <ac:link>…</ac:link>” (anchor-based).
4. **Standardize terminology:** Use one term per concept (e.g., “Coordinator” vs “Leader”) and apply consistently across the document.
5. **Centralize repeated definitions:** Move repeated definitions into a single “Definitions / Glossary” section and reference it from other sections.
6. **Avoid repeated warnings/notes:** Keep one well-placed warning/note in the most relevant section; elsewhere reference it.

### Anchor/Reference Guidance
- Create stable anchors near canonical sections (e.g., `<ac:structured-macro ac:name="anchor"><ac:parameter ac:name="">rate-limiting</ac:parameter></ac:structured-macro>`).
- Use `<ac:link>` to reference anchors instead of repeating paragraphs.

---

## Phase 2 — Technical Augmentation (only where genuinely helpful)
Add value by filling gaps **without inventing unknown system specifics**.

### Allowed Augmentations
1. **Complexity Analysis:** When algorithms/data structures are present, add time/space complexity using Big-O (e.g., $O(n \log n)$).
2. **Edge Cases & Concurrency:** Add a Confluence **Note** macro for edge cases, failure modes, race conditions, idempotency concerns.
3. **Security & Performance:** Add a **Warning** macro for likely security risks (SQLi, XSS, SSRF, authz gaps), privacy concerns, and performance bottlenecks.
4. **Why + Example:** If a concept is abstract, add a concrete example or a **Tip** macro explaining rationale and tradeoffs.

### Uncertainty Handling (IMPORTANT)
- If key details are missing and cannot be safely inferred, do **NOT** hallucinate.
- Instead, insert a short **Warning** or **Info** macro labeled “Open Question / TODO” with the exact missing detail needed.

---

## Phase 3 — Rewrite, Restructure, and Improve Readability
1. **Executive Summary (Top of Page):**
   Insert an `ac:structured-macro ac:name="info"` containing a concise TL;DR (purpose, key architecture points, how to use/operate).
2. **Engineering-Grade Language:**
   Replace vague statements with precise technical claims (latency/throughput/correctness, failure handling, contracts).
3. **Logical Heading Tree:**
   Use `<h1>`…`<h6>` in a strict semantic hierarchy (no level skipping).
4. **Reduce Noise:**
   Remove redundant filler sentences and repeated “intro” lines per section.
5. **Keep code blocks intact:**
   Do not modify the internal content of existing `<ac:structured-macro ac:name="code">...</ac:structured-macro>` blocks.
   You may add explanation **before/after** code blocks (inputs/outputs, assumptions, pitfalls).

---

## Output Constraints (ABSOLUTE)
1. Output **ONLY** valid **Confluence Storage Format (XHTML)** — no Markdown fences, no commentary.
2. Preserve Confluence namespaces/tags: `ac:*`, `ri:*`, and valid XHTML.
3. Preserve existing links/macros unless you are removing duplicated sections; do not break references.
4. When adding macros, use:
   - `<ac:structured-macro ac:name="tip">` for best practices.
   - `<ac:structured-macro ac:name="note">` for edge cases / operational gotchas.
   - `<ac:structured-macro ac:name="warning">` for security/perf risks and TODOs requiring attention.
   - `<ac:structured-macro ac:name="expand">` for deep dives that would clutter the main narrative.

---

### Input Confluence Content
{current_content}
"""
        ai_response = run_codex(prompt)

        next_version = current_version + 1
        update_payload = {
            "id": page_id,
            "type": "page",
            "title": page_title,
            "version": {
                "number": next_version
            },
            "body": {
                "storage": {
                    "value": ai_response,
                    "representation": "storage"
                }
            }
        }

        put_api_url = f"{CONFLUENCE_URL}/rest/api/content/{page_id}"
        print(f"Updating page content at: {put_api_url} with new version: {next_version}")

        try:
            put_response = requests.put(put_api_url, headers=headers, data=json.dumps(update_payload))
            put_response.raise_for_status()

            updated_page_data = put_response.json()
            print(
                f"Page '{updated_page_data['title']}' (ID: {page_id}) successfully updated to version {updated_page_data['version']['number']}.")
            print(f"View page at: {CONFLUENCE_URL}{updated_page_data['_links']['webui']}")

            return ai_response
        except requests.exceptions.HTTPError as http_err:
            print(f"HTTP error occurred: {http_err}")
            print(f"Response status code: {http_err.response.status_code}")
            try:
                error_details = http_err.response.json()
                print(f"Error details from Confluence: {json.dumps(error_details, indent=2)}")
            except json.JSONDecodeError:
                print(f"Error response body: {http_err.response.text}")
        except requests.exceptions.ConnectionError as conn_err:
            print(f"Connection error occurred: {conn_err}. Check CONFLUENCE_URL and network connectivity.")
        except requests.exceptions.Timeout as timeout_err:
            print(f"Timeout error occurred: {timeout_err}. Confluence server might be slow or unreachable.")
        except requests.exceptions.RequestException as req_err:
            print(f"An unexpected request error occurred: {req_err}")
        except KeyError as key_err:
            print(f"Error: Missing expected key in Confluence API response: {key_err}")
        except Exception as e:
            print(f"An unexpected error occurred: {e}")

    return "Operation is not recognized"


def get_confluence_data(hostname, pathname):
    page_id = get_confluence_id(pathname)

    # 1. Fetch Current Page Content and Version
    get_api_url = f"{CONFLUENCE_URL}/rest/api/content/{page_id}?expand=body.storage,version"
    print(f"Fetching page content from: {get_api_url}")

    try:
        get_response = requests.get(get_api_url, headers=headers)
        get_response.raise_for_status()
        page_data = get_response.json()

        current_content = page_data['body']['storage']['value']
        current_version = page_data['version']['number']
        page_title = page_data['title']

        print(f"Successfully fetched page '{page_title}' (ID: {page_id}). Current version: {current_version}")
        print("------ Content ------")
        print(current_content)
        print("---------------------")
        return current_content, current_version, page_id, page_title

    except requests.exceptions.HTTPError as http_err:
        print(f"HTTP error occurred: {http_err}")
        print(f"Response status code: {http_err.response.status_code}")
        try:
            error_details = http_err.response.json()
            print(f"Error details from Confluence: {json.dumps(error_details, indent=2)}")
        except json.JSONDecodeError:
            print(f"Error response body: {http_err.response.text}")
    except requests.exceptions.ConnectionError as conn_err:
        print(f"Connection error occurred: {conn_err}. Check CONFLUENCE_URL and network connectivity.")
    except requests.exceptions.Timeout as timeout_err:
        print(f"Timeout error occurred: {timeout_err}. Confluence server might be slow or unreachable.")
    except requests.exceptions.RequestException as req_err:
        print(f"An unexpected request error occurred: {req_err}")
    except KeyError as key_err:
        print(f"Error: Missing expected key in Confluence API response: {key_err}")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
