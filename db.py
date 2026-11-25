import json
import logging
import sqlite3
from pathlib import Path

from config import DATA_DIR, DB_PATH

logger = logging.getLogger(__name__)


def get_db_connection(db_path: Path | str | None = None):
    target = str(db_path or DB_PATH)
    conn = sqlite3.connect(target, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA busy_timeout=5000;')
    conn.execute('PRAGMA synchronous=NORMAL;')
    return conn


def _migrate_db(conn: sqlite3.Connection):
    """Idempotent schema migrations tracked via PRAGMA user_version."""
    version = conn.execute('PRAGMA user_version').fetchone()[0]
    if version < 2:
        conn.execute('DROP TABLE IF EXISTS feedback_messages')
        conn.execute('DROP TABLE IF EXISTS translations_local_ayahs')
        conn.execute('DROP TABLE IF EXISTS translations_local_meta')

        row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='qiraat_variants'"
        ).fetchone()
        if row and row[0] and 'UNIQUE(surah, ayah, qiraa, hafs_word, variant_text)' in row[0]:
            conn.execute('''CREATE TABLE qiraat_variants_new (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                surah        INTEGER NOT NULL,
                ayah         INTEGER NOT NULL,
                qiraa        TEXT NOT NULL,
                hafs_word    TEXT,
                variant_text TEXT NOT NULL,
                note         TEXT,
                rule_type    TEXT DEFAULT 'farsh',
                source       TEXT DEFAULT 'curated',
                UNIQUE(surah, ayah, qiraa, hafs_word, variant_text, note)
            )''')
            conn.execute('''INSERT OR IGNORE INTO qiraat_variants_new
                (id, surah, ayah, qiraa, hafs_word, variant_text, note, rule_type, source)
                SELECT id, surah, ayah, qiraa, hafs_word, variant_text, note, rule_type, source
                FROM qiraat_variants''')
            conn.execute('DROP TABLE qiraat_variants')
            conn.execute('ALTER TABLE qiraat_variants_new RENAME TO qiraat_variants')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_variants_surah_qiraa ON qiraat_variants(surah, qiraa)')

        conn.execute('PRAGMA user_version = 2')
        conn.commit()


def init_db(db_path: Path | str | None = None):
    target = str(db_path or DB_PATH)
    conn = sqlite3.connect(target, timeout=5.0)
    try:
        conn.execute('PRAGMA journal_mode=WAL;')
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

        c.execute('''CREATE TABLE IF NOT EXISTS qiraat_variants (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            surah        INTEGER NOT NULL,
            ayah         INTEGER NOT NULL,
            qiraa        TEXT NOT NULL,
            hafs_word    TEXT,
            variant_text TEXT NOT NULL,
            note         TEXT,
            rule_type    TEXT DEFAULT 'farsh',
            source       TEXT DEFAULT 'curated',
            UNIQUE(surah, ayah, qiraa, hafs_word, variant_text, note)
        )''')
        c.execute('CREATE INDEX IF NOT EXISTS idx_variants_surah_qiraa ON qiraat_variants(surah, qiraa)')

        c.execute('''CREATE TABLE IF NOT EXISTS ayah_count_notes (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            surah           INTEGER NOT NULL,
            kufi_ayah       INTEGER NOT NULL,
            counting_system TEXT NOT NULL,
            boundary_type   TEXT NOT NULL,
            anchor_word     TEXT,
            note            TEXT,
            UNIQUE(surah, kufi_ayah, counting_system, boundary_type, anchor_word)
        )''')
        c.execute('CREATE INDEX IF NOT EXISTS idx_count_notes_surah ON ayah_count_notes(surah)')
        conn.commit()

        _migrate_db(conn)
        _seed_curated_tables_if_empty(conn)
    finally:
        conn.close()


def _seed_curated_tables_if_empty(conn: sqlite3.Connection):
    c = conn.cursor()
    c.execute('SELECT COUNT(*) FROM qiraat_variants')
    if c.fetchone()[0] == 0:
        seed_variants_from_file(conn)

    c.execute('SELECT COUNT(*) FROM ayah_count_notes')
    if c.fetchone()[0] == 0:
        seed_count_notes_from_file(conn)


def seed_variants_from_file(conn: sqlite3.Connection, file_path: Path | None = None) -> int:
    path = file_path or (DATA_DIR / 'qiraat_variants_seed.json')
    if not path.exists():
        return 0
    try:
        rows = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        logger.warning('Failed to load variants seed file %s: %s', path, exc)
        return 0
    if not isinstance(rows, list):
        return 0

    tuples = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        surah = r.get('surah')
        ayah = r.get('ayah')
        qiraa = r.get('qiraa')
        variant_text = r.get('variant_text')
        if not (isinstance(surah, int) and isinstance(ayah, int) and qiraa and variant_text):
            continue
        tuples.append((
            surah,
            ayah,
            str(qiraa).strip(),
            str(r.get('hafs_word') or '').strip(),
            str(variant_text).strip(),
            str(r.get('note') or '').strip(),
            str(r.get('rule_type') or 'farsh').strip(),
            str(r.get('source') or 'curated').strip(),
        ))

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


def seed_count_notes_from_file(conn: sqlite3.Connection, file_path: Path | None = None) -> int:
    path = file_path or (DATA_DIR / 'ayah_count_notes_seed.json')
    if not path.exists():
        return 0
    try:
        rows = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        logger.warning('Failed to load count notes seed file %s: %s', path, exc)
        return 0
    if not isinstance(rows, list):
        return 0

    tuples = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        surah = r.get('surah')
        kufi_ayah = r.get('kufi_ayah')
        counting_system = r.get('counting_system')
        boundary_type = r.get('boundary_type')
        if not (isinstance(surah, int) and isinstance(kufi_ayah, int) and counting_system and boundary_type):
            continue
        tuples.append((
            surah,
            kufi_ayah,
            str(counting_system).strip(),
            str(boundary_type).strip(),
            str(r.get('anchor_word') or '').strip(),
            str(r.get('note') or '').strip(),
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
