import gzip
import json
import logging
import re

import requests
from flask import Flask, Response, jsonify, render_template, request
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.middleware.proxy_fix import ProxyFix

from config import (
    ALLOWED_AUDIO_HOSTS,
    DATA_DIR,
    DB_PATH,
    IMAMS,
    KFGQPC_JSON_URLS,
    MAX_AUDIO_PROXY_BYTES,
    MAX_TRANSLATIONS_PER_REQUEST,
    QIRAAT,
    QIRAAT_BY_KEY,
    RATELIMIT_STORAGE_URI,
    REQUEST_TIMEOUT,
    TRUST_PROXY_COUNT,
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
app.json.sort_keys = False
if TRUST_PROXY_COUNT > 0:
    app.wsgi_app = ProxyFix(
        app.wsgi_app,
        x_for=TRUST_PROXY_COUNT,
        x_proto=TRUST_PROXY_COUNT,
        x_host=TRUST_PROXY_COUNT,
    )
limiter = Limiter(
    get_remote_address,
    app=app,
    storage_uri=RATELIMIT_STORAGE_URI,
)

_CSP_POLICY = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline'; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdn.jsdelivr.net; "
    "font-src 'self' data: https://fonts.gstatic.com https://cdn.jsdelivr.net; "
    "img-src 'self' data: https:; "
    "media-src 'self' https: blob: data:; "
    "frame-src https://www.youtube.com https://www.youtube-nocookie.com; "
    "connect-src 'self'; "
    "object-src 'none'; "
    "base-uri 'self'; "
    "frame-ancestors 'none'"
)
_COMPRESSIBLE_PREFIXES = ('application/json', 'text/', 'application/javascript')


@app.after_request
def _apply_security_and_compression(response: Response) -> Response:
    response.headers.setdefault('X-Content-Type-Options', 'nosniff')
    response.headers.setdefault('X-Frame-Options', 'DENY')
    response.headers.setdefault('Referrer-Policy', 'strict-origin-when-cross-origin')
    response.headers.setdefault('Permissions-Policy', 'camera=(), microphone=(), geolocation=()')
    response.headers.setdefault('Content-Security-Policy', _CSP_POLICY)

    if (
        not response.direct_passthrough
        and response.status_code == 200
        and 'Content-Encoding' not in response.headers
        and 'gzip' in (request.headers.get('Accept-Encoding') or '').lower()
    ):
        ct = (response.content_type or '').split(';', 1)[0].strip().lower()
        if any(ct.startswith(p) for p in _COMPRESSIBLE_PREFIXES):
            raw = response.get_data()
            if len(raw) >= 1024:
                compressed = gzip.compress(raw, compresslevel=6)
                if len(compressed) < len(raw):
                    response.set_data(compressed)
                    response.headers['Content-Encoding'] = 'gzip'
                    response.headers['Content-Length'] = str(len(compressed))
                    vary = response.headers.get('Vary')
                    if vary:
                        if 'accept-encoding' not in vary.lower():
                            response.headers['Vary'] = f'{vary}, Accept-Encoding'
                    else:
                        response.headers['Vary'] = 'Accept-Encoding'
    return response


@app.errorhandler(404)
def _handle_404(err):
    if request.path.startswith('/api/'):
        return jsonify({'error': 'Not found'}), 404
    return err


@app.errorhandler(429)
def _handle_429(err):
    if request.path.startswith('/api/'):
        return jsonify({'error': 'Rate limit exceeded'}), 429
    return err


@app.errorhandler(500)
def _handle_500(err):
    if request.path.startswith('/api/'):
        return jsonify({'error': 'Internal server error'}), 500
    return err

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


def _norm_basmala_word(w: str) -> str:
    s = re.sub(r'[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06ED\u0640]', '', w)
    return s.replace('ٱ', 'ا').replace('أ', 'ا').replace('إ', 'ا')


def _clean_ayah_text(surah_id: int, ayah_num: int, text: str, strip_basmala: bool = False) -> str:
    s = str(text or '').lstrip('\ufeff').strip()
    if strip_basmala and ayah_num == 1 and surah_id not in (1, 9):
        words = s.split()
        if len(words) > 4 and [_norm_basmala_word(w) for w in words[:4]] == ['بسم', 'الله', 'الرحمن', 'الرحيم']:
            s = ' '.join(words[4:]).strip()
    return s


def _align_fatiha_ayahs(ayahs: dict[int, str]) -> dict[int, str]:
    """
    Align non-Kufi Al-Fatiha (where Ayah 1 starts with الحمد, not Basmala)
    to the 7-slot Kufi index so verses line up 1-to-1 with Hafs.
    """
    a1 = str(ayahs.get(1) or '')
    a1_clean = re.sub(r'[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06ED\u0640]', '', a1)
    if not a1_clean or 'الحمد' not in a1_clean:
        return ayahs
    aligned = {
        1: 'بسم الله الرحمن الرحيم (لا تعد آية في هذه القراءة)',
        2: ayahs.get(1, ''),
        3: ayahs.get(2, ''),
        4: ayahs.get(3, ''),
        5: ayahs.get(4, ''),
        6: ayahs.get(5, ''),
    }
    p6 = (ayahs.get(6) or '').strip()
    p7 = (ayahs.get(7) or '').strip()
    aligned[7] = f'{p6} {p7}'.strip()
    return aligned


_VERSE_ORNAMENT_RE = re.compile(r'^[\u00A0\s٠-٩0-9۞۩]+$')


def _skel_word(word: str) -> str:
    s = re.sub(r'[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06ED\u0640\u00A0\u200C\u200D\ufeff]', '', word)
    s = re.sub(r'[٠-٩0-9۞۩]+', '', s)
    s = s.replace('ٱ', 'ا').replace('أ', 'ا').replace('إ', 'ا').replace('آ', 'ا')
    s = s.replace('ى', 'ي').replace('ة', 'ه').replace('ؤ', 'و').replace('ئ', 'ي').replace('ء', '')
    return re.sub(r'[^ا-ي]', '', s)


def _align_surah_to_kufi(hafs_cleaned: dict[int, str], q_cleaned: dict[int, str]) -> dict[int, dict] | None:
    """
    Align a non-Kufi surah (surah_id > 1) onto Kufi ayah slots using monotonic
    skeleton-token boundary matching, preserving original ayah numbers for audio.
    """
    kufi_nums = sorted(hafs_cleaned)
    n_kufi = len(kufi_nums)
    if n_kufi < 2 or len(q_cleaned) < 2:
        return None

    h_slots: list[list[str]] = []
    h_cum_chars: list[int] = []
    total_h_chars = 0
    for k in kufi_nums:
        skels = [s for s in (_skel_word(w) for w in hafs_cleaned[k].split()) if s]
        h_slots.append(skels)
        total_h_chars += sum(len(s) for s in skels)
        h_cum_chars.append(total_h_chars)
    if total_h_chars == 0:
        return None

    q_tokens: list[tuple[str, str, int]] = []
    for orig_ayah in sorted(q_cleaned):
        raw_words = q_cleaned[orig_ayah].split()
        # Drop trailing verse-number ornament token if present
        while raw_words and _VERSE_ORNAMENT_RE.match(raw_words[-1]):
            raw_words.pop()
        for w in raw_words:
            sk = _skel_word(w)
            if sk:
                q_tokens.append((w, sk, orig_ayah))
            elif q_tokens:
                # Attach standalone pause/ornament mark to previous token so it stays with its verse
                prev_w, prev_sk, prev_a = q_tokens[-1]
                q_tokens[-1] = (f'{prev_w} {w}', prev_sk, prev_a)

    n_q = len(q_tokens)
    if n_q < n_kufi:
        return None

    q_cum_chars = [0] * (n_q + 1)
    for idx, (_, sk, _) in enumerate(q_tokens):
        q_cum_chars[idx + 1] = q_cum_chars[idx] + len(sk)
    total_q_chars = q_cum_chars[n_q]
    if total_q_chars == 0:
        return None

    def _sim(a: str, b: str) -> int:
        if not a or not b:
            return 0
        if a == b:
            return 4
        if len(a) >= 2 and len(b) >= 2 and (a in b or b in a):
            return 2
        if a[:2] == b[:2]:
            return 1
        return 0

    splits = [0]
    pos = 0
    q_char_idx = 0
    for i in range(n_kufi - 1):
        target_q_chars = (h_cum_chars[i] / total_h_chars) * total_q_chars
        while q_char_idx < n_q and q_cum_chars[q_char_idx] < target_q_chars:
            q_char_idx += 1

        lo = max(pos + 1, q_char_idx - 25)
        hi = min(n_q - (n_kufi - 1 - i), q_char_idx + 25)
        if lo > hi:
            lo = pos + 1
            hi = lo

        h_end = h_slots[i][-3:]
        h_next = h_slots[i + 1][:3]
        best_idx = lo
        best_score = -10**9

        for cand in range(lo, hi + 1):
            score = 0
            # Match end of current Kufi ayah
            for back in range(1, min(len(h_end), cand - pos) + 1):
                score += _sim(h_end[-back], q_tokens[cand - back][1]) * (4 - back)
            # Match start of next Kufi ayah
            for fwd in range(min(len(h_next), n_q - cand)):
                score += _sim(h_next[fwd], q_tokens[cand + fwd][1]) * (3 - fwd)
            # Small tie-breaker bonus at original KFGQPC ayah boundaries
            if q_tokens[cand - 1][2] != q_tokens[cand][2]:
                score += 1
            # Gentle distance penalty from expected character ratio
            score -= abs(cand - q_char_idx) * 0.05
            if score > best_score:
                best_score = score
                best_idx = cand

        splits.append(best_idx)
        pos = best_idx

    splits.append(n_q)

    aligned: dict[int, dict] = {}
    for i, kufi_ayah in enumerate(kufi_nums):
        s_idx, e_idx = splits[i], splits[i + 1]
        chunk = q_tokens[s_idx:e_idx]
        if not chunk:
            return None
        text = ' '.join(t[0] for t in chunk).strip()
        orig_ayahs: list[int] = []
        for _, _, oa in chunk:
            if not orig_ayahs or orig_ayahs[-1] != oa:
                orig_ayahs.append(oa)
        slot: dict = {
            'text':       text,
            'audio_ayah': orig_ayahs[0],
        }
        if len(orig_ayahs) > 1:
            slot['audio_ayah_extra'] = orig_ayahs[-1]
        aligned[kufi_ayah] = slot
    return aligned


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


@app.route('/intro')
def intro_page():
    return render_template('intro.html')


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
        requested_keys = [
            k for k in (x.strip().lower() for x in q_param.split(','))
            if k in QIRAAT_BY_KEY
        ]
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

        # Ensure 'hafs' is available for fallback riwayat and cross-qiraa verse alignment
        need_hafs = any(
            (QIRAAT_BY_KEY[k].get('fallback') and k not in existing_keys)
            or (QIRAAT_BY_KEY[k].get('countingSystem') != 'kufi')
            for k in requested_set
        )
        keys_to_ensure = {
            k for k in requested_set
            if not QIRAAT_BY_KEY[k].get('fallback')
        }
        if need_hafs:
            keys_to_ensure.add('hafs')

        missing_keys = sorted(keys_to_ensure - existing_keys)
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
        if r['qiraa'] in requested_set or r['qiraa'] == 'hafs':
            data.setdefault(r['qiraa'], {})[r['ayah']] = r['text']

    hafs_ayahs = data.get('hafs', {})
    hafs_cleaned = {
        i: _clean_ayah_text(surah_id, i, t, strip_basmala=True)
        for i, t in hafs_ayahs.items()
    }
    hafs_status = fetch_status.get('hafs', {'fetch_status': 'cached' if hafs_ayahs else 'unavailable', 'error': None})

    base_max_ayah = max(hafs_ayahs) if hafs_ayahs else max((max(m) for m in data.values() if m), default=0)

    result = {}
    max_ayah = base_max_ayah
    for q in QIRAAT:
        key = q['key']
        if key not in requested_set:
            continue
        ayahs = data.get(key, {})
        if not ayahs and q.get('fallback') and hafs_ayahs:
            ayahs = hafs_ayahs
            q_status = {'fetch_status': hafs_status['fetch_status'], 'error': hafs_status['error']}
        else:
            q_status = fetch_status.get(key, {'fetch_status': 'unavailable', 'error': None})
            if not ayahs and q_status['fetch_status'] == 'cached':
                q_status = {'fetch_status': 'unavailable', 'error': None}

        strip_basmala = (key == 'hafs' or bool(q.get('fallback')))
        cleaned = {
            i: _clean_ayah_text(surah_id, i, t, strip_basmala=strip_basmala)
            for i, t in ayahs.items()
        }
        a1_raw = str(cleaned.get(1) or '')
        a1_plain = re.sub(r'[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06ED\u0640]', '', a1_raw)
        is_non_kufi_fatiha = (
            surah_id == 1
            and (
                q.get('countingSystem') not in ('kufi', 'makki')
                or ('الحمد' in a1_plain)
            )
        )
        if surah_id == 1 and not q.get('fallback') and key != 'hafs':
            cleaned = _align_fatiha_ayahs(cleaned)
        if is_non_kufi_fatiha:
            cleaned[1] = 'بسم الله الرحمن الرحيم (لا تعد آية في هذه القراءة)'

        kufi_aligned: dict[int, dict] | None = None
        if (
            surah_id > 1
            and not q.get('fallback')
            and key != 'hafs'
            and q.get('countingSystem') != 'kufi'
            and len(hafs_cleaned) >= 2
            and len(cleaned) >= 2
            and len(cleaned) != len(hafs_cleaned)
        ):
            kufi_aligned = _align_surah_to_kufi(hafs_cleaned, cleaned)

        if kufi_aligned is not None:
            local_max = max(kufi_aligned)
            max_ayah = max(max_ayah, local_max)
            arr = [
                {
                    'text':       kufi_aligned[i]['text'],
                    'skip_diff':  False,
                    'audio_ayah': kufi_aligned[i]['audio_ayah'],
                    **({'audio_ayah_extra': kufi_aligned[i]['audio_ayah_extra']} if 'audio_ayah_extra' in kufi_aligned[i] else {}),
                }
                if i in kufi_aligned else
                {'text': '(النص غير متاح)', 'skip_diff': False, 'audio_ayah': i}
                for i in range(1, base_max_ayah + 1)
            ]
        else:
            local_max = max(cleaned, default=0)
            max_ayah = max(max_ayah, local_max)
            arr = []
            for i in range(1, max(base_max_ayah, local_max) + 1):
                item = {
                    'text': cleaned.get(i, '(النص غير متاح)'),
                    'skip_diff': False,
                    'audio_ayah': i,
                }
                if is_non_kufi_fatiha:
                    if i == 1:
                        item['skip_diff'] = True
                        item['audio_ayah'] = None
                    else:
                        item['audio_ayah'] = i - 1
                        if i == 7:
                            item['audio_ayah_extra'] = 7
                arr.append(item)

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
@limiter.limit('30 per minute')
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
    if len(req_keys) > MAX_TRANSLATIONS_PER_REQUEST:
        return jsonify({'error': f'Maximum {MAX_TRANSLATIONS_PER_REQUEST} translations per request'}), 400

    result, max_ayah = fetch_translations_for_surah(surah_id, req_keys)
    return jsonify({'available': True, 'meta': {'surah': surah_id, 'max_ayah': max_ayah}, 'data': result})


@app.route('/api/translations/everyayah')
@limiter.limit('30 per minute')
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
@limiter.limit('120 per minute')
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
@limiter.limit('60 per minute')
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
_VALID_RECITER_RE = re.compile(r'^(?:quranpedia|everyayah|qf_public|qdc_chapter|mp3quran):\d+$')
_VALID_RANGE_RE = re.compile(r'^bytes=\d*-\d*(?:,\s*\d*-\d*)*$')
_ALLOWED_AUDIO_MIME_PREFIXES = (
    'audio/',
)
_COERCE_OCTET_MIME = 'application/octet-stream'


@app.route('/api/audio/reciters')
@limiter.limit('60 per minute')
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
@limiter.limit('60 per minute')
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
    if reciter_id is not None and not _VALID_RECITER_RE.match(reciter_id):
        return jsonify({'available': False, 'error': 'Invalid reciter'}), 400

    res = resolve_surah_audio(qiraa_key, surah_id, reciter_id=reciter_id)
    return jsonify(res)


@app.route('/api/audio/ayah')
@limiter.limit('120 per minute')
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
    range_hdr = (request.headers.get('Range') or '').strip()
    if range_hdr and _VALID_RANGE_RE.match(range_hdr):
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

    if upstream.status_code not in (200, 206):
        status = upstream.status_code
        upstream.close()
        return jsonify({'error': f'Upstream HTTP {status}'}), 502

    content_length = upstream.headers.get('Content-Length')
    content_length_n: int | None = None
    if content_length is not None:
        try:
            content_length_n = int(content_length)
        except (TypeError, ValueError):
            upstream.close()
            return jsonify({'error': 'Invalid upstream Content-Length'}), 502
        if content_length_n <= 0:
            upstream.close()
            return jsonify({'error': 'Invalid upstream Content-Length'}), 502
        if content_length_n > MAX_AUDIO_PROXY_BYTES:
            upstream.close()
            return jsonify({'error': 'Upstream content too large'}), 413

    raw_ct = (upstream.headers.get('Content-Type') or 'audio/mpeg').split(';', 1)[0].strip().lower()
    if raw_ct == _COERCE_OCTET_MIME:
        safe_ct = 'audio/mpeg'
    elif any(raw_ct.startswith(p) for p in _ALLOWED_AUDIO_MIME_PREFIXES):
        safe_ct = raw_ct
    else:
        upstream.close()
        return jsonify({'error': 'Upstream returned non-audio content'}), 502

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

    headers = {
        'Content-Type':            safe_ct,
        'Cache-Control':           'public, max-age=3600',
        'X-Content-Type-Options':  'nosniff',
        'Content-Security-Policy': "default-src 'none'; sandbox",
        'Content-Disposition':     'inline',
    }
    if content_length_n is not None:
        headers['Content-Length'] = str(content_length_n)
    if upstream.headers.get('Content-Range'):
        headers['Content-Range'] = upstream.headers['Content-Range']
    if upstream.headers.get('Accept-Ranges'):
        headers['Accept-Ranges'] = upstream.headers['Accept-Ranges']

    return Response(generate(), status=upstream.status_code, headers=headers)


# ── legacy private QF endpoints (kept for backwards compat) ───────────────────
@app.route('/api/qf/source')
@limiter.limit('60 per minute')
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
@limiter.limit('60 per minute')
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
