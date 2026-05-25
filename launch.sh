#!/bin/bash
# Dune Dashboard - systemd launch wrapper
# Sets up SSH tunnel + kubectl port-forward before starting the app.
set -e

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
SETTINGS="$PROJECT_ROOT/settings.yaml"
PYTHON="$PROJECT_ROOT/.venv/bin/python3"
SSH_KEY="/home/jdiveley/.ssh/dune-dashboard-key"
SERVER_USER="dune"
SERVER_HOST="192.168.250.200"
DB_PORT="15433"
DIRECTOR_PORT="32479"

SSH_OPTS="-i $SSH_KEY -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=30 -o ServerAliveCountMax=3 -o ConnectTimeout=15 -o BatchMode=yes"

cleanup() {
    echo "[launch] Cleaning up SSH tunnel..."
    kill "$TUNNEL_PID" 2>/dev/null || true
    ssh $SSH_OPTS "${SERVER_USER}@${SERVER_HOST}" "pkill -f 'kubectl port-forward' 2>/dev/null; true" 2>/dev/null || true
}
trap cleanup EXIT

# ── 1. Detect namespace ───────────────────────────────────────────────
echo "[launch] Detecting Kubernetes namespace..."
NAMESPACE=$(ssh $SSH_OPTS "${SERVER_USER}@${SERVER_HOST}" \
    "sudo kubectl get namespaces -o name 2>/dev/null | grep 'namespace/funcom-seabass-' | head -1 | sed 's|namespace/||'" 2>/dev/null || true)

if [ -z "$NAMESPACE" ]; then
    echo "[launch] WARNING: Could not detect namespace. DB port-forward will be skipped."
    echo "[launch] The app will start but DB features will be unavailable until the tunnel is up."
else
    echo "[launch] Namespace: $NAMESPACE"
fi

# ── 2. Start SSH tunnel ───────────────────────────────────────────────
echo "[launch] Starting SSH tunnel (ports $DB_PORT + $DIRECTOR_PORT)..."
pkill -f "ssh.*-L.*${DB_PORT}" 2>/dev/null || true
sleep 1

ssh $SSH_OPTS \
    -L "${DB_PORT}:localhost:${DB_PORT}" \
    -L "${DIRECTOR_PORT}:localhost:${DIRECTOR_PORT}" \
    -N "${SERVER_USER}@${SERVER_HOST}" &
TUNNEL_PID=$!

# Wait for tunnel to be alive
for i in $(seq 1 20); do
    sleep 1
    if ! kill -0 "$TUNNEL_PID" 2>/dev/null; then
        echo "[launch] ERROR: SSH tunnel exited unexpectedly."
        exit 1
    fi
    if $PYTHON -c "import socket; s=socket.socket(); s.settimeout(1); s.connect(('127.0.0.1', $DB_PORT)); s.close()" 2>/dev/null; then
        echo "[launch] SSH tunnel established."
        break
    fi
done

# ── 3. kubectl port-forward on remote VM ────────────────────────────
if [ -n "$NAMESPACE" ]; then
    echo "[launch] Starting kubectl port-forward on VM..."
    # Discover service names dynamically (they don't carry the full namespace prefix)
    DB_SVC=$(ssh $SSH_OPTS "${SERVER_USER}@${SERVER_HOST}" \
        "sudo kubectl get svc -n ${NAMESPACE} -o name 2>/dev/null | grep 'db-dbdepl-svc' | sed 's|service/||'" 2>/dev/null || true)
    BGD_SVC=$(ssh $SSH_OPTS "${SERVER_USER}@${SERVER_HOST}" \
        "sudo kubectl get svc -n ${NAMESPACE} -o name 2>/dev/null | grep 'bgd-svc' | sed 's|service/||'" 2>/dev/null || true)

    # DB cluster port is 15432, we forward to local 15433
    DB_CLUSTER_PORT="15432"

    # Kill any stale port-forwards first
    ssh $SSH_OPTS "${SERVER_USER}@${SERVER_HOST}" "pkill -9 -f 'kubectl port-forward' 2>/dev/null; true" 2>/dev/null || true
    sleep 2

    # Start each port-forward in its own SSH session so stdin detaches cleanly
    ssh $SSH_OPTS "${SERVER_USER}@${SERVER_HOST}" \
        "nohup sudo kubectl port-forward -n ${NAMESPACE} svc/${DB_SVC} ${DB_PORT}:${DB_CLUSTER_PORT} > /tmp/pf_db.log 2>&1 < /dev/null &" 2>/dev/null || true
    ssh $SSH_OPTS "${SERVER_USER}@${SERVER_HOST}" \
        "nohup sudo kubectl port-forward -n ${NAMESPACE} svc/${BGD_SVC} ${DIRECTOR_PORT}:11717 > /tmp/pf_bgd.log 2>&1 < /dev/null &" 2>/dev/null || true

    echo "[launch] Waiting for DB to be reachable on port $DB_PORT..."
    for i in $(seq 1 30); do
        sleep 2
        if $PYTHON "$PROJECT_ROOT/scripts/db_check.py" "$DB_PORT" 2>/dev/null | grep -q "ok"; then
            echo "[launch] Database ready."
            break
        fi
    done
fi

# ── 4. Start app ─────────────────────────────────────────────────────
echo "[launch] Starting dashboard..."
cd "$PROJECT_ROOT"
exec $PYTHON run.py
