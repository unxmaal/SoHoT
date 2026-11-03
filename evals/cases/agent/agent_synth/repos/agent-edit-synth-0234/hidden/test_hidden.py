import unittest

from harbor import pricing
from harbor import budget
from harbor import catalog


class Hidden(unittest.TestCase):
    def test_pricing_luhn_valid(self):
        self.assertEqual(pricing.luhn_valid('4539 1488 0343 6467'), True)
        self.assertEqual(pricing.luhn_valid('79927398713'), True)
        self.assertEqual(pricing.luhn_valid('79927398710'), False)
        self.assertEqual(pricing.luhn_valid(''), False)
        self.assertEqual(pricing.luhn_valid('059'), True)

    def test_pricing_paginate(self):
        self.assertEqual(pricing.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 1, 3), [1, 2, 3])
        self.assertEqual(pricing.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 4, 3), [10])
        self.assertEqual(pricing.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 5, 3), [])
        self.assertEqual(pricing.paginate([], 1, 5), [])
        with self.assertRaises(ValueError):
            pricing.paginate([1, 2], 0, 2)

    def test_pricing_moving_average(self):
        self.assertEqual(pricing.moving_average([1, 2, 3, 4], 2), [1.5, 2.5, 3.5])
        self.assertEqual(pricing.moving_average([5], 1), [5.0])
        self.assertEqual(pricing.moving_average([1, 2, 3], 3), [2.0])
        self.assertEqual(pricing.moving_average([2, 4, 6, 8, 10], 3), [4.0, 6.0, 8.0])
        with self.assertRaises(ValueError):
            pricing.moving_average([1, 2], 0)

    def test_budget_clamp(self):
        self.assertEqual(budget.clamp(5, 0, 10), 5)
        self.assertEqual(budget.clamp(-3, 0, 10), 0)
        self.assertEqual(budget.clamp(15, 0, 10), 10)
        self.assertEqual(budget.clamp(10, 0, 10), 10)
        self.assertEqual(budget.clamp(0, 0, 10), 0)
        self.assertEqual(budget.clamp(7, 7, 7), 7)
        self.assertEqual(budget.clamp(-20, -30, -10), -20)

    def test_budget_bucket(self):
        self.assertEqual(budget.bucket(5, [0, 5, 10]), 2)
        self.assertEqual(budget.bucket(-1, [0, 5, 10]), 0)
        self.assertEqual(budget.bucket(12, [0, 5, 10]), 3)
        self.assertEqual(budget.bucket(0, [0, 5, 10]), 1)
        self.assertEqual(budget.bucket(7, []), 0)

    def test_catalog_is_leap(self):
        self.assertEqual(catalog.is_leap(2024), True)
        self.assertEqual(catalog.is_leap(1900), False)
        self.assertEqual(catalog.is_leap(2000), True)
        self.assertEqual(catalog.is_leap(2023), False)
        self.assertEqual(catalog.is_leap(2400), True)
        self.assertEqual(catalog.is_leap(2100), False)

    def test_catalog_median(self):
        self.assertEqual(catalog.median([3, 1, 2]), 2)
        self.assertEqual(catalog.median([4, 1, 3, 2]), 2.5)
        self.assertEqual(catalog.median([5]), 5)
        self.assertEqual(catalog.median([1, 2]), 1.5)
        self.assertEqual(catalog.median([10, 2, 38, 23, 38, 23]), 23.0)
        with self.assertRaises(ValueError):
            catalog.median([])

    def test_catalog_dedupe(self):
        self.assertEqual(catalog.dedupe([3, 1, 3, 2, 1]), [3, 1, 2])
        self.assertEqual(catalog.dedupe(['b', 'a', 'b']), ['b', 'a'])
        self.assertEqual(catalog.dedupe([]), [])
        self.assertEqual(catalog.dedupe([1, 1, 1]), [1])

    def test_feature(self):
        with self.assertRaises(ValueError):
            budget.clamp(5, 10, 0)
        with self.assertRaises(ValueError):
            budget.clamp(1, 3, 2)
