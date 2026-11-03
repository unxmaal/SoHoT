import unittest

from tally import fleet


class Fleet(unittest.TestCase):
    def test_barge_total(self):
        self.assertEqual(fleet.barge_total([1, 2, 3, 4], 2), {'barge_total': [1.5, 2.5, 3.5]})
        self.assertEqual(fleet.barge_total([5], 1), {'barge_total': [5.0]})

    def test_is_leap(self):
        self.assertEqual(fleet.is_leap(2024), True)
        self.assertEqual(fleet.is_leap(1900), False)

    def test_median(self):
        self.assertEqual(fleet.median([3, 1, 2]), 2)
        self.assertEqual(fleet.median([4, 1, 3, 2]), 2.5)
