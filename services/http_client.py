import ipaddress
import threading
from urllib.parse import urlparse

import diskcache
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config import ALLOWED_AUDIO_HOSTS, CACHE_DIR, REQUEST_RETRIES

_http_session: requests.Session | None = None
_http_session_lock = threading.Lock()
_cache = diskcache.Cache(str(CACHE_DIR))


def get_cache() -> diskcache.Cache:
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
    except Exception:
        return False
    if parsed.scheme != 'https':
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
    # Allow *.mp3quran.net subdomains (e.g., server6..server16, cdn, download)
    if host.endswith('.mp3quran.net') and len(host) > len('.mp3quran.net'):
        return True
    return False
