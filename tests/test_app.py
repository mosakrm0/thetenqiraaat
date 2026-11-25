import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import app as app_mod
import config
import db as db_mod
from services.http_client import SafeDiskCache


class TestAppRoutes(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.tmp_db = Path(self.tmpdir.name) / 'test.db'
        self.tmp_cache = SafeDiskCache(Path(self.tmpdir.name) / 'cache')

        self.db_patch = patch.object(db_mod, 'DB_PATH', self.tmp_db)
        self.cfg_db_patch = patch.object(config, 'DB_PATH', self.tmp_db)
        self.app_db_patch = patch.object(app_mod, 'DB_PATH', self.tmp_db)
        self.cache_patch = patch('services.http_client._cache', self.tmp_cache)

        self.db_patch.start()
        self.cfg_db_patch.start()
        self.app_db_patch.start()
        self.cache_patch.start()

        db_mod.init_db(self.tmp_db)
        # Pre-populate surah 1 for hafs and warsh so /api/surah/1?qiraat=hafs,warsh needs no network
        conn = db_mod.get_db_connection(self.tmp_db)
        try:
            conn.executemany(
                'INSERT OR IGNORE INTO ayahs (surah, ayah, qiraa, text) VALUES (?, ?, ?, ?)',
                [
                    (1, 1, 'hafs', 'بِسْمِ ٱللَّهِ ٱلرَّحْمَـٰنِ ٱلرَّحِيمِ'),
                    (1, 4, 'hafs', 'مَـٰلِكِ يَوْمِ ٱلدِّينِ'),
                    (1, 1, 'warsh', 'بِسْمِ اللَّهِ الرَّحْمَٰنِ الرَّحِيمِ'),
                    (1, 4, 'warsh', 'مَلِكِ يَوْمِ الدِّينِ'),
                ],
            )
            conn.commit()
        finally:
            conn.close()

        app_mod.app.config['TESTING'] = True
        app_mod.limiter.enabled = False
        self.client = app_mod.app.test_client()

    def tearDown(self):
        self.tmp_cache.close()
        self.cache_patch.stop()
        self.app_db_patch.stop()
        self.cfg_db_patch.stop()
        self.db_patch.stop()
        self.tmpdir.cleanup()

    def test_pages_return_200(self):
        for route in ('/', '/readings', '/translations', '/intro', '/feedback'):
            resp = self.client.get(route)
            self.assertEqual(resp.status_code, 200, f'{route} failed')

    def test_qiraat_endpoint_has_all_20_riwayat(self):
        resp = self.client.get('/api/qiraat')
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(len(data), 20)
        keys = [q['key'] for q in data]
        self.assertEqual(len(set(keys)), 20)
        for expected in ('hafs', 'warsh', 'qaloon', 'hisham', 'ibn_dhakwan', 'douri_kisai', 'ibn_jammaz', 'rawh', 'idris'):
            self.assertIn(expected, keys)

    def test_imams_endpoint(self):
        resp = self.client.get('/api/imams')
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(len(data), 10)

    def test_surahs_endpoint_returns_114_surahs_6236_ayahs(self):
        resp = self.client.get('/api/surahs')
        self.assertEqual(resp.status_code, 200)
        payload = resp.get_json()
        surahs = payload.get('data', [])
        self.assertEqual(len(surahs), 114)
        self.assertEqual([s['number'] for s in surahs], list(range(1, 115)))
        self.assertEqual(sum(s['numberOfAyahs'] for s in surahs), 6236)

    def test_no_emojis_in_templates_or_static_js(self):
        emoji_re = re.compile(r'[\U0001F300-\U0001FAFF\u2600-\u27BF\u25B6\u23F8\u2715\u2630\u21A9\u2709\u261D\uFE0F]')
        root = Path(config.BASE_DIR)
        files = list((root / 'templates').glob('*.html')) + list((root / 'static').glob('*.js'))
        self.assertTrue(len(files) >= 8)
        for path in files:
            text = path.read_text(encoding='utf-8')
            match = emoji_re.search(text)
            if match is not None:
                self.fail(f'Found emoji {match.group(0)!r} in {path}')

    def test_js_files_wrapped_in_iife_no_global_redeclaration(self):
        root = Path(config.BASE_DIR) / 'static'
        for name in ('common.js', 'script.js', 'translations.js'):
            text = (root / name).read_text(encoding='utf-8').strip()
            self.assertIn('(function () {', text, f'{name} must be wrapped in an IIFE')
            self.assertTrue(text.endswith('})();'), f'{name} must end with IIFE invocation')

    def test_readings_and_translations_ssr_surah_list(self):
        for route in ('/readings', '/translations'):
            resp = self.client.get(route)
            self.assertEqual(resp.status_code, 200)
            html = resp.get_data(as_text=True)
            self.assertNotIn('جاري تحميل الفهرس...', html)
            self.assertIn('window.__INITIAL_SURAHS__', html)
            self.assertIn('pickSurah(114)', html)
        readings_html = self.client.get('/readings').get_data(as_text=True)
        self.assertIn('الروايات الثماني المتوفرة رقمياً تعرض نصها العثماني الكامل', readings_html)

    def test_get_surah_with_variants_and_count_notes(self):
        resp = self.client.get('/api/surah/1?qiraat=hafs,warsh,ibn_dhakwan')
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertIn('hafs', body['data'])
        self.assertIn('warsh', body['data'])
        self.assertIn('ibn_dhakwan', body['data'])
        self.assertEqual(body['data']['warsh']['text_tier'], 'kfgqpc_full')
        self.assertEqual(body['data']['ibn_dhakwan']['ayahs'][0]['text'], 'بسم الله الرحمن الرحيم (لا تعد آية في هذه القراءة)')
        self.assertTrue(body['data']['ibn_dhakwan']['ayahs'][0]['skip_diff'])
        self.assertIsNone(body['data']['ibn_dhakwan']['ayahs'][0]['audio_ayah'])
        self.assertIn('1', body['data']['warsh']['count_notes'])
        self.assertIn('4', body['data']['hafs']['variants'])

    def test_parse_qiraat_notes_pages_handles_arabic_digits_and_riwayat(self):
        from services.qiraat import parse_qiraat_notes_pages
        notes = {'pages': [{'page': 1, 'farsh': ['٤ - (مَالِكِ): قرأ عاصم والكسائي بألف وقرأ ابن عامر وحمزة بحذفها.'], 'usul': []}]}
        pages = {'pages': [{'page': 1, 'verses': [{'chapter': 1, 'number': 4, 'text': 'مَـٰلِكِ يَوْمِ ٱلدِّينِ'}]}]}
        tuples = parse_qiraat_notes_pages(notes, pages)
        riwayat_matched = {t[2] for t in tuples}
        self.assertIn('hafs', riwayat_matched)
        self.assertIn('hisham', riwayat_matched)
        self.assertIn('khalaf_hamzah', riwayat_matched)

    def test_parse_qiraat_notes_pages_604_multi_surah_and_tatweel(self):
        from services.qiraat import parse_qiraat_notes_pages
        notes = {'pages': [{
            'page': 604,
            'farsh': [
                'سورة الإخلاص',
                '٤ـ (كفوا): حفص بضم الفاء وبالواو والباقون ويعقوب بالهمز.',
            ],
            'usul': [
                'سورةالناس',
                'امال دورى ابى عمرو الف(الناس) الخمسة.',
            ],
        }]}
        pages = {'pages': [{
            'page': 604,
            'verses': [
                {'chapter': 112, 'number': 1, 'text': 'قُلْ هُوَ اللَّهُ أَحَدٌ'},
                {'chapter': 112, 'number': 4, 'text': 'وَلَمْ يَكُن لَّهُ كُفُوًا أَحَدٌ'},
                {'chapter': 114, 'number': 1, 'text': 'قُلْ أَعُوذُ بِرَبِّ النَّاسِ'},
            ],
        }]}
        tuples = parse_qiraat_notes_pages(notes, pages)
        # Ayah 1 of 112 must have ZERO variants
        self.assertFalse(any(t[0] == 112 and t[1] == 1 for t in tuples))
        # كفوا must be on (112, 4)
        self.assertTrue(any(t[0] == 112 and t[1] == 4 and t[2] == 'hafs' for t in tuples))
        # الناس must be on (114, 1) ONLY for douri
        nas_tuples = [t for t in tuples if t[0] == 114 and t[1] == 1]
        self.assertEqual({t[2] for t in nas_tuples}, {'douri'})

    def test_surah_112_strips_bom_and_prepended_basmala_and_fatiha_aligns(self):
        conn = db_mod.get_db_connection(self.tmp_db)
        try:
            conn.executemany(
                'INSERT OR REPLACE INTO ayahs (surah, ayah, qiraa, text) VALUES (?, ?, ?, ?)',
                [
                    (1, 1, 'hafs', '\ufeffبِسْمِ ٱللَّهِ ٱلرَّحْمَـٰنِ ٱلرَّحِيمِ'),
                    (1, 4, 'hafs', 'مَـٰلِكِ يَوْمِ ٱلدِّينِ'),
                    (1, 7, 'hafs', 'صِرَٰطَ ٱلَّذِينَ أَنْعَمْتَ عَلَيْهِمْ غَيْرِ ٱلْمَغْضُوبِ عَلَيْهِمْ وَلَا ٱلضَّآلِّينَ'),
                    (1, 1, 'warsh', 'اِ۬لْحَمْدُ لِلهِ رَبِّ اِ۬لْعَٰلَمِينَ'),
                    (1, 3, 'warsh', 'مَلِكِ يَوْمِ الدِّينِ'),
                    (1, 6, 'warsh', 'صِرَٰطَ ٱلَّذِينَ أَنْعَمْتَ عَلَيْهِمْ'),
                    (1, 7, 'warsh', 'غَيْرِ ٱلْمَغْضُوبِ عَلَيْهِمْ وَلَا ٱلضَّآلِّينَ'),
                    (112, 1, 'hafs', 'بِسْمِ ٱللَّهِ ٱلرَّحْمَـٰنِ ٱلرَّحِيمِ قُلْ هُوَ ٱللَّهُ أَحَدٌ'),
                ],
            )
            conn.commit()
        finally:
            conn.close()

        r1 = self.client.get('/api/surah/1?qiraat=hafs,warsh,hisham').get_json()['data']
        self.assertFalse(r1['hafs']['ayahs'][0]['text'].startswith('\ufeff'))
        self.assertFalse(r1['hafs']['ayahs'][0]['skip_diff'])
        self.assertEqual(r1['hafs']['ayahs'][0]['audio_ayah'], 1)

        self.assertEqual(r1['warsh']['ayahs'][0]['text'], 'بسم الله الرحمن الرحيم (لا تعد آية في هذه القراءة)')
        self.assertTrue(r1['warsh']['ayahs'][0]['skip_diff'])
        self.assertIsNone(r1['warsh']['ayahs'][0]['audio_ayah'])
        self.assertEqual(r1['warsh']['ayahs'][1]['audio_ayah'], 1)
        self.assertFalse(r1['warsh']['ayahs'][1]['skip_diff'])
        self.assertIn('مَلِكِ', r1['warsh']['ayahs'][3]['text'])
        self.assertEqual(r1['warsh']['ayahs'][6]['audio_ayah'], 6)
        self.assertEqual(r1['warsh']['ayahs'][6]['audio_ayah_extra'], 7)

        self.assertEqual(r1['hisham']['ayahs'][0]['text'], 'بسم الله الرحمن الرحيم (لا تعد آية في هذه القراءة)')
        self.assertTrue(r1['hisham']['ayahs'][0]['skip_diff'])
        self.assertIsNone(r1['hisham']['ayahs'][0]['audio_ayah'])
        self.assertEqual(r1['hisham']['ayahs'][1]['audio_ayah'], 1)
        self.assertEqual(r1['hisham']['ayahs'][6]['audio_ayah'], 6)
        self.assertEqual(r1['hisham']['ayahs'][6]['audio_ayah_extra'], 7)

        r112 = self.client.get('/api/surah/112?qiraat=hafs').get_json()['data']
        self.assertTrue(r112['hafs']['ayahs'][0]['text'].startswith('قُلْ هُوَ'))

    def test_curated_seed_json_has_valid_qiraat_keys(self):
        import json
        seed_path = Path(config.BASE_DIR) / 'data' / 'qiraat_variants_seed.json'
        rows = json.loads(seed_path.read_text(encoding='utf-8'))
        for row in rows:
            self.assertIn(row['qiraa'], config.QIRAAT_BY_KEY)

    def test_get_surah_invalid_id(self):
        self.assertEqual(self.client.get('/api/surah/0').status_code, 400)
        self.assertEqual(self.client.get('/api/surah/115').status_code, 400)

    def test_audio_proxy_ssrf_and_limits(self):
        self.assertEqual(self.client.get('/api/audio-proxy').status_code, 400)
        self.assertEqual(self.client.get('/api/audio-proxy?url=http://everyayah.com/data/a.mp3').status_code, 400)
        self.assertEqual(self.client.get('/api/audio-proxy?url=https://127.0.0.1/a.mp3').status_code, 400)
        self.assertEqual(self.client.get('/api/audio-proxy?url=https://evil.example.com/a.mp3').status_code, 400)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {'Content-Length': '4', 'Content-Type': 'audio/mpeg'}
        mock_resp.iter_content.return_value = [b'ID3\x03']
        with patch('services.http_client._http_session') as mock_sess:
            mock_sess.get.return_value = mock_resp
            with patch('app.get_http_session', return_value=mock_sess):
                resp = self.client.get('/api/audio-proxy?url=https://cdn.mp3quran.net/test/001.mp3')
                self.assertEqual(resp.status_code, 200)
                self.assertEqual(resp.data, b'ID3\x03')

        # Oversized Content-Length
        big_resp = MagicMock()
        big_resp.status_code = 200
        big_resp.headers = {'Content-Length': str(60 * 1024 * 1024)}
        with patch('app.get_http_session') as mock_get_sess:
            mock_get_sess.return_value.get.return_value = big_resp
            resp = self.client.get('/api/audio-proxy?url=https://everyayah.com/data/x/001001.mp3')
            self.assertEqual(resp.status_code, 413)

    def test_responsive_markup_and_assets(self):
        for route in ('/', '/readings', '/translations', '/intro', '/feedback'):
            html = self.client.get(route).get_data(as_text=True)
            self.assertIn('viewport-fit=cover', html, f'{route} missing viewport-fit=cover')
            self.assertIn('href="/intro"', html, f'{route} missing /intro nav link')

        intro_html = self.client.get('/intro').get_data(as_text=True)
        for token in ('https://www.youtube.com/embed/EeFu2pcGobQ', 'https://www.youtube.com/watch?v=EeFu2pcGobQ', 'فيديو تعريفي', 'video-frame'):
            self.assertIn(token, intro_html, f'/intro missing {token}')

        feedback_html = self.client.get('/feedback').get_data(as_text=True)
        self.assertIn('https://github.com/mosakrm0/thetenqiraaat', feedback_html)

        for route in ('/readings', '/translations'):
            html = self.client.get(route).get_data(as_text=True)
            self.assertIn('id="sb-backdrop"', html, f'{route} missing drawer backdrop')

        root = Path(config.BASE_DIR) / 'static'
        css = (root / 'style.css').read_text(encoding='utf-8')
        for token in ('--cmp-cols', 'minmax(min(260px, 100%), 1fr)', '.sb-backdrop', '.video-frame', 'aspect-ratio: 16 / 9', 'pointer: coarse', '1024px', '900px', '768px', '480px', '360px'):
            self.assertIn(token, css, f'style.css missing responsive rule: {token}')

        common_js = (root / 'common.js').read_text(encoding='utf-8')
        for fn in ('initResponsiveShell', 'toggleSidebar', 'closeSidebarOnMobile', 'normalizeArabicSearch'):
            self.assertIn(fn, common_js, f'common.js missing {fn}')

    def test_security_headers_case_insensitive_qiraat_and_json_errors(self):
        for route in ('/', '/api/qiraat'):
            resp = self.client.get(route)
            self.assertEqual(resp.headers.get('X-Content-Type-Options'), 'nosniff')
            self.assertEqual(resp.headers.get('X-Frame-Options'), 'DENY')
            self.assertEqual(resp.headers.get('Referrer-Policy'), 'strict-origin-when-cross-origin')
            self.assertIn("default-src 'self'", resp.headers.get('Content-Security-Policy', ''))

        # Case-insensitive qiraat param
        r_upper = self.client.get('/api/surah/1?qiraat=HAFS,Warsh')
        self.assertEqual(r_upper.status_code, 200)
        self.assertIn('hafs', r_upper.get_json()['data'])
        self.assertIn('warsh', r_upper.get_json()['data'])

        # Malformed reciter returns 400 JSON, not 500
        for bad in ('qf_public:abc', 'qdc_chapter:abc', 'mp3quran:abc', 'unknown:1'):
            r_rec = self.client.get(f'/api/audio/surah-map?qiraa=hafs&surah=1&reciter={bad}')
            self.assertEqual(r_rec.status_code, 400)
            self.assertFalse(r_rec.get_json()['available'])

        # JSON 404 on /api/*
        r_404 = self.client.get('/api/does-not-exist')
        self.assertEqual(r_404.status_code, 404)
        self.assertEqual(r_404.content_type, 'application/json')

        # Max translations cap
        too_many = ','.join(f'k{i}' for i in range(config.MAX_TRANSLATIONS_PER_REQUEST + 1))
        r_cap = self.client.get(f'/api/translations/surah/1?keys={too_many}')
        self.assertEqual(r_cap.status_code, 400)

    def test_audio_proxy_blocks_redirects_html_and_bad_urls(self):
        for bad_url in (
            'https://everyayah.com:8443/data/a.mp3',
            'https://user:pass@everyayah.com/data/a.mp3',
            'https://evil-sub.mp3quran.net/index.html',
            'https://everyayah.com/../../etc/passwd',
        ):
            self.assertEqual(self.client.get(f'/api/audio-proxy?url={bad_url}').status_code, 400)

        for status, hdrs in (
            (302, {'Location': 'https://evil.com/x', 'Content-Length': '1', 'Content-Type': 'audio/mpeg'}),
            (200, {'Content-Length': '-5', 'Content-Type': 'audio/mpeg'}),
            (200, {'Content-Length': '14', 'Content-Type': 'text/html; charset=utf-8'}),
        ):
            mock_resp = MagicMock()
            mock_resp.status_code = status
            mock_resp.headers = hdrs
            mock_resp.iter_content.return_value = [b'<html>x</html>']
            with patch('app.get_http_session') as gs:
                gs.return_value.get.return_value = mock_resp
                resp = self.client.get('/api/audio-proxy?url=https://everyayah.com/data/001001.mp3')
                self.assertEqual(resp.status_code, 502)

    def test_multi_surah_alignment_and_khalaf_ashir_patterns(self):
        conn = db_mod.get_db_connection(self.tmp_db)
        try:
            conn.executemany(
                'INSERT OR REPLACE INTO ayahs (surah, ayah, qiraa, text) VALUES (?, ?, ?, ?)',
                [
                    (2, 1, 'hafs', 'بِسْمِ ٱللَّهِ ٱلرَّحْمَـٰنِ ٱلرَّحِيمِ الٓمٓ'),
                    (2, 2, 'hafs', 'ذَٰلِكَ ٱلْكِتَٰبُ لَا رَيْبَ فِيهِ هُدًى لِّلْمُتَّقِينَ'),
                    (2, 3, 'hafs', 'ٱلَّذِينَ يُؤْمِنُونَ بِٱلْغَيْبِ وَيُقِيمُونَ ٱلصَّلَوٰةَ'),
                    (2, 1, 'warsh', 'أَلَٓمِّٓ ذَٰلِكَ اَ۬لْكِتَٰبُ لَا رَيْبَ فِيهِ هُدىٗ لِّلْمُتَّقِينَ 1'),
                    (2, 2, 'warsh', 'اَ۬لذِينَ يُومِنُونَ بِالْغَيْبِ وَيُقِيمُونَ اَ۬لصَّلَوٰةَ 2'),
                ],
            )
            conn.commit()
        finally:
            conn.close()

        r2 = self.client.get('/api/surah/2?qiraat=hafs,warsh').get_json()
        self.assertEqual(r2['meta']['max_ayah'], 3)
        self.assertIn('أَلَٓمِّٓ', r2['data']['warsh']['ayahs'][0]['text'])
        self.assertIn('رَيْبَ', r2['data']['warsh']['ayahs'][1]['text'])
        self.assertIn('يُومِنُونَ', r2['data']['warsh']['ayahs'][2]['text'])

        from services.qiraat import _match_riwayat_in_note
        self.assertEqual(_match_riwayat_in_note('قرأ خلف البزار بالإمالة'), ['idris', 'ishaq'])
        self.assertEqual(_match_riwayat_in_note('وافق العاشر حفصا'), ['hafs', 'idris', 'ishaq'])

    def test_frontend_security_and_accessibility_invariants(self):
        root = Path(config.BASE_DIR)
        tr_js = (root / 'static' / 'translations.js').read_text(encoding='utf-8')
        self.assertNotIn('onclick="removeSelected(', tr_js)
        self.assertIn('loadTicket', tr_js)
        self.assertIn('normalizeArabicSearch', tr_js)

        sc_js = (root / 'static' / 'script.js').read_text(encoding='utf-8')
        self.assertNotIn('onchange="onReciterChange(', sc_js)
        self.assertIn('normalizeArabicSearch', sc_js)

        for tpl in ('readings.html', 'translations.html', 'intro.html'):
            html = (root / 'templates' / tpl).read_text(encoding='utf-8')
            self.assertIn('<main id="content">', html)
            self.assertIn('<h1 class="tb-name"', html)

        css = (root / 'static' / 'style.css').read_text(encoding='utf-8')
        self.assertIn(':focus:not(:focus-visible)', css)


if __name__ == '__main__':
    unittest.main()
