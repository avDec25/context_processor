import subprocess
import requests

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


def pull_request_operation(request_id: str, payload: dict) -> str:
    if payload['operation'] == "review":
        pr_data = pull_request_data(payload['hostname'], payload['pathname'])
        print(pr_data['diffs'])

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
        return run_codex(prompt)

# if __name__ == '__main__':
#     codex_prompt = "what is a pull request"
#     print(run_codex(codex_prompt))
