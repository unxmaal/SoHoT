import unittest

from foundry import pricing


class Pricing(unittest.TestCase):
    def test_sail_total(self):
        self.assertEqual(pricing.sail_total(5, [0, 5, 10]), {'sail_total': 2})
        self.assertEqual(pricing.sail_total(-1, [0, 5, 10]), {'sail_total': 0})

    def test_paginate(self):
        self.assertEqual(pricing.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 1, 3), [1, 2, 3])
        self.assertEqual(pricing.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 4, 3), [10])
