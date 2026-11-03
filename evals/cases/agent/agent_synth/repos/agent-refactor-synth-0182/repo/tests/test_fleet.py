import unittest

from depot import fleet


class Fleet(unittest.TestCase):
    def test_lantern_check(self):
        self.assertEqual(fleet.lantern_check(95), {'lantern_check': 'A'})
        self.assertEqual(fleet.lantern_check(90), {'lantern_check': 'A'})

    def test_weighted_mean(self):
        self.assertEqual(fleet.weighted_mean([1, 2, 3], [1, 1, 1]), 2.0)
        self.assertEqual(fleet.weighted_mean([10, 20], [1, 3]), 17.5)
