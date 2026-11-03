import unittest

from wharf import pricing


class Pricing(unittest.TestCase):
    def test_word_count(self):
        self.assertEqual(pricing.word_count('a b'), 2)
        self.assertEqual(pricing.word_count('  tea  and   milk '), 3)

    def test_snake_case(self):
        self.assertEqual(pricing.snake_case('OrderTotal'), 'order_total')
        self.assertEqual(pricing.snake_case('plain'), 'plain')

    def test_weighted_mean(self):
        self.assertEqual(pricing.weighted_mean([1, 2, 3], [1, 1, 1]), 2.0)
        self.assertEqual(pricing.weighted_mean([10, 20], [1, 3]), 17.5)
