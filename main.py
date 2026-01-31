from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
import json
from PromptExecutor import summarize_pull_request

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
    operation, args = payload['operation'].split(":")

    if operation == "summarize":
        response = summarize_pull_request(args, payload)
        return response
    else:
        return {"message": f"Operation {operation} is not supported"}
