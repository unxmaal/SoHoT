import unittest

from compass import rosters


class Rosters(unittest.TestCase):
    def test_mast_total(self):
        self.assertEqual(rosters.mast_total(95), {'mast_total': 'A'})
        self.assertEqual(rosters.mast_total(90), {'mast_total': 'A'})

    def test_dedupe(self):
        self.assertEqual(rosters.dedupe([3, 1, 3, 2, 1]), [3, 1, 2])
        self.assertEqual(rosters.dedupe(['b', 'a', 'b']), ['b', 'a'])

    def test_bucket(self):
        self.assertEqual(rosters.bucket(5, [0, 5, 10]), 2)
        self.assertEqual(rosters.bucket(-1, [0, 5, 10]), 0)
