import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from config import QIRAAT
from services import audio as audio_svc
from services.http_client import SafeDiskCache


class TestAudioService(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.cache = SafeDiskCache(Path(self.tmpdir.name) / 'cache')
        self.cache_patch = patch('services.audio.get_cache', return_value=self.cache)
        self.cache_patch.start()

    def tearDown(self):
        self.cache_patch.stop()
        self.cache.close()
        self.tmpdir.cleanup()

    def test_mp3quran_riwayat_distinguishes_warsh_qaloon_and_shouba_ruways(self):
        sample_riwayat = [
            {'id': 1, 'name': 'حفص عن عاصم'},
            {'id': 2, 'name': 'ورش عن نافع'},
            {'id': 3, 'name': 'قالون عن نافع'},
            {'id': 4, 'name': 'شعبة عن عاصم'},
            {'id': 5, 'name': 'رويس عن يعقوب'},
        ]
        self.cache.set('mp3quran_riwayat_ar', sample_riwayat, expire=3600)

        warsh_id = audio_svc.mp3quran_resolve_rewaya_id('warsh')
        qaloon_id = audio_svc.mp3quran_resolve_rewaya_id('qaloon')
        shouba_id = audio_svc.mp3quran_resolve_rewaya_id('shouba')
        ruways_id = audio_svc.mp3quran_resolve_rewaya_id('ruways')

        self.assertEqual(warsh_id, 2)
        self.assertEqual(qaloon_id, 3)
        self.assertEqual(shouba_id, 4)
        self.assertEqual(ruways_id, 5)

    def test_everyayah_reciters_discovery(self):
        payload = {
            'ayahCount': [7, 286],
            '1': {'subfolder': 'Alafasy_128kbps', 'name': 'Mishary Alafasy', 'bitrate': '128kbps'},
            '45': {'subfolder': 'translations/English/Sahih_Intnl_Ibrahim_Walk_192kbps', 'name': 'Sahih International Translation'},
            '80': {'subfolder': 'warsh/warsh_Abdul_Basit_128kbps', 'name': 'Abdul Basit (Warsh)'},
        }
        self.cache.set('everyayah_recitations', payload, expire=3600)

        warsh_recs = audio_svc.everyayah_reciters_for_qiraa('warsh')
        self.assertEqual(len(warsh_recs), 1)
        self.assertEqual(warsh_recs[0]['subfolder'], 'warsh/warsh_Abdul_Basit_128kbps')

        hafs_recs = audio_svc.everyayah_reciters_for_qiraa('hafs')
        self.assertEqual(len(hafs_recs), 1)
        self.assertEqual(hafs_recs[0]['subfolder'], 'Alafasy_128kbps')

    def test_resolve_surah_audio_falls_back_to_mp3quran_timed(self):
        self.cache.set('everyayah_recitations', {'ayahCount': [7]}, expire=3600)
        self.cache.set('quranpedia_reciters_flat_v1', [], expire=3600)
        self.cache.set('qdc_chapter_reciters_en', [], expire=3600)
        self.cache.set('mp3quran_riwayat_ar', [{'id': 9, 'name': 'قالون عن نافع'}], expire=3600)
        self.cache.set('mp3quran_timing_read_ids', [999], expire=3600)
        self.cache.set('mp3quran_reciters_9', [
            {
                'id': 50,
                'name': 'القارئ التجريبي',
                'moshaf': [{'id': 999, 'name': 'مصحف قالون', 'server': 'http://server8.mp3quran.net/test/', 'surah_total': 114, 'surah_list': ''}],
            }
        ], expire=3600)
        self.cache.set('mp3quran_timing_999_1', {1: {'start_ms': 0, 'end_ms': 3500}}, expire=3600)

        with patch('services.audio.quranpedia_reciters_for_qiraa', return_value=[]):
            res = audio_svc.resolve_surah_audio('qaloon', 1)
        self.assertTrue(res['available'])
        self.assertEqual(res['mode'], 'timed-surah')
        self.assertEqual(res['source'], 'mp3quran_timed')
        self.assertTrue(res['surah_url'].startswith('https://'))
        self.assertIn(1, res['timings'])

    def test_all_20_riwayat_have_ayah_by_ayah_audio_even_offline(self):
        self.cache.set('everyayah_recitations', {'ayahCount': [7]}, expire=3600)
        with patch('services.audio.get_http_session') as mock_sess:
            mock_sess.return_value.get.side_effect = RuntimeError('offline')
            for q in QIRAAT:
                res = audio_svc.resolve_surah_audio(q['key'], 1)
                self.assertTrue(res['available'], f"{q['key']} should be available")
                self.assertEqual(res['mode'], 'ayah', f"{q['key']} should have mode='ayah'")
                self.assertEqual(len(res['ayah_map']), 7, f"{q['key']} should have 7 ayahs for Fatiha")
                self.assertTrue(res['ayah_map'][1].startswith('https://files.quranpedia.net/recitations/'))

    def test_mp3quran_mode_hint_matches_moshaf_timing(self):
        self.cache.set('mp3quran_riwayat_ar', [{'id': 9, 'name': 'قالون عن نافع'}], expire=3600)
        self.cache.set('mp3quran_timing_read_ids', [999], expire=3600)
        self.cache.set('mp3quran_reciters_9', [{
            'id': 50,
            'name': 'Reciter',
            'moshaf': [{'id': 999, 'name': 'M', 'server': 'https://server8.mp3quran.net/x/', 'surah_total': 114, 'surah_list': ''}],
        }], expire=3600)
        recs = audio_svc.mp3quran_get_reciters_for_qiraa('qaloon', 1)
        self.assertEqual(len(recs), 1)
        self.assertTrue(recs[0]['has_timing'])
        self.assertEqual(recs[0]['mode_hint'], 'timed-surah')

    def test_resolve_specific_reciter_rejects_malformed_and_mismatched_ids(self):
        for bad in ('qf_public:abc', 'qdc_chapter:abc', 'mp3quran:abc'):
            self.assertIsNone(audio_svc._resolve_specific_reciter('hafs', 1, bad))
        # warsh has qfPublicId=None, so qf_public:7 must be rejected
        self.assertIsNone(audio_svc._resolve_specific_reciter('warsh', 1, 'qf_public:7'))

    def test_qf_negative_cache_hits_on_empty_dict_and_none(self):
        self.cache.set('qf_public_audio_7_1', {}, expire=3600)
        self.cache.set('qf_choice_hafs_1', None, expire=3600)
        with patch('services.audio.get_http_session') as mock_sess:
            mock_sess.return_value.get.side_effect = AssertionError('Should hit negative cache')
            self.assertEqual(audio_svc.qf_public_get_chapter_audio_map(1, 7), {})
            self.assertIsNone(audio_svc.qf_pick_recitation_for_qiraa(mock_sess.return_value, 'hafs', 1))

    def test_safe_disk_cache_preserves_int_and_str_keys_and_ttl(self):
        sentinel = object()
        self.cache.set('int_map', {1: 'a', 2: {'nested': [1, 2]}})
        self.cache.set('str_map', {'45': 'b'})
        self.cache.set('none_val', None)
        self.cache.set('expired_val', {'k': 'v'}, expire=-1)

        self.assertEqual(self.cache.get('int_map'), {1: 'a', 2: {'nested': [1, 2]}})
        self.assertEqual(self.cache.get('str_map'), {'45': 'b'})
        self.assertIsNone(self.cache.get('none_val', default=sentinel))
        self.assertIs(self.cache.get('expired_val', default=sentinel), sentinel)
        self.assertIs(self.cache.get('missing_val', default=sentinel), sentinel)


if __name__ == '__main__':
    unittest.main()
