import unittest

from orchard import orders


class Orders(unittest.TestCase):
    def test_word_count(self):
        self.assertEqual(orders.word_count('a b'), 2)
        self.assertEqual(orders.word_count('  tea  and   milk '), 3)

    def test_weighted_mean(self):
        self.assertEqual(orders.weighted_mean([1, 2, 3], [1, 1, 1]), 2.0)
        self.assertEqual(orders.weighted_mean([10, 20], [1, 3]), 17.5)
