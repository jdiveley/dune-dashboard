# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the app

The app requires a running SSH tunnel and kubectl port-forwards before Flask can start. Use `launch.sh` (the systemd-safe wrapper) rather than `run.py` directly:

```bash
./launch.sh          # sets up tunnel + port-forwards, then starts Flask
python run.py        # direct start (requires tunnel already running externally)
```

The systemd service (`dune-dashboard.service`) calls `launch.sh`. Manage it with:

```bash
sudo systemctl start|stop|restart|status dune-dashboard
sudo journalctl -u dune-dashboard -f
```

## Tests

```bash
pytest               # all tests
pytest tests/test_api_auth.py          # single file
pytest -k test_name  # single test by name
```

Tests use mocks — they do not require a live server, tunnel, or database.

## Architecture

The app is a Flask + Flask-SocketIO dashboard for managing a Dune Awakening game server. It never talks to the game server directly from the browser — everything goes through this Python backend, which connects to the game server VM over SSH.

**Dependency chain:**

```
Browser → Flask (port 5050)
              ↓ DB queries
          localhost:15433  ← SSH -L tunnel ← game server VM
                                               ↑ kubectl port-forward → K8s DB svc (port 15432)
              ↓ Director API
          localhost:32479  ← SSH -L tunnel ← game server VM
                                               ↑ kubectl port-forward → K8s BGD svc (port 11717)
              ↓ SSH commands (kubectl, iptables, etc.)
          paramiko → game server VM (direct, no tunnel needed)
```

**App factory** (`app/factory.py`): wires all services together, registers routes, starts three background threads: connection monitor (60s health checks + auto-reconnect), SSL cert monitor, and update checker.

**Settings** (`app/config.py`): loads `settings.yaml`, deep-merges defaults, supports env var overrides (`DUNE_SERVER_HOST`, `DUNE_DB_PASSWORD`, `DUNE_K8S_NAMESPACE`, `DUNE_DASHBOARD_PORT`). Auto-migrates plaintext passwords to Argon2.

### Services (`app/services/`)

| Service | What it does |
|---|---|
| `database.py` | psycopg2 connection pool; all queries use RealDictCursor and parameterized SQL |
| `ssh.py` | Paramiko persistent connection (not subprocess); thread-safe; returns `(stdout, stderr, rc)` |
| `k8s.py` | Thin wrapper: prepends `sudo kubectl -n <namespace>` to commands run via SSHService |
| `player.py` | All player DB queries: online status, search, faction, inventory, progression, overview counts |
| `vehicle.py` | Vehicle/module queries and type mapping |
| `chat.py` | Reads chat from text-router pod logs, stores in `dashboard.chat_history`, backfills on startup |
| `admin.py` | Bans, kicks, IP detection/blocking, iptables firewall management, vitals/XP/faction editing |
| `director.py` | HTTP to director NodePort API; also patches K8s ConfigMap for `director.ini` overrides |
| `updater.py` | Polls GitHub API every 30min; replaces files safely (skips `settings.yaml`, `.git`, logs) |
| `audit.py` | In-memory ring buffer (1000 entries) + daily log files; redacts sensitive fields |

### Routes (`app/routes/`)

- **`main.py`** — Jinja2 template views (`/overview`, `/players`, `/chat`, `/vehicles`, `/server`, `/admin`, etc.). Injects connection status and static game data (factions, guilds, maps) via context processor. Static data is cached for 5 minutes.
- **`auth.py`** — Single-user Argon2 login; IP blocked for 15 min after 5 failures.
- **`api.py`** — All REST endpoints. Login required on all routes. Key groupings: server actions/pods/metrics, battlegroup control, firewall rules, player admin (ban/kick/vitals/XP/items), chat logs.

### WebSocket (`app/websocket/shell.py`)

Handles interactive shells via SocketIO: `shell_create` (type=`vm` or `k8s`), `shell_command`, `shell_close`. VM shells SSH to the game server; K8s shells use `kubectl exec`.

### Key conventions

- **Database schemas**: game data lives in the `dune` schema; dashboard-owned tables (bans, player_ips, chat_history) live in the `dashboard` schema to stay isolated from game backups.
- **SSH commands**: always go through `SSHService.run()` — never `subprocess` — so the persistent paramiko connection is reused.
- **Firewall management** (`admin.py`): manipulates iptables on the game server VM via SSH, not locally. Rules touch INPUT, FORWARD, and mangle PREROUTING chains.
- **K8s namespace**: auto-detected at startup by scanning for a namespace matching `funcom-seabass-*`. On this deployment: `funcom-seabass-sh-7affed93f292734b-otgeen`.

### Known bugs (upstream, do not fix unless asked)

- `api_files_save` in `api.py`: base64 content is computed but never piped to pod stdin — file saves silently zero out the file.
- `delete_vehicle` route body is truncated in `api.py` — the endpoint never registers with Flask.
