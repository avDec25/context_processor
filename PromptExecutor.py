import subprocess
import requests
from pr_manager import read_pr_ai_response, write_pr_ai_response, delete_pr_ai_response

BITBUCKET_TOKEN = "REDACTED"


def run_codex(prompt: str):
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
    if operation in ['explain', 'review', 'delete']:
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
