import json
import logging

import requests
from flask import Flask, Response, jsonify, render_template, request
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from config import (
    ALLOWED_AUDIO_HOSTS,
    DATA_DIR,
    DB_PATH,
    IMAMS,
    KFGQPC_JSON_URLS,
    MAX_AUDIO_PROXY_BYTES,
    QIRAAT,
    QIRAAT_BY_KEY,
    RATELIMIT_STORAGE_URI,
    REQUEST_TIMEOUT,
)
from db import get_db_connection, init_db
from services.audio import (
    everyayah_ayah_count_for_surah,
    everyayah_build_ayah_url,
    list_reciters_for_qiraa,
    qf_get_ayah_audio_url,
    qf_is_enabled,
    qf_pick_recitation_for_qiraa,
    qf_public_get_chapter_audio_map,
    resolve_surah_audio,
)
from services.http_client import get_http_session, is_allowed_audio_url
from services.qiraat import (
    fetch_external_and_store,
    get_surah_count_notes,
    get_surah_variants,
)
from services.translations import (
    everyayah_find_track,
    everyayah_translation_tracks,
    fetch_translations_for_surah,
    unified_translations_catalog,
)

logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)
limiter = Limiter(
    get_remote_address,
    app=app,
    storage_uri=RATELIMIT_STORAGE_URI,
)

# Re-export symbols for backward compatibility (e.g. seed_db.py, Dockerfile, tests)
__all__ = [
    'app',
    'init_db',
    'QIRAAT',
    'DB_PATH',
    'KFGQPC_JSON_URLS',
    'ALLOWED_AUDIO_HOSTS',
    'is_allowed_audio_url',
]


# ── pages ──────────────────────────────────────────────────────────────────────
@app.route('/')
def home_page():
    return render_template('index.html')


@app.route('/readings')
def readings_page():
    return render_template('readings.html', surahs=_load_surahs_list())


@app.route('/translations')
def translations_page():
    return render_template('translations.html', surahs=_load_surahs_list())


@app.route('/feedback')
def feedback_page():
    return render_template('feedback.html')


_SURAHS_CACHE: list[dict] | None = None


def _load_surahs_list() -> list[dict]:
    global _SURAHS_CACHE
    if _SURAHS_CACHE is not None:
        return _SURAHS_CACHE
    path = DATA_DIR / 'surahs.json'
    _SURAHS_CACHE = json.loads(path.read_text(encoding='utf-8'))
    return _SURAHS_CACHE


# ── qiraat API ─────────────────────────────────────────────────────────────────
@app.route('/api/surahs')
def get_surahs():
    """Return all 114 canonical Surahs locally with zero external network dependency."""
    return jsonify({'data': _load_surahs_list()})


@app.route('/api/qiraat')
def get_qiraat():
    """Expose the canonical QIRAAT list (all 20 riwayat) so the frontend stays in sync."""
    return jsonify(QIRAAT)


@app.route('/api/imams')
def get_imams():
    """Expose the 10 Imams grouping metadata."""
    return jsonify(IMAMS)


@app.route('/api/surah/<int:surah_id>')
@limiter.limit('60 per minute')
def get_surah(surah_id):
    if surah_id < 1 or surah_id > 114:
        return jsonify({'error': 'Invalid Surah'}), 400

    q_param = (request.args.get('qiraat') or '').strip()
    if q_param:
        requested_keys = [k.strip().lower() for k in q_param.split(',') if k.strip() in QIRAAT_BY_KEY]
        if not requested_keys:
            return jsonify({'error': 'No valid qiraat keys requested'}), 400
    else:
        requested_keys = [q['key'] for q in QIRAAT]

    requested_set = set(requested_keys)

    conn = get_db_connection()
    try:
        c = conn.cursor()
        c.execute('SELECT DISTINCT qiraa FROM ayahs WHERE surah = ?', (surah_id,))
        existing_keys = {row['qiraa'] for row in c.fetchall()}
        missing_keys = sorted(requested_set - existing_keys)

        fetch_status = {key: {'fetch_status': 'cached', 'error': None} for key in (existing_keys & requested_set)}
        if missing_keys:
            fetch_status.update(fetch_external_and_store(surah_id, conn, missing_keys))

        c.execute('SELECT ayah, qiraa, text FROM ayahs WHERE surah = ? ORDER BY ayah', (surah_id,))
        rows = c.fetchall()

        variants_map = get_surah_variants(conn, surah_id, requested_keys)
        count_notes_map = get_surah_count_notes(conn, surah_id, requested_keys)
    finally:
        conn.close()

    data: dict[str, dict[int, str]] = {}
    for r in rows:
        if r['qiraa'] in requested_set:
            data.setdefault(r['qiraa'], {})[r['ayah']] = r['text']

    max_ayah = max((max(m) for m in data.values() if m), default=0)

    result = {}
    for q in QIRAAT:
        key = q['key']
        if key not in requested_set:
            continue
        ayahs = data.get(key, {})
        arr = [{'text': ayahs.get(i, '(النص غير متاح)')} for i in range(1, max_ayah + 1)]
        q_status = fetch_status.get(key, {'fetch_status': 'unavailable', 'error': None})
        if not ayahs and q_status['fetch_status'] == 'cached':
            q_status = {'fetch_status': 'unavailable', 'error': None}

        q_variants = variants_map.get(key, {})
        q_count_notes = count_notes_map.get(key, {})

        result[key] = {
            'ayahs':           arr,
            'fallback':        bool(q.get('fallback', False)),
            'text_tier':       q.get('textTier', 'hafs_fallback'),
            'font_family':     q.get('fontFamily', "'Amiri Quran','Amiri',serif"),
            'counting_system': q.get('countingSystem', 'kufi'),
            'fetch_status':    q_status['fetch_status'],
            'error':           q_status['error'],
            'variants':        {str(k): v for k, v in q_variants.items()},
            'count_notes':     {str(k): v for k, v in q_count_notes.items()},
        }

    return jsonify({'data': result, 'meta': {'surah': surah_id, 'max_ayah': max_ayah}})


# ── translations API ───────────────────────────────────────────────────────────
@app.route('/api/translations/catalog')
def translations_catalog():
    return jsonify({'available': True, 'items': unified_translations_catalog()})


@app.route('/api/translations/surah/<int:surah_id>')
@limiter.limit('60 per minute')
def translations_surah(surah_id):
    if surah_id < 1 or surah_id > 114:
        return jsonify({'error': 'Invalid Surah'}), 400

    keys_q = (request.args.get('keys') or '').strip()
    req_keys = []
    seen = set()
    for x in keys_q.split(','):
        k = x.strip()
        if k and k not in seen:
            seen.add(k)
            req_keys.append(k)
    if not req_keys:
        req_keys = ['hafs_ar_text']

    result, max_ayah = fetch_translations_for_surah(surah_id, req_keys)
    return jsonify({'available': True, 'meta': {'surah': surah_id, 'max_ayah': max_ayah}, 'data': result})


@app.route('/api/translations/everyayah')
def everyayah_translations_catalog():
    try:
        tracks = everyayah_translation_tracks()
    except Exception as exc:
        logger.warning('EveryAyah catalog fetch failed: %s', exc)
        return jsonify({'available': False, 'error': 'Failed to fetch EveryAyah catalog'}), 502

    return jsonify({
        'available': True,
        'tracks':    tracks,
        'baseline':  {
            'key':     'hafs_ar_text',
            'name':    'العربية - حفص (نص)',
            'source':  'alquran',
            'edition': 'quran-uthmani',
            'mode':    'ayah-text',
        },
    })


@app.route('/api/translations/everyayah/ayah')
def everyayah_translation_ayah_url():
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
        'url':       url,
        'source':    'everyayah',
        'track':     {
            'trackId':   track['trackId'],
            'name':      track['name'],
            'subfolder': track['subfolder'],
        },
    })


@app.route('/api/translations/everyayah/surah-map')
def everyayah_translation_surah_map():
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
        'available':  True,
        'source':     'everyayah',
        'track':      {
            'trackId':   track['trackId'],
            'name':      track['name'],
            'subfolder': track['subfolder'],
        },
        'ayah_count': ayah_count,
        'ayah_map':   ayah_map,
    })


# ── audio API ──────────────────────────────────────────────────────────────────
@app.route('/api/audio/reciters')
def audio_reciters():
    qiraa_key = (request.args.get('qiraa') or '').strip().lower()
    try:
        surah_id = int(request.args.get('surah') or 1)
    except (TypeError, ValueError):
        return jsonify({'available': False, 'error': 'Invalid surah'}), 400

    if surah_id < 1 or surah_id > 114:
        return jsonify({'available': False, 'error': 'Invalid surah'}), 400
    if qiraa_key not in QIRAAT_BY_KEY:
        return jsonify({'available': False, 'error': 'Invalid qiraa'}), 400

    reciters = list_reciters_for_qiraa(qiraa_key, surah_id)
    return jsonify({
        'available': bool(reciters),
        'qiraa':     qiraa_key,
        'surah':     surah_id,
        'reciters':  reciters,
    })


@app.route('/api/audio/surah-map')
def surah_audio_map():
    """
    Return the full surah audio map using the 4-tier resolver:
      - mode='ayah'        -> ayah_map: {ayah: url}
      - mode='timed-surah' -> surah_url + timings: {ayah: {start_ms, end_ms}}
      - mode='surah'       -> surah_url
    """
    qiraa_key = (request.args.get('qiraa') or '').strip().lower()
    reciter_id = (request.args.get('reciter') or '').strip() or None
    try:
        surah_id = int(request.args.get('surah'))
    except (TypeError, ValueError):
        return jsonify({'available': False, 'error': 'Invalid surah'}), 400

    if surah_id < 1 or surah_id > 114:
        return jsonify({'available': False, 'error': 'Invalid surah'}), 400
    if qiraa_key not in QIRAAT_BY_KEY:
        return jsonify({'available': False, 'error': 'Invalid qiraa'}), 400

    res = resolve_surah_audio(qiraa_key, surah_id, reciter_id=reciter_id)
    return jsonify(res)


@app.route('/api/audio/ayah')
def ayah_audio():
    qiraa_key = (request.args.get('qiraa') or '').strip().lower()
    try:
        surah_id = int(request.args.get('surah'))
        ayah_id = int(request.args.get('ayah'))
    except (TypeError, ValueError):
        return jsonify({'available': False, 'error': 'Invalid surah/ayah'}), 400

    if surah_id < 1 or surah_id > 114 or ayah_id < 1:
        return jsonify({'available': False, 'error': 'Invalid surah/ayah'}), 400
    if qiraa_key not in QIRAAT_BY_KEY:
        return jsonify({'available': False, 'error': 'Invalid qiraa'}), 400

    q = QIRAAT_BY_KEY[qiraa_key]
    if q.get('qfPublicId'):
        try:
            ayah_map = qf_public_get_chapter_audio_map(surah_id, q['qfPublicId'])
            url = ayah_map.get(ayah_id)
            if url:
                return jsonify({'available': True, 'url': url, 'source': 'qf_public'})
        except Exception as exc:
            logger.warning('QF public audio error for %s %s:%s: %s', qiraa_key, surah_id, ayah_id, exc)

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


@app.route('/api/audio-proxy')
@limiter.limit('60 per minute; 5 per second')
def audio_proxy():
    url = request.args.get('url', '').strip()
    if not url:
        return jsonify({'error': 'Missing url parameter'}), 400
    if not is_allowed_audio_url(url):
        return jsonify({'error': 'URL not allowed'}), 400

    req_headers = {}
    range_hdr = request.headers.get('Range')
    if range_hdr:
        req_headers['Range'] = range_hdr

    session = get_http_session()
    try:
        upstream = session.get(
            url,
            headers=req_headers,
            stream=True,
            timeout=REQUEST_TIMEOUT,
            allow_redirects=False,
        )
    except requests.RequestException as exc:
        logger.warning('Audio proxy fetch failed: %s', exc)
        return jsonify({'error': 'Upstream fetch failed'}), 502

    if upstream.status_code >= 400:
        status = upstream.status_code
        upstream.close()
        return jsonify({'error': f'Upstream HTTP {status}'}), 502

    content_length = upstream.headers.get('Content-Length')
    if content_length is None:
        upstream.close()
        return jsonify({'error': 'Upstream Content-Length is required'}), 413
    try:
        content_length_n = int(content_length)
    except (TypeError, ValueError):
        upstream.close()
        return jsonify({'error': 'Invalid upstream Content-Length'}), 502
    if content_length_n > MAX_AUDIO_PROXY_BYTES:
        upstream.close()
        return jsonify({'error': 'Upstream content too large'}), 413

    def generate():
        bytes_read = 0
        try:
            for chunk in upstream.iter_content(chunk_size=64 * 1024):
                if chunk:
                    bytes_read += len(chunk)
                    if bytes_read > MAX_AUDIO_PROXY_BYTES:
                        break
                    yield chunk
        finally:
            upstream.close()

    content_type = upstream.headers.get('Content-Type', 'audio/mpeg')
    headers = {
        'Content-Type':   content_type,
        'Content-Length': str(content_length_n),
        'Cache-Control':  'public, max-age=3600',
    }
    if upstream.headers.get('Content-Range'):
        headers['Content-Range'] = upstream.headers['Content-Range']
    if upstream.headers.get('Accept-Ranges'):
        headers['Accept-Ranges'] = upstream.headers['Accept-Ranges']

    return Response(generate(), status=upstream.status_code, headers=headers)


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
    if qiraa not in QIRAAT_BY_KEY:
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
    return jsonify({
        'available':     True,
        'recitation_id': choice['id'],
        'reciter':       choice['name'],
        'source':        'quran_foundation',
    })


@app.route('/api/qf/ayah-url')
def qf_ayah_url():
    qiraa = (request.args.get('qiraa') or '').strip().lower()
    try:
        surah_id = int(request.args.get('surah'))
        ayah_id = int(request.args.get('ayah'))
    except (TypeError, ValueError):
        return jsonify({'available': False, 'error': 'Invalid surah/ayah'}), 400
    if surah_id < 1 or surah_id > 114 or ayah_id < 1:
        return jsonify({'available': False, 'error': 'Invalid surah/ayah'}), 400
    if qiraa not in QIRAAT_BY_KEY:
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
    return jsonify({
        'available': True,
        'url':       url,
        'reciter':   choice['name'] if choice else None,
        'source':    'quran_foundation',
    })


if __name__ == '__main__':
    init_db()
    app.run(debug=False, port=7860)
