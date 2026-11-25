import concurrent.futures
import logging
import sqlite3

import requests

from config import (
    KFGQPC_CACHE_TTL_SEC,
    KFGQPC_JSON_URLS,
    QIRAAT,
    QIRAAT10_API_BASE,
    QIRAAT_AYAH_MAP_URL,
    QIRAAT_BY_KEY,
    QF_QIRAAT_ENABLED,
    REQUEST_TIMEOUT,
)
from services.http_client import get_cache, get_http_session

logger = logging.getLogger(__name__)


def extract_ayahs(source: str, payload: dict) -> dict[int, str]:
    ayah_map: dict[int, str] = {}
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


def _kfgqpc_to_int(value) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        value = value.strip()
        if value.isdigit():
            return int(value)
    return None


def _kfgqpc_get_rows(session: requests.Session, text_id: str) -> tuple[list | None, str | None]:
    url = KFGQPC_JSON_URLS.get(text_id)
    if not url:
        return None, f'Unsupported KFGQPC textId: {text_id}'

    cache = get_cache()
    cache_key = f'kfgqpc_json_{text_id}'
    cached = cache.get(cache_key)
    if isinstance(cached, list):
        return cached, None

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

    cache.set(cache_key, payload, expire=KFGQPC_CACHE_TTL_SEC)
    return payload, None


def fetch_kfgqpc_ayahs(session: requests.Session, surah_id: int, text_id: str) -> tuple[dict[int, str], str | None]:
    rows, err = _kfgqpc_get_rows(session, text_id)
    if err:
        return {}, err

    ayah_map: dict[int, str] = {}
    target_surah = int(surah_id)
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        sura_no = _kfgqpc_to_int(row.get('sura_no'))
        if sura_no != target_surah:
            continue
        ayah_no = _kfgqpc_to_int(row.get('aya_no'))
        aya_text = row.get('aya_text')
        if isinstance(ayah_no, int) and isinstance(aya_text, str) and aya_text:
            ayah_map[ayah_no] = aya_text

    if not ayah_map:
        return {}, 'No ayahs found for this surah in KFGQPC dataset'
    return ayah_map, None


def fetch_qiraa_ayahs(surah_id: int, qiraa: dict) -> tuple[dict[int, str], str | None]:
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


def fetch_external_and_store(surah_id: int, conn: sqlite3.Connection, qiraa_keys: list[str]) -> dict[str, dict]:
    c = conn.cursor()
    status_map: dict[str, dict] = {}
    key_set = set(qiraa_keys)
    tasks = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=7) as executor:
        for q in QIRAAT:
            if q['key'] not in key_set:
                continue
            tasks.append((q, executor.submit(fetch_qiraa_ayahs, surah_id, q)))

        for q, future in tasks:
            try:
                ayah_map, err = future.result()
                if err:
                    status_map[q['key']] = {'fetch_status': 'error', 'error': err}
                    logger.warning('Fetch failed for %s (surah %s): %s', q['key'], surah_id, err)
                    continue

                before = conn.total_changes
                c.executemany(
                    'INSERT OR IGNORE INTO ayahs (surah, ayah, qiraa, text) VALUES (?, ?, ?, ?)',
                    [(surah_id, ayah_num, q['key'], text) for ayah_num, text in sorted(ayah_map.items())],
                )
                conn.commit()
                inserted = conn.total_changes - before
                status_map[q['key']] = {
                    'fetch_status': 'fetched' if inserted > 0 else 'cached',
                    'error': None,
                }
            except Exception as exc:
                status_map[q['key']] = {'fetch_status': 'error', 'error': str(exc)}
                logger.warning('Fetch exception for %s (surah %s): %s', q['key'], surah_id, exc)

    return status_map


def get_surah_variants(conn: sqlite3.Connection, surah_id: int, qiraa_keys: list[str] | None = None) -> dict[str, dict[int, list[dict]]]:
    """
    Return {qiraa_key: {ayah_num: [{hafs_word, variant_text, note, rule_type, source}]}}
    from SQLite qiraat_variants (plus optional QF Qira'at v4 enrichment if enabled).
    """
    c = conn.cursor()
    if qiraa_keys:
        placeholders = ','.join('?' for _ in qiraa_keys)
        c.execute(
            f'''SELECT ayah, qiraa, hafs_word, variant_text, note, rule_type, source
                FROM qiraat_variants
                WHERE surah = ? AND qiraa IN ({placeholders})
                ORDER BY ayah, id''',
            [surah_id, *qiraa_keys],
        )
    else:
        c.execute(
            '''SELECT ayah, qiraa, hafs_word, variant_text, note, rule_type, source
               FROM qiraat_variants
               WHERE surah = ?
               ORDER BY ayah, id''',
            (surah_id,),
        )

    out: dict[str, dict[int, list[dict]]] = {}
    for row in c.fetchall():
        q_map = out.setdefault(row['qiraa'], {})
        q_map.setdefault(int(row['ayah']), []).append({
            'hafs_word':    row['hafs_word'] or '',
            'variant_text': row['variant_text'] or '',
            'note':         row['note'] or '',
            'rule_type':    row['rule_type'] or 'farsh',
            'source':       row['source'] or 'curated',
        })

    if QF_QIRAAT_ENABLED:
        _enrich_variants_from_qf_if_available(surah_id, out)

    return out


def _enrich_variants_from_qf_if_available(surah_id: int, out: dict) -> None:
    """Best-effort hook for Quran Foundation Qira'at API v4 (requires qiraat.read scope)."""
    try:
        from services.audio import qf_api_get, qf_is_enabled
        if not qf_is_enabled():
            return
        cache = get_cache()
        cache_key = f'qf_qiraat_matrix_{surah_id}'
        cached = cache.get(cache_key)
        if cached is None:
            session = get_http_session()
            payload = qf_api_get(session, f'/qiraat/matrix/by_chapter/{int(surah_id)}')
            cache.set(cache_key, payload or {}, expire=60 * 60 * 6)
    except Exception as exc:
        logger.debug('QF qiraat matrix unavailable for surah %s: %s', surah_id, exc)


def get_surah_count_notes(conn: sqlite3.Connection, surah_id: int, qiraa_keys: list[str] | None = None) -> dict[str, dict[int, list[dict]]]:
    """
    Return {qiraa_key: {kufi_ayah: [{boundary_type, anchor_word, note, counting_system}]}}.
    """
    c = conn.cursor()
    c.execute(
        '''SELECT kufi_ayah, counting_system, boundary_type, anchor_word, note
           FROM ayah_count_notes
           WHERE surah = ?
           ORDER BY kufi_ayah, id''',
        (surah_id,),
    )
    by_system: dict[str, dict[int, list[dict]]] = {}
    for row in c.fetchall():
        sys_map = by_system.setdefault(row['counting_system'], {})
        sys_map.setdefault(int(row['kufi_ayah']), []).append({
            'counting_system': row['counting_system'],
            'boundary_type':   row['boundary_type'],
            'anchor_word':     row['anchor_word'] or '',
            'note':            row['note'] or '',
        })

    target_keys = qiraa_keys or [q['key'] for q in QIRAAT]
    result: dict[str, dict[int, list[dict]]] = {}
    for qk in target_keys:
        meta = QIRAAT_BY_KEY.get(qk)
        if not meta:
            continue
        cs = meta.get('countingSystem')
        if cs and cs in by_system:
            result[qk] = by_system[cs]
    return result


def sync_ayah_map_from_github(conn: sqlite3.Connection) -> int:
    """
    Download quranpedia/qiraat-ayah-map boundary primitives JSON and store
    entries into ayah_count_notes.
    """
    session = get_http_session()
    resp = session.get(QIRAAT_AYAH_MAP_URL, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    payload = resp.json()
    surahs = payload.get('surahs') if isinstance(payload, dict) else None
    if not isinstance(surahs, dict):
        raise ValueError('Invalid qiraat-ayah-map JSON structure')

    tuples = []
    for surah_str, ayahs_obj in surahs.items():
        if not str(surah_str).isdigit() or not isinstance(ayahs_obj, dict):
            continue
        surah_num = int(surah_str)
        for ayah_str, boundary_obj in ayahs_obj.items():
            if not str(ayah_str).isdigit() or not isinstance(boundary_obj, dict):
                continue
            ayah_num = int(ayah_str)

            end_obj = boundary_obj.get('end')
            if isinstance(end_obj, dict):
                word = str(end_obj.get('word') or '').strip()
                for sys_name in end_obj.get('counted_by') or []:
                    tuples.append((
                        surah_num, ayah_num, str(sys_name).strip(), 'end', word,
                        f'تُعدّ «{word}» رأس آية في هذا العد' if word else '',
                    ))

            for internal_obj in boundary_obj.get('internal') or []:
                if not isinstance(internal_obj, dict):
                    continue
                word = str(internal_obj.get('word') or '').strip()
                for sys_name in internal_obj.get('counted_by') or []:
                    tuples.append((
                        surah_num, ayah_num, str(sys_name).strip(), 'internal', word,
                        f'يُفصل عند «{word}» كرأس آية داخل الآية الكوفية' if word else '',
                    ))

    if not tuples:
        return 0
    before = conn.total_changes
    conn.executemany(
        '''INSERT OR IGNORE INTO ayah_count_notes
           (surah, kufi_ayah, counting_system, boundary_type, anchor_word, note)
           VALUES (?, ?, ?, ?, ?, ?)''',
        tuples,
    )
    conn.commit()
    return conn.total_changes - before


def fetch_qiraat10_page_notes(page_number: int) -> list[dict]:
    """Optional helper to query QZTA/qiraat-api (qiraat10.com) for Mushaf page annotations."""
    if not QIRAAT10_API_BASE:
        return []
    cache = get_cache()
    cache_key = f'qiraat10_page_{page_number}'
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    try:
        session = get_http_session()
        resp = session.get(f'{QIRAAT10_API_BASE}/qiraat/page/{int(page_number)}', timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        items = data if isinstance(data, list) else data.get('data', [])
        if not isinstance(items, list):
            items = []
        cache.set(cache_key, items, expire=60 * 60 * 24)
        return items
    except Exception as exc:
        logger.debug('qiraat10 API unavailable for page %s: %s', page_number, exc)
        return []
