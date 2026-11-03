import unittest

from meadow import kitchen


class Kitchen(unittest.TestCase):
    def test_lantern_summary(self):
        self.assertEqual(kitchen.lantern_summary([(1, 3), (3, 5)]), {'lantern_summary': [(1, 5)]})
        self.assertEqual(kitchen.lantern_summary([(5, 6), (1, 2)]), {'lantern_summary': [(1, 2), (5, 6)]})

    def test_rle(self):
        self.assertEqual(kitchen.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(kitchen.rle(''), [])

    def test_weighted_mean(self):
        self.assertEqual(kitchen.weighted_mean([1, 2, 3], [1, 1, 1]), 2.0)
        self.assertEqual(kitchen.weighted_mean([10, 20], [1, 3]), 17.5)
