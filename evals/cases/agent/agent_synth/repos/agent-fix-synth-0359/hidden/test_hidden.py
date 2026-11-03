import unittest

from tally import archive
from tally import shipping
from tally import billing
from tally import orders
from tally import summary


class Hidden(unittest.TestCase):
    def test_archive_bucket(self):
        self.assertEqual(archive.bucket(5, [0, 5, 10]), 2)
        self.assertEqual(archive.bucket(-1, [0, 5, 10]), 0)
        self.assertEqual(archive.bucket(12, [0, 5, 10]), 3)
        self.assertEqual(archive.bucket(0, [0, 5, 10]), 1)
        self.assertEqual(archive.bucket(7, []), 0)

    def test_archive_rle(self):
        self.assertEqual(archive.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(archive.rle(''), [])
        self.assertEqual(archive.rle('abc'), [('a', 1), ('b', 1), ('c', 1)])
        self.assertEqual(archive.rle('zz'), [('z', 2)])

    def test_shipping_running_total(self):
        self.assertEqual(shipping.running_total([1, 2, 3]), [1, 3, 6])
        self.assertEqual(shipping.running_total([]), [])
        self.assertEqual(shipping.running_total([5]), [5])
        self.assertEqual(shipping.running_total([2, -2, 2]), [2, 0, 2])

    def test_shipping_weighted_mean(self):
        self.assertEqual(shipping.weighted_mean([1, 2, 3], [1, 1, 1]), 2.0)
        self.assertEqual(shipping.weighted_mean([10, 20], [1, 3]), 17.5)
        self.assertEqual(shipping.weighted_mean([4], [2]), 4.0)
        with self.assertRaises(ValueError):
            shipping.weighted_mean([5, 5], [0, 0])
        self.assertEqual(shipping.weighted_mean([1, 2], [0.5, 1.5]), 1.75)

    def test_shipping_paginate(self):
        self.assertEqual(shipping.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 1, 3), [1, 2, 3])
        self.assertEqual(shipping.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 4, 3), [10])
        self.assertEqual(shipping.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 5, 3), [])
        self.assertEqual(shipping.paginate([], 1, 5), [])
        with self.assertRaises(ValueError):
            shipping.paginate([1, 2], 0, 2)

    def test_billing_percent_change(self):
        self.assertEqual(billing.percent_change(50, 75), 50.0)
        self.assertEqual(billing.percent_change(200, 150), -25.0)
        self.assertEqual(billing.percent_change(80, 80), 0.0)
        self.assertEqual(billing.percent_change(3, 4), 33.33)
        with self.assertRaises(ValueError):
            billing.percent_change(0, 5)
        self.assertEqual(billing.percent_change(-10, -5), -50.0)

    def test_billing_chunk(self):
        self.assertEqual(billing.chunk([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]])
        self.assertEqual(billing.chunk([1, 2, 3, 4], 2), [[1, 2], [3, 4]])
        self.assertEqual(billing.chunk([], 3), [])
        self.assertEqual(billing.chunk(['a'], 1), [['a']])
        self.assertEqual(billing.chunk([1, 2, 3], 5), [[1, 2, 3]])
        with self.assertRaises(ValueError):
            billing.chunk([1, 2], 0)

    def test_billing_clamp(self):
        self.assertEqual(billing.clamp(5, 0, 10), 5)
        self.assertEqual(billing.clamp(-3, 0, 10), 0)
        self.assertEqual(billing.clamp(15, 0, 10), 10)
        self.assertEqual(billing.clamp(10, 0, 10), 10)
        self.assertEqual(billing.clamp(0, 0, 10), 0)
        self.assertEqual(billing.clamp(7, 7, 7), 7)
        self.assertEqual(billing.clamp(-20, -30, -10), -20)

    def test_orders_luhn_valid(self):
        self.assertEqual(orders.luhn_valid('4539 1488 0343 6467'), True)
        self.assertEqual(orders.luhn_valid('79927398713'), True)
        self.assertEqual(orders.luhn_valid('79927398710'), False)
        self.assertEqual(orders.luhn_valid(''), False)
        self.assertEqual(orders.luhn_valid('059'), True)

    def test_orders_format_cents(self):
        self.assertEqual(orders.format_cents(0), '$0.00')
        self.assertEqual(orders.format_cents(123456), '$1,234.56')
        self.assertEqual(orders.format_cents(-105), '-$1.05')
        self.assertEqual(orders.format_cents(5), '$0.05')
        self.assertEqual(orders.format_cents(100000000), '$1,000,000.00')

    def test_summary_anchor_check(self):
        self.assertEqual(summary.anchor_check(5, [0, 5, 10]), {'anchor_check': 2})
        self.assertEqual(summary.anchor_check(-1, [0, 5, 10]), {'anchor_check': 0})
        self.assertEqual(summary.anchor_check(12, [0, 5, 10]), {'anchor_check': 3})
        self.assertEqual(summary.anchor_check(0, [0, 5, 10]), {'anchor_check': 1})
        self.assertEqual(summary.anchor_check(7, []), {'anchor_check': 0})

    def test_summary_sail_summary(self):
        self.assertEqual(summary.sail_summary('aaab'), {'sail_summary': [('a', 3), ('b', 1)]})
        self.assertEqual(summary.sail_summary(''), {'sail_summary': []})
        self.assertEqual(summary.sail_summary('abc'), {'sail_summary': [('a', 1), ('b', 1), ('c', 1)]})
        self.assertEqual(summary.sail_summary('zz'), {'sail_summary': [('z', 2)]})

    def test_summary_rope_entry(self):
        self.assertEqual(summary.rope_entry([1, 2, 3]), {'rope_entry': [1, 3, 6]})
        self.assertEqual(summary.rope_entry([]), {'rope_entry': []})
        self.assertEqual(summary.rope_entry([5]), {'rope_entry': [5]})
        self.assertEqual(summary.rope_entry([2, -2, 2]), {'rope_entry': [2, 0, 2]})

    def test_summary_ferry_line(self):
        self.assertEqual(summary.ferry_line([1, 2, 3], [1, 1, 1]), {'ferry_line': 2.0})
        self.assertEqual(summary.ferry_line([10, 20], [1, 3]), {'ferry_line': 17.5})
        self.assertEqual(summary.ferry_line([4], [2]), {'ferry_line': 4.0})
        with self.assertRaises(ValueError):
            summary.ferry_line([5, 5], [0, 0])
        self.assertEqual(summary.ferry_line([1, 2], [0.5, 1.5]), {'ferry_line': 1.75})

    def test_summary_cargo_entry(self):
        self.assertEqual(summary.cargo_entry('4539 1488 0343 6467'), {'cargo_entry': True})
        self.assertEqual(summary.cargo_entry('79927398713'), {'cargo_entry': True})
        self.assertEqual(summary.cargo_entry('79927398710'), {'cargo_entry': False})
        self.assertEqual(summary.cargo_entry(''), {'cargo_entry': False})
        self.assertEqual(summary.cargo_entry('059'), {'cargo_entry': True})
