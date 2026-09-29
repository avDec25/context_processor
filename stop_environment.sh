#!/bin/bash

PID_FILE="/tmp/context_processor_env.pid"
STATUS_FILE="/tmp/context_processor_status.txt"
FASTAPI_PID_FILE="/tmp/context_processor_fastapi.pid"
LOG_FILE="/tmp/context_processor.log"

log_status() {
    echo "$1" > "$STATUS_FILE"
    echo "[$(date '+%H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

# Stop the coordinator first. Its trap also stops the server and Compose
# environment. This keeps a sysapp-managed start/stop cycle self-contained.
ENV_PID=""
if [ -f "$PID_FILE" ]; then
    ENV_PID="$(cat "$PID_FILE")"
fi

if [ -n "$ENV_PID" ] && kill -0 "$ENV_PID" 2>/dev/null; then
    log_status "stopping:pid=${ENV_PID}"
    kill "$ENV_PID"

    WAITED=0
    MAX_WAIT=10
    while kill -0 "$ENV_PID" 2>/dev/null; do
        sleep 1
        WAITED=$((WAITED + 1))
        if [ "$WAITED" -ge "$MAX_WAIT" ]; then
            log_status "force_killing:pid=${ENV_PID}"
            kill -9 "$ENV_PID" 2>/dev/null || true
            break
        fi
    done

    rm -f "$FASTAPI_PID_FILE" "$PID_FILE"
    log_status "stopped"
    echo "context_processor environment stopped."
    exit 0
fi

# A server may have been started outside sysapp. Fall back to its recorded PID
# or the process name so stopping remains idempotent in either case.
PID=""
if [ -f "$FASTAPI_PID_FILE" ]; then
    PID="$(cat "$FASTAPI_PID_FILE")"
fi

if [ -z "$PID" ] || ! kill -0 "$PID" 2>/dev/null; then
    PID="$(pgrep -f "uvicorn main:app" 2>/dev/null | head -n 1 || true)"
fi

if [ -z "$PID" ] || ! kill -0 "$PID" 2>/dev/null; then
    echo "context_processor is not running."
    rm -f "$FASTAPI_PID_FILE" "$PID_FILE"
    log_status "stopped"
    exit 0
fi

log_status "stopping:pid=${PID}"
kill "$PID"

WAITED=0
MAX_WAIT=10
while kill -0 "$PID" 2>/dev/null; do
    sleep 1
    WAITED=$((WAITED + 1))
    if [ "$WAITED" -ge "$MAX_WAIT" ]; then
        log_status "force_killing:pid=${PID}"
        kill -9 "$PID" 2>/dev/null || true
        break
    fi
done

rm -f "$FASTAPI_PID_FILE" "$PID_FILE"
log_status "stopped"
echo "context_processor (pid ${PID}) stopped."
