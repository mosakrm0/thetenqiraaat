"""
seed_db.py — pre-populates quran.db with Quranic text, variant notes, and
ayah-counting boundary notes for all 20 riwayat (the Ten Qiraat).

Caches KFGQPC full-Quran JSON downloads in memory so each dataset is fetched
at most once per run instead of 114 times.
"""
import argparse
import logging
import sqlite3
import sys
import time
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

sys.path.insert(0, str(Path(__file__).parent))
from config import DB_PATH, KFGQPC_JSON_URLS, QIRAAT  # noqa: E402
from db import init_db, seed_count_notes_from_file, seed_variants_from_file  # noqa: E402
from services.qiraat import sync_ayah_map_from_github  # noqa: E402

REQUEST_TIMEOUT = 15
REQUEST_RETRIES = 2

logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)


def build_http_session():
    retry = Retry(
        total=REQUEST_RETRIES,
        backoff_factor=0.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=('GET',),
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=20, pool_maxsize=20)
    session = requests.Session()
    session.mount('https://', adapter)
    session.mount('http://', adapter)
    return session


def fetch_alquran(session, surah, text_id):
    url = f"https://api.alquran.cloud/v1/surah/{surah}/{text_id}"
    resp = session.get(url, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    ayahs = {}
    for ayah in data.get('data', {}).get('ayahs', []):
        verse = ayah.get('numberInSurah')
        text = ayah.get('text')
        if isinstance(verse, int) and isinstance(text, str):
            ayahs[verse] = text
    return ayahs


def fetch_fawaz(session, surah, text_id):
    url = f"https://cdn.jsdelivr.net/gh/fawazahmed0/quran-api@1/editions/{text_id}/{surah}.json"
    resp = session.get(url, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    ayahs = {}
    for ayah in data.get('chapter', []):
        verse = ayah.get('verse')
        text = ayah.get('text')
        if isinstance(verse, int) and isinstance(text, str):
            ayahs[verse] = text
    return ayahs


def _to_int(v):
    if isinstance(v, int):
        return v
    if isinstance(v, str):
        v = v.strip()
        if v.isdigit():
            return int(v)
    return None


def load_kfgqpc_by_surah(session, text_id, mem_cache: dict) -> dict[int, dict[int, str]]:
    """
    Download and parse a KFGQPC JSON file once, returning {surah_no: {aya_no: text}}.
    """
    if text_id in mem_cache:
        return mem_cache[text_id]

    url = KFGQPC_JSON_URLS.get(text_id)
    if not url:
        raise ValueError(f'Unsupported KFGQPC text_id: {text_id}')

    logger.info('Downloading KFGQPC dataset for %s (once)...', text_id)
    resp = session.get(url, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, list):
        raise ValueError('KFGQPC JSON payload is not a list')

    by_surah: dict[int, dict[int, str]] = {}
    for row in data:
        if not isinstance(row, dict):
            continue
        sura_no = _to_int(row.get('sura_no'))
        verse = _to_int(row.get('aya_no'))
        text = row.get('aya_text')
        if isinstance(sura_no, int) and isinstance(verse, int) and isinstance(text, str) and text:
            by_surah.setdefault(sura_no, {})[verse] = text

    mem_cache[text_id] = by_surah
    return by_surah


def fetch_kfgqpc(session, surah, text_id, mem_cache: dict | None = None):
    cache = mem_cache if mem_cache is not None else {}
    by_surah = load_kfgqpc_by_surah(session, text_id, cache)
    return by_surah.get(int(surah), {})


def fetch_qiraa_ayahs(session, surah, qiraa, kfgqpc_cache: dict):
    if qiraa['source'] == 'kfgqpc':
        return fetch_kfgqpc(session, surah, qiraa['textId'], kfgqpc_cache)
    if qiraa['source'] == 'fawaz':
        return fetch_fawaz(session, surah, qiraa['textId'])
    return fetch_alquran(session, surah, qiraa['textId'])


def seed(start_surah=1, end_surah=114, pause=0.1, qiraa_filter: set[str] | None = None):
    kfgqpc_cache: dict = {}
    with sqlite3.connect(str(DB_PATH)) as conn:
        c = conn.cursor()
        session = build_http_session()
        try:
            for q in QIRAAT:
                if qiraa_filter and q['key'] not in qiraa_filter:
                    continue
                logger.info('Fetching %s (textId=%s, fallback=%s) ...', q['key'], q['textId'], q['fallback'])
                for surah in range(start_surah, end_surah + 1):
                    c.execute('SELECT COUNT(*) FROM ayahs WHERE surah = ? AND qiraa = ?', (surah, q['key']))
                    if c.fetchone()[0] > 0:
                        continue

                    try:
                        ayah_map = fetch_qiraa_ayahs(session, surah, q, kfgqpc_cache)
                    except requests.RequestException as err:
                        logger.warning('Network error for %s surah %s: %s', q['key'], surah, err)
                        continue
                    except ValueError as err:
                        logger.warning('Parse error for %s surah %s: %s', q['key'], surah, err)
                        continue

                    if not ayah_map:
                        logger.warning('No ayahs for %s surah %s', q['key'], surah)
                        continue

                    before = conn.total_changes
                    c.executemany(
                        'INSERT OR IGNORE INTO ayahs (surah, ayah, qiraa, text) VALUES (?, ?, ?, ?)',
                        [(surah, n, q['key'], t) for n, t in sorted(ayah_map.items())],
                    )
                    conn.commit()
                    logger.info('  Surah %s: inserted %s ayahs', surah, conn.total_changes - before)
                    if q['source'] != 'kfgqpc' and pause > 0:
                        time.sleep(pause)
        finally:
            session.close()

    logger.info('Seeding complete.')


def parse_args():
    parser = argparse.ArgumentParser(description='Seed Quran qiraat text and annotations into SQLite.')
    parser.add_argument('--start-surah', type=int, default=1)
    parser.add_argument('--end-surah',   type=int, default=114)
    parser.add_argument('--pause',       type=float, default=0.1)
    parser.add_argument('--qiraat',      type=str, default='', help='Comma-separated qiraa keys to seed')
    parser.add_argument('--seed-variants', action='store_true', help='Re-import local variants & count notes JSONs')
    parser.add_argument('--sync-ayah-map', action='store_true', help='Sync quranpedia/qiraat-ayah-map from GitHub')
    return parser.parse_args()


if __name__ == '__main__':
    args = parse_args()
    init_db()

    if args.seed_variants:
        with sqlite3.connect(str(DB_PATH)) as conn:
            v_cnt = seed_variants_from_file(conn)
            n_cnt = seed_count_notes_from_file(conn)
            logger.info('Seeded variants (+%s), count notes (+%s).', v_cnt, n_cnt)

    if args.sync_ayah_map:
        with sqlite3.connect(str(DB_PATH)) as conn:
            added = sync_ayah_map_from_github(conn)
            logger.info('Synced qiraat-ayah-map (+%s rows).', added)

    start = max(1, min(114, args.start_surah))
    end = max(1, min(114, args.end_surah))
    if start > end:
        start, end = end, start

    q_filter = {x.strip() for x in args.qiraat.split(',') if x.strip()} or None
    seed(start_surah=start, end_surah=end, pause=max(0.0, args.pause), qiraa_filter=q_filter)
