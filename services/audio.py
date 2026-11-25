import concurrent.futures
import json
import logging
import re
import threading
import time

import requests

from config import (
    DATA_DIR,
    EVERYAYAH_CACHE_TTL_SEC,
    EVERYAYAH_RECITATIONS_URL,
    MP3QURAN_API_BASE,
    MP3QURAN_CACHE_TTL_SEC,
    MP3QURAN_TIMING_EMPTY_TTL_SEC,
    QF_API_BASES,
    QF_AUDIO_CDN_BASE,
    QF_AUTH_BASES,
    QF_CHAPTER_CACHE_TTL_SEC,
    QF_CLIENT_ID,
    QF_CLIENT_SECRET,
    QF_ENV,
    QF_PUBLIC_API_BASE,
    QF_PUBLIC_AUDIO_TTL_SEC,
    QF_QIRAA_HINTS,
    QF_RESCACHE_TTL_SEC,
    QF_SCOPE,
    QF_TOKEN_BUFFER_SEC,
    QIRAAT_BY_KEY,
    QURAN_COM_V4_API_BASE,
    QURANPEDIA_API_BASE,
    QURANPEDIA_CACHE_TTL_SEC,
    REQUEST_TIMEOUT,
)
from services.http_client import get_cache, get_http_session

logger = logging.getLogger(__name__)

_qf_token_lock = threading.Lock()
_qf_token = {'value': None, 'exp': 0.0}
_SURAH_AYAH_COUNTS: dict[int, int] | None = None
_CACHE_MISS = object()


def get_surah_ayah_count(surah_id: int) -> int:
    global _SURAH_AYAH_COUNTS
    if _SURAH_AYAH_COUNTS is None:
        try:
            items = json.loads((DATA_DIR / 'surahs.json').read_text(encoding='utf-8'))
            _SURAH_AYAH_COUNTS = {int(s['number']): int(s['numberOfAyahs']) for s in items}
        except (KeyError, OSError, TypeError, ValueError):
            _SURAH_AYAH_COUNTS = {}
    return _SURAH_AYAH_COUNTS.get(int(surah_id), 0)


def _normalize_ar(text: str) -> str:
    s = str(text or '').strip().lower()
    s = re.sub(r'[\u064B-\u065F\u0670]', '', s)
    s = s.replace('أ', 'ا').replace('إ', 'ا').replace('آ', 'ا')
    s = s.replace('ى', 'ي').replace('ة', 'ه')
    s = re.sub(r'\s+', ' ', s)
    return s


# ── QF private API helpers (optional OAuth2) ──────────────────────────────────
def qf_is_enabled() -> bool:
    return bool(QF_CLIENT_ID and QF_CLIENT_SECRET)


def qf_env_key() -> str:
    return 'prelive' if QF_ENV == 'prelive' else 'production'


def qf_auth_base_url() -> str:
    return QF_AUTH_BASES[qf_env_key()]


def qf_api_base_url() -> str:
    return QF_API_BASES[qf_env_key()]


def qf_token_valid() -> bool:
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


def qf_get_token(session, force_refresh: bool = False):
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


def qf_extract_list(payload, key: str) -> list:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        v = payload.get(key)
        if isinstance(v, list):
            return v
    return []


def qf_api_get(session, path: str, params=None, retry_401: bool = True):
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


def qf_build_recitation_text(recitation: dict) -> str:
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


def qf_score_recitation_for_qiraa(qiraa_key: str, recitation: dict) -> int:
    hints = QF_QIRAA_HINTS.get(qiraa_key, [])
    hay = qf_build_recitation_text(recitation)
    return sum(10 for h in hints if h.lower() in hay)


def qf_get_recitations(session) -> list:
    cache = get_cache()
    cached = cache.get('qf_recitations')
    if cached:
        return cached
    payload = qf_api_get(session, '/resources/recitations', params={'language': 'ar'})
    items = qf_extract_list(payload, 'recitations')
    if not items:
        payload = qf_api_get(session, '/resources/recitations', params={'language': 'en'})
        items = qf_extract_list(payload, 'recitations')
    cache.set('qf_recitations', items, expire=QF_RESCACHE_TTL_SEC)
    return items


def qf_parse_ayah_number(verse_key) -> int | None:
    if not isinstance(verse_key, str) or ':' not in verse_key:
        return None
    try:
        return int(verse_key.split(':', 1)[1])
    except (IndexError, TypeError, ValueError):
        return None


def qf_extract_audio_file_url(item) -> str | None:
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


def _fetch_chapter_audio_map_paginated(fetch_fn) -> dict[int, str]:
    ayah_map: dict[int, str] = {}
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
            except (TypeError, ValueError):
                total_pages = 1
        if page >= total_pages:
            break
        page += 1
    return ayah_map


def qf_get_chapter_audio_map(session, recitation_id: int, surah_number: int) -> dict[int, str]:
    cache = get_cache()
    cache_key = f'qf_chapter_audio_{recitation_id}_{surah_number}'
    cached = cache.get(cache_key, default=_CACHE_MISS)
    if cached is not _CACHE_MISS:
        return cached

    def fetch_fn(page):
        return qf_api_get(
            session,
            f'/recitations/{int(recitation_id)}/by_chapter/{int(surah_number)}',
            params={'page': page, 'per_page': 50},
        )

    ayah_map = _fetch_chapter_audio_map_paginated(fetch_fn)
    cache.set(cache_key, ayah_map, expire=QF_CHAPTER_CACHE_TTL_SEC)
    return ayah_map


def qf_pick_recitation_for_qiraa(session, qiraa_key: str, surah_number: int):
    cache = get_cache()
    choice_cache_key = f'qf_choice_{qiraa_key}_{surah_number}'
    cached = cache.get(choice_cache_key, default=_CACHE_MISS)
    if cached is not _CACHE_MISS:
        return cached

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
        except (requests.RequestException, RuntimeError, TypeError, ValueError) as exc:
            logger.debug('QF recitation candidate %s failed for surah %s: %s', rid, surah_number, exc)
            continue

    cache.set(choice_cache_key, chosen, expire=3600)
    return chosen


def qf_get_ayah_audio_url(session, qiraa_key: str, surah_number: int, ayah_number: int):
    choice = qf_pick_recitation_for_qiraa(session, qiraa_key, surah_number)
    if not choice:
        return None, None
    ayah_map = qf_get_chapter_audio_map(session, choice['id'], surah_number)
    return ayah_map.get(int(ayah_number)), choice


# ── QF public (no-auth) per-ayah audio ────────────────────────────────────────
def _resolve_audio_url(raw_url: str) -> str:
    if raw_url.startswith(('http://', 'https://')):
        return raw_url
    return QF_AUDIO_CDN_BASE + raw_url.lstrip('/')


def qf_public_get_chapter_audio_map(surah_number: int, qf_public_id: int) -> dict[int, str]:
    cache = get_cache()
    cache_key = f'qf_public_audio_{qf_public_id}_{surah_number}'
    cached = cache.get(cache_key, default=_CACHE_MISS)
    if cached is not _CACHE_MISS:
        return cached

    session = get_http_session()
    ayah_map: dict[int, str] = {}
    page = 1
    while True:
        url = f"{QF_PUBLIC_API_BASE}/recitations/{qf_public_id}/by_chapter/{surah_number}"
        try:
            resp = session.get(url, params={'page': page, 'per_page': 50}, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            payload = resp.json()
        except (requests.RequestException, RuntimeError, TypeError, ValueError) as exc:
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
        except (TypeError, ValueError):
            total_pages = 1
        if page >= total_pages:
            break
        page += 1

    cache.set(cache_key, ayah_map, expire=QF_PUBLIC_AUDIO_TTL_SEC)
    return ayah_map


# ── Quranpedia ayah-by-ayah reciters (covers all 20 canonical riwayat) ────────
def quranpedia_get_recitations_flat() -> list[dict]:
    cache = get_cache()
    cached = cache.get('quranpedia_reciters_flat_v1')
    if isinstance(cached, list):
        return cached

    try:
        session = get_http_session()
        resp = session.get(f'{QURANPEDIA_API_BASE}/reciters', timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        payload = resp.json()
    except (requests.RequestException, RuntimeError, ValueError) as exc:
        logger.warning('Quranpedia reciters fetch failed: %s', exc)
        return []

    flat: list[dict] = []
    if isinstance(payload, list):
        for r in payload:
            if isinstance(r, list):
                flat.extend(x for x in r if isinstance(x, dict))
            elif isinstance(r, dict):
                if isinstance(r.get('recitations'), list):
                    flat.extend(x for x in r['recitations'] if isinstance(x, dict))
                else:
                    flat.append(r)

    if flat:
        cache.set('quranpedia_reciters_flat_v1', flat, expire=QURANPEDIA_CACHE_TTL_SEC)
    return flat


def quranpedia_reciters_for_qiraa(qiraa_key: str, surah_id: int) -> list[dict]:
    """
    Return per-ayah MP3 reciters from Quranpedia for `qiraa_key`.
    Falls back to static verified Quranpedia defaults if API is unreachable.
    """
    meta = QIRAAT_BY_KEY.get(qiraa_key)
    if not meta:
        return []
    rawi_id = meta.get('quranpediaRawiId')
    results: list[dict] = []
    seen_ids: set[str] = set()

    if rawi_id:
        for item in quranpedia_get_recitations_flat():
            rawi = item.get('rawi') or {}
            cls = item.get('classification') or {}
            if rawi.get('id') != rawi_id or cls.get('id') != 2:
                continue
            surahs_list = item.get('surahs_list')
            if isinstance(surahs_list, list) and surahs_list and surah_id not in surahs_list:
                continue
            server = _normalize_server_url(item.get('server') or '')
            rec_id = item.get('id')
            if not (server and rec_id):
                continue
            full_id = f'quranpedia:{rec_id}'
            if full_id in seen_ids:
                continue
            seen_ids.add(full_id)
            results.append({
                'id':         full_id,
                'qp_id':      int(rec_id),
                'name':       str(item.get('name') or f'Quranpedia #{rec_id}').strip(),
                'server':     server,
                'source':     'quranpedia',
                'mode_hint':  'ayah',
            })

    # Always include static verified fallback if API didn't return anything
    if not results:
        for rec_id, name, server in meta.get('quranpediaDefaultReciters') or []:
            full_id = f'quranpedia:{rec_id}'
            if full_id in seen_ids:
                continue
            seen_ids.add(full_id)
            results.append({
                'id':         full_id,
                'qp_id':      int(rec_id),
                'name':       name,
                'server':     _normalize_server_url(server),
                'source':     'quranpedia',
                'mode_hint':  'ayah',
            })

    return results


def _build_quranpedia_ayah_map(server: str, surah_id: int) -> dict[int, str]:
    count = get_surah_ayah_count(surah_id) or everyayah_ayah_count_for_surah(surah_id) or 286
    base = server.rstrip('/')
    return {i: f'{base}/{surah_id:03d}{i:03d}.mp3' for i in range(1, count + 1)}


# ── EveryAyah dynamic reciter discovery ───────────────────────────────────────
def everyayah_get_recitations_payload() -> dict:
    cache = get_cache()
    cached = cache.get('everyayah_recitations')
    if isinstance(cached, dict):
        return cached

    session = get_http_session()
    resp = session.get(EVERYAYAH_RECITATIONS_URL, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    payload = resp.json()
    if not isinstance(payload, dict):
        raise TypeError('EveryAyah recitations payload is invalid')

    cache.set('everyayah_recitations', payload, expire=EVERYAYAH_CACHE_TTL_SEC)
    return payload


def everyayah_ayah_count_for_surah(surah_id: int) -> int:
    local_count = get_surah_ayah_count(surah_id)
    if local_count > 0:
        return local_count
    try:
        payload = everyayah_get_recitations_payload()
        arr = payload.get('ayahCount')
        if isinstance(arr, list) and (1 <= surah_id <= len(arr)):
            return int(arr[surah_id - 1])
    except (requests.RequestException, RuntimeError, TypeError, ValueError) as exc:
        logger.debug('EveryAyah ayah count unavailable for surah %s: %s', surah_id, exc)
    return 0


def everyayah_build_ayah_url(subfolder: str, surah_id: int, ayah_id: int) -> str:
    clean_sub = str(subfolder or '').strip('/')
    return f"https://everyayah.com/data/{clean_sub}/{surah_id:03d}{ayah_id:03d}.mp3"


def everyayah_reciters_for_qiraa(qiraa_key: str) -> list[dict]:
    meta = QIRAAT_BY_KEY.get(qiraa_key)
    if not meta:
        return []
    hints = [h.lower() for h in meta.get('everyAyahHints', [])]
    if not hints:
        return []

    try:
        payload = everyayah_get_recitations_payload()
    except (requests.RequestException, RuntimeError, TypeError, ValueError) as exc:
        logger.debug('EveryAyah payload unavailable: %s', exc)
        return []

    results: list[dict] = []
    for key, row in payload.items():
        if not (isinstance(key, str) and key.isdigit() and isinstance(row, dict)):
            continue
        subfolder = str(row.get('subfolder') or '').strip('/')
        name = str(row.get('name') or '').strip()
        if not subfolder:
            continue
        low_sub = subfolder.lower()
        low_name = name.lower()
        if low_sub.startswith(('translations/', 'english/', 'multilanguage/')):
            continue
        if 'translation' in low_name or 'translated' in low_name:
            continue

        if qiraa_key != 'hafs' and not any(h in low_sub or h in low_name for h in hints):
            continue
        if qiraa_key == 'hafs':
            if any(x in low_sub for x in ('warsh/', 'qaloon', 'douri', 'susi', 'shouba')):
                continue
            if not any(h in low_sub or h in low_name for h in hints):
                continue

        results.append({
            'id':        f'everyayah:{key}',
            'track_id':  int(key),
            'name':      name or subfolder,
            'subfolder': subfolder,
            'source':    'everyayah',
            'mode_hint': 'ayah',
        })

    def _sort_key(item: dict):
        sub = item['subfolder'].lower()
        score = 0
        if 'alafasy' in sub or 'warsh_abdul_basit' in sub:
            score -= 100
        if '128kbps' in sub:
            score -= 10
        return (score, item['name'].lower())

    results.sort(key=_sort_key)
    return results


# ── MP3Quran v3 dynamic riwayat, reciters, and ayat_timing ────────────────────
def mp3quran_get_riwayat() -> list[dict]:
    cache = get_cache()
    cached = cache.get('mp3quran_riwayat_ar')
    if isinstance(cached, list):
        return cached
    try:
        session = get_http_session()
        resp = session.get(f'{MP3QURAN_API_BASE}/riwayat', params={'language': 'ar'}, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        payload = resp.json()
        items = payload.get('riwayat') if isinstance(payload, dict) else []
        if not isinstance(items, list):
            items = []
        if items:
            cache.set('mp3quran_riwayat_ar', items, expire=MP3QURAN_CACHE_TTL_SEC)
        return items
    except (requests.RequestException, RuntimeError, ValueError) as exc:
        logger.warning('MP3Quran riwayat fetch failed: %s', exc)
        return []


def mp3quran_get_timing_read_ids() -> set[int]:
    cache = get_cache()
    cached = cache.get('mp3quran_timing_read_ids')
    if isinstance(cached, list):
        return set(cached)
    try:
        session = get_http_session()
        resp = session.get(f'{MP3QURAN_API_BASE}/ayat_timing/reads', timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        payload = resp.json()
        ids = [int(x['id']) for x in payload if isinstance(x, dict) and str(x.get('id', '')).isdigit()] if isinstance(payload, list) else []
        if ids:
            cache.set('mp3quran_timing_read_ids', ids, expire=MP3QURAN_CACHE_TTL_SEC)
        return set(ids)
    except (requests.RequestException, RuntimeError, ValueError):
        return set()


def mp3quran_resolve_rewaya_id(qiraa_key: str) -> int | None:
    meta = QIRAAT_BY_KEY.get(qiraa_key)
    if not meta:
        return None
    if meta.get('rewayaId'):
        return int(meta['rewayaId'])

    riwayat = mp3quran_get_riwayat()
    if not riwayat:
        return None

    hints = [_normalize_ar(h) for h in meta.get('mp3quranHints', []) if h]
    best_id = None
    best_score = 0
    for item in riwayat:
        if not isinstance(item, dict) or not item.get('id'):
            continue
        r_name = _normalize_ar(item.get('name') or '')
        if not r_name:
            continue
        score = 0
        for idx, hint in enumerate(hints):
            if r_name == hint:
                score = max(score, 1000 - idx)
            elif hint in r_name:
                score = max(score, 100 + len(hint) - idx)
        if score > best_score:
            best_score = score
            best_id = int(item['id'])

    return best_id


def _normalize_server_url(server: str) -> str | None:
    if not server:
        return None
    s = str(server).strip()
    if not s.endswith('/'):
        s += '/'
    if s.startswith('http://'):
        s = 'https://' + s[len('http://'):]
    return s


def _parse_surah_set(surah_list: str) -> set[int]:
    out: set[int] = set()
    for part in str(surah_list or '').split(','):
        part = part.strip()
        if part.isdigit():
            val = int(part)
            if val > 0:
                out.add(val)
    return out


def mp3quran_get_reciters_for_qiraa(qiraa_key: str, surah_id: int) -> list[dict]:
    rewaya_id = mp3quran_resolve_rewaya_id(qiraa_key)
    if not rewaya_id:
        return []

    cache = get_cache()
    cache_key = f'mp3quran_reciters_{rewaya_id}'
    reciters = cache.get(cache_key)
    if not isinstance(reciters, list):
        try:
            session = get_http_session()
            resp = session.get(
                f'{MP3QURAN_API_BASE}/reciters',
                params={'language': 'ar', 'rewaya': rewaya_id},
                timeout=REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            payload = resp.json()
            reciters = payload.get('reciters') if isinstance(payload, dict) else []
            if not isinstance(reciters, list):
                reciters = []
            cache.set(cache_key, reciters, expire=MP3QURAN_CACHE_TTL_SEC)
        except (requests.RequestException, RuntimeError, ValueError) as exc:
            logger.warning('MP3Quran reciters fetch failed (rewaya %s): %s', rewaya_id, exc)
            return []

    timing_reads = mp3quran_get_timing_read_ids()
    items: list[dict] = []
    for rec in reciters:
        if not isinstance(rec, dict):
            continue
        rec_name = str(rec.get('name') or '').strip()
        rec_id = rec.get('id')
        has_timing = bool(rec_id and int(rec_id) in timing_reads)
        for m in rec.get('moshaf') or []:
            if not isinstance(m, dict) or not m.get('server'):
                continue
            surah_set = _parse_surah_set(m.get('surah_list', ''))
            surah_total = int(m.get('surah_total') or 0)
            if surah_set and surah_id not in surah_set and surah_total < 114:
                continue
            moshaf_id = m.get('id')
            base_url = _normalize_server_url(m.get('server'))
            if not (moshaf_id and base_url):
                continue
            surah_url = f'{base_url}{surah_id:03d}.mp3'
            m_name = str(m.get('name') or '').strip()
            label = f'{rec_name} ({m_name})' if m_name else rec_name
            moshaf_has_timing = has_timing or (int(moshaf_id) in timing_reads)
            items.append({
                'id':          f'mp3quran:{moshaf_id}',
                'moshaf_id':   int(moshaf_id),
                'has_timing':  moshaf_has_timing,
                'name':        label or f'MP3Quran #{moshaf_id}',
                'surah_url':   surah_url,
                'surah_total': surah_total,
                'source':      'mp3quran',
                'mode_hint':   'timed-surah' if moshaf_has_timing else 'surah',
            })

    items.sort(key=lambda x: (0 if x['has_timing'] else 1, -x['surah_total'], x['name']))
    return items


def mp3quran_get_ayat_timing(moshaf_id: int, surah_id: int) -> dict[int, dict[str, int]]:
    cache = get_cache()
    cache_key = f'mp3quran_timing_{moshaf_id}_{surah_id}'
    cached = cache.get(cache_key)
    if isinstance(cached, dict):
        return cached

    session = get_http_session()
    timings: dict[int, dict[str, int]] = {}
    try:
        resp = session.get(
            f'{MP3QURAN_API_BASE}/ayat_timing',
            params={'surah': int(surah_id), 'read': int(moshaf_id)},
            timeout=REQUEST_TIMEOUT,
        )
        if resp.status_code == 404:
            cache.set(cache_key, {}, expire=MP3QURAN_TIMING_EMPTY_TTL_SEC)
            return {}
        resp.raise_for_status()
        payload = resp.json()
        if isinstance(payload, list):
            for row in payload:
                if not isinstance(row, dict):
                    continue
                ayah = row.get('ayah')
                start_t = row.get('start_time')
                end_t = row.get('end_time')
                if (
                    isinstance(ayah, int)
                    and ayah >= 1
                    and isinstance(start_t, (int, float))
                    and isinstance(end_t, (int, float))
                    and end_t > start_t
                ):
                    timings[ayah] = {'start_ms': int(start_t), 'end_ms': int(end_t)}
    except (requests.RequestException, RuntimeError, TypeError, ValueError) as exc:
        logger.debug('MP3Quran ayat_timing failed (read=%s surah=%s): %s', moshaf_id, surah_id, exc)
        cache.set(cache_key, {}, expire=MP3QURAN_TIMING_EMPTY_TTL_SEC)
        return {}

    ttl = MP3QURAN_CACHE_TTL_SEC if timings else MP3QURAN_TIMING_EMPTY_TTL_SEC
    cache.set(cache_key, timings, expire=ttl)
    return timings


# ── Quran.com / QDC public chapter reciters + verse timestamps ────────────────
def qdc_get_chapter_reciters_for_qiraa(qiraa_key: str) -> list[dict]:
    meta = QIRAAT_BY_KEY.get(qiraa_key)
    if not meta:
        return []
    hints = [h.lower() for h in meta.get('qdcHints', [])]
    if not hints:
        return []

    cache = get_cache()
    reciters = cache.get('qdc_chapter_reciters_en')
    if not isinstance(reciters, list):
        try:
            session = get_http_session()
            resp = session.get(
                f'{QURAN_COM_V4_API_BASE}/resources/chapter_reciters',
                params={'language': 'en'},
                timeout=REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            payload = resp.json()
            reciters = payload.get('reciters') if isinstance(payload, dict) else []
            if not isinstance(reciters, list):
                reciters = []
            cache.set('qdc_chapter_reciters_en', reciters, expire=MP3QURAN_CACHE_TTL_SEC)
        except (requests.RequestException, RuntimeError, ValueError) as exc:
            logger.debug('QDC chapter_reciters unavailable: %s', exc)
            return []

    out: list[dict] = []
    for r in reciters:
        if not isinstance(r, dict) or not r.get('id'):
            continue
        qirat_name = ''
        q_obj = r.get('qirat')
        if isinstance(q_obj, dict):
            qirat_name = str(q_obj.get('name') or '').lower()
        rec_name = str(r.get('name') or '').strip()
        hay = f'{qirat_name} {rec_name.lower()}'
        if any(h in hay for h in hints):
            out.append({
                'id':         f"qdc_chapter:{r['id']}",
                'reciter_id': int(r['id']),
                'name':       rec_name or f"QDC #{r['id']}",
                'source':     'qdc_chapter',
                'mode_hint':  'timed-surah',
            })
    return out


def qdc_get_chapter_audio_with_timings(reciter_id: int, surah_id: int) -> tuple[str | None, dict[int, dict[str, int]]]:
    cache = get_cache()
    cache_key = f'qdc_chapter_audio_{reciter_id}_{surah_id}'
    cached = cache.get(cache_key)
    if isinstance(cached, dict) and 'surah_url' in cached:
        return cached['surah_url'], cached.get('timings') or {}

    try:
        session = get_http_session()
        resp = session.get(
            f'{QURAN_COM_V4_API_BASE}/chapter_recitations/{int(reciter_id)}/{int(surah_id)}',
            params={'segments': 'true'},
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        payload = resp.json()
        audio_file = payload.get('audio_file') if isinstance(payload, dict) else None
        if not isinstance(audio_file, dict):
            return None, {}
        surah_url = audio_file.get('audio_url')
        timings: dict[int, dict[str, int]] = {}
        for ts in audio_file.get('timestamps') or []:
            if not isinstance(ts, dict):
                continue
            ayah_num = qf_parse_ayah_number(ts.get('verse_key'))
            t_from = ts.get('timestamp_from')
            t_to = ts.get('timestamp_to')
            if ayah_num and isinstance(t_from, (int, float)) and isinstance(t_to, (int, float)) and t_to > t_from:
                timings[ayah_num] = {'start_ms': int(t_from), 'end_ms': int(t_to)}
        cache.set(cache_key, {'surah_url': surah_url, 'timings': timings}, expire=QF_PUBLIC_AUDIO_TTL_SEC)
        return surah_url, timings
    except (requests.RequestException, RuntimeError, TypeError, ValueError) as exc:
        logger.debug('QDC chapter audio fetch failed (reciter=%s surah=%s): %s', reciter_id, surah_id, exc)
        return None, {}


# ── Unified Reciter Discovery & 4-Tier Surah Audio Resolver ───────────────────
def list_reciters_for_qiraa(qiraa_key: str, surah_id: int) -> list[dict]:
    if qiraa_key not in QIRAAT_BY_KEY:
        return []
    reciters: list[dict] = []

    for qp in quranpedia_reciters_for_qiraa(qiraa_key, surah_id):
        reciters.append({
            'id':        qp['id'],
            'name':      qp['name'],
            'source':    'quranpedia',
            'mode_hint': 'ayah',
        })

    for ea in everyayah_reciters_for_qiraa(qiraa_key):
        reciters.append({
            'id':        ea['id'],
            'name':      ea['name'],
            'source':    'everyayah',
            'mode_hint': 'ayah',
        })

    meta = QIRAAT_BY_KEY[qiraa_key]
    if meta.get('qfPublicId'):
        reciters.append({
            'id':        f"qf_public:{meta['qfPublicId']}",
            'name':      f"{meta['rawiName']} (QuranCDN)",
            'source':    'qf_public',
            'mode_hint': 'ayah',
        })

    for qdc in qdc_get_chapter_reciters_for_qiraa(qiraa_key):
        reciters.append({
            'id':        qdc['id'],
            'name':      f"{qdc['name']} (Quran.com)",
            'source':    'qdc_chapter',
            'mode_hint': 'timed-surah',
        })

    for mp3 in mp3quran_get_reciters_for_qiraa(qiraa_key, surah_id)[:20]:
        reciters.append({
            'id':        mp3['id'],
            'name':      mp3['name'],
            'source':    'mp3quran',
            'mode_hint': mp3['mode_hint'],
        })

    return reciters


def _resolve_specific_reciter(qiraa_key: str, surah_id: int, reciter_id: str) -> dict | None:
    if reciter_id.startswith('quranpedia:'):
        target_id = reciter_id.split(':', 1)[1]
        for qp in quranpedia_reciters_for_qiraa(qiraa_key, surah_id):
            if str(qp['qp_id']) == target_id:
                return {
                    'available':    True,
                    'mode':         'ayah',
                    'source':       'quranpedia',
                    'reciter_id':   qp['id'],
                    'reciter_name': qp['name'],
                    'ayah_map':     _build_quranpedia_ayah_map(qp['server'], surah_id),
                }

    if reciter_id.startswith('everyayah:'):
        tid = reciter_id.split(':', 1)[1]
        for ea in everyayah_reciters_for_qiraa(qiraa_key):
            if str(ea['track_id']) == tid:
                count = get_surah_ayah_count(surah_id) or everyayah_ayah_count_for_surah(surah_id) or 286
                return {
                    'available':    True,
                    'mode':         'ayah',
                    'source':       'everyayah',
                    'reciter_id':   ea['id'],
                    'reciter_name': ea['name'],
                    'ayah_map':     {i: everyayah_build_ayah_url(ea['subfolder'], surah_id, i) for i in range(1, count + 1)},
                }

    if reciter_id.startswith('qf_public:'):
        try:
            pid = int(reciter_id.split(':', 1)[1])
        except ValueError:
            return None
        if QIRAAT_BY_KEY.get(qiraa_key, {}).get('qfPublicId') != pid:
            return None
        ayah_map = qf_public_get_chapter_audio_map(surah_id, pid)
        if ayah_map:
            return {
                'available':    True,
                'mode':         'ayah',
                'source':       'qf_public',
                'reciter_id':   reciter_id,
                'reciter_name': QIRAAT_BY_KEY[qiraa_key]['rawiName'],
                'ayah_map':     ayah_map,
            }

    if reciter_id.startswith('qdc_chapter:'):
        try:
            rid = int(reciter_id.split(':', 1)[1])
        except ValueError:
            return None
        allowed_rids = {r['reciter_id'] for r in qdc_get_chapter_reciters_for_qiraa(qiraa_key)}
        if rid not in allowed_rids:
            return None
        surah_url, timings = qdc_get_chapter_audio_with_timings(rid, surah_id)
        if surah_url and timings:
            return {
                'available':    True,
                'mode':         'timed-surah',
                'source':       'qdc_timed',
                'reciter_id':   reciter_id,
                'reciter_name': f'Quran.com #{rid}',
                'surah_url':    surah_url,
                'timings':      timings,
            }
        if surah_url:
            return {
                'available':    True,
                'mode':         'surah',
                'source':       'qdc_chapter',
                'reciter_id':   reciter_id,
                'reciter_name': f'Quran.com #{rid}',
                'surah_url':    surah_url,
            }

    if reciter_id.startswith('mp3quran:'):
        try:
            mid = int(reciter_id.split(':', 1)[1])
        except ValueError:
            return None
        for mp3 in mp3quran_get_reciters_for_qiraa(qiraa_key, surah_id):
            if mp3['moshaf_id'] == mid:
                timings = mp3quran_get_ayat_timing(mid, surah_id)
                if timings:
                    return {
                        'available':    True,
                        'mode':         'timed-surah',
                        'source':       'mp3quran_timed',
                        'reciter_id':   mp3['id'],
                        'reciter_name': mp3['name'],
                        'surah_url':    mp3['surah_url'],
                        'timings':      timings,
                    }
                return {
                    'available':    True,
                    'mode':         'surah',
                    'source':       'mp3quran',
                    'reciter_id':   mp3['id'],
                    'reciter_name': mp3['name'],
                    'surah_url':    mp3['surah_url'],
                }
    return None


def resolve_surah_audio(qiraa_key: str, surah_id: int, reciter_id: str | None = None) -> dict:
    """
    Unified 4-tier audio resolver:
      Tier 1 (ayah):        EveryAyah (Hafs/Warsh) & Quranpedia per-ayah MP3s (all 20 riwayat!) + QF public CDN
      Tier 2 (timed-surah): MP3Quran v3 surah MP3 + ayat_timing timestamps
      Tier 3 (timed-surah): Quran.com / QDC chapter MP3 + verse timestamps
      Tier 4 (surah):       MP3Quran full-surah MP3 fallback
    """
    if qiraa_key not in QIRAAT_BY_KEY:
        return {'available': False, 'error': 'Invalid qiraa'}

    if reciter_id:
        specific = _resolve_specific_reciter(qiraa_key, surah_id, reciter_id)
        if specific:
            return specific

    meta = QIRAAT_BY_KEY[qiraa_key]

    # Tier 1a: For Hafs, prefer EveryAyah Alafasy first; for all other 19 riwayat, prefer Quranpedia per-ayah
    if qiraa_key == 'hafs':
        ea_reciters = everyayah_reciters_for_qiraa(qiraa_key)
        if ea_reciters:
            ea = ea_reciters[0]
            count = get_surah_ayah_count(surah_id) or everyayah_ayah_count_for_surah(surah_id) or 286
            return {
                'available':    True,
                'mode':         'ayah',
                'source':       'everyayah',
                'reciter_id':   ea['id'],
                'reciter_name': ea['name'],
                'ayah_map':     {i: everyayah_build_ayah_url(ea['subfolder'], surah_id, i) for i in range(1, count + 1)},
            }

    qp_reciters = quranpedia_reciters_for_qiraa(qiraa_key, surah_id)
    if qp_reciters:
        qp = qp_reciters[0]
        return {
            'available':    True,
            'mode':         'ayah',
            'source':       'quranpedia',
            'reciter_id':   qp['id'],
            'reciter_name': qp['name'],
            'ayah_map':     _build_quranpedia_ayah_map(qp['server'], surah_id),
        }

    ea_reciters = everyayah_reciters_for_qiraa(qiraa_key)
    if ea_reciters:
        ea = ea_reciters[0]
        count = get_surah_ayah_count(surah_id) or everyayah_ayah_count_for_surah(surah_id) or 286
        return {
            'available':    True,
            'mode':         'ayah',
            'source':       'everyayah',
            'reciter_id':   ea['id'],
            'reciter_name': ea['name'],
            'ayah_map':     {i: everyayah_build_ayah_url(ea['subfolder'], surah_id, i) for i in range(1, count + 1)},
        }

    # Tier 1b: QF public CDN per-ayah
    if meta.get('qfPublicId'):
        try:
            ayah_map = qf_public_get_chapter_audio_map(surah_id, meta['qfPublicId'])
            if ayah_map:
                return {
                    'available':    True,
                    'mode':         'ayah',
                    'source':       'qf_public',
                    'reciter_id':   f"qf_public:{meta['qfPublicId']}",
                    'reciter_name': meta['rawiName'],
                    'ayah_map':     ayah_map,
                }
        except (requests.RequestException, RuntimeError, TypeError, ValueError) as exc:
            logger.warning('QF public surah-map error %s %s: %s', qiraa_key, surah_id, exc)

    # Tier 2: MP3Quran v3 surah + ayat_timing
    mp3_reciters = mp3quran_get_reciters_for_qiraa(qiraa_key, surah_id)
    if mp3_reciters:
        top_candidates = mp3_reciters[:5]
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as ex:
            futures = {ex.submit(mp3quran_get_ayat_timing, c['moshaf_id'], surah_id): c for c in top_candidates}
            for cand in top_candidates:
                fut = next(f for f, c in futures.items() if c is cand)
                try:
                    timings = fut.result()
                except (concurrent.futures.CancelledError, requests.RequestException, RuntimeError, TypeError, ValueError):
                    timings = {}
                if timings:
                    return {
                        'available':    True,
                        'mode':         'timed-surah',
                        'source':       'mp3quran_timed',
                        'reciter_id':   cand['id'],
                        'reciter_name': cand['name'],
                        'surah_url':    cand['surah_url'],
                        'timings':      timings,
                    }

    # Tier 3: Quran.com / QDC chapter audio + verse timestamps
    for qdc in qdc_get_chapter_reciters_for_qiraa(qiraa_key)[:3]:
        surah_url, timings = qdc_get_chapter_audio_with_timings(qdc['reciter_id'], surah_id)
        if surah_url and timings:
            return {
                'available':    True,
                'mode':         'timed-surah',
                'source':       'qdc_timed',
                'reciter_id':   qdc['id'],
                'reciter_name': qdc['name'],
                'surah_url':    surah_url,
                'timings':      timings,
            }

    # Tier 4: MP3Quran full-surah fallback
    if mp3_reciters:
        cand = mp3_reciters[0]
        return {
            'available':    True,
            'mode':         'surah',
            'source':       'mp3quran',
            'reciter_id':   cand['id'],
            'reciter_name': cand['name'],
            'surah_url':    cand['surah_url'],
        }

    return {'available': False, 'reason': 'not_found'}
