import subprocess
import requests
import os
import tempfile
from pathlib import Path
from pr_manager import read_pr_ai_response, write_pr_ai_response, delete_pr_ai_response
from confluence_manager import read_confluence_ai_response, write_confluence_ai_response, delete_confluence_ai_response
import json
import asyncio
from concurrent.futures import ThreadPoolExecutor
from prompt_db import get_prompt_with_data
from dotenv import load_dotenv

# Load environment variables from .env.local.conf
env_path = Path(__file__).parent / '.env.local.conf'
load_dotenv(dotenv_path=env_path)

BITBUCKET_TOKEN = os.getenv("BITBUCKET_TOKEN", "")
CONFLUENCE_URL = os.getenv("CONFLUENCE_URL", "https://confluence.rakuten-it.com/confluence")
PERSONAL_ACCESS_TOKEN = os.getenv("PERSONAL_ACCESS_TOKEN", "")
headers = {
    "Authorization": f"Bearer {PERSONAL_ACCESS_TOKEN}",
    "Accept": "application/json",
    "Content-Type": "application/json"  # Required for PUT requests with JSON body
}


async def run_codex(prompt: str):
    print(f"\n\n--> Running codex...")
    loop = asyncio.get_event_loop()

    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
        tmp_path = f.name

    try:
        # codex exec writes its response via terminal UI, not stdout.
        # --output-last-message writes the final AI response to a file.
        # --full-auto avoids hanging on approval prompts.
        # --ephemeral avoids polluting session history.
        cmd = ["codex", "exec", "--skip-git-repo-check", "--full-auto", "--ephemeral", "-c", "mcp_servers={}", "--output-last-message", tmp_path, "-"]
        print(f"--> Command: {' '.join(cmd)}")
        await loop.run_in_executor(
            None,
            lambda: subprocess.run(
                cmd,
                input=prompt,
                text=True,
                capture_output=True,
            )
        )
        with open(tmp_path, 'r') as f:
            return f.read()
    finally:
        os.unlink(tmp_path)


async def pull_request_data(hostname, pathname):
    # Replace /overview with /diff to get the actual diff content
    if pathname.endswith('/overview'):
        pathname = pathname.replace('/overview', '/diff')

    url = f"https://{hostname}/rest/api/latest{pathname}"
    print(f"Fetching PR data from: {url}")

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
        if response.get(operation):
            return response[operation]

        pr_data = await pull_request_data(payload['hostname'], payload['pathname'])
        print(f"PR Data keys: {pr_data.keys()}")

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

    return "Operation is not recognized"


def get_confluence_id(pathname: str) -> str:
    return pathname.split('/')[5]


async def confluence_operation(payload: dict) -> str:
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

        current_content, current_version, page_id, page_title = await get_confluence_data(payload['hostname'],
                                                                                           payload['pathname'])
        prompt = None

        if payload['operation'] == "explain":
            prompt = await get_prompt_with_data('confluence_explain', confluence_content=current_content)
            if not prompt:
                return "Failed to load prompt template 'confluence_explain'"
            ai_response = await run_codex(prompt)
            write_confluence_ai_response(confluence_id, {
                payload['operation']: ai_response,
            })
            return ai_response

        elif payload['operation'] == "rewrite":
            prompt = await get_prompt_with_data('confluence_rewrite', confluence_content=current_content)
            if not prompt:
                return "Failed to load prompt template 'confluence_rewrite'"
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
            print(f"Updating page content at: {put_api_url} with new version: {next_version}")

            try:
                loop = asyncio.get_event_loop()
                put_response = await loop.run_in_executor(
                    None,
                    lambda: requests.put(put_api_url, headers=headers, data=json.dumps(update_payload))
                )
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


async def get_confluence_data(hostname, pathname):
    page_id = get_confluence_id(pathname)

    # 1. Fetch Current Page Content and Version
    get_api_url = f"{CONFLUENCE_URL}/rest/api/content/{page_id}?expand=body.storage,version"
    print(f"Fetching page content from: {get_api_url}")

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
