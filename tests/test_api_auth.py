"""Test that administrative API routes require authentication"""

import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


ADMIN_ENDPOINTS = [
    ("post", "/server/battlegroup/action"),
    ("post", "/server/battlegroup/update"),
    ("get", "/server/firewall"),
    ("post", "/server/firewall/block"),
    ("post", "/server/firewall/unblock"),
    ("get", "/api/chat_logs"),
    ("post", "/api/set_player_ip"),
    ("post", "/api/detect_player_ips"),
    ("post", "/api/ban_player"),
    ("post", "/api/get_player_ban"),
    ("post", "/api/get_player_history"),
    ("post", "/api/unban_player"),
    ("post", "/api/emergency_unban"),
    ("post", "/api/kick_player"),
    ("post", "/api/edit_vitals"),
    ("post", "/api/maintenance/create_indexes"),
    ("delete", "/api/vehicles/1"),
    ("delete", "/api/buildings/1"),
    ("post", "/api/add_item"),
    ("get", "/api/item_catalog"),
    ("post", "/api/item_catalog/add"),
    ("post", "/api/item_catalog/sync"),
    ("post", "/api/player/1/teleport"),
    ("post", "/api/player/1/whisper"),
    ("get",  "/api/player/1/stats"),
    ("get",  "/api/player/1/dungeon_history"),
    ("get",  "/api/player/1/currency_history"),
    ("get",  "/api/player/1/journey"),
    ("post", "/api/player/1/rename"),
    ("post", "/api/player/1/repair_gear"),
    ("post", "/api/player/1/fill_water"),
    ("post", "/api/player/1/wipe_codex"),
    ("post", "/api/player/1/dismiss_tutorials"),
    ("post", "/api/player/1/grant_keystones"),
    ("post", "/api/player/1/reset_keystones"),
    ("post", "/api/player/1/complete_journey"),
    ("post", "/api/player/1/reset_journey"),
    ("post", "/api/player/1/wipe_journey"),
    ("post", "/api/player/1/award_xp"),
    ("post", "/api/player/1/set_skill_points"),
    ("post", "/api/player/1/teleport_to_player"),
    ("post", "/api/player/1/spawn_vehicle"),
    ("post", "/api/service_broadcast"),
    ("post", "/api/shutdown_broadcast"),
    ("get",  "/api/storage"),
    ("get",  "/api/storage/1/items"),
    ("get",  "/api/market/listings"),
    ("get",  "/api/market/sales"),
    ("get",  "/api/players/search"),
]


@pytest.fixture
def client(tmp_path, monkeypatch):
    settings_path = tmp_path / "settings.yaml"
    settings_path.write_text(
        """
server:
  host: 127.0.0.1
  user: dune
dashboard:
  host: 127.0.0.1
  port: 5050
  debug: false
  secret_key: test-secret
database:
  host: 127.0.0.1
  port: 15433
  user: postgres
  password: postgres
  name: dune
kubernetes:
  namespace: test
auth:
  enabled: true
  username: admin
  password_hash: "$argon2id$v=19$m=65536,t=3,p=4$invalid$invalid"
logging:
  file: logs/test.log
""",
        encoding="utf-8",
    )

    monkeypatch.setattr("app.services.database.DatabaseService.ensure_tables", lambda self: None)
    monkeypatch.setattr("app.services.admin.AdminService.create_indexes", lambda self: (True, [], None))
    monkeypatch.setattr("app.services.updater.UpdateService.start_checker", lambda self: None)

    from app.factory import create_app
    app, _ = create_app(str(settings_path))
    app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    return app.test_client()


@pytest.mark.parametrize(("method", "path"), ADMIN_ENDPOINTS)
def test_admin_endpoints_require_login(client, method, path):
    """All administrative endpoints should require authentication when auth is enabled."""
    response = getattr(client, method)(path)
    assert response.status_code in (302, 401, 403), f"{method.upper()} {path} returned {response.status_code}, expected 302/401/403"