import atexit
import ipaddress
import re
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
atexit.register(_cache.close)

_MP3QURAN_SUBDOMAIN_RE = re.compile(r'^(?:server\d{1,3}|cdn|download|verse)\.mp3quran\.net$')


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
