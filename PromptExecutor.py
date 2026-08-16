import subprocess
import requests
import os
import sys
import tempfile
import logging
import configparser
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


def get_confluence_id(pathname: str) -> str:
    return pathname.split('/')[5]


async def confluence_operation(payload: dict) -> str:
    operation = payload.get('operation')
    if operation in ['rewrite', 'explain', 'delete', 'page_update']:
        confluence_id = get_confluence_id(payload.get('pathname'))

        if payload['operation'] == "delete":
            if delete_confluence_ai_response(confluence_id):
                return f"Success: Deleted entry {confluence_id}"
            else:
                return "Failed: None Deleted"

        response = read_confluence_ai_response(confluence_id) or {}
        cached_response = response.get(operation)
        if isinstance(cached_response, str) and cached_response.strip():
            return cached_response

        current_content, current_version, page_id, page_title = await get_confluence_data(payload['hostname'],
                                                                                           payload['pathname'])
        prompt = None

        if payload['operation'] == "explain":
            prompt = await get_prompt_with_data('confluence_explain', confluence_content=current_content)
            if not prompt:
                raise PromptExecutionError("Failed to load prompt template 'confluence_explain'")
            ai_response = await run_codex(prompt)
            write_confluence_ai_response(confluence_id, {
                payload['operation']: ai_response,
            })
            return ai_response

        elif payload['operation'] == "rewrite" or payload['operation'] == "page_update":
            if payload['operation'] == "page_update":
                prompt = await get_prompt_with_data(
                    'confluence_page_update',
                    confluence_content=current_content,
                    instruction=payload.get('instruction', '')
                )
            else:
                prompt = await get_prompt_with_data('confluence_rewrite', confluence_content=current_content)

            if not prompt:
                raise PromptExecutionError(f"Failed to load prompt template 'confluence_{payload['operation']}'")

            ai_response = await run_codex(prompt)

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
            logger.info("Updating Confluence page at: %s (version %d)", put_api_url, next_version)

            try:
                loop = asyncio.get_event_loop()
                put_response = await loop.run_in_executor(
                    None,
                    lambda: requests.put(put_api_url, headers=headers, data=json.dumps(update_payload))
                )
                put_response.raise_for_status()

                updated_page_data = put_response.json()
                logger.info("Page '%s' (ID: %s) updated to version %s. View: %s%s",
                            updated_page_data['title'], page_id,
                            updated_page_data['version']['number'],
                            CONFLUENCE_URL, updated_page_data['_links']['webui'])

                return ai_response
            except requests.exceptions.HTTPError as http_err:
                logger.error("HTTP error updating Confluence page: %s (status %s)", http_err, http_err.response.status_code)
                try:
                    logger.error("Confluence error details: %s", _t(json.dumps(http_err.response.json())))
                except json.JSONDecodeError:
                    logger.error("Confluence error body: %s", _t(http_err.response.text))
            except requests.exceptions.ConnectionError as conn_err:
                logger.error("Connection error updating Confluence page: %s", conn_err)
            except requests.exceptions.Timeout as timeout_err:
                logger.error("Timeout updating Confluence page: %s", timeout_err)
            except requests.exceptions.RequestException as req_err:
                logger.error("Request error updating Confluence page: %s", req_err)
            except KeyError as key_err:
                logger.error("Missing key in Confluence API response: %s", key_err)
            except Exception as e:
                logger.error("Unexpected error updating Confluence page: %s", e)

    return "Operation is not recognized"


async def get_confluence_data(hostname, pathname):
    page_id = get_confluence_id(pathname)

    # 1. Fetch Current Page Content and Version
    get_api_url = f"{CONFLUENCE_URL}/rest/api/content/{page_id}?expand=body.storage,version"
    logger.info("Fetching Confluence page content from: %s", get_api_url)

    try:
        loop = asyncio.get_event_loop()
        get_response = await loop.run_in_executor(
            None,
            lambda: requests.get(get_api_url, headers=headers)
        )
        get_response.raise_for_status()
        page_data = get_response.json()

        current_content = page_data['body']['storage']['value']
        current_version = page_data['version']['number']
        page_title = page_data['title']

        logger.info("Fetched Confluence page '%s' (ID: %s), version %s, content: %s",
                    page_title, page_id, current_version, _t(current_content))
        return current_content, current_version, page_id, page_title

    except requests.exceptions.HTTPError as http_err:
        logger.error("HTTP error fetching Confluence page: %s (status %s)", http_err, http_err.response.status_code)
        try:
            logger.error("Confluence error details: %s", _t(json.dumps(http_err.response.json())))
        except json.JSONDecodeError:
            logger.error("Confluence error body: %s", _t(http_err.response.text))
    except requests.exceptions.ConnectionError as conn_err:
        logger.error("Connection error fetching Confluence page: %s", conn_err)
    except requests.exceptions.Timeout as timeout_err:
        logger.error("Timeout fetching Confluence page: %s", timeout_err)
    except requests.exceptions.RequestException as req_err:
        logger.error("Request error fetching Confluence page: %s", req_err)
    except KeyError as key_err:
        logger.error("Missing key in Confluence page response: %s", key_err)
    except Exception as e:
        logger.error("Unexpected error fetching Confluence page: %s", e)
