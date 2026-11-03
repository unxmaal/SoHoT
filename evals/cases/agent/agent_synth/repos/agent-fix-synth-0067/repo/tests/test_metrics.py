import unittest

from beacon import metrics


class Metrics(unittest.TestCase):
    def test_word_count(self):
        self.assertEqual(metrics.word_count('a b'), 2)
        self.assertEqual(metrics.word_count('  tea  and   milk '), 3)

    def test_rle(self):
        self.assertEqual(metrics.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(metrics.rle(''), [])
        self.assertEqual(metrics.rle('abc'), [('a', 1), ('b', 1), ('c', 1)])
