import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import diskcache

import app as app_mod
import config
import db as db_mod


class TestAppRoutes(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.tmp_db = Path(self.tmpdir.name) / 'test.db'
        self.tmp_cache = diskcache.Cache(str(Path(self.tmpdir.name) / 'cache'))

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
        for route in ('/', '/readings', '/translations', '/feedback'):
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

    def test_get_surah_with_variants_and_count_notes(self):
        resp = self.client.get('/api/surah/1?qiraat=hafs,warsh')
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertIn('hafs', body['data'])
        self.assertIn('warsh', body['data'])
        self.assertEqual(body['data']['warsh']['text_tier'], 'kfgqpc_full')
        self.assertIn('1', body['data']['warsh']['count_notes'])
        self.assertIn('4', body['data']['hafs']['variants'])

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


if __name__ == '__main__':
    unittest.main()
