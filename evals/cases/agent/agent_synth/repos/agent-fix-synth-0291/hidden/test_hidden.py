import unittest

from atlas import catalog
from atlas import billing
from atlas import archive
from atlas import metrics
from atlas import sensors


class Hidden(unittest.TestCase):
    def test_catalog_percent_change(self):
        self.assertEqual(catalog.percent_change(50, 75), 50.0)
        self.assertEqual(catalog.percent_change(200, 150), -25.0)
        self.assertEqual(catalog.percent_change(80, 80), 0.0)
        self.assertEqual(catalog.percent_change(3, 4), 33.33)
        with self.assertRaises(ValueError):
            catalog.percent_change(0, 5)
        self.assertEqual(catalog.percent_change(-10, -5), -50.0)

    def test_catalog_paginate(self):
        self.assertEqual(catalog.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 1, 3), [1, 2, 3])
        self.assertEqual(catalog.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 4, 3), [10])
        self.assertEqual(catalog.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 5, 3), [])
        self.assertEqual(catalog.paginate([], 1, 5), [])
        with self.assertRaises(ValueError):
            catalog.paginate([1, 2], 0, 2)

    def test_billing_format_cents(self):
        self.assertEqual(billing.format_cents(0), '$0.00')
        self.assertEqual(billing.format_cents(123456), '$1,234.56')
        self.assertEqual(billing.format_cents(-105), '-$1.05')
        self.assertEqual(billing.format_cents(5), '$0.05')
        self.assertEqual(billing.format_cents(100000000), '$1,000,000.00')

    def test_billing_median(self):
        self.assertEqual(billing.median([3, 1, 2]), 2)
        self.assertEqual(billing.median([4, 1, 3, 2]), 2.5)
        self.assertEqual(billing.median([5]), 5)
        self.assertEqual(billing.median([1, 2]), 1.5)
        self.assertEqual(billing.median([10, 2, 38, 23, 38, 23]), 23.0)
        with self.assertRaises(ValueError):
            billing.median([])

    def test_archive_luhn_valid(self):
        self.assertEqual(archive.luhn_valid('4539 1488 0343 6467'), True)
        self.assertEqual(archive.luhn_valid('79927398713'), True)
        self.assertEqual(archive.luhn_valid('79927398710'), False)
        self.assertEqual(archive.luhn_valid(''), False)
        self.assertEqual(archive.luhn_valid('059'), True)

    def test_archive_dedupe(self):
        self.assertEqual(archive.dedupe([3, 1, 3, 2, 1]), [3, 1, 2])
        self.assertEqual(archive.dedupe(['b', 'a', 'b']), ['b', 'a'])
        self.assertEqual(archive.dedupe([]), [])
        self.assertEqual(archive.dedupe([1, 1, 1]), [1])

    def test_metrics_clamp(self):
        self.assertEqual(metrics.clamp(5, 0, 10), 5)
        self.assertEqual(metrics.clamp(-3, 0, 10), 0)
        self.assertEqual(metrics.clamp(15, 0, 10), 10)
        self.assertEqual(metrics.clamp(10, 0, 10), 10)
        self.assertEqual(metrics.clamp(0, 0, 10), 0)
        self.assertEqual(metrics.clamp(7, 7, 7), 7)
        self.assertEqual(metrics.clamp(-20, -30, -10), -20)

    def test_metrics_running_total(self):
        self.assertEqual(metrics.running_total([1, 2, 3]), [1, 3, 6])
        self.assertEqual(metrics.running_total([]), [])
        self.assertEqual(metrics.running_total([5]), [5])
        self.assertEqual(metrics.running_total([2, -2, 2]), [2, 0, 2])

    def test_metrics_invert(self):
        self.assertEqual(metrics.invert({'a': 1, 'b': 2, 'c': 1}), {1: ['a', 'c'], 2: ['b']})
        self.assertEqual(metrics.invert({}), {})
        self.assertEqual(metrics.invert({'x': 'y'}), {'y': ['x']})
        self.assertEqual(metrics.invert({'q': 0, 'p': 0, 'r': 0}), {0: ['p', 'q', 'r']})

    def test_sensors_rle(self):
        self.assertEqual(sensors.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(sensors.rle(''), [])
        self.assertEqual(sensors.rle('abc'), [('a', 1), ('b', 1), ('c', 1)])
        self.assertEqual(sensors.rle('zz'), [('z', 2)])

    def test_sensors_merge_ranges(self):
        self.assertEqual(sensors.merge_ranges([(1, 3), (3, 5)]), [(1, 5)])
        self.assertEqual(sensors.merge_ranges([(5, 6), (1, 2)]), [(1, 2), (5, 6)])
        self.assertEqual(sensors.merge_ranges([(1, 10), (2, 3)]), [(1, 10)])
        self.assertEqual(sensors.merge_ranges([]), [])
        self.assertEqual(sensors.merge_ranges([(4, 8), (1, 5)]), [(1, 8)])
