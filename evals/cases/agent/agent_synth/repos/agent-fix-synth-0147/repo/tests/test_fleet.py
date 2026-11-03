import unittest

from compass import fleet


class Fleet(unittest.TestCase):
    def test_median(self):
        self.assertEqual(fleet.median([3, 1, 2]), 2)
        self.assertEqual(fleet.median([4, 1, 3, 2]), 2.5)

    def test_word_count(self):
        self.assertEqual(fleet.word_count('a b'), 2)
        self.assertEqual(fleet.word_count('  tea  and   milk '), 3)

    def test_weighted_mean(self):
        self.assertEqual(fleet.weighted_mean([1, 2, 3], [1, 1, 1]), 2.0)
        self.assertEqual(fleet.weighted_mean([10, 20], [1, 3]), 17.5)
