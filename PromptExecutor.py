import subprocess
import requests
import os
import sys
import tempfile
import logging
import configparser
import hashlib
import re
import xml.etree.ElementTree as ET
from html.entities import name2codepoint
from urllib.parse import parse_qs, urlsplit
from datetime import date
from pathlib import Path
from pr_manager import read_pr_ai_response, write_pr_ai_response, delete_pr_ai_response
from confluence_manager import read_confluence_ai_response, write_confluence_ai_response, delete_confluence_ai_response
from email_manager import extract_todos, read_email_summary, write_email_summary
import json
import asyncio
from prompt_db import get_prompt_with_data
from dotenv import load_dotenv

logger = logging.getLogger(__name__)
_TRUNCATE = 500


class PromptExecutionError(RuntimeError):
    """Raised when Codex does not produce a usable response."""


def _t(text: str, limit: int = _TRUNCATE) -> str:
    """Return text truncated with a marker when it exceeds limit chars."""
    s = str(text)
    return s if len(s) <= limit else s[:limit] + f"… [{len(s)} chars total]"

# Load environment variables from .env.local.conf
env_path = Path(__file__).parent / '.env.local.conf'
load_dotenv(dotenv_path=env_path)

CODEX_TIMEOUT_SECONDS = int(os.getenv("CODEX_TIMEOUT_SECONDS", "600"))

# sysapp/email-reader owns the actual Outlook connection (Microsoft Graph or
# local AppleScript export). Context Processor drives that same program as a
# subprocess so email collection stays in exactly one place.
EMAIL_READER_DIR = Path(os.getenv("EMAIL_READER_DIR", str(Path.home() / "sysapp" / "email-reader")))
EMAIL_READER_CONFIG = EMAIL_READER_DIR / "config.txt"

BITBUCKET_TOKEN = os.getenv("BITBUCKET_TOKEN", "")
CONFLUENCE_URL = os.getenv("CONFLUENCE_URL", "https://confluence.rakuten-it.com/confluence")
PERSONAL_ACCESS_TOKEN = os.getenv("PERSONAL_ACCESS_TOKEN", "")
headers = {
    "Authorization": f"Bearer {PERSONAL_ACCESS_TOKEN}",
    "Accept": "application/json",
    "Content-Type": "application/json"  # Required for PUT requests with JSON body
}


async def run_codex(prompt: str) -> str:
    if not prompt or not prompt.strip():
        raise PromptExecutionError("Cannot execute an empty prompt")

    logger.info("Running codex (prompt: %s)", _t(prompt))

    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
        tmp_path = f.name

    try:
        # `--full-auto` was removed from `codex exec` in CLI 0.147. These
        # prompts only need inference, so keep execution non-interactive and
        # explicitly deny workspace writes with the supported sandbox option.
        cmd = [
            "codex", "exec",
            "--skip-git-repo-check",
            "--sandbox", "read-only",
            "--ephemeral",
            "-c", "mcp_servers={}",
            "--output-last-message", tmp_path,
            "-",
        ]
        logger.debug("Command: %s", " ".join(cmd))
        try:
            result = await asyncio.to_thread(
                subprocess.run,
                cmd,
                input=prompt,
                text=True,
                capture_output=True,
                timeout=CODEX_TIMEOUT_SECONDS,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise PromptExecutionError(
                f"Codex did not finish within {CODEX_TIMEOUT_SECONDS} seconds"
            ) from exc

        if result.returncode != 0:
            details = (result.stderr or result.stdout or "no error output").strip()
            logger.error("Codex failed with exit code %d: %s", result.returncode, _t(details))
            raise PromptExecutionError(
                f"Codex execution failed with exit code {result.returncode}"
            )

        with open(tmp_path, 'r') as f:
            response = f.read()

        if not response.strip():
            logger.error("Codex completed successfully but returned an empty response")
            raise PromptExecutionError("Codex returned an empty response")

        logger.info("Codex completed with a non-empty response (%d chars)", len(response))
        return response
    finally:
        try:
            os.unlink(tmp_path)
        except FileNotFoundError:
            pass


def _load_email_reader_config() -> configparser.ConfigParser:
    config = configparser.ConfigParser()
    if not config.read(EMAIL_READER_CONFIG):
        raise PromptExecutionError(f"Email reader configuration file not found: {EMAIL_READER_CONFIG}")
    return config


def _email_export_path(config: configparser.ConfigParser, start_date: str, end_date: str) -> Path:
    """Mirror outlook_applescript_export.py's interval_data_path naming convention
    so Context Processor reads back exactly the file that program wrote."""
    output_dir = EMAIL_READER_DIR / config["mail"]["output_directory"]
    configured_name = Path(config["local_outlook"]["data_file"])
    suffix = configured_name.suffix or ".jsonl"
    stem = configured_name.stem if configured_name.suffix else configured_name.name
    return output_dir / f"{stem}_{start_date}_to_{end_date}{suffix}"


def get_email_interval_key(folder: str, start_date: str, end_date: str) -> str:
    return f"{folder}__{start_date}__{end_date}"


async def collect_emails(start_date: str, end_date: str, refresh: bool = False):
    """Collect emails for a date interval the same way sysapp/email-reader does:
    drive outlook_applescript_export.py, which exports Outlook messages to a
    local JSON Lines cache file keyed by the interval, then read that file back."""
    config = _load_email_reader_config()
    data_path = _email_export_path(config, start_date, end_date)
    folder = config.get("local_outlook", "folder", fallback="Inbox")

    cmd = [
        sys.executable, str(EMAIL_READER_DIR / "outlook_applescript_export.py"),
        "--config", str(EMAIL_READER_CONFIG),
        "--start-date", start_date,
        "--end-date", end_date,
    ]
    if refresh:
        cmd.append("--refresh")

    logger.info("Collecting emails for %s to %s (folder: %s)", start_date, end_date, folder)
    result = await asyncio.to_thread(
        subprocess.run, cmd, cwd=str(EMAIL_READER_DIR), text=True, capture_output=True, check=False,
    )
    if result.returncode != 0:
        details = (result.stderr or result.stdout or "no error output").strip()
        logger.error("Email export failed with exit code %d: %s", result.returncode, _t(details))
        raise PromptExecutionError(f"Email export failed with exit code {result.returncode}: {_t(details, 300)}")

    if not data_path.is_file():
        raise PromptExecutionError(f"Email export completed but expected file was not created: {data_path.name}")

    emails = _read_email_export(data_path)

    return emails, folder, data_path


def _read_email_export(data_path: Path) -> list:
    """Read the email-reader's JSON feed, whether it is an array or JSON Lines."""
    raw_data = data_path.read_text(encoding="utf-8").strip()
    if not raw_data:
        return []

    if raw_data.startswith("["):
        try:
            emails = json.loads(raw_data)
        except json.JSONDecodeError as exc:
            raise PromptExecutionError(
                f"Invalid JSON in {data_path.name}: {exc.msg}"
            ) from exc
        if not isinstance(emails, list):
            raise PromptExecutionError(f"Expected a JSON array in {data_path.name}")
        return emails

    emails = []
    for line_number, line in enumerate(raw_data.splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            emails.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise PromptExecutionError(
                f"Invalid JSON on line {line_number} of {data_path.name}: {exc.msg}"
            ) from exc
    return emails


async def email_summary_operation(payload: dict) -> dict:
    start_date = (payload.get('start_date') or '').strip()
    end_date = (payload.get('end_date') or '').strip()
    refresh = bool(payload.get('refresh', False))

    if not start_date or not end_date:
        raise PromptExecutionError("Both 'start_date' and 'end_date' are required (YYYY-MM-DD)")
    try:
        start = date.fromisoformat(start_date)
        end = date.fromisoformat(end_date)
    except ValueError as exc:
        raise PromptExecutionError("Dates must use ISO format YYYY-MM-DD") from exc
    if start > end:
        raise PromptExecutionError("'start_date' must be on or before 'end_date'")

    if not refresh:
        probed_folder = _load_email_reader_config().get("local_outlook", "folder", fallback="Inbox")
        cached = read_email_summary(get_email_interval_key(probed_folder, start_date, end_date))
        if cached and cached.get('ai_summary'):
            return cached

    emails, folder, data_path = await collect_emails(start_date, end_date, refresh)
    interval_key = get_email_interval_key(folder, start_date, end_date)

    prompt = await get_prompt_with_data(
        'email_interval_summary',
        folder=folder,
        start_date=start_date,
        end_date=end_date,
        email_count=len(emails),
        email_data=json.dumps(emails, ensure_ascii=False, indent=2),
    )
    if not prompt:
        raise PromptExecutionError("Failed to load prompt template 'email_interval_summary'")

    ai_summary = await run_codex(prompt)

    record = {
        'interval_key': interval_key,
        'folder': folder,
        'start_date': start_date,
        'end_date': end_date,
        'email_count': len(emails),
        'emails': emails,
        'ai_summary': ai_summary,
        'todos': extract_todos(ai_summary),
    }
    write_email_summary(record)

    # The emails are now durably stored in Postgres (record['emails']); the
    # exporter's local .jsonl was only a temporary hand-off file, so remove it
    # from its original place in sysapp/email-reader/downloads.
    try:
        data_path.unlink()
        logger.info("Removed temporary export file %s after saving to Postgres", data_path)
    except OSError as exc:
        logger.warning("Could not remove temporary export file %s: %s", data_path, exc)

    return record


async def pull_request_data(hostname, pathname):
    # Replace /overview with /diff to get the actual diff content
    if pathname.endswith('/overview'):
        pathname = pathname.replace('/overview', '/diff')

    url = f"https://{hostname}/rest/api/latest{pathname}"
    logger.info("Fetching PR data from: %s", url)

    loop = asyncio.get_event_loop()
    # Run the blocking HTTP request in a thread pool executor
    response = await loop.run_in_executor(
        None,
        lambda: requests.get(url, headers={
            "Authorization": f"Bearer {BITBUCKET_TOKEN}",
            "Accept": "application/json"
        })
    )

    # Check for errors
    if response.status_code != 200:
        return {
            'message': f'Error fetching PR data: {response.text}',
            'status-code': response.status_code
        }

    return response.json()


def get_pr_id(pathname: str) -> str:
    pr_id_data = pathname.split('/')
    pr_id = f"{pr_id_data[2]}__{pr_id_data[4]}__{pr_id_data[6]}"
    return pr_id


async def pull_request_operation(payload: dict) -> str:
    operation = payload.get('operation')
    if operation in ['explain', 'review', 'delete', 'test_checklist']:
        pr_id = get_pr_id(payload.get('pathname'))

        if payload['operation'] == "delete":
            if delete_pr_ai_response(pr_id):
                return f"Success: Deleted entry {pr_id}"
            else:
                return "Failed: None Deleted"

        response = read_pr_ai_response(pr_id) or {}
        cached_response = response.get(operation)
        if isinstance(cached_response, str) and cached_response.strip():
            return cached_response

        pr_data = await pull_request_data(payload['hostname'], payload['pathname'])
        logger.info("PR data keys: %s", list(pr_data.keys()))

        # Extract diff content and metadata
        diff_content = pr_data.get('diffs') or pr_data.get('diff') or str(pr_data)
        from_hash = pr_data.get('fromHash', 'unknown')
        to_hash = pr_data.get('toHash', 'unknown')
        context_lines = pr_data.get('contextLines', 'default')
        is_truncated = pr_data.get('truncated', False)
        truncated_warning = "- ⚠️ WARNING: Diff is truncated! Full changes not visible." if is_truncated else ""

        prompt = None
        if payload['operation'] == "review":
            prompt = await get_prompt_with_data(
                'pr_review',
                pr_data=diff_content,
                from_hash=from_hash,
                to_hash=to_hash,
                context_lines=context_lines,
                truncated_warning=truncated_warning
            )

        elif payload['operation'] == "test_checklist":
            prompt = await get_prompt_with_data(
                'pr_test_checklist',
                pr_data=diff_content,
                from_hash=from_hash,
                to_hash=to_hash,
                context_lines=context_lines,
                truncated_warning=truncated_warning
            )

        elif payload['operation'] == "explain":
            prompt = await get_prompt_with_data(
                'pr_explain',
                pr_data=diff_content,
                from_hash=from_hash,
                to_hash=to_hash,
                context_lines=context_lines,
                truncated_warning=truncated_warning
            )
        if prompt:
            ai_response = await run_codex(prompt)
            write_pr_ai_response(pr_id, {
                payload['operation']: ai_response,
            })
            return ai_response

        raise PromptExecutionError(f"Failed to load prompt template for '{operation}'")

    return "Operation is not recognized"


CONFLUENCE_PROMPTS = {
    "explain": "confluence_explain",
    "rewrite": "confluence_rewrite",
    "page_update": "confluence_page_update",
}


def get_confluence_id(pathname: str, search: str = "") -> str:
    """Support space URLs and the older viewpage.action?pageId=... URLs."""
    parsed = urlsplit(pathname or "")
    match = re.search(r"/pages/([0-9]+)(?:/|$)", parsed.path)
    page_id = match.group(1) if match else parse_qs(search.lstrip("?") or parsed.query).get("pageId", [""])[0]
    if not re.fullmatch(r"[0-9]+", page_id):
        raise ValueError("A Confluence page URL with a numeric page ID is required")
    return page_id


def validate_confluence_storage(content: str) -> str:
    """Reject prose, Markdown fences and malformed storage before replacing a page."""
    content = content.strip()
    if not content or "<!DOCTYPE" in content.upper() or "<!ENTITY" in content.upper():
        raise PromptExecutionError("Model returned empty or invalid Confluence storage")
    # Confluence also uses named HTML entities; normalize them only for parsing.
    def entity(match):
        name = match.group(1)
        return f"&#{name2codepoint[name]};" if name in name2codepoint else match.group(0)

    parse_content = re.sub(r"&([A-Za-z][A-Za-z0-9]+);", entity, content)
    try:
        root = ET.fromstring(
            '<root xmlns:ac="http://atlassian.com/content" xmlns:ri="http://atlassian.com/resource">'
            + parse_content + '</root>'
        )
    except ET.ParseError as exc:
        raise PromptExecutionError("Model returned malformed Confluence storage; page was not updated") from exc
    if (not len(root) or (root.text or "").strip()
            or any((child.tail or "").strip() for child in root)
            or any(node.tag in {"html", "head", "body", "script"} for node in root.iter())):
        raise PromptExecutionError("Model must return only the complete Confluence storage body")
    return content


async def confluence_operation(payload: dict) -> str:
    operation = payload.get("operation")
    if operation not in {*CONFLUENCE_PROMPTS, "delete"}:
        raise ValueError("Unrecognized Confluence operation")
    if payload.get("hostname") != urlsplit(CONFLUENCE_URL).hostname:
        raise ValueError("Page hostname does not match the configured Confluence server")
    confluence_id = get_confluence_id(payload.get("pathname"), payload.get("search", ""))
    instruction = payload.get("instruction", "")
    if operation == "page_update" and (not isinstance(instruction, str) or not instruction.strip()):
        raise ValueError("page_update requires a non-empty instruction")

    if operation == "delete":
        if delete_confluence_ai_response(confluence_id):
            return f"Success: Cleared cached results for {confluence_id}"
        raise PromptExecutionError("Failed to clear cached results; database unavailable or deletion failed")

    current_content, current_version, page_id, page_title = await get_confluence_data(
        payload["hostname"], payload["pathname"], payload.get("search", "")
    )
    prompt_data = {"confluence_content": current_content}
    if operation == "page_update":
        prompt_data["instruction"] = instruction.strip()
    prompt_key = CONFLUENCE_PROMPTS[operation]
    try:
        prompt = await get_prompt_with_data(prompt_key, **prompt_data)
    except ValueError as exc:
        raise PromptExecutionError(str(exc)) from exc
    if not prompt:
        raise PromptExecutionError(f"Failed to load prompt template '{prompt_key}'")

    # Only explanations are reusable. Include the rendered prompt so prompt edits
    # and external page edits both invalidate cached results, including legacy ones.
    fingerprint = hashlib.sha256(json.dumps(
        [CONFLUENCE_URL, current_version, page_title, prompt], ensure_ascii=False
    ).encode("utf-8")).hexdigest()
    if operation == "explain":
        response = read_confluence_ai_response(confluence_id) or {}
        cached = response.get("explain")
        if (response.get("explain_fingerprint") == fingerprint
                and isinstance(cached, str) and cached.strip()):
            return cached

    ai_response = await run_codex(prompt)
    if operation == "explain":
        write_confluence_ai_response(confluence_id, {
            "explain": ai_response, "explain_fingerprint": fingerprint,
        })
        return ai_response

    ai_response = validate_confluence_storage(ai_response)
    if ai_response == current_content.strip():
        return ai_response
    update_payload = {
        "id": page_id,
        "type": "page",
        "title": page_title,
        "version": {"number": current_version + 1},
        "body": {"storage": {"value": ai_response, "representation": "storage"}},
    }
    put_api_url = f"{CONFLUENCE_URL.rstrip('/')}/rest/api/content/{page_id}"
    try:
        put_response = await asyncio.to_thread(
            requests.put, put_api_url, headers=headers, json=update_payload, timeout=30
        )
        put_response.raise_for_status()
    except requests.exceptions.RequestException as exc:
        raise PromptExecutionError(f"Failed to update Confluence page {page_id}: {exc}") from exc
    # Version-based cache validation also protects against cache deletion failure.
    delete_confluence_ai_response(confluence_id)
    return ai_response


async def get_confluence_data(hostname, pathname, search=""):
    page_id = get_confluence_id(pathname, search)
    get_api_url = f"{CONFLUENCE_URL.rstrip('/')}/rest/api/content/{page_id}"
    try:
        response = await asyncio.to_thread(
            requests.get, get_api_url, headers=headers,
            params={"expand": "body.storage,version"}, timeout=30
        )
        response.raise_for_status()
        page_data = response.json()
        content = page_data["body"]["storage"]["value"]
        version = page_data["version"]["number"]
        title = page_data["title"]
        if not isinstance(content, str) or not isinstance(version, int) or not isinstance(title, str):
            raise ValueError("Invalid page content, version or title")
        return content, version, page_id, title
    except (requests.exceptions.RequestException, KeyError, TypeError, ValueError) as exc:
        raise PromptExecutionError(f"Failed to fetch Confluence page {page_id}: {exc}") from exc
