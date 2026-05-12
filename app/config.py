"""Settings loader - reads settings.yaml with env var overrides"""

import os
import yaml
import logging

logger = logging.getLogger(__name__)

DEFAULTS = {
    'server': {
        'host': '127.0.0.1',
        'user': 'dune',
        'ssh_key': None,
    },
    'dashboard': {
        'host': '127.0.0.1',
        'port': 5050,
        'debug': False,
        'secret_key': 'change-me-to-random-string',
    },
    'database': {
        'host': '127.0.0.1',
        'port': 15433,
        'user': 'postgres',
        'password': 'postgres',
        'name': 'dune',
        'schema': 'dune',
        'min_connections': 2,
        'max_connections': 10,
    },
    'kubernetes': {
        'namespace': '',
        'battlegroup_script': '/home/dune/.dune/bin/battlegroup',
    },
    'director': {
        'port': 32479,
    },
    'filebrowser': {
        'port': 18888,
    },
    'cache': {
        'chat_pod_ttl': 60,
        'chat_messages_ttl': 10,
        'static_data_ttl': 300,
    },
    'auth': {
        'enabled': True,
        'username': 'admin',
        'password': 'changeme',
    },
    'logging': {
        'level': 'INFO',
        'file': 'logs/dashboard.log',
        'max_bytes': 10485760,
        'backup_count': 5,
    },
}


def deep_merge(base, override):
    """Deep merge override dict into base dict."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_settings(settings_path=None):
    """Load settings from YAML file with defaults and env var overrides."""
    if settings_path is None:
        settings_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'settings.yaml')

    settings = DEFAULTS.copy()

    if os.path.exists(settings_path):
        try:
            with open(settings_path, 'r') as f:
                file_settings = yaml.safe_load(f) or {}
            settings = deep_merge(settings, file_settings)
            logger.info(f"Settings loaded from {settings_path}")
        except Exception as e:
            logger.error(f"Failed to load settings from {settings_path}: {e}")
            logger.warning("Using default settings")
    else:
        logger.warning(f"Settings file not found at {settings_path}, using defaults")

    env_overrides = {}

    if os.environ.get('DUNE_SERVER_HOST'):
        env_overrides.setdefault('server', {})['host'] = os.environ['DUNE_SERVER_HOST']
    if os.environ.get('DUNE_SERVER_USER'):
        env_overrides.setdefault('server', {})['user'] = os.environ['DUNE_SERVER_USER']
    if os.environ.get('DUNE_DB_PASSWORD'):
        env_overrides.setdefault('database', {})['password'] = os.environ['DUNE_DB_PASSWORD']
    if os.environ.get('DUNE_K8S_NAMESPACE'):
        env_overrides.setdefault('kubernetes', {})['namespace'] = os.environ['DUNE_K8S_NAMESPACE']
    if os.environ.get('DUNE_AUTH_PASSWORD'):
        env_overrides.setdefault('auth', {})['password'] = os.environ['DUNE_AUTH_PASSWORD']
    if os.environ.get('DUNE_DASHBOARD_PORT'):
        env_overrides.setdefault('dashboard', {})['port'] = int(os.environ['DUNE_DASHBOARD_PORT'])

    if env_overrides:
        settings = deep_merge(settings, env_overrides)
        logger.info("Environment variable overrides applied")

    return settings
