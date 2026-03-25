import logging
import os
import sqlite3
import threading
import time
from pathlib import Path
from urllib.parse import urlparse
import requests
from flask import Flask, Response, jsonify, render_template, request
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

app = Flask(__name__)

# ── paths ──────────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
DB_PATH = BASE_DIR / 'quran.db'

# ── config ─────────────────────────────────────────────────────────────────────
REQUEST_TIMEOUT = float(os.getenv('QURAN_API_TIMEOUT', '12'))
REQUEST_RETRIES = int(os.getenv('QURAN_API_RETRIES', '2'))
MAX_AUDIO_PROXY_BYTES = 50 * 1024 * 1024  # 50 MB safety cap
KFGQPC_CACHE_TTL_SEC = 60 * 60 * 12
EVERYAYAH_RECITATIONS_URL = 'https://everyayah.com/data/recitations.js'
EVERYAYAH_CACHE_TTL_SEC = 60 * 60 * 24
ALQURAN_TRANSLATIONS_URL = 'https://api.alquran.cloud/v1/edition?format=text&type=translation'
FAWAZ_EDITIONS_URL = 'https://raw.githubusercontent.com/fawazahmed0/quran-api/refs/heads/1/editions.json'
TRANSLATIONS_CACHE_TTL_SEC = 60 * 60 * 12

KFGQPC_JSON_URLS = {
    'warsh':  'https://raw.githubusercontent.com/thetruetruth/quran-data-kfgqpc/main/warsh/data/warshData_v10.json',
    'qaloon': 'https://raw.githubusercontent.com/thetruetruth/quran-data-kfgqpc/main/qaloon/data/QaloonData_v10.json',
    'bazzi':  'https://raw.githubusercontent.com/thetruetruth/quran-data-kfgqpc/main/bazzi/data/BazziData_v07.json',
    'douri':  'https://raw.githubusercontent.com/thetruetruth/quran-data-kfgqpc/main/doori/data/DooriData_v09.json',
    'susi':   'https://raw.githubusercontent.com/thetruetruth/quran-data-kfgqpc/main/soosi/data/SoosiData09.json',
    'shouba': 'https://raw.githubusercontent.com/thetruetruth/quran-data-kfgqpc/main/shouba/data/ShoubaData08.json',
    'qumbul': 'https://raw.githubusercontent.com/thetruetruth/quran-data-kfgqpc/main/qumbul/data/QumbulData_v07.json',
}

QF_CLIENT_ID     = os.getenv('QF_CLIENT_ID', '').strip()
QF_CLIENT_SECRET = os.getenv('QF_CLIENT_SECRET', '').strip()
QF_ENV           = os.getenv('QF_ENV', 'production').strip().lower()

QF_AUTH_BASES = {
    'prelive':    'https://prelive-oauth2.quran.foundation',
    'production': 'https://oauth2.quran.foundation',
}
QF_API_BASES = {
    'prelive':    'https://apis-prelive.quran.foundation/content/api/v4',
    'production': 'https://apis.quran.foundation/content/api/v4',
}

# Public (no-auth) QF API for per-ayah audio files
QF_PUBLIC_API_BASE   = 'https://api.qurancdn.com/api/qdc'
QF_AUDIO_CDN_BASE    = 'https://verses.quran.foundation/'

QF_SCOPE              = 'content'
QF_TOKEN_BUFFER_SEC   = 30
QF_RESCACHE_TTL_SEC   = 60 * 60 * 6
QF_CHAPTER_CACHE_TTL_SEC = 60 * 60 * 3
QF_PUBLIC_AUDIO_TTL_SEC  = 60 * 60 * 6

QF_QIRAA_HINTS = {
    'hafs':    ['حفص', 'hafs', 'asim', 'asim'],
    'warsh':   ['ورش', 'warsh', 'nafi', 'نافع'],
    'shouba':  ['شعبة', 'shouba', 'shu\'bah', 'asim', 'عاصم'],
    'qaloon':  ['قالون', 'qaloon', 'qalon', 'nafi', 'نافع'],
    'bazzi':   ['البزي', 'bazzi', 'ibn kathir', 'ابن كثير'],
    'qumbul':  ['قنبل', 'qumbul', 'qunbul', 'ibn kathir', 'ابن كثير'],
    'douri':   ['الدوري', 'doori', 'duri', 'abu amr', 'ابو عمرو', 'أبو عمرو'],
    'susi':    ['السوسي', 'susi', 'sousi', 'abu amr', 'ابو عمرو', 'أبو عمرو'],
    'hisham':  ['هشام', 'hisham', 'ibn amir', 'ابن عامر'],
    'khallad': ['خلاد', 'khallad', 'hamzah', 'حمزة'],
    'harith':  ['الحارث', 'harith', 'kisai', 'kisaei', 'كسائي', 'الكسائي'],
    'wardan':  ['وردان', 'wardan', 'abu jafar', 'abu jaafar', 'أبو جعفر'],
    'ruways':  ['رويس', 'ruways', 'yaqub', 'يعقوب'],
    'ishaq':   ['إسحاق', 'اسحاق', 'ishaq', 'khalaf', 'خلف'],
}

# ── single source of truth for qiraat ─────────────────────────────────────────
# Each entry:
#   key        – internal identifier
#   textId     – edition ID used to fetch Arabic text
#   source     – 'fawaz', 'alquran', or 'mp3quran' (audio fallback)
#   fallback   – True when textId is Hafs/Uthmani stand-in (no dedicated digital text)
#   qfPublicId – recitation ID on api.qurancdn.com (public, no auth needed); None = not available
#   rewayaId   – mp3quran.net rewaya ID for audio fallback
QIRAAT = [
    {"key": "hafs",    "textId": "quran-uthmani",        "source": "alquran", "fallback": False, "qfPublicId": 7,    "rewayaId": None},
    {"key": "warsh",   "textId": "warsh",                "source": "kfgqpc",  "fallback": False, "qfPublicId": None, "rewayaId": 5},
    {"key": "shouba",  "textId": "shouba",               "source": "kfgqpc",  "fallback": False, "qfPublicId": None, "rewayaId": 15},
    {"key": "qaloon",  "textId": "qaloon",               "source": "kfgqpc",  "fallback": False, "qfPublicId": None, "rewayaId": 5},
    {"key": "bazzi",   "textId": "bazzi",                "source": "kfgqpc",  "fallback": False, "qfPublicId": None, "rewayaId": 4},
    {"key": "qumbul",  "textId": "qumbul",               "source": "kfgqpc",  "fallback": False, "qfPublicId": None, "rewayaId": 6},
    {"key": "douri",   "textId": "douri",                "source": "kfgqpc",  "fallback": False, "qfPublicId": None, "rewayaId": 13},
    {"key": "susi",    "textId": "susi",                 "source": "kfgqpc",  "fallback": False, "qfPublicId": None, "rewayaId": 7},
    {"key": "hisham",  "textId": "quran-uthmani",        "source": "alquran", "fallback": True,  "qfPublicId": None, "rewayaId": 14},
    {"key": "khallad", "textId": "quran-uthmani",        "source": "alquran", "fallback": True,  "qfPublicId": None, "rewayaId": 11},
    {"key": "harith",  "textId": "quran-uthmani",        "source": "alquran", "fallback": True,  "qfPublicId": None, "rewayaId": 10},
    {"key": "wardan",  "textId": "quran-uthmani",        "source": "alquran", "fallback": True,  "qfPublicId": None, "rewayaId": 12},
    {"key": "ruways",  "textId": "quran-uthmani",        "source": "alquran", "fallback": True,  "qfPublicId": None, "rewayaId": 15},
    {"key": "ishaq",   "textId": "quran-uthmani",        "source": "alquran", "fallback": True,  "qfPublicId": None, "rewayaId": 16},
]

ALLOWED_AUDIO_HOSTS = {
    'server6.mp3quran.net',  'server7.mp3quran.net',  'server8.mp3quran.net',
    'server9.mp3quran.net',  'server10.mp3quran.net', 'server11.mp3quran.net',
    'server12.mp3quran.net', 'server13.mp3quran.net', 'server14.mp3quran.net',
    'server16.mp3quran.net', 'everyayah.com',
    'cdn.islamic.network',   'verses.quran.foundation',
    'audio.qurancdn.com',    'download.quranicaudio.com',
}

logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

# ── module-level HTTP session (reused across requests) ─────────────────────────
_http_session: requests.Session | None = None
_http_session_lock = threading.Lock()

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

# ── QF auth (private API, optional) ───────────────────────────────────────────
_qf_token_lock = threading.Lock()
_qf_token = {'value': None, 'exp': 0.0}
_qf_recitations_cache: dict = {'exp': 0.0, 'items': []}
_qf_choice_cache: dict = {}
_qf_chapter_audio_cache: dict = {}

# QF public audio cache  {(qf_public_id, surah): {'exp': float, 'ayah_map': dict}}
_qf_public_audio_cache: dict = {}
_kfgqpc_json_cache: dict = {}
_everyayah_recitations_cache: dict = {'exp': 0.0, 'payload': None}
_alquran_translations_cache: dict = {'exp': 0.0, 'items': None}
_fawaz_editions_cache: dict = {'exp': 0.0, 'items': None}


def get_db_connection():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with sqlite3.connect(str(DB_PATH)) as conn:
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS ayahs (
            id    INTEGER PRIMARY KEY AUTOINCREMENT,
            surah INTEGER,
            ayah  INTEGER,
            qiraa TEXT,
            text  TEXT,
            UNIQUE(surah, ayah, qiraa)
        )''')
        c.execute('CREATE INDEX IF NOT EXISTS idx_ayahs_surah_qiraa ON ayahs(surah, qiraa)')
        conn.commit()


# ── QF private API helpers ─────────────────────────────────────────────────────
def qf_is_enabled():
    return bool(QF_CLIENT_ID and QF_CLIENT_SECRET)

def qf_env_key():
    return 'prelive' if QF_ENV == 'prelive' else 'production'

def qf_auth_base_url():
    return QF_AUTH_BASES[qf_env_key()]

def qf_api_base_url():
    return QF_API_BASES[qf_env_key()]

def qf_token_valid():
    return bool(_qf_token['value']) and (_qf_token['exp'] - QF_TOKEN_BUFFER_SEC) > time.time()

def qf_request_token(session):
    resp = session.post(
        f"{qf_auth_base_url()}/oauth2/token",
        data={'grant_type': 'client_credentials', 'scope': QF_SCOPE},
        auth=(QF_CLIENT_ID, QF_CLIENT_SECRET),
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    payload = resp.json()
    access_token = payload.get('access_token')
    if not access_token:
        raise ValueError('QF token response missing access_token')
    return access_token, time.time() + max(60, int(payload.get('expires_in', 3600)))

def qf_get_token(session, force_refresh=False):
    if not qf_is_enabled():
        raise RuntimeError('Quran Foundation integration is not configured')
    if not force_refresh and qf_token_valid():
        return _qf_token['value']
    with _qf_token_lock:
        if not force_refresh and qf_token_valid():
            return _qf_token['value']
        token, exp = qf_request_token(session)
        _qf_token['value'] = token
        _qf_token['exp'] = exp
        return token

def qf_extract_list(payload, key):
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        v = payload.get(key)
        if isinstance(v, list):
            return v
    return []

def qf_api_get(session, path, params=None, retry_401=True):
    token = qf_get_token(session)
    headers = {'x-auth-token': token, 'x-client-id': QF_CLIENT_ID}
    url = f"{qf_api_base_url()}{path}"
    resp = session.get(url, params=params or {}, headers=headers, timeout=REQUEST_TIMEOUT)
    if resp.status_code == 401 and retry_401:
        token = qf_get_token(session, force_refresh=True)
        headers['x-auth-token'] = token
        resp = session.get(url, params=params or {}, headers=headers, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    return resp.json()

def qf_build_recitation_text(recitation):
    if not isinstance(recitation, dict):
        return ''
    parts = [
        str(recitation.get('reciter_name') or ''),
        str(recitation.get('style') or ''),
        str(recitation.get('name') or ''),
    ]
    translated = recitation.get('translated_name')
    if isinstance(translated, dict):
        parts.append(str(translated.get('name') or ''))
    return ' '.join(parts).strip().lower()

def qf_score_recitation_for_qiraa(qiraa_key, recitation):
    hints = QF_QIRAA_HINTS.get(qiraa_key, [])
    hay = qf_build_recitation_text(recitation)
    return sum(10 for h in hints if h.lower() in hay)

def qf_get_recitations(session):
    now = time.time()
    if _qf_recitations_cache['exp'] > now and _qf_recitations_cache['items']:
        return _qf_recitations_cache['items']
    payload = qf_api_get(session, '/resources/recitations', params={'language': 'ar'})
    items = qf_extract_list(payload, 'recitations')
    if not items:
        payload = qf_api_get(session, '/resources/recitations', params={'language': 'en'})
        items = qf_extract_list(payload, 'recitations')
    _qf_recitations_cache['items'] = items
    _qf_recitations_cache['exp'] = now + QF_RESCACHE_TTL_SEC
    return items

def qf_parse_ayah_number(verse_key):
    if not isinstance(verse_key, str) or ':' not in verse_key:
        return None
    try:
        return int(verse_key.split(':', 1)[1])
    except Exception:
        return None

def qf_extract_audio_file_url(item):
    if not isinstance(item, dict):
        return None
    for key in ('url', 'audio_url', 'file_url'):
        v = item.get(key)
        if isinstance(v, str) and v:
            return v
    audio_file = item.get('audio_file')
    if isinstance(audio_file, dict):
        v = audio_file.get('url')
        if isinstance(v, str) and v:
            return v
    return None

def _fetch_chapter_audio_map_paginated(session, fetch_fn, surah_number):
    """Generic paginator for endpoints returning {audio_files, pagination}."""
    ayah_map = {}
    page = 1
    while True:
        payload = fetch_fn(page)
        audio_files = qf_extract_list(payload, 'audio_files')
        if not audio_files:
            break
        for item in audio_files:
            verse_key = item.get('verse_key') or item.get('ayah_key')
            ayah_number = qf_parse_ayah_number(verse_key)
            audio_url = qf_extract_audio_file_url(item)
            if ayah_number and audio_url:
                ayah_map[ayah_number] = audio_url
        pagination = payload.get('pagination') if isinstance(payload, dict) else None
        total_pages = 1
        if isinstance(pagination, dict):
            try:
                total_pages = int(pagination.get('total_pages') or 1)
            except Exception:
                pass
        if page >= total_pages:
            break
        page += 1
    return ayah_map

def qf_get_chapter_audio_map(session, recitation_id, surah_number):
    cache_key = (int(recitation_id), int(surah_number))
    cached = _qf_chapter_audio_cache.get(cache_key)
    now = time.time()
    if cached and cached['exp'] > now:
        return cached['ayah_map']

    def fetch_fn(page):
        return qf_api_get(
            session,
            f'/recitations/{int(recitation_id)}/by_chapter/{int(surah_number)}',
            params={'page': page, 'per_page': 50},
        )

    ayah_map = _fetch_chapter_audio_map_paginated(session, fetch_fn, surah_number)
    _qf_chapter_audio_cache[cache_key] = {'exp': now + QF_CHAPTER_CACHE_TTL_SEC, 'ayah_map': ayah_map}
    return ayah_map

def qf_pick_recitation_for_qiraa(session, qiraa_key, surah_number):
    choice_cache_key = (qiraa_key, int(surah_number))
    cached = _qf_choice_cache.get(choice_cache_key)
    now = time.time()
    if cached and cached.get('exp', 0) > now:
        return cached.get('choice')

    scored = sorted(
        [(qf_score_recitation_for_qiraa(qiraa_key, r), r)
         for r in qf_get_recitations(session)
         if isinstance(r.get('id'), int) and qf_score_recitation_for_qiraa(qiraa_key, r) > 0],
        key=lambda x: x[0], reverse=True,
    )

    chosen = None
    for _, recitation in scored[:12]:
        rid = recitation.get('id')
        try:
            if qf_get_chapter_audio_map(session, rid, surah_number):
                chosen = {'id': rid, 'name': recitation.get('reciter_name') or recitation.get('name') or str(rid)}
                break
        except Exception:
            continue

    _qf_choice_cache[choice_cache_key] = {'exp': now + 3600, 'choice': chosen}
    return chosen

def qf_get_ayah_audio_url(session, qiraa_key, surah_number, ayah_number):
    choice = qf_pick_recitation_for_qiraa(session, qiraa_key, surah_number)
    if not choice:
        return None, None
    ayah_map = qf_get_chapter_audio_map(session, choice['id'], surah_number)
    return ayah_map.get(int(ayah_number)), choice


# ── QF public (no-auth) per-ayah audio ────────────────────────────────────────
def _resolve_audio_url(raw_url: str) -> str:
    """Make a relative QF CDN path into an absolute URL."""
    if raw_url.startswith('http://') or raw_url.startswith('https://'):
        return raw_url
    return QF_AUDIO_CDN_BASE + raw_url.lstrip('/')

def qf_public_get_chapter_audio_map(surah_number: int, qf_public_id: int) -> dict:
    """
    Fetch per-ayah audio URLs from the public QF CDN API (no OAuth needed).
    Returns {ayah_number: absolute_url}.
    """
    cache_key = (int(qf_public_id), int(surah_number))
    cached = _qf_public_audio_cache.get(cache_key)
    now = time.time()
    if cached and cached['exp'] > now:
        return cached['ayah_map']

    session = get_http_session()
    ayah_map = {}
    page = 1
    while True:
        url = f"{QF_PUBLIC_API_BASE}/recitations/{qf_public_id}/by_chapter/{surah_number}"
        try:
            resp = session.get(url, params={'page': page, 'per_page': 50}, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            payload = resp.json()
        except Exception as exc:
            logger.warning('QF public audio fetch failed for recitation %s surah %s page %s: %s',
                           qf_public_id, surah_number, page, exc)
            break

        for item in payload.get('audio_files', []):
            verse_key = item.get('verse_key', '')
            ayah_num = qf_parse_ayah_number(verse_key)
            raw_url = item.get('url', '')
            if ayah_num and raw_url:
                ayah_map[ayah_num] = _resolve_audio_url(raw_url)

        pagination = payload.get('pagination') or {}
        try:
            total_pages = int(pagination.get('total_pages') or 1)
        except Exception:
            total_pages = 1
        if page >= total_pages:
            break
        page += 1

    _qf_public_audio_cache[cache_key] = {'exp': now + QF_PUBLIC_AUDIO_TTL_SEC, 'ayah_map': ayah_map}
    return ayah_map


# ── EveryAyah translation tracks (audio, ayah-by-ayah) ───────────────────────
def everyayah_get_recitations_payload() -> dict:
    now = time.time()
    cached = _everyayah_recitations_cache
    if cached.get('exp', 0) > now and isinstance(cached.get('payload'), dict):
        return cached['payload']

    session = get_http_session()
    resp = session.get(EVERYAYAH_RECITATIONS_URL, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    payload = resp.json()
    if not isinstance(payload, dict):
        raise ValueError('EveryAyah recitations payload is invalid')

    _everyayah_recitations_cache['exp'] = now + EVERYAYAH_CACHE_TTL_SEC
    _everyayah_recitations_cache['payload'] = payload
    return payload

def _everyayah_is_translation_track(name: str, subfolder: str) -> bool:
    n = (name or '').lower()
    s = (subfolder or '').lower()
    if s.startswith('translations/'):
        return True
    if s.startswith('english/') or s.startswith('multilanguage/'):
        return True
    return ('translated' in n) or ('translation' in n) or ('word for word' in n)


def _normalize_lang_code(value: str) -> str:
    v = str(value or '').strip().lower()
    if not v:
        return ''
    aliases = {
        'english': 'en', 'arabic': 'ar', 'urdu': 'ur', 'persian': 'fa',
        'farsi': 'fa',
        'azerbaijani': 'az', 'bosnian': 'bs', 'french': 'fr', 'german': 'de',
        'spanish': 'es', 'russian': 'ru', 'turkish': 'tr', 'indonesian': 'id',
        'malay': 'ms',
    }
    if v in aliases:
        return aliases[v]
    if len(v) == 2 and v.isalpha():
        return v
    if '-' in v:
        head = v.split('-', 1)[0]
        if len(head) == 2 and head.isalpha():
            return head
    if '_' in v:
        head = v.split('_', 1)[0]
        if len(head) == 2 and head.isalpha():
            return head
    return ''


def _everyayah_track_language(name: str, subfolder: str) -> str:
    hay = f"{name} {subfolder}".lower()
    parts = [p for p in str(subfolder or '').lower().split('/') if p]

    if parts:
        p0 = parts[0]
        if p0 == 'english':
            return 'en'
        if p0 == 'multilanguage':
            return ''
        if p0 == 'translations' and len(parts) > 1:
            p1 = parts[1]
            if p1 in {'azerbaijani', 'az'}:
                return 'az'
            if 'urdu' in p1:
                return 'ur'
            if any(k in p1 for k in ('fooladvand', 'makarem', 'parhizgar', 'kabiri', 'persian', 'farsi')):
                return 'fa'
            if any(k in p1 for k in ('korkut', 'besim', 'bosnian')):
                return 'bs'

    if any(k in hay for k in ('english', 'sahih', 'ibrahim walk')):
        return 'en'
    if 'urdu' in hay or 'shamshad' in hay or 'farhat' in hay:
        return 'ur'
    if any(k in hay for k in ('persian', 'farsi', 'fooladvand', 'makarem', 'parhizgar', 'kabiri')):
        return 'fa'
    if 'azerbaijani' in hay or 'balayev' in hay:
        return 'az'
    if 'bosnian' in hay or 'besim' in hay or 'korkut' in hay:
        return 'bs'
    return ''

def everyayah_translation_tracks() -> list[dict]:
    payload = everyayah_get_recitations_payload()
    # Explicit mapping avoids language/audio mismatches from ambiguous names.
    track_lang_by_id = {
        45: 'en',
        47: 'fa',
        48: 'fa',
        50: 'az',
        63: 'ur',
        72: 'bs',
        78: 'ur',
    }
    items = []
    for key, value in payload.items():
        if not (isinstance(key, str) and key.isdigit() and isinstance(value, dict)):
            continue
        track_id = int(key)
        subfolder = str(value.get('subfolder') or '')
        name = str(value.get('name') or '').strip()
        if not subfolder or not _everyayah_is_translation_track(name, subfolder):
            continue
        lang = track_lang_by_id.get(track_id) or _everyayah_track_language(name, subfolder)
        items.append({
            'trackId': track_id,
            'name': name or subfolder,
            'subfolder': subfolder,
            'bitrate': value.get('bitrate'),
            'language': lang,
            'source': 'everyayah',
            'mode': 'ayah-audio',
        })
    items.sort(key=lambda x: (str(x.get('name') or '').lower(), int(x.get('trackId') or 0)))
    return items

def everyayah_find_track(track_id: int) -> dict | None:
    for item in everyayah_translation_tracks():
        if int(item['trackId']) == int(track_id):
            return item
    return None

def everyayah_ayah_count_for_surah(surah_id: int) -> int:
    payload = everyayah_get_recitations_payload()
    arr = payload.get('ayahCount')
    if not isinstance(arr, list) or not (1 <= surah_id <= len(arr)):
        return 0
    try:
        return int(arr[surah_id - 1])
    except Exception:
        return 0

def everyayah_build_ayah_url(subfolder: str, surah_id: int, ayah_id: int) -> str:
    return f"https://everyayah.com/data/{subfolder}/{surah_id:03d}{ayah_id:03d}.mp3"


def alquran_translation_editions() -> list[dict]:
    now = time.time()
    cached = _alquran_translations_cache
    if cached.get('exp', 0) > now and isinstance(cached.get('items'), list):
        return cached['items']

    session = get_http_session()
    resp = session.get(ALQURAN_TRANSLATIONS_URL, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    payload = resp.json()
    data = payload.get('data') if isinstance(payload, dict) else None
    if not isinstance(data, list):
        raise ValueError('alquran editions payload is invalid')

    items = []
    for row in data:
        if not isinstance(row, dict):
            continue
        identifier = row.get('identifier')
        if not isinstance(identifier, str) or not identifier:
            continue
        items.append({
            'key': f'alquran:{identifier}',
            'source': 'alquran',
            'edition': identifier,
            'name': row.get('name') or identifier,
            'englishName': row.get('englishName') or identifier,
            'language': row.get('language') or '',
            'direction': row.get('direction') or 'ltr',
            'mode': 'ayah-text',
        })

    items.sort(key=lambda x: (str(x.get('language') or ''), str(x.get('englishName') or '').lower()))
    _alquran_translations_cache['exp'] = now + TRANSLATIONS_CACHE_TTL_SEC
    _alquran_translations_cache['items'] = items
    return items


def fawaz_translation_editions() -> list[dict]:
    now = time.time()
    cached = _fawaz_editions_cache
    if cached.get('exp', 0) > now and isinstance(cached.get('items'), list):
        return cached['items']

    session = get_http_session()
    resp = session.get(FAWAZ_EDITIONS_URL, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    payload = resp.json()
    if not isinstance(payload, dict):
        raise ValueError('fawaz editions payload is invalid')

    items = []
    for _, row in payload.items():
        if not isinstance(row, dict):
            continue
        name = row.get('name')
        if not isinstance(name, str) or not name:
            continue
        # Keep translation-like editions and drop Arabic recitation datasets.
        if name.startswith('ara-'):
            continue

        language = str(row.get('language') or '')
        items.append({
            'key': f'fawaz:{name}',
            'source': 'fawaz',
            'edition': name,
            'name': row.get('author') or name,
            'englishName': name,
            'language': language,
            'direction': row.get('direction') or 'ltr',
            'mode': 'ayah-text',
        })

    items.sort(key=lambda x: (str(x.get('language') or ''), str(x.get('englishName') or '').lower()))
    _fawaz_editions_cache['exp'] = now + TRANSLATIONS_CACHE_TTL_SEC
    _fawaz_editions_cache['items'] = items
    return items


def fetch_alquran_edition_ayahs(surah_id: int, edition: str) -> tuple[dict, str | None]:
    session = get_http_session()
    url = f'https://api.alquran.cloud/v1/surah/{surah_id}/{edition}'
    try:
        resp = session.get(url, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        payload = resp.json()
    except requests.RequestException as exc:
        return {}, f'Network error: {exc}'
    except ValueError as exc:
        return {}, f'Invalid JSON: {exc}'

    ayah_map = {}
    for item in payload.get('data', {}).get('ayahs', []):
        verse = item.get('numberInSurah')
        text = item.get('text')
        if isinstance(verse, int) and isinstance(text, str):
            ayah_map[verse] = text
    if not ayah_map:
        return {}, 'No ayahs returned from source'
    return ayah_map, None


def fetch_fawaz_edition_ayahs(surah_id: int, edition: str) -> tuple[dict, str | None]:
    session = get_http_session()
    url = f'https://raw.githubusercontent.com/fawazahmed0/quran-api/refs/heads/1/editions/{edition}/{surah_id}.json'
    try:
        resp = session.get(url, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        payload = resp.json()
    except requests.RequestException as exc:
        return {}, f'Network error: {exc}'
    except ValueError as exc:
        return {}, f'Invalid JSON: {exc}'

    ayah_map = {}
    for item in payload.get('chapter', []):
        verse = item.get('verse')
        text = item.get('text')
        if isinstance(verse, int) and isinstance(text, str):
            ayah_map[verse] = text
    if not ayah_map:
        return {}, 'No ayahs returned from source'
    return ayah_map, None


def unified_translations_catalog() -> list[dict]:
    catalog = [{
        'key': 'hafs_ar_text',
        'source': 'alquran',
        'edition': 'quran-uthmani',
        'name': 'العربية - حفص (نص)',
        'englishName': 'Arabic Hafs (Text)',
        'language': 'ar',
        'direction': 'rtl',
        'mode': 'ayah-text',
        'audio_subfolder': 'Alafasy_128kbps',
        'has_audio': True,
    }]

    alquran_by_edition = {}
    alquran_by_lang = {}
    fawaz_by_lang = {}
    try:
        for row in alquran_translation_editions():
            edition = str(row.get('edition') or '')
            lang = _normalize_lang_code(row.get('language'))
            if edition:
                alquran_by_edition[edition] = row
            if lang and lang not in alquran_by_lang:
                alquran_by_lang[lang] = row
    except Exception as exc:
        logger.warning('alquran translation catalog failed: %s', exc)

    try:
        for row in fawaz_translation_editions():
            lang = _normalize_lang_code(row.get('language'))
            if lang and lang not in fawaz_by_lang:
                fawaz_by_lang[lang] = row
    except Exception as exc:
        logger.warning('fawaz translation catalog failed: %s', exc)

    # Prefer specific editions when known, then general language fallback.
    preferred_alquran_editions = {
        'en': ['en.sahih'],
        'fa': ['fa.fooladvand', 'fa.makarem'],
        'bs': ['bs.korkut'],
        'ur': ['ur.jalandhry'],
    }

    everyayah_by_lang = {}
    try:
        for track in everyayah_translation_tracks():
            lang = _normalize_lang_code(track.get('language'))
            if not lang or lang == 'ar':
                continue
            if lang not in everyayah_by_lang:
                everyayah_by_lang[lang] = track
    except Exception as exc:
        logger.warning('everyayah translation catalog failed: %s', exc)

    preferred_track_id_by_lang = {
        'en': 45,
        'fa': 48,
        'ur': 63,
        'az': 50,
        'bs': 72,
    }

    for lang, tid in preferred_track_id_by_lang.items():
        tr = everyayah_find_track(tid)
        if tr:
            everyayah_by_lang[lang] = tr

    for lang in sorted(everyayah_by_lang.keys()):
        try:
            text_row = None

            for edition in preferred_alquran_editions.get(lang, []):
                text_row = alquran_by_edition.get(edition)
                if text_row:
                    break

            if not text_row:
                text_row = alquran_by_lang.get(lang)
            if not text_row:
                text_row = fawaz_by_lang.get(lang)

            if not text_row:
                continue

            track = everyayah_by_lang[lang]
            catalog.append({
                **text_row,
                'language': lang,
                'audio_subfolder': track.get('subfolder'),
                'has_audio': True,
            })
        except Exception as exc:
            logger.warning('translation language skipped (%s): %s', lang, exc)

    return catalog


# ── text fetching ──────────────────────────────────────────────────────────────
def is_allowed_audio_url(url):
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    if parsed.scheme not in {'http', 'https'}:
        return False
    return (parsed.hostname or '').lower() in ALLOWED_AUDIO_HOSTS

def extract_ayahs(source, payload):
    ayah_map = {}
    if source == 'fawaz':
        for item in payload.get('chapter', []):
            verse = item.get('verse')
            text = item.get('text')
            if isinstance(verse, int) and isinstance(text, str):
                ayah_map[verse] = text
    else:
        for item in payload.get('data', {}).get('ayahs', []):
            verse = item.get('numberInSurah')
            text = item.get('text')
            if isinstance(verse, int) and isinstance(text, str):
                ayah_map[verse] = text
    return ayah_map

def _kfgqpc_to_int(value):
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        value = value.strip()
        if value.isdigit():
            return int(value)
    return None

def _kfgqpc_get_rows(session, text_id):
    url = KFGQPC_JSON_URLS.get(text_id)
    if not url:
        return None, f'Unsupported KFGQPC textId: {text_id}'

    now = time.time()
    cached = _kfgqpc_json_cache.get(text_id)
    if cached and cached.get('exp', 0) > now and isinstance(cached.get('rows'), list):
        return cached['rows'], None

    try:
        resp = session.get(url, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        payload = resp.json()
    except requests.RequestException as exc:
        return None, f'Network error: {exc}'
    except ValueError as exc:
        return None, f'Invalid JSON: {exc}'

    if not isinstance(payload, list):
        return None, 'KFGQPC payload is not a list'

    _kfgqpc_json_cache[text_id] = {'exp': now + KFGQPC_CACHE_TTL_SEC, 'rows': payload}
    return payload, None

def fetch_kfgqpc_ayahs(session, surah_id, text_id):
    rows, err = _kfgqpc_get_rows(session, text_id)
    if err:
        return {}, err

    ayah_map = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        sura_no = _kfgqpc_to_int(row.get('sura_no'))
        if sura_no != int(surah_id):
            continue
        ayah_no = _kfgqpc_to_int(row.get('aya_no'))
        aya_text = row.get('aya_text')
        if isinstance(ayah_no, int) and isinstance(aya_text, str) and aya_text:
            ayah_map[ayah_no] = aya_text

    if not ayah_map:
        return {}, 'No ayahs found for this surah in KFGQPC dataset'
    return ayah_map, None

def fetch_qiraa_ayahs(surah_id, qiraa):
    session = get_http_session()
    if qiraa['source'] == 'kfgqpc':
        return fetch_kfgqpc_ayahs(session, surah_id, qiraa['textId'])
    if qiraa['source'] == 'fawaz':
        url = f"https://cdn.jsdelivr.net/gh/fawazahmed0/quran-api@1/editions/{qiraa['textId']}/{surah_id}.json"
    else:
        url = f"https://api.alquran.cloud/v1/surah/{surah_id}/{qiraa['textId']}"
    try:
        resp = session.get(url, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        payload = resp.json()
    except requests.RequestException as exc:
        return {}, f'Network error: {exc}'
    except ValueError as exc:
        return {}, f'Invalid JSON: {exc}'
    ayah_map = extract_ayahs(qiraa['source'], payload)
    if not ayah_map:
        return {}, 'No ayahs returned from source'
    return ayah_map, None

def fetch_external_and_store(surah_id, conn, qiraa_keys):
    c = conn.cursor()
    status_map = {}
    key_set = set(qiraa_keys)

    for q in QIRAAT:
        if q['key'] not in key_set:
            continue

        ayah_map, err = fetch_qiraa_ayahs(surah_id, q)
        if err:
            status_map[q['key']] = {'fetch_status': 'error', 'error': err}
            logger.warning('Fetch failed for %s (surah %s): %s', q['key'], surah_id, err)
            continue

        before = conn.total_changes
        c.executemany(
            'INSERT OR IGNORE INTO ayahs (surah, ayah, qiraa, text) VALUES (?, ?, ?, ?)',
            [(surah_id, ayah_num, q['key'], text) for ayah_num, text in sorted(ayah_map.items())],
        )
        conn.commit()  # commit per-qiraa so partial progress is saved on crash
        inserted = conn.total_changes - before
        status_map[q['key']] = {
            'fetch_status': 'fetched' if inserted > 0 else 'cached',
            'error': None,
        }

    return status_map


# ── routes ─────────────────────────────────────────────────────────────────────
@app.route('/')
def home_page():
    return render_template('index.html')


@app.route('/readings')
def readings_page():
    return render_template('readings.html')


@app.route('/translations')
def translations_page():
    return render_template('translations.html')


@app.route('/feedback')
def feedback_page():
    return render_template('feedback.html')


@app.route('/api/qiraat')
def get_qiraat():
    """Expose the canonical QIRAAT list so the frontend stays in sync."""
    return jsonify(QIRAAT)


@app.route('/api/translations/catalog')
def translations_catalog():
    return jsonify({'available': True, 'items': unified_translations_catalog()})


@app.route('/api/translations/surah/<int:surah_id>')
def translations_surah(surah_id):
    """
    Unified ayah-by-ayah translations endpoint.
    Query params:
      keys: comma-separated translation keys from /api/translations/catalog
            e.g. hafs_ar_text,alquran:en.asad,fawaz:eng-ummmuhammad,everyayah:45
    """
    if surah_id < 1 or surah_id > 114:
        return jsonify({'error': 'Invalid Surah'}), 400

    keys_q = (request.args.get('keys') or '').strip()
    req_keys = [x.strip() for x in keys_q.split(',') if x.strip()]
    if not req_keys:
        req_keys = ['hafs_ar_text']

    catalog = {item['key']: item for item in unified_translations_catalog()}

    # Enforce one translation per language.
    filtered_keys = []
    seen_langs = set()
    for key in req_keys:
        meta = catalog.get(key)
        if not meta:
            filtered_keys.append(key)
            continue
        lang = _normalize_lang_code(meta.get('language'))
        if lang and lang in seen_langs:
            continue
        if lang:
            seen_langs.add(lang)
        filtered_keys.append(key)
    req_keys = filtered_keys

    result = {}
    max_ayah = 0
    for key in req_keys:
        meta = catalog.get(key)
        if not meta:
            result[key] = {
                'key': key,
                'mode': 'unknown',
                'fetch_status': 'unavailable',
                'error': 'Unknown translation key',
            }
            continue

        source = meta.get('source')
        mode = meta.get('mode') or 'ayah-text'

        if mode == 'ayah-audio' and source == 'everyayah':
            try:
                track_id = int(meta.get('trackId'))
                track = everyayah_find_track(track_id)
                if not track:
                    raise ValueError('Track not found')
                ayah_count = everyayah_ayah_count_for_surah(surah_id)
                ayah_map = {
                    i: everyayah_build_ayah_url(track['subfolder'], surah_id, i)
                    for i in range(1, ayah_count + 1)
                }
                max_ayah = max(max_ayah, ayah_count)
                result[key] = {
                    'key': key,
                    'mode': 'ayah-audio',
                    'name': meta.get('name'),
                    'source': source,
                    'language': meta.get('language', ''),
                    'direction': meta.get('direction', 'ltr'),
                    'fetch_status': 'fetched',
                    'ayah_map': ayah_map,
                    'ayah_count': ayah_count,
                    'error': None,
                }
            except Exception as exc:
                result[key] = {
                    'key': key,
                    'mode': 'ayah-audio',
                    'name': meta.get('name'),
                    'source': source,
                    'language': meta.get('language', ''),
                    'direction': meta.get('direction', 'ltr'),
                    'fetch_status': 'error',
                    'error': str(exc),
                }
            continue

        if key == 'hafs_ar_text':
            ayahs, err = fetch_alquran_edition_ayahs(surah_id, 'quran-uthmani')
        elif source == 'alquran':
            ayahs, err = fetch_alquran_edition_ayahs(surah_id, str(meta.get('edition') or ''))
        elif source == 'fawaz':
            ayahs, err = fetch_fawaz_edition_ayahs(surah_id, str(meta.get('edition') or ''))
        else:
            ayahs, err = {}, 'Unsupported translation source'

        if err:
            result[key] = {
                'key': key,
                'mode': 'ayah-text',
                'name': meta.get('name'),
                'source': source,
                'language': meta.get('language', ''),
                'direction': meta.get('direction', 'ltr'),
                'fetch_status': 'error',
                'error': err,
            }
            continue

        text_ayah_count = max(ayahs.keys(), default=0)
        max_ayah = max(max_ayah, text_ayah_count)
        ayah_audio_map = None
        audio_subfolder = str(meta.get('audio_subfolder') or '').strip()
        if audio_subfolder:
            audio_ayah_count = everyayah_ayah_count_for_surah(surah_id) or text_ayah_count
            if audio_ayah_count > 0:
                ayah_audio_map = {
                    i: everyayah_build_ayah_url(audio_subfolder, surah_id, i)
                    for i in range(1, audio_ayah_count + 1)
                }
                max_ayah = max(max_ayah, audio_ayah_count)

        result[key] = {
            'key': key,
            'mode': 'ayah-text',
            'name': meta.get('name'),
            'source': source,
            'language': meta.get('language', ''),
            'direction': meta.get('direction', 'ltr'),
            'has_audio': bool(ayah_audio_map),
            'ayah_audio_map': ayah_audio_map,
            'fetch_status': 'fetched',
            'ayahs': [{'text': ayahs.get(i, '(النص غير متاح)')} for i in range(1, text_ayah_count + 1)],
            'error': None,
        }

    # Normalize text arrays to a single ayah range.
    for key, entry in result.items():
        if entry.get('mode') != 'ayah-text' or 'ayahs' not in entry:
            continue
        cur = entry['ayahs']
        if len(cur) < max_ayah:
            entry['ayahs'] = cur + ([{'text': '(النص غير متاح)'}] * (max_ayah - len(cur)))

    return jsonify({'available': True, 'meta': {'surah': surah_id, 'max_ayah': max_ayah}, 'data': result})


@app.route('/api/translations/everyayah')
def everyayah_translations_catalog():
    """
    Return all translation audio tracks available on EveryAyah.
    Includes Arabic Hafs text as a convenience baseline entry.
    """
    try:
        tracks = everyayah_translation_tracks()
    except Exception as exc:
        logger.warning('EveryAyah catalog fetch failed: %s', exc)
        return jsonify({'available': False, 'error': 'Failed to fetch EveryAyah catalog'}), 502

    return jsonify({
        'available': True,
        'tracks': tracks,
        'baseline': {
            'key': 'hafs_ar_text',
            'name': 'العربية - حفص (نص)',
            'source': 'alquran',
            'edition': 'quran-uthmani',
            'mode': 'ayah-text',
        },
    })


@app.route('/api/translations/everyayah/ayah')
def everyayah_translation_ayah_url():
    """
    Return a single ayah audio translation URL from EveryAyah.

    Query params: track, surah, ayah
    """
    try:
        track_id = int(request.args.get('track'))
        surah_id = int(request.args.get('surah'))
        ayah_id = int(request.args.get('ayah'))
    except (TypeError, ValueError):
        return jsonify({'available': False, 'error': 'Invalid track/surah/ayah'}), 400

    if surah_id < 1 or surah_id > 114 or ayah_id < 1:
        return jsonify({'available': False, 'error': 'Invalid surah/ayah'}), 400

    try:
        track = everyayah_find_track(track_id)
    except Exception as exc:
        logger.warning('EveryAyah track lookup failed: %s', exc)
        return jsonify({'available': False, 'error': 'Failed to read EveryAyah catalog'}), 502

    if not track:
        return jsonify({'available': False, 'error': 'Track not found'}), 404

    surah_ayah_count = everyayah_ayah_count_for_surah(surah_id)
    if surah_ayah_count and ayah_id > surah_ayah_count:
        return jsonify({'available': False, 'error': 'Invalid ayah for this surah'}), 400

    url = everyayah_build_ayah_url(track['subfolder'], surah_id, ayah_id)
    return jsonify({
        'available': True,
        'url': url,
        'source': 'everyayah',
        'track': {
            'trackId': track['trackId'],
            'name': track['name'],
            'subfolder': track['subfolder'],
        },
    })


@app.route('/api/translations/everyayah/surah-map')
def everyayah_translation_surah_map():
    """
    Return ayah->URL map for a full surah for one EveryAyah translation track.

    Query params: track, surah
    """
    try:
        track_id = int(request.args.get('track'))
        surah_id = int(request.args.get('surah'))
    except (TypeError, ValueError):
        return jsonify({'available': False, 'error': 'Invalid track/surah'}), 400

    if surah_id < 1 or surah_id > 114:
        return jsonify({'available': False, 'error': 'Invalid surah'}), 400

    try:
        track = everyayah_find_track(track_id)
    except Exception as exc:
        logger.warning('EveryAyah surah-map track lookup failed: %s', exc)
        return jsonify({'available': False, 'error': 'Failed to read EveryAyah catalog'}), 502

    if not track:
        return jsonify({'available': False, 'error': 'Track not found'}), 404

    ayah_count = everyayah_ayah_count_for_surah(surah_id)
    if ayah_count < 1:
        return jsonify({'available': False, 'error': 'Could not determine ayah count'}), 502

    ayah_map = {
        idx: everyayah_build_ayah_url(track['subfolder'], surah_id, idx)
        for idx in range(1, ayah_count + 1)
    }
    return jsonify({
        'available': True,
        'source': 'everyayah',
        'track': {
            'trackId': track['trackId'],
            'name': track['name'],
            'subfolder': track['subfolder'],
        },
        'ayah_count': ayah_count,
        'ayah_map': ayah_map,
    })


@app.route('/api/surah/<int:surah_id>')
def get_surah(surah_id):
    if surah_id < 1 or surah_id > 114:
        return jsonify({'error': 'Invalid Surah'}), 400

    conn = get_db_connection()
    try:
        c = conn.cursor()
        c.execute('SELECT DISTINCT qiraa FROM ayahs WHERE surah = ?', (surah_id,))
        existing_keys = {row['qiraa'] for row in c.fetchall()}
        all_keys = {q['key'] for q in QIRAAT}
        missing_keys = sorted(all_keys - existing_keys)

        fetch_status = {key: {'fetch_status': 'cached', 'error': None} for key in existing_keys}
        if missing_keys:
            fetch_status.update(fetch_external_and_store(surah_id, conn, missing_keys))

        c.execute('SELECT ayah, qiraa, text FROM ayahs WHERE surah = ? ORDER BY ayah', (surah_id,))
        rows = c.fetchall()
    finally:
        conn.close()

    fallback_map = {q['key']: q.get('fallback', False) for q in QIRAAT}
    data: dict = {}
    for r in rows:
        data.setdefault(r['qiraa'], {})[r['ayah']] = r['text']

    max_ayah = max((max(m) for m in data.values() if m), default=0)

    result = {}
    for q in QIRAAT:
        key = q['key']
        ayahs = data.get(key, {})
        arr = [{'text': ayahs.get(i, '(النص غير متاح)')} for i in range(1, max_ayah + 1)]
        q_status = fetch_status.get(key, {'fetch_status': 'unavailable', 'error': None})
        if not ayahs and q_status['fetch_status'] == 'cached':
            q_status = {'fetch_status': 'unavailable', 'error': None}
        result[key] = {
            'ayahs':        arr,
            'fallback':     fallback_map.get(key, False),
            'fetch_status': q_status['fetch_status'],
            'error':        q_status['error'],
        }

    return jsonify({'data': result, 'meta': {'surah': surah_id, 'max_ayah': max_ayah}})


@app.route('/api/audio/ayah')
def ayah_audio():
    """
    Return a per-ayah audio URL.
    Uses QF public CDN when qfPublicId is set; falls back to private QF API
    if credentials are configured.

    Query params: qiraa, surah, ayah
    """
    qiraa_key = (request.args.get('qiraa') or '').strip().lower()
    try:
        surah_id = int(request.args.get('surah'))
        ayah_id  = int(request.args.get('ayah'))
    except (TypeError, ValueError):
        return jsonify({'available': False, 'error': 'Invalid surah/ayah'}), 400

    if surah_id < 1 or surah_id > 114 or ayah_id < 1:
        return jsonify({'available': False, 'error': 'Invalid surah/ayah'}), 400

    qiraa_map = {q['key']: q for q in QIRAAT}
    if qiraa_key not in qiraa_map:
        return jsonify({'available': False, 'error': 'Invalid qiraa'}), 400

    q = qiraa_map[qiraa_key]

    # ── path 1: public QF CDN (no credentials needed) ──────────────────────
    if q.get('qfPublicId'):
        try:
            ayah_map = qf_public_get_chapter_audio_map(surah_id, q['qfPublicId'])
            url = ayah_map.get(ayah_id)
            if url:
                return jsonify({'available': True, 'url': url, 'source': 'qf_public'})
        except Exception as exc:
            logger.warning('QF public audio error for %s %s:%s: %s', qiraa_key, surah_id, ayah_id, exc)

    # ── path 2: private QF API (optional credentials) ──────────────────────
    if qf_is_enabled():
        session = get_http_session()
        try:
            url, choice = qf_get_ayah_audio_url(session, qiraa_key, surah_id, ayah_id)
            if url:
                return jsonify({
                    'available': True,
                    'url':       url,
                    'reciter':   choice['name'] if choice else None,
                    'source':    'qf_private',
                })
        except Exception as exc:
            logger.warning('QF private audio error for %s %s:%s: %s', qiraa_key, surah_id, ayah_id, exc)

    return jsonify({'available': False, 'reason': 'not_found'})


@app.route('/api/audio/surah-map')
def surah_audio_map():
    """
    Return the full ayah→URL map for a surah/qiraa so the frontend can
    pre-resolve all URLs in one shot instead of N per-ayah requests.

    Query params: qiraa, surah
    """
    qiraa_key = (request.args.get('qiraa') or '').strip().lower()
    try:
        surah_id = int(request.args.get('surah'))
    except (TypeError, ValueError):
        return jsonify({'available': False, 'error': 'Invalid surah'}), 400

    if surah_id < 1 or surah_id > 114:
        return jsonify({'available': False, 'error': 'Invalid surah'}), 400

    qiraa_map = {q['key']: q for q in QIRAAT}
    if qiraa_key not in qiraa_map:
        return jsonify({'available': False, 'error': 'Invalid qiraa'}), 400

    q = qiraa_map[qiraa_key]

    if q.get('qfPublicId'):
        try:
            ayah_map = qf_public_get_chapter_audio_map(surah_id, q['qfPublicId'])
            if ayah_map:
                return jsonify({'available': True, 'ayah_map': ayah_map, 'source': 'qf_public'})
        except Exception as exc:
            logger.warning('QF public surah-map error %s %s: %s', qiraa_key, surah_id, exc)

    return jsonify({'available': False, 'reason': 'not_found'})


@app.route('/api/audio-proxy')
def audio_proxy():
    url = request.args.get('url', '').strip()
    if not url:
        return jsonify({'error': 'Missing url parameter'}), 400
    if not is_allowed_audio_url(url):
        return jsonify({'error': 'URL not allowed'}), 400

    session = get_http_session()
    try:
        upstream = session.get(url, stream=True, timeout=REQUEST_TIMEOUT)
    except requests.RequestException as exc:
        logger.warning('Audio proxy fetch failed: %s', exc)
        return jsonify({'error': 'Upstream fetch failed'}), 502

    if upstream.status_code >= 400:
        status = upstream.status_code
        upstream.close()
        return jsonify({'error': f'Upstream HTTP {status}'}), 502

    def generate():
        sent = 0
        try:
            for chunk in upstream.iter_content(chunk_size=64 * 1024):
                if chunk:
                    sent += len(chunk)
                    if sent > MAX_AUDIO_PROXY_BYTES:
                        logger.warning('Audio proxy: size limit hit for %s', url)
                        break
                    yield chunk
        finally:
            upstream.close()

    content_type = upstream.headers.get('Content-Type', 'audio/mpeg')
    headers = {'Content-Type': content_type, 'Cache-Control': 'public, max-age=3600'}
    content_length = upstream.headers.get('Content-Length')
    if content_length:
        headers['Content-Length'] = content_length

    return Response(generate(), headers=headers)


# ── legacy private QF endpoints (kept for backwards compat) ───────────────────
@app.route('/api/qf/source')
def qf_source():
    qiraa = (request.args.get('qiraa') or '').strip().lower()
    try:
        surah_id = int(request.args.get('surah'))
    except (TypeError, ValueError):
        return jsonify({'available': False, 'error': 'Invalid surah'}), 400
    if surah_id < 1 or surah_id > 114:
        return jsonify({'available': False, 'error': 'Invalid surah'}), 400
    if qiraa not in {q['key'] for q in QIRAAT}:
        return jsonify({'available': False, 'error': 'Invalid qiraa'}), 400
    if not qf_is_enabled():
        return jsonify({'available': False, 'reason': 'not_configured'})
    session = get_http_session()
    try:
        choice = qf_pick_recitation_for_qiraa(session, qiraa, surah_id)
    except Exception as exc:
        logger.warning('QF source check failed: %s', exc)
        return jsonify({'available': False, 'reason': 'upstream_error'})
    if not choice:
        return jsonify({'available': False, 'reason': 'not_found'})
    return jsonify({'available': True, 'recitation_id': choice['id'],
                    'reciter': choice['name'], 'source': 'quran_foundation'})


@app.route('/api/qf/ayah-url')
def qf_ayah_url():
    qiraa = (request.args.get('qiraa') or '').strip().lower()
    try:
        surah_id = int(request.args.get('surah'))
        ayah_id  = int(request.args.get('ayah'))
    except (TypeError, ValueError):
        return jsonify({'available': False, 'error': 'Invalid surah/ayah'}), 400
    if surah_id < 1 or surah_id > 114 or ayah_id < 1:
        return jsonify({'available': False, 'error': 'Invalid surah/ayah'}), 400
    if qiraa not in {q['key'] for q in QIRAAT}:
        return jsonify({'available': False, 'error': 'Invalid qiraa'}), 400
    if not qf_is_enabled():
        return jsonify({'available': False, 'reason': 'not_configured'})
    session = get_http_session()
    try:
        url, choice = qf_get_ayah_audio_url(session, qiraa, surah_id, ayah_id)
    except Exception as exc:
        logger.warning('QF ayah audio failed: %s', exc)
        return jsonify({'available': False, 'reason': 'upstream_error'})
    if not url:
        return jsonify({'available': False, 'reason': 'not_found'})
    return jsonify({'available': True, 'url': url,
                    'reciter': choice['name'] if choice else None,
                    'source': 'quran_foundation'})


if __name__ == '__main__':
    init_db()
    app.run(debug=False, port=7860)
