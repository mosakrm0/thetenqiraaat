import atexit
import ipaddress
import json
import re
import sqlite3
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config import ALLOWED_AUDIO_HOSTS, CACHE_DIR, REQUEST_RETRIES

_INT_DICT_TAG = '__int_dict__'


def _encode_cache_value(value):
    if isinstance(value, dict):
        if any(isinstance(k, int) and not isinstance(k, bool) for k in value):
            return {
                _INT_DICT_TAG: [
                    [k, _encode_cache_value(v)]
                    for k, v in value.items()
                ],
            }
        return {k: _encode_cache_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_encode_cache_value(v) for v in value]
    if isinstance(value, tuple):
        return [_encode_cache_value(v) for v in value]
    return value


def _decode_cache_value(value):
    if isinstance(value, dict):
        if len(value) == 1 and _INT_DICT_TAG in value and isinstance(value[_INT_DICT_TAG], list):
            return {
                k: _decode_cache_value(v)
                for k, v in value[_INT_DICT_TAG]
            }
        return {k: _decode_cache_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_decode_cache_value(v) for v in value]
    return value


class SafeDiskCache:
    """SQLite + JSON disk cache with TTL support and no pickle deserialization."""

    def __init__(self, directory: Path | str):
        cache_dir = Path(directory)
        cache_dir.mkdir(parents=True, exist_ok=True)
        self._db_path = cache_dir / 'safe_cache.db'
        self._lock = threading.Lock()
        self._closed = False
        self._conn = sqlite3.connect(str(self._db_path), timeout=5.0, check_same_thread=False)
        self._conn.execute('PRAGMA journal_mode=WAL;')
        self._conn.execute('PRAGMA synchronous=NORMAL;')
        self._conn.execute('PRAGMA busy_timeout=5000;')
        self._conn.execute(
            '''CREATE TABLE IF NOT EXISTS cache_entries (
                key        TEXT PRIMARY KEY,
                value      TEXT NOT NULL,
                expires_at REAL
            )'''
        )
        self._conn.commit()

    def get(self, key: str, default=None):
        with self._lock:
            if self._closed:
                return default
            try:
                row = self._conn.execute(
                    'SELECT value, expires_at FROM cache_entries WHERE key = ?',
                    (key,),
                ).fetchone()
                if row is None:
                    return default
                raw_val, expires_at = row
                if expires_at is not None and expires_at <= time.time():
                    self._conn.execute('DELETE FROM cache_entries WHERE key = ?', (key,))
                    self._conn.commit()
                    return default
                return _decode_cache_value(json.loads(raw_val))
            except (sqlite3.Error, TypeError, ValueError):
                return default

    def set(self, key: str, value, expire: float | None = None) -> bool:
        expires_at = (time.time() + float(expire)) if expire is not None else None
        encoded = json.dumps(_encode_cache_value(value), ensure_ascii=False, separators=(',', ':'))
        with self._lock:
            if self._closed:
                return False
            self._conn.execute(
                'INSERT OR REPLACE INTO cache_entries (key, value, expires_at) VALUES (?, ?, ?)',
                (key, encoded, expires_at),
            )
            self._conn.commit()
            return True

    def close(self) -> None:
        with self._lock:
            if not self._closed:
                self._closed = True
                self._conn.close()


_http_session: requests.Session | None = None
_http_session_lock = threading.Lock()
_cache = SafeDiskCache(CACHE_DIR)
atexit.register(_cache.close)

_MP3QURAN_SUBDOMAIN_RE = re.compile(r'^(?:server\d{1,3}|cdn|download|verse)\.mp3quran\.net$')


def get_cache() -> SafeDiskCache:
    return _cache


def get_http_session() -> requests.Session:
    global _http_session
    if _http_session is not None:
        return _http_session
    with _http_session_lock:
        if _http_session is not None:
            return _http_session
        retry = Retry(
            total=REQUEST_RETRIES,
            backoff_factor=0.5,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=('GET', 'POST'),
        )
        adapter = HTTPAdapter(max_retries=retry, pool_connections=20, pool_maxsize=20)
        s = requests.Session()
        s.mount('https://', adapter)
        s.mount('http://', adapter)
        _http_session = s
        return s


def is_allowed_audio_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        port = parsed.port
    except (AttributeError, TypeError, ValueError):
        return False
    if parsed.scheme != 'https':
        return False
    if parsed.username is not None or parsed.password is not None:
        return False
    if port not in (None, 443):
        return False
    if '..' in (parsed.path or '').split('/'):
        return False
    host = (parsed.hostname or '').lower().strip('.')
    if not host:
        return False

    # Reject raw IP addresses (SSRF guard)
    try:
        ipaddress.ip_address(host)
        return False
    except ValueError:
        pass

    if host in ALLOWED_AUDIO_HOSTS:
        return True
    # Allow known *.mp3quran.net audio server subdomains (e.g., server6..server16, cdn, download)
    return bool(_MP3QURAN_SUBDOMAIN_RE.match(host))
