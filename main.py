from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
import json
from PromptExecutor import pull_request_operation
import uuid

app = FastAPI()

app.add_middleware(
    CORSMiddleware,  # type: ignore
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    return {"message": "Health OK!"}


@app.post("/pullrequest")
async def pr_processor(request: Request):
    data = await request.body()
    payload = json.loads(data.decode("utf-8"))

    request_id = str(uuid.uuid4())
    response = pull_request_operation(request_id, payload)

    return response
