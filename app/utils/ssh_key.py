"""Centralized SSH key resolution utility.

All SSH key lookup logic lives here to avoid duplication across
SSHService, WebSocket shell, and launcher scripts.
"""

import os
import logging

logger = logging.getLogger(__name__)


def resolve_ssh_key(ssh_key_from_settings=None):
    """Resolve SSH key path from settings or fallback locations.

    Search order:
    1. Path from settings.yaml (if it exists)
    2. ~/.ssh/dune-dashboard-key (recommended location)
    3. %TEMP%/dune-tunnel-key (Windows temp)
    4. /tmp/dune-tunnel-key (Linux/macOS temp)
    5. %TEMP%/dune-awakening-server-sshKey
    6. /tmp/dune-awakening-server-sshKey
    7. internal-scripts/ssh/sshKey (project-local, legacy)
    8. parent/internal-scripts/ssh/sshKey (legacy)
    9. %LOCALAPPDATA%/DuneAwakeningServer/sshKey (Windows legacy)
    10. ~/.ssh/id_ed25519 (default OpenSSH key)
    11. ~/.ssh/id_rsa (default OpenSSH key)

    Args:
        ssh_key_from_settings: The ssh_key value from settings.yaml, or None.

    Returns:
        The first existing SSH key path found, or None.
    """
    if ssh_key_from_settings:
        key = str(ssh_key_from_settings).strip("'\"")
        if os.path.exists(key):
            logger.debug("SSH key found in settings: %s", key)
            return key

    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    temp_dir = os.environ.get('TEMP') or os.environ.get('TMPDIR') or ('/tmp' if os.name != 'nt' else 'C:\\Temp')
    local_appdata = os.environ.get('LOCALAPPDATA', '')
    user_home = os.path.expanduser('~')

    potential_paths = [
        os.path.join(user_home, '.ssh', 'dune-dashboard-key'),
        os.path.join(temp_dir, 'dune-tunnel-key'),
        os.path.join(temp_dir, 'dune-awakening-server-sshKey'),
        os.path.join(base_dir, 'internal-scripts', 'ssh', 'sshKey'),
        os.path.join(os.path.dirname(base_dir), 'internal-scripts', 'ssh', 'sshKey'),
        os.path.join(user_home, '.ssh', 'id_ed25519'),
        os.path.join(user_home, '.ssh', 'id_rsa'),
    ]
    if local_appdata:
        potential_paths.insert(3, os.path.join(local_appdata, 'DuneAwakeningServer', 'sshKey'))

    for path in potential_paths:
        if os.path.exists(path):
            logger.debug("SSH key found at: %s", path)
            return path

    logger.warning("No SSH key found in any fallback location")
    return None
