import concurrent.futures
import logging

import requests

from config import (
    ALQURAN_TRANSLATIONS_URL,
    FAWAZ_EDITIONS_URL,
    REQUEST_TIMEOUT,
    TRANSLATIONS_CACHE_TTL_SEC,
)
from services.audio import (
    everyayah_ayah_count_for_surah,
    everyayah_build_ayah_url,
    everyayah_get_recitations_payload,
)
from services.http_client import get_cache, get_http_session

logger = logging.getLogger(__name__)


def _everyayah_is_translation_track(name: str, subfolder: str) -> bool:
    n = (name or '').lower()
    s = (subfolder or '').lower()
    if s.startswith('translations/') or s.startswith('english/') or s.startswith('multilanguage/'):
        return True
    return ('translated' in n) or ('translation' in n) or ('word for word' in n)


def normalize_lang_code(value: str) -> str:
    v = str(value or '').strip().lower()
    if not v:
        return ''
    aliases = {
        'english': 'en', 'arabic': 'ar', 'urdu': 'ur', 'persian': 'fa',
        'farsi': 'fa', 'azerbaijani': 'az', 'bosnian': 'bs', 'french': 'fr',
        'german': 'de', 'spanish': 'es', 'russian': 'ru', 'turkish': 'tr',
        'indonesian': 'id', 'malay': 'ms', 'bengali': 'bn', 'hindi': 'hi',
        'pashto': 'ps', 'divehi': 'dv', 'czech': 'cs', 'dutch': 'nl',
        'italian': 'it', 'portuguese': 'pt', 'swedish': 'sv', 'norwegian': 'no',
        'danish': 'da', 'finnish': 'fi', 'polish': 'pl', 'romanian': 'ro',
        'albanian': 'sq', 'kurdish': 'ku', 'tajik': 'tg', 'tamil': 'ta',
        'telugu': 'te', 'malayalam': 'ml', 'hausa': 'ha', 'swahili': 'sw',
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
    return v[:3] if v.isalpha() and len(v) == 3 else ''


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
            'trackId':   track_id,
            'name':      name or subfolder,
            'subfolder': subfolder,
            'bitrate':   value.get('bitrate'),
            'language':  lang,
            'source':    'everyayah',
            'mode':      'ayah-audio',
        })
    items.sort(key=lambda x: (str(x.get('name') or '').lower(), int(x.get('trackId') or 0)))
    return items


def everyayah_find_track(track_id: int) -> dict | None:
    for item in everyayah_translation_tracks():
        if int(item['trackId']) == int(track_id):
            return item
    return None


def alquran_translation_editions() -> list[dict]:
    cache = get_cache()
    cached = cache.get('alquran_translations')
    if isinstance(cached, list):
        return cached

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
            'key':         f'alquran:{identifier}',
            'source':      'alquran',
            'edition':     identifier,
            'name':        row.get('name') or identifier,
            'englishName': row.get('englishName') or identifier,
            'language':    normalize_lang_code(row.get('language') or ''),
            'direction':   row.get('direction') or 'ltr',
            'mode':        'ayah-text',
        })

    items.sort(key=lambda x: (str(x.get('language') or ''), str(x.get('englishName') or '').lower()))
    cache.set('alquran_translations', items, expire=TRANSLATIONS_CACHE_TTL_SEC)
    return items


def fawaz_translation_editions() -> list[dict]:
    cache = get_cache()
    cached = cache.get('fawaz_editions')
    if isinstance(cached, list):
        return cached

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
        if name.startswith('ara-'):
            continue

        language = normalize_lang_code(row.get('language') or '')
        items.append({
            'key':         f'fawaz:{name}',
            'source':      'fawaz',
            'edition':     name,
            'name':        row.get('author') or name,
            'englishName': name,
            'language':    language,
            'direction':   row.get('direction') or 'ltr',
            'mode':        'ayah-text',
        })

    items.sort(key=lambda x: (str(x.get('language') or ''), str(x.get('englishName') or '').lower()))
    cache.set('fawaz_editions', items, expire=TRANSLATIONS_CACHE_TTL_SEC)
    return items


def fetch_alquran_edition_ayahs(surah_id: int, edition: str) -> tuple[dict[int, str], str | None]:
    cache = get_cache()
    cache_key = f'tr_alquran_{edition}_{surah_id}'
    cached = cache.get(cache_key)
    if isinstance(cached, dict) and cached:
        return cached, None

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

    ayah_map: dict[int, str] = {}
    for item in payload.get('data', {}).get('ayahs', []):
        verse = item.get('numberInSurah')
        text = item.get('text')
        if isinstance(verse, int) and isinstance(text, str):
            ayah_map[verse] = text
    if not ayah_map:
        return {}, 'No ayahs returned from source'
    cache.set(cache_key, ayah_map, expire=TRANSLATIONS_CACHE_TTL_SEC)
    return ayah_map, None


def fetch_fawaz_edition_ayahs(surah_id: int, edition: str) -> tuple[dict[int, str], str | None]:
    cache = get_cache()
    cache_key = f'tr_fawaz_{edition}_{surah_id}'
    cached = cache.get(cache_key)
    if isinstance(cached, dict) and cached:
        return cached, None

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

    ayah_map: dict[int, str] = {}
    for item in payload.get('chapter', []):
        verse = item.get('verse')
        text = item.get('text')
        if isinstance(verse, int) and isinstance(text, str):
            ayah_map[verse] = text
    if not ayah_map:
        return {}, 'No ayahs returned from source'
    cache.set(cache_key, ayah_map, expire=TRANSLATIONS_CACHE_TTL_SEC)
    return ayah_map, None


def unified_translations_catalog() -> list[dict]:
    """
    Return all available translations (AlQuran Cloud + Fawaz), tagging editions
    whose language has an EveryAyah audio track with `has_audio: True`.
    """
    catalog: list[dict] = [{
        'key':             'hafs_ar_text',
        'source':          'alquran',
        'edition':         'quran-uthmani',
        'name':            'العربية - حفص (نص)',
        'englishName':     'Arabic Hafs (Text)',
        'language':        'ar',
        'direction':       'rtl',
        'mode':            'ayah-text',
        'audio_subfolder': 'Alafasy_128kbps',
        'has_audio':       True,
    }]

    everyayah_by_lang: dict[str, dict] = {}
    try:
        for track in everyayah_translation_tracks():
            lang = normalize_lang_code(track.get('language') or '')
            if not lang or lang == 'ar':
                continue
            everyayah_by_lang.setdefault(lang, track)
        preferred_track_id_by_lang = {'en': 45, 'fa': 48, 'ur': 63, 'az': 50, 'bs': 72}
        for lang, tid in preferred_track_id_by_lang.items():
            tr = everyayah_find_track(tid)
            if tr:
                everyayah_by_lang[lang] = tr
    except Exception as exc:
        logger.warning('everyayah translation catalog failed: %s', exc)

    seen_keys = {'hafs_ar_text'}
    all_editions: list[dict] = []

    try:
        all_editions.extend(alquran_translation_editions())
    except Exception as exc:
        logger.warning('alquran translation catalog failed: %s', exc)

    try:
        all_editions.extend(fawaz_translation_editions())
    except Exception as exc:
        logger.warning('fawaz translation catalog failed: %s', exc)

    for row in all_editions:
        key = row.get('key')
        if not key or key in seen_keys:
            continue
        seen_keys.add(key)
        lang = normalize_lang_code(row.get('language') or '')
        track = everyayah_by_lang.get(lang)
        catalog.append({
            **row,
            'language':        lang,
            'audio_subfolder': track.get('subfolder') if track else None,
            'has_audio':       bool(track),
        })

    # Put audio-backed items first, then sort by language and name
    catalog[1:] = sorted(
        catalog[1:],
        key=lambda x: (0 if x.get('has_audio') else 1, str(x.get('language') or 'zzz'), str(x.get('englishName') or '').lower()),
    )
    return catalog


def fetch_translations_for_surah(surah_id: int, req_keys: list[str]) -> tuple[dict, int]:
    catalog = {item['key']: item for item in unified_translations_catalog()}
    result: dict[str, dict] = {}
    max_ayah = 0

    def _fetch_one(key: str):
        meta = catalog.get(key)
        if not meta:
            return key, {
                'key':          key,
                'mode':         'unknown',
                'fetch_status': 'unavailable',
                'error':        'Unknown translation key',
            }, 0

        source = meta.get('source')
        mode = meta.get('mode') or 'ayah-text'

        if mode == 'ayah-audio' and source == 'everyayah':
            try:
                track_id = int(meta.get('trackId'))
                track = everyayah_find_track(track_id)
                if not track:
                    raise ValueError('Track not found')
                ayah_count = everyayah_ayah_count_for_surah(surah_id)
                ayah_map = {i: everyayah_build_ayah_url(track['subfolder'], surah_id, i) for i in range(1, ayah_count + 1)}
                return key, {
                    'key':          key,
                    'mode':         'ayah-audio',
                    'name':         meta.get('name'),
                    'source':       source,
                    'language':     meta.get('language', ''),
                    'direction':    meta.get('direction', 'ltr'),
                    'fetch_status': 'fetched',
                    'ayah_map':     ayah_map,
                    'ayah_count':   ayah_count,
                    'error':        None,
                }, ayah_count
            except Exception as exc:
                return key, {
                    'key':          key,
                    'mode':         'ayah-audio',
                    'name':         meta.get('name'),
                    'source':       source,
                    'language':     meta.get('language', ''),
                    'direction':    meta.get('direction', 'ltr'),
                    'fetch_status': 'error',
                    'error':        str(exc),
                }, 0

        if key == 'hafs_ar_text':
            ayahs, err = fetch_alquran_edition_ayahs(surah_id, 'quran-uthmani')
        elif source == 'alquran':
            ayahs, err = fetch_alquran_edition_ayahs(surah_id, str(meta.get('edition') or ''))
        elif source == 'fawaz':
            ayahs, err = fetch_fawaz_edition_ayahs(surah_id, str(meta.get('edition') or ''))
        else:
            ayahs, err = {}, 'Unsupported translation source'

        if err:
            return key, {
                'key':          key,
                'mode':         'ayah-text',
                'name':         meta.get('name'),
                'englishName':  meta.get('englishName'),
                'source':       source,
                'language':     meta.get('language', ''),
                'direction':    meta.get('direction', 'ltr'),
                'fetch_status': 'error',
                'error':        err,
            }, 0

        text_ayah_count = max(ayahs.keys(), default=0)
        local_max = text_ayah_count
        ayah_audio_map = None
        audio_subfolder = str(meta.get('audio_subfolder') or '').strip()
        if audio_subfolder:
            audio_ayah_count = everyayah_ayah_count_for_surah(surah_id) or text_ayah_count
            if audio_ayah_count > 0:
                ayah_audio_map = {
                    i: everyayah_build_ayah_url(audio_subfolder, surah_id, i)
                    for i in range(1, audio_ayah_count + 1)
                }
                local_max = max(local_max, audio_ayah_count)

        return key, {
            'key':            key,
            'mode':           'ayah-text',
            'name':           meta.get('name'),
            'englishName':    meta.get('englishName'),
            'source':         source,
            'language':       meta.get('language', ''),
            'direction':      meta.get('direction', 'ltr'),
            'has_audio':      bool(ayah_audio_map),
            'ayah_audio_map': ayah_audio_map,
            'fetch_status':   'fetched',
            'ayahs':          [{'text': ayahs.get(i, '(النص غير متاح)')} for i in range(1, text_ayah_count + 1)],
            'error':          None,
        }, local_max

    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
        futures = [executor.submit(_fetch_one, k) for k in req_keys]
        for fut in futures:
            k, entry, l_max = fut.result()
            result[k] = entry
            max_ayah = max(max_ayah, l_max)

    for entry in result.values():
        if entry.get('mode') != 'ayah-text' or 'ayahs' not in entry:
            continue
        cur = entry['ayahs']
        if len(cur) < max_ayah:
            entry['ayahs'] = cur + ([{'text': '(النص غير متاح)'}] * (max_ayah - len(cur)))

    return result, max_ayah
