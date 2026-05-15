#!/bin/bash
# Dune Awakening Dashboard - Legacy Setup Entry Point
# This now redirects to the unified launcher.

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_ROOT"

echo "Starting Dune Awakening Dashboard Launcher..."
echo ""

if [ -f "$PROJECT_ROOT/start.sh" ]; then
    chmod +x "$PROJECT_ROOT/start.sh"
    bash "$PROJECT_ROOT/start.sh"
else
    echo "[ERROR] start.sh not found."
    exit 1
fi
