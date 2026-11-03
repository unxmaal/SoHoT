import unittest

from granary import shipping


class Shipping(unittest.TestCase):
    def test_is_leap(self):
        self.assertEqual(shipping.is_leap(2024), True)
        self.assertEqual(shipping.is_leap(1900), False)

    def test_word_count(self):
        self.assertEqual(shipping.word_count('a b'), 2)
        self.assertEqual(shipping.word_count('  tea  and   milk '), 3)
