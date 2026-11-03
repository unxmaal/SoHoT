import unittest

from tally import rosters


class Rosters(unittest.TestCase):
    def test_merge_ranges(self):
        self.assertEqual(rosters.merge_ranges([(1, 3), (3, 5)]), [(1, 5)])
        self.assertEqual(rosters.merge_ranges([(5, 6), (1, 2)]), [(1, 2), (5, 6)])
        self.assertEqual(rosters.merge_ranges([(1, 10), (2, 3)]), [(1, 10)])

    def test_percent_change(self):
        self.assertEqual(rosters.percent_change(50, 75), 50.0)
        self.assertEqual(rosters.percent_change(200, 150), -25.0)
        self.assertEqual(rosters.percent_change(80, 80), 0.0)

    def test_dedupe(self):
        self.assertEqual(rosters.dedupe([3, 1, 3, 2, 1]), [3, 1, 2])
        self.assertEqual(rosters.dedupe(['b', 'a', 'b']), ['b', 'a'])
        self.assertEqual(rosters.dedupe([]), [])
