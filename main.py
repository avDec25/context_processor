import json
import logging
import time
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from PromptExecutor import (
    PromptExecutionError,
    pull_request_operation,
    confluence_operation,
)
from prompt_db import close_connection_pool, list_prompts, get_prompt, update_prompt

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

app = FastAPI()


@app.exception_handler(PromptExecutionError)
async def prompt_execution_error_handler(request: Request, exc: PromptExecutionError):
    logger.error("Prompt execution failed for %s: %s", request.url.path, exc)
    return JSONResponse(status_code=502, content={"detail": str(exc)})


@app.middleware("http")
async def access_log(request: Request, call_next):
    start = time.monotonic()
    response = await call_next(request)
    ms = (time.monotonic() - start) * 1000
    content_length = request.headers.get("content-length")
    size_str = f" (body: {int(content_length)/1024:.1f}KB)" if content_length else ""
    logger.info("%s %s → %d (%.0fms)%s", request.method, request.url.path, response.status_code, ms, size_str)
    return response

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


class ConfluenceRequest(BaseModel):
    operation: Literal["explain", "rewrite", "page_update", "delete"]
    hostname: str
    pathname: str
    search: str = ""
    instruction: str = ""


@app.post("/confluence")
async def confluence_processor(payload: ConfluenceRequest):
    try:
        return await confluence_operation(payload.dict())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


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
    try:
        success = await update_prompt(prompt_key, prompt_update.prompt_text)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if not success:
        raise HTTPException(status_code=404, detail=f"Prompt '{prompt_key}' not found or update failed")

    return {"message": f"Prompt '{prompt_key}' updated successfully", "success": True}
