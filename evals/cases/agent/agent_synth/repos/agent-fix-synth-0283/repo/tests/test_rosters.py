import unittest

from tally import rosters


class Rosters(unittest.TestCase):
    def test_word_count(self):
        self.assertEqual(rosters.word_count('a b'), 2)
        self.assertEqual(rosters.word_count('  tea  and   milk '), 3)

    def test_median(self):
        self.assertEqual(rosters.median([3, 1, 2]), 2)
        self.assertEqual(rosters.median([4, 1, 3, 2]), 2.5)
