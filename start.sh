#!/bin/bash
# Dune Awakening Dashboard Launcher (Linux/macOS)
# Starts SSH tunnel, DB port-forward, then runs the dashboard

set -e

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
SETTINGS_FILE="$PROJECT_ROOT/settings.yaml"

# Determine Python command
PYTHON=""
if command -v python3 &>/dev/null; then
    PYTHON="python3"
elif command -v python &>/dev/null; then
    PYTHON="python"
else
    echo "[ERROR] Python not found. Install Python 3.8+ first."
    exit 1
fi

# Check if settings exist
if [ ! -f "$SETTINGS_FILE" ]; then
    echo "[WARN] settings.yaml not found. Running setup..."
    bash "$PROJECT_ROOT/setup.sh"
    if [ ! -f "$SETTINGS_FILE" ]; then
        echo "[ERROR] Setup failed."
        exit 1
    fi
fi

# Read settings safely via Python
eval "$($PYTHON -c "
import yaml, json, os, sys
with open('$SETTINGS_FILE') as f:
    s = yaml.safe_load(f) or {}
ssh_key = s.get('server', {}).get('ssh_key') or ''
print(f'SSH_HOST=\"{s.get(\"server\", {}).get(\"host\", \"\")}\"')
print(f'SSH_USER=\"{s.get(\"server\", {}).get(\"user\", \"dune\")}\"')
print(f'SSH_KEY=\"{ssh_key}\"')
print(f'LOCAL_PORT={s.get(\"database\", {}).get(\"port\", 15433)}')
print(f'DASHBOARD_PORT={s.get(\"dashboard\", {}).get(\"port\", 5050)}')
print(f'NAMESPACE=\"{s.get(\"kubernetes\", {}).get(\"namespace\", \"\")}\"')
")"

# Fallback SSH key resolution
LOCAL_KEY="$PROJECT_ROOT/internal-scripts/ssh/sshKey"
if [ -z "$SSH_KEY" ] || [ ! -f "$SSH_KEY" ]; then
    if [ -f "$LOCAL_KEY" ]; then
        SSH_KEY="$LOCAL_KEY"
    else
        echo "[ERROR] SSH key not found. Set ssh_key in settings.yaml or place key at:"
        echo "  - $LOCAL_KEY"
        echo "  - /tmp/dune-tunnel-key"
        exit 1
    fi
fi

chmod 600 "$SSH_KEY" 2>/dev/null || true

# Track SSH tunnel PID for cleanup
SSH_PID=""

cleanup() {
    echo "Stopping tunnels..."
    if [ -n "$SSH_PID" ] && kill -0 "$SSH_PID" 2>/dev/null; then
        kill "$SSH_PID" 2>/dev/null || true
    fi
    ssh -i "$SSH_KEY" -o ConnectTimeout=5 "${SSH_USER}@${SSH_HOST}" "pkill -f 'kubectl port-forward' 2>/dev/null" || true
    exit 0
}
trap cleanup EXIT INT TERM

echo ""
echo "============================================================"
echo "  Dune Awakening Dashboard"
echo "============================================================"
echo ""

echo "[1/4] Starting SSH tunnel (localhost:$LOCAL_PORT -> VM)..."
ssh -i "$SSH_KEY" \
    -o StrictHostKeyChecking=accept-new \
    -o ServerAliveInterval=30 \
    -o ServerAliveCountMax=3 \
    -L "${LOCAL_PORT}:localhost:${LOCAL_PORT}" \
    -N -f "${SSH_USER}@${SSH_HOST}"

# Get the PID of the background SSH process
if command -v pgrep &>/dev/null; then
    SSH_PID=$(pgrep -f "ssh.*${SSH_HOST}.*${LOCAL_PORT}.*-N" | head -1)
else
    SSH_PID=$(ps aux | grep "ssh.*${SSH_HOST}.*${LOCAL_PORT}.*-N" | grep -v grep | awk '{print $2}' | head -1)
fi

sleep 3
echo "[OK]   SSH tunnel up on localhost:$LOCAL_PORT"

echo "[2/4] Starting DB port-forward on VM..."

# Auto-detect DB service name
DB_SVC=$(ssh -i "$SSH_KEY" -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10 "${SSH_USER}@${SSH_HOST}" "sudo kubectl get svc -n ${NAMESPACE} -o name 2>/dev/null" | grep -E 'db.*svc|postgres' | head -1 | sed 's|service/||')
if [ -z "$DB_SVC" ]; then
    DB_SVC="${NAMESPACE}-db-dbdepl-svc"
fi

ssh -i "$SSH_KEY" \
    -o StrictHostKeyChecking=accept-new \
    -o ServerAliveInterval=30 \
    "${SSH_USER}@${SSH_HOST}" \
    "nohup sudo kubectl port-forward -n ${NAMESPACE} svc/${DB_SVC} ${LOCAL_PORT}:15432 > /tmp/pf.log 2>&1 &"

sleep 5

echo "[3/4] Checking database connection..."
DB_OK=false
for i in $(seq 1 15); do
    if $PYTHON -c "import psycopg2; psycopg2.connect(host='localhost', port=$LOCAL_PORT, user='postgres', password='postgres', dbname='dune', connect_timeout=3).close()" 2>/dev/null; then
        DB_OK=true
        break
    fi
    sleep 1
done

if [ "$DB_OK" = true ]; then
    echo "[OK]   Database connected"
else
    echo "[ERROR] Database connection failed."
    echo "Checking port-forward log on VM..."
    ssh -i "$SSH_KEY" -o ConnectTimeout=10 "${SSH_USER}@${SSH_HOST}" "cat /tmp/pf.log" 2>/dev/null || echo "Log empty or unreadable."
    echo ""
    echo "Verify DB service exists:"
    echo "  ssh -i $SSH_KEY ${SSH_USER}@${SSH_HOST} 'sudo kubectl get svc -n $NAMESPACE'"
    exit 1
fi

echo "[4/4] Starting dashboard..."

# Check dependencies
if ! $PYTHON -c "import flask_socketio, yaml, flask_login" 2>/dev/null; then
    echo "  Installing dependencies..."
    $PYTHON -m pip install -r "$PROJECT_ROOT/requirements.txt" --quiet
fi

cd "$PROJECT_ROOT"
$PYTHON run.py
