#!/bin/bash
# Dune Dashboard - systemd launch wrapper
# Sets up SSH tunnel + kubectl port-forwards before starting the app.
set -e

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
PYTHON="$PROJECT_ROOT/.venv/bin/python3"
SSH_KEY="/home/jdiveley/.ssh/dune-dashboard-key"
SERVER_USER="dune"
SERVER_HOST="192.168.250.200"
DB_PORT="15433"
DB_CLUSTER_PORT="15432"
DIRECTOR_PORT="32479"

SSH_OPTS="-i $SSH_KEY -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=30 -o ServerAliveCountMax=3 -o ConnectTimeout=15 -o BatchMode=yes"

# ── Helpers ──────────────────────────────────────────────────────────

start_bgd_pf() {
    ssh $SSH_OPTS "${SERVER_USER}@${SERVER_HOST}" \
        "nohup sudo kubectl port-forward -n ${NAMESPACE} svc/${BGD_SVC} ${DIRECTOR_PORT}:11717 > /tmp/pf_bgd.log 2>&1 < /dev/null &" 2>/dev/null || true
}

bgd_port_alive() {
    # Check on the REMOTE side — local socket.connect() always succeeds because
    # the SSH daemon accepts the TCP handshake before it attempts the remote
    # forward, so a local TCP check never detects a dead port-forward.
    ssh $SSH_OPTS "${SERVER_USER}@${SERVER_HOST}" \
        "ss -tln 2>/dev/null | grep -q ':${DIRECTOR_PORT}'" 2>/dev/null
}

cleanup() {
    echo "[launch] Cleaning up..."
    kill "$WATCHDOG_PID" 2>/dev/null || true
    kill "$TUNNEL_PID" 2>/dev/null || true
    ssh $SSH_OPTS "${SERVER_USER}@${SERVER_HOST}" "sudo pkill -f 'kubectl port-forward' 2>/dev/null; true" 2>/dev/null || true
}
trap cleanup EXIT

# ── 1. Detect namespace ───────────────────────────────────────────────
echo "[launch] Detecting Kubernetes namespace..."
NAMESPACE=$(ssh $SSH_OPTS "${SERVER_USER}@${SERVER_HOST}" \
    "sudo kubectl get namespaces -o name 2>/dev/null | grep 'namespace/funcom-seabass-' | head -1 | sed 's|namespace/||'" 2>/dev/null || true)

if [ -z "$NAMESPACE" ]; then
    echo "[launch] WARNING: Could not detect namespace. DB port-forward will be skipped."
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

# ── 3. kubectl port-forwards on remote VM ────────────────────────────
if [ -n "$NAMESPACE" ]; then
    echo "[launch] Starting kubectl port-forwards on VM..."

    DB_SVC=$(ssh $SSH_OPTS "${SERVER_USER}@${SERVER_HOST}" \
        "sudo kubectl get svc -n ${NAMESPACE} -o name 2>/dev/null | grep 'db-dbdepl-svc' | sed 's|service/||'" 2>/dev/null || true)
    BGD_SVC=$(ssh $SSH_OPTS "${SERVER_USER}@${SERVER_HOST}" \
        "sudo kubectl get svc -n ${NAMESPACE} -o name 2>/dev/null | grep 'bgd-svc' | sed 's|service/||'" 2>/dev/null || true)

    # Kill any stale port-forwards (sudo so we can kill root-owned processes)
    ssh $SSH_OPTS "${SERVER_USER}@${SERVER_HOST}" "sudo pkill -9 -f 'kubectl port-forward' 2>/dev/null; true" 2>/dev/null || true
    sleep 2

    # Each port-forward gets its own SSH session so stdin detaches cleanly
    ssh $SSH_OPTS "${SERVER_USER}@${SERVER_HOST}" \
        "nohup sudo kubectl port-forward -n ${NAMESPACE} svc/${DB_SVC} ${DB_PORT}:${DB_CLUSTER_PORT} > /tmp/pf_db.log 2>&1 < /dev/null &" 2>/dev/null || true
    start_bgd_pf

    echo "[launch] Waiting for DB to be reachable on port $DB_PORT..."
    for i in $(seq 1 30); do
        sleep 2
        if $PYTHON "$PROJECT_ROOT/scripts/db_check.py" "$DB_PORT" 2>/dev/null | grep -q "ok"; then
            echo "[launch] Database ready."
            break
        fi
    done

    # ── 4. BGD watchdog ──────────────────────────────────────────────
    # Runs in background alongside Flask; restarts BGD port-forward if it dies.
    (
        while true; do
            sleep 30
            if ! bgd_port_alive; then
                echo "[launch] BGD port-forward down, restarting..."
                start_bgd_pf
                sleep 5
                if bgd_port_alive; then
                    echo "[launch] BGD port-forward restored."
                else
                    echo "[launch] BGD port-forward restart failed, will retry."
                fi
            fi
        done
    ) &
    WATCHDOG_PID=$!
fi

# ── 5. Start app ──────────────────────────────────────────────────────
echo "[launch] Starting dashboard..."
cd "$PROJECT_ROOT"
exec $PYTHON run.py
