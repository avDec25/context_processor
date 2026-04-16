#!/bin/bash

PID_FILE="/tmp/context_processor_env.pid"
STATUS_FILE="/tmp/context_processor_status.txt"
FASTAPI_PID_FILE="/tmp/context_processor_fastapi.pid"
APP_DIR="/Users/ts-amar.vashishth/context_processor"

echo $$ > "$PID_FILE"

log_status() {
    echo "$1" > "$STATUS_FILE"
    echo "[$(date '+%H:%M:%S')] $1"
}

cleanup() {
    log_status "stopping"
    if [ -f "$FASTAPI_PID_FILE" ]; then
        kill "$(cat "$FASTAPI_PID_FILE")" 2>/dev/null || true
        rm -f "$FASTAPI_PID_FILE"
    fi
    cd "$APP_DIR"
    nerdctl compose -f deploy/docker-compose.yaml down 2>/dev/null || true
    rm -f "$PID_FILE"
    log_status "stopped"
    exit 0
}

trap cleanup SIGTERM SIGINT

# ── 1. Start Rancher Desktop ──────────────────────────────────────────────────
log_status "starting_rancher"
open -a "Rancher Desktop" 2>/dev/null || true

# ── 2. Wait for Rancher Desktop to be ready ──────────────────────────────────
log_status "waiting_rancher"
MAX_WAIT=300
WAITED=0
until nerdctl ps &>/dev/null 2>&1; do
    sleep 5
    WAITED=$((WAITED + 5))
    log_status "waiting_rancher:${WAITED}s"
    if [ $WAITED -ge $MAX_WAIT ]; then
        log_status "error:Rancher Desktop did not start within ${MAX_WAIT}s"
        rm -f "$PID_FILE"
        exit 1
    fi
done
log_status "rancher_ready"

# ── 3. Run make prereq ────────────────────────────────────────────────────────
log_status "running_prereq"
cd "$APP_DIR"
if ! make prereq 2>&1; then
    log_status "error:make prereq failed"
    rm -f "$PID_FILE"
    exit 1
fi
log_status "prereq_done"

# ── 4. Start FastAPI server ───────────────────────────────────────────────────
log_status "starting_fastapi"
cd "$APP_DIR"
uvicorn main:app --reload --host 0.0.0.0 --port 8000 &
FASTAPI_PID=$!
echo "$FASTAPI_PID" > "$FASTAPI_PID_FILE"
log_status "running:pid=${FASTAPI_PID}"

# Wait until FastAPI exits or we are signaled
wait $FASTAPI_PID
log_status "fastapi_exited"
rm -f "$FASTAPI_PID_FILE" "$PID_FILE"
