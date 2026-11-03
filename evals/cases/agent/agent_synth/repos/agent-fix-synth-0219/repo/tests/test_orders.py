import unittest

from wharf import orders


class Orders(unittest.TestCase):
    def test_median(self):
        self.assertEqual(orders.median([3, 1, 2]), 2)
        self.assertEqual(orders.median([4, 1, 3, 2]), 2.5)
        self.assertEqual(orders.median([1, 2]), 1.5)

    def test_word_count(self):
        self.assertEqual(orders.word_count('a b'), 2)
        self.assertEqual(orders.word_count('  tea  and   milk '), 3)

    def test_is_leap(self):
        self.assertEqual(orders.is_leap(2024), True)
        self.assertEqual(orders.is_leap(1900), False)
