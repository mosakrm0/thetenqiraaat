"""
seed_db.py — pre-populates quran.db with Quranic text for all qiraat.

Imports QIRAAT and DB_PATH directly from app.py to avoid duplication.
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

# Import the single source of truth from app
sys.path.insert(0, str(Path(__file__).parent))
from app import QIRAAT, DB_PATH

REQUEST_TIMEOUT = 12
REQUEST_RETRIES = 2
KFGQPC_JSON_URLS = {
    'warsh':  'https://raw.githubusercontent.com/thetruetruth/quran-data-kfgqpc/main/warsh/data/warshData_v10.json',
    'qaloon': 'https://raw.githubusercontent.com/thetruetruth/quran-data-kfgqpc/main/qaloon/data/QaloonData_v10.json',
    'bazzi':  'https://raw.githubusercontent.com/thetruetruth/quran-data-kfgqpc/main/bazzi/data/BazziData_v07.json',
    'douri':  'https://raw.githubusercontent.com/thetruetruth/quran-data-kfgqpc/main/doori/data/DooriData_v09.json',
    'susi':   'https://raw.githubusercontent.com/thetruetruth/quran-data-kfgqpc/main/soosi/data/SoosiData09.json',
    'shouba': 'https://raw.githubusercontent.com/thetruetruth/quran-data-kfgqpc/main/shouba/data/ShoubaData08.json',
    'qumbul': 'https://raw.githubusercontent.com/thetruetruth/quran-data-kfgqpc/main/qumbul/data/QumbulData_v07.json',
}

logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)


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
        text  = ayah.get('text')
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
        text  = ayah.get('text')
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


def fetch_kfgqpc(session, surah, text_id):
    url = KFGQPC_JSON_URLS.get(text_id)
    if not url:
        raise ValueError(f'Unsupported KFGQPC text_id: {text_id}')

    resp = session.get(url, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, list):
        raise ValueError('KFGQPC JSON payload is not a list')

    ayahs = {}
    surah = int(surah)
    for row in data:
        if not isinstance(row, dict):
            continue
        sura_no = _to_int(row.get('sura_no'))
        if sura_no != surah:
            continue
        verse = _to_int(row.get('aya_no'))
        text = row.get('aya_text')
        if isinstance(verse, int) and isinstance(text, str) and text:
            ayahs[verse] = text
    return ayahs


def fetch_qiraa_ayahs(session, surah, qiraa):
    if qiraa['source'] == 'kfgqpc':
        return fetch_kfgqpc(session, surah, qiraa['textId'])
    if qiraa['source'] == 'fawaz':
        return fetch_fawaz(session, surah, qiraa['textId'])
    return fetch_alquran(session, surah, qiraa['textId'])


def seed(start_surah=1, end_surah=114, pause=0.1):
    with sqlite3.connect(str(DB_PATH)) as conn:
        c = conn.cursor()
        session = build_http_session()
        try:
            for q in QIRAAT:
                logger.info('Fetching %s (textId=%s, fallback=%s) ...', q['key'], q['textId'], q['fallback'])
                for surah in range(start_surah, end_surah + 1):
                    logger.info('  Surah %s/114', surah)

                    c.execute('SELECT COUNT(*) FROM ayahs WHERE surah = ? AND qiraa = ?', (surah, q['key']))
                    if c.fetchone()[0] > 0:
                        continue

                    try:
                        ayah_map = fetch_qiraa_ayahs(session, surah, q)
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
                    conn.commit()  # commit per surah — crash-safe
                    logger.info('    Inserted %s ayahs', conn.total_changes - before)
                    time.sleep(pause)
        finally:
            session.close()

    logger.info('Seeding complete.')


def parse_args():
    parser = argparse.ArgumentParser(description='Seed Quran qiraat text into SQLite cache.')
    parser.add_argument('--start-surah', type=int, default=1)
    parser.add_argument('--end-surah',   type=int, default=114)
    parser.add_argument('--pause',       type=float, default=0.1)
    return parser.parse_args()


if __name__ == '__main__':
    args = parse_args()
    start = max(1, min(114, args.start_surah))
    end   = max(1, min(114, args.end_surah))
    if start > end:
        start, end = end, start
    init_db()
    seed(start_surah=start, end_surah=end, pause=max(0.0, args.pause))
