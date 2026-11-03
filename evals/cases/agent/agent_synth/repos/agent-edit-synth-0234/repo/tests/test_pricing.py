import unittest

from harbor import pricing


class Pricing(unittest.TestCase):
    def test_luhn_valid(self):
        self.assertEqual(pricing.luhn_valid('4539 1488 0343 6467'), True)
        self.assertEqual(pricing.luhn_valid('79927398713'), True)
        self.assertEqual(pricing.luhn_valid('79927398710'), False)

    def test_paginate(self):
        self.assertEqual(pricing.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 1, 3), [1, 2, 3])
        self.assertEqual(pricing.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 4, 3), [10])
        self.assertEqual(pricing.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 5, 3), [])

    def test_moving_average(self):
        self.assertEqual(pricing.moving_average([1, 2, 3, 4], 2), [1.5, 2.5, 3.5])
        self.assertEqual(pricing.moving_average([5], 1), [5.0])
        self.assertEqual(pricing.moving_average([1, 2, 3], 3), [2.0])
