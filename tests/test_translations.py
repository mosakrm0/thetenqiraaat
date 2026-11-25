import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from services import translations as tr_svc
from services.http_client import SafeDiskCache


class TestTranslationsService(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.cache = SafeDiskCache(Path(self.tmpdir.name) / 'cache')
        self.c1 = patch('services.translations.get_cache', return_value=self.cache)
        self.c2 = patch('services.audio.get_cache', return_value=self.cache)
        self.c1.start()
        self.c2.start()

    def tearDown(self):
        self.c2.stop()
        self.c1.stop()
        self.cache.close()
        self.tmpdir.cleanup()

    def test_catalog_includes_text_only_and_audio_backed(self):
        self.cache.set('everyayah_recitations', {
            'ayahCount': [7],
            '45': {'subfolder': 'translations/English/Sahih', 'name': 'English Translation'},
        }, expire=3600)
        self.cache.set('alquran_translations', [
            {'key': 'alquran:en.sahih', 'source': 'alquran', 'edition': 'en.sahih', 'name': 'Sahih', 'englishName': 'Sahih', 'language': 'en', 'direction': 'ltr', 'mode': 'ayah-text'},
            {'key': 'alquran:fr.hamidullah', 'source': 'alquran', 'edition': 'fr.hamidullah', 'name': 'Hamidullah', 'englishName': 'Hamidullah', 'language': 'fr', 'direction': 'ltr', 'mode': 'ayah-text'},
        ], expire=3600)
        self.cache.set('fawaz_editions_v2', [], expire=3600)

        with patch('services.translations.get_http_session') as mock_sess:
            mock_sess.return_value.get.side_effect = AssertionError('Network should not be called')
            items = tr_svc.unified_translations_catalog()
        keys = {x['key']: x for x in items}
        self.assertIn('hafs_ar_text', keys)
        self.assertIn('alquran:en.sahih', keys)
        self.assertIn('alquran:fr.hamidullah', keys)
        self.assertTrue(keys['alquran:en.sahih']['has_audio'])
        self.assertFalse(keys['alquran:fr.hamidullah']['has_audio'])

    def test_fetch_translations_allows_multiple_editions_same_language(self):
        self.cache.set('everyayah_recitations', {'ayahCount': [7]}, expire=3600)
        self.cache.set('alquran_translations', [
            {'key': 'alquran:en.sahih', 'source': 'alquran', 'edition': 'en.sahih', 'name': 'Sahih', 'englishName': 'Sahih', 'language': 'en', 'direction': 'ltr', 'mode': 'ayah-text'},
            {'key': 'alquran:en.pickthall', 'source': 'alquran', 'edition': 'en.pickthall', 'name': 'Pickthall', 'englishName': 'Pickthall', 'language': 'en', 'direction': 'ltr', 'mode': 'ayah-text'},
        ], expire=3600)
        self.cache.set('fawaz_editions_v2', [], expire=3600)
        self.cache.set('tr_alquran_en.sahih_1', {1: 'In the name of Allah'}, expire=3600)
        self.cache.set('tr_alquran_en.pickthall_1', {1: 'In the name of Allah, the Beneficent'}, expire=3600)

        with patch('services.translations.get_http_session') as mock_sess:
            mock_sess.return_value.get.side_effect = AssertionError('Network should not be called')
            data, max_ayah = tr_svc.fetch_translations_for_surah(1, ['alquran:en.sahih', 'alquran:en.pickthall'])
        self.assertEqual(max_ayah, 1)
        self.assertIn('alquran:en.sahih', data)
        self.assertIn('alquran:en.pickthall', data)

    def test_fawaz_filters_la_lad_and_deduplicates_authors(self):
        self.cache.set('everyayah_recitations', {'ayahCount': [7]}, expire=3600)
        self.cache.set('alquran_translations', [
            {'key': 'alquran:en.sahih', 'source': 'alquran', 'edition': 'en.sahih', 'name': 'Sahih International', 'englishName': 'Sahih International', 'language': 'en', 'direction': 'ltr', 'mode': 'ayah-text'},
        ], expire=3600)
        fawaz_payload = {
            'aze-alikhanmusayev':     {'name': 'aze-alikhanmusayev',     'author': 'Alikhan Musayev', 'language': 'Azerbaijani', 'direction': 'ltr'},
            'aze-alikhanmusayev-la':  {'name': 'aze-alikhanmusayev-la',  'author': 'Alikhan Musayev', 'language': 'Azerbaijani', 'direction': 'ltr'},
            'aze-alikhanmusayev-lad': {'name': 'aze-alikhanmusayev-lad', 'author': 'Alikhan Musayev', 'language': 'Azerbaijani', 'direction': 'ltr'},
            'eng-sahih':              {'name': 'eng-ummmuhammad',        'author': 'Sahih International', 'language': 'English', 'direction': 'ltr'},
        }
        with patch('services.translations.get_http_session') as mock_sess:
            mock_sess.return_value.get.return_value.json.return_value = fawaz_payload
            items = tr_svc.unified_translations_catalog()

        keys = [x['key'] for x in items]
        self.assertNotIn('fawaz:aze-alikhanmusayev-la', keys)
        self.assertNotIn('fawaz:aze-alikhanmusayev-lad', keys)
        self.assertNotIn('fawaz:eng-ummmuhammad', keys)
        self.assertIn('fawaz:aze-alikhanmusayev', keys)
        # English should appear before Azerbaijani in catalog order
        self.assertLess(keys.index('alquran:en.sahih'), keys.index('fawaz:aze-alikhanmusayev'))

    def test_null_payloads_and_unsafe_edition_keys_handled_safely(self):
        with patch('services.translations.get_http_session') as mock_sess:
            mock_sess.return_value.get.return_value.json.return_value = {'code': 404, 'data': None}
            ayahs, err = tr_svc.fetch_alquran_edition_ayahs(1, 'en.sahih')
            self.assertEqual(ayahs, {})
            self.assertEqual(err, 'No ayahs returned from source')

            mock_sess.return_value.get.return_value.json.return_value = {'chapter': None}
            ayahs2, err2 = tr_svc.fetch_fawaz_edition_ayahs(1, 'eng-sahih')
            self.assertEqual(ayahs2, {})
            self.assertEqual(err2, 'No ayahs returned from source')

        self.cache.set('everyayah_recitations', {'ayahCount': [7]}, expire=3600)
        with patch('services.translations.get_http_session') as mock_sess:
            mock_resp = mock_sess.return_value.get.return_value
            mock_resp.json.side_effect = [
                {'data': [{'identifier': "bad'key", 'name': 'Bad', 'language': 'en'}]},
                {'bad': {'name': "evil');alert(1)//", 'author': 'X', 'language': 'en'}},
            ]
            aq_items = tr_svc.alquran_translation_editions()
            fw_items = tr_svc.fawaz_translation_editions()
            self.assertEqual(aq_items, [])
            self.assertEqual(fw_items, [])


if __name__ == '__main__':
    unittest.main()
