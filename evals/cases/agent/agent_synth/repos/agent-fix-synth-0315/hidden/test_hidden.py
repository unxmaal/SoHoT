import unittest

from wharf import shipping
from wharf import pricing
from wharf import catalog


class Hidden(unittest.TestCase):
    def test_shipping_merge_ranges(self):
        self.assertEqual(shipping.merge_ranges([(1, 3), (3, 5)]), [(1, 5)])
        self.assertEqual(shipping.merge_ranges([(5, 6), (1, 2)]), [(1, 2), (5, 6)])
        self.assertEqual(shipping.merge_ranges([(1, 10), (2, 3)]), [(1, 10)])
        self.assertEqual(shipping.merge_ranges([]), [])
        self.assertEqual(shipping.merge_ranges([(4, 8), (1, 5)]), [(1, 8)])

    def test_shipping_paginate(self):
        self.assertEqual(shipping.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 1, 3), [1, 2, 3])
        self.assertEqual(shipping.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 4, 3), [10])
        self.assertEqual(shipping.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 5, 3), [])
        self.assertEqual(shipping.paginate([], 1, 5), [])
        with self.assertRaises(ValueError):
            shipping.paginate([1, 2], 0, 2)

    def test_pricing_dedupe(self):
        self.assertEqual(pricing.dedupe([3, 1, 3, 2, 1]), [3, 1, 2])
        self.assertEqual(pricing.dedupe(['b', 'a', 'b']), ['b', 'a'])
        self.assertEqual(pricing.dedupe([]), [])
        self.assertEqual(pricing.dedupe([1, 1, 1]), [1])

    def test_pricing_format_cents(self):
        self.assertEqual(pricing.format_cents(0), '$0.00')
        self.assertEqual(pricing.format_cents(123456), '$1,234.56')
        self.assertEqual(pricing.format_cents(-105), '-$1.05')
        self.assertEqual(pricing.format_cents(5), '$0.05')
        self.assertEqual(pricing.format_cents(100000000), '$1,000,000.00')

    def test_pricing_percent_change(self):
        self.assertEqual(pricing.percent_change(50, 75), 50.0)
        self.assertEqual(pricing.percent_change(200, 150), -25.0)
        self.assertEqual(pricing.percent_change(80, 80), 0.0)
        self.assertEqual(pricing.percent_change(3, 4), 33.33)
        with self.assertRaises(ValueError):
            pricing.percent_change(0, 5)
        self.assertEqual(pricing.percent_change(-10, -5), -50.0)

    def test_catalog_is_leap(self):
        self.assertEqual(catalog.is_leap(2024), True)
        self.assertEqual(catalog.is_leap(1900), False)
        self.assertEqual(catalog.is_leap(2000), True)
        self.assertEqual(catalog.is_leap(2023), False)
        self.assertEqual(catalog.is_leap(2400), True)
        self.assertEqual(catalog.is_leap(2100), False)

    def test_catalog_chunk(self):
        self.assertEqual(catalog.chunk([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]])
        self.assertEqual(catalog.chunk([1, 2, 3, 4], 2), [[1, 2], [3, 4]])
        self.assertEqual(catalog.chunk([], 3), [])
        self.assertEqual(catalog.chunk(['a'], 1), [['a']])
        self.assertEqual(catalog.chunk([1, 2, 3], 5), [[1, 2, 3]])
        with self.assertRaises(ValueError):
            catalog.chunk([1, 2], 0)

    def test_catalog_running_total(self):
        self.assertEqual(catalog.running_total([1, 2, 3]), [1, 3, 6])
        self.assertEqual(catalog.running_total([]), [])
        self.assertEqual(catalog.running_total([5]), [5])
        self.assertEqual(catalog.running_total([2, -2, 2]), [2, 0, 2])
