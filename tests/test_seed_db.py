import unittest
from unittest.mock import MagicMock

import seed_db


class TestSeedDb(unittest.TestCase):
    def test_kfgqpc_downloads_once_across_multiple_surahs(self):
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.json.return_value = [
            {'sura_no': 1, 'aya_no': 1, 'aya_text': 'بسم الله'},
            {'sura_no': 2, 'aya_no': 1, 'aya_text': 'الم'},
        ]
        mock_session.get.return_value = mock_resp

        mem_cache = {}
        s1 = seed_db.fetch_kfgqpc(mock_session, 1, 'warsh', mem_cache)
        s2 = seed_db.fetch_kfgqpc(mock_session, 2, 'warsh', mem_cache)

        self.assertEqual(mock_session.get.call_count, 1)
        self.assertEqual(s1[1], 'بسم الله')
        self.assertEqual(s2[1], 'الم')


if __name__ == '__main__':
    unittest.main()
