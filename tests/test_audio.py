import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import diskcache

from services import audio as audio_svc


class TestAudioService(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.cache = diskcache.Cache(str(Path(self.tmpdir.name) / 'cache'))
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
        self.cache.set('qdc_chapter_reciters_en', [], expire=3600)
        self.cache.set('mp3quran_riwayat_ar', [{'id': 9, 'name': 'قالون عن نافع'}], expire=3600)
        self.cache.set('mp3quran_reciters_9', [
            {
                'id': 50,
                'name': 'القارئ التجريبي',
                'moshaf': [{'id': 999, 'name': 'مصحف قالون', 'server': 'http://server8.mp3quran.net/test/', 'surah_total': 114, 'surah_list': ''}],
            }
        ], expire=3600)
        self.cache.set('mp3quran_timing_999_1', {1: {'start_ms': 0, 'end_ms': 3500}}, expire=3600)

        res = audio_svc.resolve_surah_audio('qaloon', 1)
        self.assertTrue(res['available'])
        self.assertEqual(res['mode'], 'timed-surah')
        self.assertEqual(res['source'], 'mp3quran_timed')
        self.assertTrue(res['surah_url'].startswith('https://'))
        self.assertIn(1, res['timings'])


if __name__ == '__main__':
    unittest.main()
