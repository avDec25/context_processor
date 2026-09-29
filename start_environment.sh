#!/bin/bash

set -o pipefail

PID_FILE="/tmp/context_processor_env.pid"
STATUS_FILE="/tmp/context_processor_status.txt"
FASTAPI_PID_FILE="/tmp/context_processor_fastapi.pid"
LOG_FILE="/tmp/context_processor.log"
APP_DIR="/Users/ts-amar.vashishth/context_processor"
VENV_PYTHON="/Users/ts-amar.vashishth/.venv/bin/python3"
DB_CONTAINER="pr_postgres_container"
DB_USER="admin"
DB_NAME="context_processor"

# Rancher Desktop exposes Docker through this context.  A stale DOCKER_HOST
# inherited from a terminal or launch agent overrides that context and makes a
# healthy Rancher Desktop look unavailable.
unset DOCKER_HOST
export DOCKER_CONTEXT="rancher-desktop"

log_status() {
    echo "$1" > "$STATUS_FILE"
    echo "[$(date '+%H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

# A healthy server may have been started outside sysapp.  Do not overwrite its
# state or attempt to create a second environment in that case.
if curl --fail --silent --max-time 2 http://localhost:8000/ | grep -q 'Health OK'; then
    log_status "running:existing_service"
    exit 0
fi

echo $$ > "$PID_FILE"
> "$LOG_FILE"

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
until docker --context "$DOCKER_CONTEXT" info &>/dev/null; do
    sleep 5
    WAITED=$((WAITED + 5))
    log_status "waiting_rancher:${WAITED}s"
    if [ $WAITED -ge $MAX_WAIT ]; then
        log_status "error:Rancher Desktop Docker context was unavailable after ${MAX_WAIT}s"
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

# Prefer this project's container, but reuse the container that already owns
# the application's configured Postgres port when one is running.
if [ "$(docker inspect --format '{{.State.Running}}' "$DB_CONTAINER" 2>/dev/null)" != "true" ]; then
    DB_CONTAINER="$(docker ps -q --filter 'publish=5432' | head -n 1)"
fi

if [ -z "$DB_CONTAINER" ]; then
    log_status "error:no Postgres container is running on port 5432"
    rm -f "$PID_FILE"
    exit 1
fi

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
