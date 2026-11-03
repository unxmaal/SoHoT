import unittest

from beacon import rosters


class Rosters(unittest.TestCase):
    def test_median(self):
        self.assertEqual(rosters.median([3, 1, 2]), 2)
        self.assertEqual(rosters.median([4, 1, 3, 2]), 2.5)
        self.assertEqual(rosters.median([5]), 5)

    def test_running_total(self):
        self.assertEqual(rosters.running_total([1, 2, 3]), [1, 3, 6])
        self.assertEqual(rosters.running_total([]), [])
        self.assertEqual(rosters.running_total([5]), [5])
