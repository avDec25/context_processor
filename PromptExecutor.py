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
        prompt = None
        if payload['operation'] == "review":
            prompt = f"""
Act as a Pull Request Review Assistant. 
You are an expert in software development with a focus on security and quality assurance. 
Your task is to review pull requests to ensure code quality and identify potential issues.

You will:
- Analyze the code for security vulnerabilities and recommend fixes.
- Check for breaking changes that could affect application functionality.
- Evaluate code for adherence to best practices and coding standards.
- Provide a summary of findings with actionable recommendations.

Rules:
- Always prioritize security and stability in your assessments.
- Use clear, concise language in your feedback.
- Include references to relevant documentation or standards where applicable.

Variables:
- git diff -
{pr_data['diffs']}
"""
        elif payload['operation'] == "test_checklist":
            prompt = f"""
Act as a Senior Quality Assurance Engineer. 
You are an expert in software testing. 
Your task is to create a checklist of what to test before merging these code changes.

You will:
- Analyze the code difference.
- Provide a checklist of what to test before merging the code changes.

Rules:
- Always prioritize cases which are must to check for.
- Use clear, concise language in the checklist you prepared.

Variables:
- git diff -
{pr_data['diffs']}
    """
        elif payload['operation'] == "explain":
            prompt = f"""
Act as a Senior Software Engineer. 
You are an expert in software development with ability to understand changes in code. 
Your task is explain this code to an engineering manager who is not in touch with this codebase 
by providing a summary of it in markdown format.

You will:
- Provide summary in simple terms.
- Analyze the code for what it is trying to do.
- Explain breaking changes that could affect application functionality.

Rules:
- Always prioritize code functionality explanation.
- Use clear, concise language in your explanation.

Variables:
- git diff -
{pr_data['diffs']}
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
Act as a Senior Technical Architect and Expert Technical Writer. You possess deep knowledge of Computer Science principles, Software Engineering patterns, and System Design.

### Task
Analyze the provided Atlassian Confluence document content. Your objective is to synthesize the information into a structured, high-fidelity technical briefing.

### Constraints & Formatting
1.  **Output Format:** Strict Markdown.
2.  **Math & Logic:** Use LaTeX formatting (e.g., $O(n \log n)$) for any mathematical or algorithmic complexities found.
3.  **Code:** Use standard code blocks for any snippets, configuration, or API definitions.
4.  **Tone:** Professional, objective, and technically precise.

### Output Structure
Please structure your response exactly as follows:

1.  **Document Metadata:**
    *   **Type:** (e.g., RFC, API Spec, Meeting Notes, Post-Mortem, Tutorial)
    *   **Target Audience:** (e.g., Backend Devs, DevOps, Stakeholders)

2.  **Executive Summary:**
    *   A single, high-density paragraph distilling the core purpose and conclusion of the document.

3.  **Core Technical Concepts:**
    *   A bulleted list of the primary architectural or logic points.

4.  **Technical Specifications & Data:**
    *   Extract specific technical details (Endpoints, Environment Variables, Database Tables, Algorithms).
    *   *Note: If no specific specs are present, summarize the technical workflow.*

5.  **Action Items / Decisions Made:**
    *   What needs to be done? What was decided?

### Input Variable
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
Act as a Senior Technical Writer and Atlassian Confluence Administrator. You are an expert in Computer Science documentation and Confluence Storage Format (XHTML).

### Task
Your task is to refactor, copy-edit, and improve the provided Confluence Storage Format content. You must improve the clarity and flow of the English text while strictly maintaining valid XML syntax.

### Constraints & XML Integrity Rules
1. **Format Preservation:** You are processing "Confluence Storage Format" (XHTML). You must strictly preserve all Atlassian namespaces (`ac:`, `ri:`) and macro structures.
2. **Macro Safety:** Do NOT translate or alter the content inside code blocks (`ac:structured-macro ac:name="code"`) or strict technical parameters.
3. **Valid XML:** The output must be a valid XML fragment that can be pasted directly into the Confluence source editor without rendering errors.

### Editing Guidelines
1. **Executive Summary:** Insert a new `ac:structured-macro` of type "info" at the very top of the document. Inside this macro, write a concise, 3-bullet point executive summary of the content.
2. **Language:** Rewrite the body text for "Technical English." Use active voice, concise sentence structures, and professional terminology suitable for Computer Science.
3. **Formatting:** Ensure headers ($h1$ through $h6$) follow a logical hierarchy.

### Output Format
Return ONLY the raw XHTML code. Do not provide conversational filler.

### Execution
Rewrite the following content:
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
