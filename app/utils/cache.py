"""Simple TTL-based cache"""

import datetime
import logging

logger = logging.getLogger(__name__)


class TTLCache:
    def __init__(self, ttl_seconds=60):
        self._data = None
        self._timestamp = 0
        self._ttl = ttl_seconds

    def get(self):
        current_time = datetime.datetime.now().timestamp()
        if self._data and (current_time - self._timestamp) < self._ttl:
            return self._data
        return None

    def set(self, data):
        self._data = data
        self._timestamp = datetime.datetime.now().timestamp()

    def invalidate(self):
        self._data = None
        self._timestamp = 0


class MultiCache:
    def __init__(self, ttl_seconds=60):
        self._cache = {}
        self._ttl = ttl_seconds

    def get(self, key):
        entry = self._cache.get(key)
        if not entry:
            return None
        current_time = datetime.datetime.now().timestamp()
        if (current_time - entry['timestamp']) < self._ttl:
            return entry['data']
        return None

    def set(self, key, data):
        self._cache[key] = {'data': data, 'timestamp': datetime.datetime.now().timestamp()}

    def invalidate(self, key=None):
        if key:
            self._cache.pop(key, None)
        else:
            self._cache = {}
