import concurrent.futures
import logging
import re
import sqlite3

import requests

from config import (
    KFGQPC_CACHE_TTL_SEC,
    KFGQPC_JSON_URLS,
    QIRAAT,
    QIRAAT10_API_BASE,
    QIRAAT_AYAH_MAP_URL,
    QIRAAT_BY_KEY,
    QIRAAT_NOTES_URL,
    QURAN_DATA_PAGES_URL,
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
        query_keys = [*qiraa_keys, '_all']
        placeholders = ','.join('?' for _ in query_keys)
        c.execute(
            f'''SELECT ayah, qiraa, hafs_word, variant_text, note, rule_type, source
                FROM qiraat_variants
                WHERE surah = ? AND qiraa IN ({placeholders})
                ORDER BY ayah, id''',
            [surah_id, *query_keys],
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
    all_notes: dict[int, list[dict]] = {}
    for row in c.fetchall():
        item = {
            'hafs_word':    row['hafs_word'] or '',
            'variant_text': row['variant_text'] or '',
            'note':         row['note'] or '',
            'rule_type':    row['rule_type'] or 'farsh',
            'source':       row['source'] or 'curated',
        }
        if row['qiraa'] == '_all':
            all_notes.setdefault(int(row['ayah']), []).append(item)
        else:
            q_map = out.setdefault(row['qiraa'], {})
            q_map.setdefault(int(row['ayah']), []).append(item)

    if all_notes:
        target_keys = qiraa_keys or [q['key'] for q in QIRAAT]
        for qk in target_keys:
            q_map = out.setdefault(qk, {})
            for ayah_num, items in all_notes.items():
                q_map.setdefault(ayah_num, []).extend(items)

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


def _ar_digits_to_ascii(text: str) -> str:
    trans = str.maketrans('٠١٢٣٤٥٦٧٨٩', '0123456789')
    return str(text or '').translate(trans)


def _match_riwayat_in_note(note_text: str) -> list[str]:
    """Identify canonical riwayat keys referenced in an Arabic Qiraat farsh/usul note."""
    norm = _ar_digits_to_ascii(note_text)
    matched: set[str] = set()

    # Specific transmitters
    rawi_patterns = [
        ('qaloon',        ['قالون']),
        ('warsh',         ['ورش']),
        ('bazzi',         ['البزي', 'بزي']),
        ('qumbul',        ['قنبل']),
        ('douri',         ['الدوري عن أبي عمرو', 'الدوري عن ابي عمرو']),
        ('susi',          ['السوسي']),
        ('hisham',        ['هشام']),
        ('ibn_dhakwan',   ['ابن ذكوان', 'ذكوان']),
        ('shouba',        ['شعبة']),
        ('hafs',          ['حفص']),
        ('khalaf_hamzah', ['خلف عن حمزة']),
        ('khallad',       ['خلاد']),
        ('harith',        ['أبو الحارث', 'ابو الحارث', 'الحارث']),
        ('douri_kisai',   ['الدوري عن الكسائي']),
        ('wardan',        ['ابن وردان', 'وردان']),
        ('ibn_jammaz',    ['ابن جماز', 'جماز']),
        ('ruways',        ['رويس']),
        ('rawh',          ['روح']),
        ('ishaq',         ['إسحاق', 'اسحاق']),
        ('idris',         ['إدريس', 'ادريس']),
    ]
    for key, pats in rawi_patterns:
        if any(p in norm for p in pats):
            matched.add(key)

    # Generic الدوري (applies to both Abu Amr and Al-Kisa'i if neither specific phrase matched)
    if 'الدوري' in norm and 'douri' not in matched and 'douri_kisai' not in matched:
        matched.update(['douri', 'douri_kisai'])

    # Imams & canonical groupings
    group_patterns = [
        (['نافع'],                  ['qaloon', 'warsh']),
        (['ابن كثير'],              ['bazzi', 'qumbul']),
        (['أبو عمرو', 'أبوعمرو', 'ابو عمرو'], ['douri', 'susi']),
        (['ابن عامر', 'الشامي'],    ['hisham', 'ibn_dhakwan']),
        (['عاصم'],                  ['shouba', 'hafs']),
        (['حمزة'],                  ['khalaf_hamzah', 'khallad']),
        (['الكسائي', 'الكسائى'],    ['harith', 'douri_kisai']),
        (['أبو جعفر', 'أبوجعفر', 'ابو جعفر'], ['wardan', 'ibn_jammaz']),
        (['يعقوب'],                 ['ruways', 'rawh']),
        (['خلف العاشر', 'خلف في اختياره'], ['ishaq', 'idris']),
        (['الكوفيون', 'الكوفيين'], ['shouba', 'hafs', 'khalaf_hamzah', 'khallad', 'harith', 'douri_kisai', 'ishaq', 'idris']),
        (['المدنيان'],              ['qaloon', 'warsh', 'wardan', 'ibn_jammaz']),
        (['الحرميان'],              ['qaloon', 'warsh', 'bazzi', 'qumbul']),
        (['البصريان'],              ['douri', 'susi', 'ruways', 'rawh']),
    ]
    for pats, keys in group_patterns:
        if any(p in norm for p in pats):
            matched.update(keys)

    if not matched:
        return ['_all']
    return sorted(matched)


def parse_qiraat_notes_pages(notes_payload: dict, quran_pages_payload: dict) -> list[tuple]:
    """
    Parse QZTA/qiraat-api qiraat-notes.json (604 pages) + quran-data.json page->verses map
    into tuples ready for qiraat_variants:
      (surah, ayah, qiraa, hafs_word, variant_text, note, rule_type, source)
    """
    page_verses: dict[int, list[tuple[int, int]]] = {}
    for p_obj in quran_pages_payload.get('pages') or []:
        if not isinstance(p_obj, dict) or not p_obj.get('page'):
            continue
        p_num = int(p_obj['page'])
        v_list = []
        for v in p_obj.get('verses') or []:
            if isinstance(v, dict) and v.get('chapter') and v.get('number'):
                v_list.append((int(v['chapter']), int(v['number'])))
        if v_list:
            page_verses[p_num] = v_list

    tuples: list[tuple] = []
    for p_entry in notes_payload.get('pages') or []:
        if not isinstance(p_entry, dict) or not p_entry.get('page'):
            continue
        p_num = int(p_entry['page'])
        verses_on_page = page_verses.get(p_num) or []
        if not verses_on_page:
            continue

        # Map ayah_num -> list of (surah, ayah) on this page (handles multi-surah pages)
        ayah_lookup: dict[int, list[tuple[int, int]]] = {}
        for s_id, a_id in verses_on_page:
            ayah_lookup.setdefault(a_id, []).append((s_id, a_id))

        for rule_type, field in (('farsh', 'farsh'), ('usul', 'usul')):
            for raw_note in p_entry.get(field) or []:
                note_str = str(raw_note or '').strip()
                if not note_str:
                    continue

                # Extract leading ayah numbers before '-' (e.g. "٤ - (مَالِكِ): ..." or "١٣، ١١ - ...")
                ascii_note = _ar_digits_to_ascii(note_str)
                head_match = re.match(r'^([0-9،,\s]+)\s*[-–:]\s*(.*)$', ascii_note)
                target_coords: list[tuple[int, int]] = []
                body = note_str
                if head_match:
                    nums = [int(n) for n in re.findall(r'\d+', head_match.group(1))]
                    for n in nums:
                        target_coords.extend(ayah_lookup.get(n, []))
                if not target_coords:
                    # Page-level usul or unmatched number -> attach to first verse on the page
                    target_coords = [verses_on_page[0]]

                # Extract word inside first (...) if present
                word_match = re.search(r'\(([^)]{1,60})\)', note_str)
                hafs_word = word_match.group(1).strip() if word_match else ''
                variant_text = hafs_word or ('أصول القراءة' if rule_type == 'usul' else 'فرش الحروف')

                riwayat_keys = _match_riwayat_in_note(note_str)
                # Keep DB compact: if >=10 riwayat match or '_all', store once under '_all'
                if len(riwayat_keys) >= 10:
                    riwayat_keys = ['_all']

                for s_id, a_id in target_coords:
                    for rk in riwayat_keys:
                        tuples.append((
                            s_id, a_id, rk, hafs_word, variant_text,
                            note_str, rule_type, 'shatibiyyah_durrah',
                        ))

    return tuples


def sync_qiraat_notes_from_github(conn: sqlite3.Connection) -> int:
    """Download 604-page Ten-Qiraat Farsh & Usul notes and store into qiraat_variants."""
    session = get_http_session()
    notes_resp = session.get(QIRAAT_NOTES_URL, timeout=max(REQUEST_TIMEOUT, 20))
    notes_resp.raise_for_status()
    pages_resp = session.get(QURAN_DATA_PAGES_URL, timeout=max(REQUEST_TIMEOUT, 20))
    pages_resp.raise_for_status()

    tuples = parse_qiraat_notes_pages(notes_resp.json(), pages_resp.json())
    if not tuples:
        return 0

    before = conn.total_changes
    conn.executemany(
        '''INSERT OR IGNORE INTO qiraat_variants
           (surah, ayah, qiraa, hafs_word, variant_text, note, rule_type, source)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
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
