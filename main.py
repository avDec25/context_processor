import json
from pathlib import Path

from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from PromptExecutor import pull_request_operation, confluence_operation
from prompt_db import close_connection_pool, list_prompts, get_prompt, update_prompt

app = FastAPI()

app.add_middleware(
    CORSMiddleware,  # type: ignore
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup resources on application shutdown."""
    close_connection_pool()


@app.get("/")
async def root():
    return {"message": "Health OK!"}


@app.post("/pullrequest")
async def pr_processor(request: Request):
    data = await request.body()
    payload = json.loads(data.decode("utf-8"))

    response = await pull_request_operation(payload)

    return response


@app.post("/confluence")
async def confluence_processor(request: Request):
    data = await request.body()
    payload = json.loads(data.decode("utf-8"))

    response = await confluence_operation(payload)

    return response


# Pydantic model for prompt update
class PromptUpdate(BaseModel):
    prompt_text: str


@app.get("/prompts/editor", response_class=HTMLResponse)
async def get_prompt_editor():
    """Serve the prompt editor web interface."""
    html_path = Path(__file__).parent / "templates" / "prompt_editor.html"

    if not html_path.exists():
        raise HTTPException(status_code=404, detail="Prompt editor template not found")

    return html_path.read_text()


@app.get("/prompts")
async def get_all_prompts():
    """List all prompts with metadata."""
    prompts = await list_prompts()
    return prompts


@app.get("/prompts/{prompt_key}")
async def get_prompt_by_key(prompt_key: str):
    """Get a specific prompt by key."""
    prompt_text = await get_prompt(prompt_key)

    if prompt_text is None:
        raise HTTPException(status_code=404, detail=f"Prompt '{prompt_key}' not found")

    # Get metadata from list
    prompts = await list_prompts()
    metadata = next((p for p in prompts if p['key'] == prompt_key), {})

    return {
        "key": prompt_key,
        "prompt_text": prompt_text,
        "description": metadata.get('description'),
        "updated_at": metadata.get('updated_at')
    }


@app.put("/prompts/{prompt_key}")
async def update_prompt_by_key(prompt_key: str, prompt_update: PromptUpdate):
    """Update a prompt's text."""
    success = await update_prompt(prompt_key, prompt_update.prompt_text)

    if not success:
        raise HTTPException(status_code=404, detail=f"Prompt '{prompt_key}' not found or update failed")

    return {"message": f"Prompt '{prompt_key}' updated successfully", "success": True}
