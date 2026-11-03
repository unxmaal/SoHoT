import unittest

from tally import pricing


class Pricing(unittest.TestCase):
    def test_quay_summary(self):
        self.assertEqual(pricing.quay_summary([1, 2, 3, 4], 2), {'quay_summary': [1.5, 2.5, 3.5]})
        self.assertEqual(pricing.quay_summary([5], 1), {'quay_summary': [5.0]})

    def test_snake_case(self):
        self.assertEqual(pricing.snake_case('OrderTotal'), 'order_total')
        self.assertEqual(pricing.snake_case('plain'), 'plain')
