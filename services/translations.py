import concurrent.futures
import logging
import re

import requests

from config import (
    ALQURAN_TRANSLATIONS_URL,
    FAWAZ_EDITIONS_URL,
    REQUEST_TIMEOUT,
    TRANSLATIONS_CACHE_TTL_SEC,
)
from db import get_db_connection
from services.audio import (
    everyayah_ayah_count_for_surah,
    everyayah_build_ayah_url,
    everyayah_get_recitations_payload,
)
from services.http_client import get_cache, get_http_session

logger = logging.getLogger(__name__)
_SAFE_EDITION_RE = re.compile(r'^[a-zA-Z0-9._-]+$')


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
        if not isinstance(identifier, str) or not identifier or not _SAFE_EDITION_RE.match(identifier):
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
    cached = cache.get('fawaz_editions_v2')
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
        if not isinstance(name, str) or not name or not _SAFE_EDITION_RE.match(name):
            continue
        # Skip Arabic recitation datasets and duplicate -la / -lad transliteration variants
        if name.startswith('ara-') or name.endswith('-la') or name.endswith('-lad'):
            continue

        language = normalize_lang_code(row.get('language') or '')
        display_name = str(row.get('author') or '').strip() or name
        items.append({
            'key':         f'fawaz:{name}',
            'source':      'fawaz',
            'edition':     name,
            'name':        display_name,
            'englishName': name,
            'language':    language,
            'direction':   row.get('direction') or 'ltr',
            'mode':        'ayah-text',
        })

    items.sort(key=lambda x: (str(x.get('language') or ''), str(x.get('name') or '').lower()))
    cache.set('fawaz_editions_v2', items, expire=TRANSLATIONS_CACHE_TTL_SEC)
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
    if isinstance(payload, dict):
        data = payload.get('data')
        ayahs_list = data.get('ayahs') if isinstance(data, dict) else None
        if isinstance(ayahs_list, list):
            for item in ayahs_list:
                if not isinstance(item, dict):
                    continue
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
    if isinstance(payload, dict):
        chapter = payload.get('chapter')
        if isinstance(chapter, list):
            for item in chapter:
                if not isinstance(item, dict):
                    continue
                verse = item.get('verse')
                text = item.get('text')
                if isinstance(verse, int) and isinstance(text, str):
                    ayah_map[verse] = text
    if not ayah_map:
        return {}, 'No ayahs returned from source'
    cache.set(cache_key, ayah_map, expire=TRANSLATIONS_CACHE_TTL_SEC)
    return ayah_map, None


def _norm_basmala_word(w: str) -> str:
    s = re.sub(r'[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06ED\u0640]', '', w)
    return s.replace('ٱ', 'ا').replace('أ', 'ا').replace('إ', 'ا')


def _fetch_local_hafs_ayahs(surah_id: int) -> dict[int, str]:
    try:
        conn = get_db_connection()
        try:
            rows = conn.execute(
                "SELECT ayah, text FROM ayahs WHERE surah = ? AND qiraa = 'hafs' ORDER BY ayah",
                (surah_id,),
            ).fetchall()
        finally:
            conn.close()
    except Exception:
        return {}
    out: dict[int, str] = {}
    for r in rows:
        a = int(r['ayah'])
        txt = str(r['text'] or '').lstrip('\ufeff').strip()
        if a == 1 and surah_id not in (1, 9):
            words = txt.split()
            if len(words) > 4 and [_norm_basmala_word(w) for w in words[:4]] == ['بسم', 'الله', 'الرحمن', 'الرحيم']:
                txt = ' '.join(words[4:]).strip()
        if txt:
            out[a] = txt
    return out


def unified_translations_catalog() -> list[dict]:
    """
    Return all available translations (AlQuran Cloud + Fawaz), tagging editions
    whose language has an EveryAyah audio track with `has_audio: True`.
    """
    cache = get_cache()
    cached_catalog = cache.get('unified_translations_catalog_v1')
    if isinstance(cached_catalog, list) and cached_catalog:
        return cached_catalog

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
    all_editions: list[dict] = []

    def _load_everyayah():
        out = {}
        for track in everyayah_translation_tracks():
            lang = normalize_lang_code(track.get('language') or '')
            if not lang or lang == 'ar':
                continue
            out.setdefault(lang, track)
        preferred_track_id_by_lang = {'en': 45, 'fa': 48, 'ur': 63, 'az': 50, 'bs': 72}
        for lang, tid in preferred_track_id_by_lang.items():
            tr = everyayah_find_track(tid)
            if tr:
                out[lang] = tr
        return out

    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        fut_ea = executor.submit(_load_everyayah)
        fut_aq = executor.submit(alquran_translation_editions)
        fut_fw = executor.submit(fawaz_translation_editions)

        try:
            everyayah_by_lang = fut_ea.result()
        except Exception as exc:
            logger.warning('everyayah translation catalog failed: %s', exc)
        try:
            all_editions.extend(fut_aq.result())
        except Exception as exc:
            logger.warning('alquran translation catalog failed: %s', exc)
        try:
            all_editions.extend(fut_fw.result())
        except Exception as exc:
            logger.warning('fawaz translation catalog failed: %s', exc)

    _LANG_PRIORITY = {
        'ar': 0, 'en': 1, 'ur': 2, 'fa': 3, 'tr': 4, 'fr': 5, 'id': 6,
        'de': 7, 'es': 8, 'ru': 9, 'bn': 10, 'ms': 11, 'bs': 12, 'az': 13,
        'hi': 14, 'zh': 15, 'it': 16, 'pt': 17, 'nl': 18, 'sq': 19, 'sw': 20, 'ha': 21,
    }
    _POPULAR_EDITIONS = {
        'en.sahih': 0, 'en.pickthall': 1, 'en.yusufali': 2, 'en.asad': 3,
        'ur.jalandhry': 0, 'fa.fooladvand': 0, 'fa.makarem': 1,
        'fr.hamidullah': 0, 'tr.diyanet': 0, 'id.indonesian': 0,
    }

    def _norm_author(val: str) -> str:
        s = re.sub(r'[^a-z0-9\u0600-\u06FF]+', '', str(val or '').lower())
        return s

    seen_keys = {'hafs_ar_text'}
    seen_authors: set[tuple[str, str]] = set()
    for row in all_editions:
        key = row.get('key')
        if not key or key in seen_keys:
            continue
        lang = normalize_lang_code(row.get('language') or '')
        author_sig = _norm_author(row.get('name') or row.get('englishName') or key)
        if lang and author_sig and (lang, author_sig) in seen_authors:
            continue
        seen_keys.add(key)
        if lang and author_sig:
            seen_authors.add((lang, author_sig))
        track = everyayah_by_lang.get(lang)
        catalog.append({
            **row,
            'language':        lang,
            'audio_subfolder': track.get('subfolder') if track else None,
            'has_audio':       bool(track),
        })

    catalog[1:] = sorted(
        catalog[1:],
        key=lambda x: (
            _LANG_PRIORITY.get(str(x.get('language') or ''), 999),
            str(x.get('language') or 'zzz'),
            _POPULAR_EDITIONS.get(str(x.get('edition') or ''), 50),
            0 if x.get('has_audio') else 1,
            str(x.get('name') or x.get('englishName') or '').lower(),
        ),
    )
    if len(catalog) > 1:
        cache.set('unified_translations_catalog_v1', catalog, expire=TRANSLATIONS_CACHE_TTL_SEC)
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
            ayahs = _fetch_local_hafs_ayahs(surah_id)
            err = None
            if not ayahs:
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
