import json

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from PromptExecutor import pull_request_operation, confluence_operation
from prompt_db import close_connection_pool

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
