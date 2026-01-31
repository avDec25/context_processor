import asyncio
import json


async def run_command_async(cmd_str):
    proc = await asyncio.create_subprocess_shell(
        cmd_str,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )

    stdout, stderr = await proc.communicate()

    if proc.returncode == 0:
        return stdout.decode().strip()
    else:
        raise Exception(stderr.decode().strip())


async def summarize_pull_request(request_id: str, explain_to: str, payload: json) -> str:
    print(explain_to)
    print(payload)
    output = await run_command_async("ls -la")
    return output
#     return """
# Executive Summary
# This PR executes a critical frontend dependency upgrade, migrating the application from legacy jQuery versions (v1.4.2/v1.11.1) to v1.12.4 across five key JSP views (Item Top, Product List, Keyword List).
#
# Key Insights:
#
# Technical Debt Reduction: component.js was significantly refactored to address breaking changes. Specifically, deprecated .live() calls were replaced with delegated .on() event handlers, and .unbind() was replaced with .off().
# Logic Modernization: Nested document.ready calls were flattened, and animation queues were optimized using .stop(true, true).
# Recommendations:
#
# Targeted QA: Strictly enforce regression testing on Favorites and Item Comparison functionality, as the event delegation rewrite poses a high risk of regression in dynamic elements.
# Validation: Verify that the new jQuery 1.12.4.min.js asset loads correctly across all environments before merging.
# """
