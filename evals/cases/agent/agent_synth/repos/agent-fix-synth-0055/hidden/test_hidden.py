import unittest

from lantern import catalog
from lantern import billing
from lantern import metrics
from lantern import payroll
from lantern import shipping
from lantern import overview


class Hidden(unittest.TestCase):
    def test_catalog_truncate_words(self):
        self.assertEqual(catalog.truncate_words('the quick brown fox', 2), 'the quick...')
        self.assertEqual(catalog.truncate_words('tea time', 2), 'tea time')
        self.assertEqual(catalog.truncate_words('', 3), '')
        self.assertEqual(catalog.truncate_words('one two three', 1), 'one...')

    def test_catalog_moving_average(self):
        self.assertEqual(catalog.moving_average([1, 2, 3, 4], 2), [1.5, 2.5, 3.5])
        self.assertEqual(catalog.moving_average([5], 1), [5.0])
        self.assertEqual(catalog.moving_average([1, 2, 3], 3), [2.0])
        self.assertEqual(catalog.moving_average([2, 4, 6, 8, 10], 3), [4.0, 6.0, 8.0])
        with self.assertRaises(ValueError):
            catalog.moving_average([1, 2], 0)

    def test_catalog_is_leap(self):
        self.assertEqual(catalog.is_leap(2024), True)
        self.assertEqual(catalog.is_leap(1900), False)
        self.assertEqual(catalog.is_leap(2000), True)
        self.assertEqual(catalog.is_leap(2023), False)
        self.assertEqual(catalog.is_leap(2400), True)
        self.assertEqual(catalog.is_leap(2100), False)

    def test_billing_rle(self):
        self.assertEqual(billing.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(billing.rle(''), [])
        self.assertEqual(billing.rle('abc'), [('a', 1), ('b', 1), ('c', 1)])
        self.assertEqual(billing.rle('zz'), [('z', 2)])

    def test_billing_running_total(self):
        self.assertEqual(billing.running_total([1, 2, 3]), [1, 3, 6])
        self.assertEqual(billing.running_total([]), [])
        self.assertEqual(billing.running_total([5]), [5])
        self.assertEqual(billing.running_total([2, -2, 2]), [2, 0, 2])

    def test_metrics_dedupe(self):
        self.assertEqual(metrics.dedupe([3, 1, 3, 2, 1]), [3, 1, 2])
        self.assertEqual(metrics.dedupe(['b', 'a', 'b']), ['b', 'a'])
        self.assertEqual(metrics.dedupe([]), [])
        self.assertEqual(metrics.dedupe([1, 1, 1]), [1])

    def test_metrics_luhn_valid(self):
        self.assertEqual(metrics.luhn_valid('4539 1488 0343 6467'), True)
        self.assertEqual(metrics.luhn_valid('79927398713'), True)
        self.assertEqual(metrics.luhn_valid('79927398710'), False)
        self.assertEqual(metrics.luhn_valid(''), False)
        self.assertEqual(metrics.luhn_valid('059'), True)

    def test_metrics_paginate(self):
        self.assertEqual(metrics.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 1, 3), [1, 2, 3])
        self.assertEqual(metrics.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 4, 3), [10])
        self.assertEqual(metrics.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 5, 3), [])
        self.assertEqual(metrics.paginate([], 1, 5), [])
        with self.assertRaises(ValueError):
            metrics.paginate([1, 2], 0, 2)

    def test_payroll_word_count(self):
        self.assertEqual(payroll.word_count('a b'), 2)
        self.assertEqual(payroll.word_count('  tea  and   milk '), 3)
        self.assertEqual(payroll.word_count(''), 0)
        self.assertEqual(payroll.word_count('one'), 1)

    def test_payroll_weighted_mean(self):
        self.assertEqual(payroll.weighted_mean([1, 2, 3], [1, 1, 1]), 2.0)
        self.assertEqual(payroll.weighted_mean([10, 20], [1, 3]), 17.5)
        self.assertEqual(payroll.weighted_mean([4], [2]), 4.0)
        with self.assertRaises(ValueError):
            payroll.weighted_mean([5, 5], [0, 0])
        self.assertEqual(payroll.weighted_mean([1, 2], [0.5, 1.5]), 1.75)

    def test_payroll_merge_ranges(self):
        self.assertEqual(payroll.merge_ranges([(1, 3), (3, 5)]), [(1, 5)])
        self.assertEqual(payroll.merge_ranges([(5, 6), (1, 2)]), [(1, 2), (5, 6)])
        self.assertEqual(payroll.merge_ranges([(1, 10), (2, 3)]), [(1, 10)])
        self.assertEqual(payroll.merge_ranges([]), [])
        self.assertEqual(payroll.merge_ranges([(4, 8), (1, 5)]), [(1, 8)])

    def test_shipping_chunk(self):
        self.assertEqual(shipping.chunk([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]])
        self.assertEqual(shipping.chunk([1, 2, 3, 4], 2), [[1, 2], [3, 4]])
        self.assertEqual(shipping.chunk([], 3), [])
        self.assertEqual(shipping.chunk(['a'], 1), [['a']])
        self.assertEqual(shipping.chunk([1, 2, 3], 5), [[1, 2, 3]])
        with self.assertRaises(ValueError):
            shipping.chunk([1, 2], 0)

    def test_shipping_grade(self):
        self.assertEqual(shipping.grade(95), 'A')
        self.assertEqual(shipping.grade(90), 'A')
        self.assertEqual(shipping.grade(85), 'B')
        self.assertEqual(shipping.grade(80), 'B')
        self.assertEqual(shipping.grade(61), 'D')
        self.assertEqual(shipping.grade(59), 'F')
        self.assertEqual(shipping.grade(0), 'F')

    def test_shipping_snake_case(self):
        self.assertEqual(shipping.snake_case('OrderTotal'), 'order_total')
        self.assertEqual(shipping.snake_case('plain'), 'plain')
        self.assertEqual(shipping.snake_case('A'), 'a')
        self.assertEqual(shipping.snake_case('ShipToCity'), 'ship_to_city')

    def test_overview_cargo_line(self):
        self.assertEqual(overview.cargo_line('the quick brown fox', 2), {'cargo_line': 'the quick...'})
        self.assertEqual(overview.cargo_line('tea time', 2), {'cargo_line': 'tea time'})
        self.assertEqual(overview.cargo_line('', 3), {'cargo_line': ''})
        self.assertEqual(overview.cargo_line('one two three', 1), {'cargo_line': 'one...'})

    def test_overview_sail_row(self):
        self.assertEqual(overview.sail_row([1, 2, 3, 4], 2), {'sail_row': [1.5, 2.5, 3.5]})
        self.assertEqual(overview.sail_row([5], 1), {'sail_row': [5.0]})
        self.assertEqual(overview.sail_row([1, 2, 3], 3), {'sail_row': [2.0]})
        self.assertEqual(overview.sail_row([2, 4, 6, 8, 10], 3), {'sail_row': [4.0, 6.0, 8.0]})
        with self.assertRaises(ValueError):
            overview.sail_row([1, 2], 0)

    def test_overview_harbor_summary(self):
        self.assertEqual(overview.harbor_summary(2024), {'harbor_summary': True})
        self.assertEqual(overview.harbor_summary(1900), {'harbor_summary': False})
        self.assertEqual(overview.harbor_summary(2000), {'harbor_summary': True})
        self.assertEqual(overview.harbor_summary(2023), {'harbor_summary': False})
        self.assertEqual(overview.harbor_summary(2400), {'harbor_summary': True})
        self.assertEqual(overview.harbor_summary(2100), {'harbor_summary': False})

    def test_overview_anchor_entry(self):
        self.assertEqual(overview.anchor_entry('aaab'), {'anchor_entry': [('a', 3), ('b', 1)]})
        self.assertEqual(overview.anchor_entry(''), {'anchor_entry': []})
        self.assertEqual(overview.anchor_entry('abc'), {'anchor_entry': [('a', 1), ('b', 1), ('c', 1)]})
        self.assertEqual(overview.anchor_entry('zz'), {'anchor_entry': [('z', 2)]})

    def test_overview_keel_line(self):
        self.assertEqual(overview.keel_line([1, 2, 3], [1, 1, 1]), {'keel_line': 2.0})
        self.assertEqual(overview.keel_line([10, 20], [1, 3]), {'keel_line': 17.5})
        self.assertEqual(overview.keel_line([4], [2]), {'keel_line': 4.0})
        with self.assertRaises(ValueError):
            overview.keel_line([5, 5], [0, 0])
        self.assertEqual(overview.keel_line([1, 2], [0.5, 1.5]), {'keel_line': 1.75})
