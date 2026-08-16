#!/bin/bash

PID_FILE="/tmp/context_processor_env.pid"
STATUS_FILE="/tmp/context_processor_status.txt"
FASTAPI_PID_FILE="/tmp/context_processor_fastapi.pid"
LOG_FILE="/tmp/context_processor.log"
APP_DIR="/Users/ts-amar.vashishth/context_processor"
VENV_PYTHON="/Users/ts-amar.vashishth/.venv/bin/python3"
DB_CONTAINER="pr_postgres_container"
DB_USER="admin"
DB_NAME="context_processor"

echo $$ > "$PID_FILE"
> "$LOG_FILE"

log_status() {
    echo "$1" > "$STATUS_FILE"
    echo "[$(date '+%H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

cleanup() {
    log_status "stopping"
    if [ -f "$FASTAPI_PID_FILE" ]; then
        kill "$(cat "$FASTAPI_PID_FILE")" 2>/dev/null || true
        rm -f "$FASTAPI_PID_FILE"
    fi
    cd "$APP_DIR"
    docker compose -f deploy/docker-compose.yaml down 2>/dev/null || true
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
until docker ps &>/dev/null 2>&1; do
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

# ── 3. Run make prereq (starts the Postgres container) ───────────────────────
log_status "running_prereq"
cd "$APP_DIR"
if ! make prereq 2>&1 | tee -a "$LOG_FILE"; then
    log_status "error:make prereq failed"
    rm -f "$PID_FILE"
    exit 1
fi
log_status "prereq_done"

# ── 4. Wait for Postgres to accept connections ────────────────────────────────
log_status "waiting_postgres"
MAX_WAIT=60
WAITED=0
until docker exec "$DB_CONTAINER" pg_isready -U "$DB_USER" -d "$DB_NAME" &>/dev/null; do
    sleep 2
    WAITED=$((WAITED + 2))
    if [ $WAITED -ge $MAX_WAIT ]; then
        log_status "error:Postgres did not become ready within ${MAX_WAIT}s"
        rm -f "$PID_FILE"
        exit 1
    fi
done
log_status "postgres_ready"

# ── 5. Initialize the database schema/seed data ───────────────────────────────
log_status "initializing_db"
if ! docker exec -i "$DB_CONTAINER" psql -U "$DB_USER" -d "$DB_NAME" < "$APP_DIR/deploy/db_setup.sql" >> "$LOG_FILE" 2>&1; then
    log_status "error:db_setup.sql failed"
    rm -f "$PID_FILE"
    exit 1
fi
log_status "db_initialized"

# ── 6. Install/update Python dependencies ─────────────────────────────────────
log_status "installing_dependencies"
if ! "$VENV_PYTHON" -m pip install -q -r "$APP_DIR/requirements.txt" >> "$LOG_FILE" 2>&1; then
    log_status "error:pip install failed"
    rm -f "$PID_FILE"
    exit 1
fi
log_status "dependencies_ready"

# ── 7. Start FastAPI server ───────────────────────────────────────────────────
log_status "starting_fastapi"
cd "$APP_DIR"
"$VENV_PYTHON" -m uvicorn main:app --reload --host 0.0.0.0 --port 8000 >> "$LOG_FILE" 2>&1 &
FASTAPI_PID=$!
echo "$FASTAPI_PID" > "$FASTAPI_PID_FILE"
log_status "running:pid=${FASTAPI_PID}"

# Wait until FastAPI exits or we are signaled
wait $FASTAPI_PID
log_status "fastapi_exited"
rm -f "$FASTAPI_PID_FILE" "$PID_FILE"
