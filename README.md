# Context Processor

## Restart the server

Kill the running process and restart:

```bash
pkill -f "uvicorn main:app" ; cd /Users/amar/context_processor && ./start_server.sh
```

Or if you need the full environment (Rancher Desktop + Postgres + FastAPI):

```bash
pkill -f "uvicorn main:app" ; cd /Users/amar/context_processor && ./start_environment.sh
```

The API will be available at `http://localhost:8000` and the prompt editor at `http://localhost:8000/prompts/editor`.
