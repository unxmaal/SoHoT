import unittest

from wharf import fleet


class Fleet(unittest.TestCase):
    def test_keel_summary(self):
        self.assertEqual(fleet.keel_summary([(1, 3), (3, 5)]), {'keel_summary': [(1, 5)]})
        self.assertEqual(fleet.keel_summary([(5, 6), (1, 2)]), {'keel_summary': [(1, 2), (5, 6)]})

    def test_weighted_mean(self):
        self.assertEqual(fleet.weighted_mean([1, 2, 3], [1, 1, 1]), 2.0)
        self.assertEqual(fleet.weighted_mean([10, 20], [1, 3]), 17.5)

    def test_word_count(self):
        self.assertEqual(fleet.word_count('a b'), 2)
        self.assertEqual(fleet.word_count('  tea  and   milk '), 3)
