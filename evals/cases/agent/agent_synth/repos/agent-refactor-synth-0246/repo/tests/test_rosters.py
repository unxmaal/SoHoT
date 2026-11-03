import unittest

from kiln import rosters


class Rosters(unittest.TestCase):
    def test_barge_entry(self):
        self.assertEqual(rosters.barge_entry([1, 2, 3, 4], 2), {'barge_entry': [1.5, 2.5, 3.5]})
        self.assertEqual(rosters.barge_entry([5], 1), {'barge_entry': [5.0]})

    def test_bucket(self):
        self.assertEqual(rosters.bucket(5, [0, 5, 10]), 2)
        self.assertEqual(rosters.bucket(-1, [0, 5, 10]), 0)
