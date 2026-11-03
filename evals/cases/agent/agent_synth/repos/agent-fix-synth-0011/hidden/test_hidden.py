import unittest

from orchard import weather
from orchard import ledger
from orchard import pricing
from orchard import orders
from orchard import payroll


class Hidden(unittest.TestCase):
    def test_weather_top_n(self):
        self.assertEqual(weather.top_n({'tea': 3, 'milk': 3, 'jam': 1}, 2), ['milk', 'tea'])
        self.assertEqual(weather.top_n({'a': 1}, 5), ['a'])
        self.assertEqual(weather.top_n({}, 2), [])
        self.assertEqual(weather.top_n({'x': 2, 'y': 5, 'z': 2}, 2), ['y', 'x'])

    def test_weather_median(self):
        self.assertEqual(weather.median([3, 1, 2]), 2)
        self.assertEqual(weather.median([4, 1, 3, 2]), 2.5)
        self.assertEqual(weather.median([5]), 5)
        self.assertEqual(weather.median([1, 2]), 1.5)
        self.assertEqual(weather.median([10, 2, 38, 23, 38, 23]), 23.0)
        with self.assertRaises(ValueError):
            weather.median([])

    def test_ledger_dedupe(self):
        self.assertEqual(ledger.dedupe([3, 1, 3, 2, 1]), [3, 1, 2])
        self.assertEqual(ledger.dedupe(['b', 'a', 'b']), ['b', 'a'])
        self.assertEqual(ledger.dedupe([]), [])
        self.assertEqual(ledger.dedupe([1, 1, 1]), [1])

    def test_ledger_chunk(self):
        self.assertEqual(ledger.chunk([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]])
        self.assertEqual(ledger.chunk([1, 2, 3, 4], 2), [[1, 2], [3, 4]])
        self.assertEqual(ledger.chunk([], 3), [])
        self.assertEqual(ledger.chunk(['a'], 1), [['a']])
        self.assertEqual(ledger.chunk([1, 2, 3], 5), [[1, 2, 3]])
        with self.assertRaises(ValueError):
            ledger.chunk([1, 2], 0)

    def test_pricing_merge_ranges(self):
        self.assertEqual(pricing.merge_ranges([(1, 3), (3, 5)]), [(1, 5)])
        self.assertEqual(pricing.merge_ranges([(5, 6), (1, 2)]), [(1, 2), (5, 6)])
        self.assertEqual(pricing.merge_ranges([(1, 10), (2, 3)]), [(1, 10)])
        self.assertEqual(pricing.merge_ranges([]), [])
        self.assertEqual(pricing.merge_ranges([(4, 8), (1, 5)]), [(1, 8)])

    def test_pricing_paginate(self):
        self.assertEqual(pricing.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 1, 3), [1, 2, 3])
        self.assertEqual(pricing.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 4, 3), [10])
        self.assertEqual(pricing.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 5, 3), [])
        self.assertEqual(pricing.paginate([], 1, 5), [])
        with self.assertRaises(ValueError):
            pricing.paginate([1, 2], 0, 2)

    def test_pricing_clamp(self):
        self.assertEqual(pricing.clamp(5, 0, 10), 5)
        self.assertEqual(pricing.clamp(-3, 0, 10), 0)
        self.assertEqual(pricing.clamp(15, 0, 10), 10)
        self.assertEqual(pricing.clamp(10, 0, 10), 10)
        self.assertEqual(pricing.clamp(0, 0, 10), 0)
        self.assertEqual(pricing.clamp(7, 7, 7), 7)
        self.assertEqual(pricing.clamp(-20, -30, -10), -20)

    def test_orders_running_total(self):
        self.assertEqual(orders.running_total([1, 2, 3]), [1, 3, 6])
        self.assertEqual(orders.running_total([]), [])
        self.assertEqual(orders.running_total([5]), [5])
        self.assertEqual(orders.running_total([2, -2, 2]), [2, 0, 2])

    def test_orders_parse_duration(self):
        self.assertEqual(orders.parse_duration('1h30m'), 5400)
        self.assertEqual(orders.parse_duration('45s'), 45)
        self.assertEqual(orders.parse_duration('2h'), 7200)
        self.assertEqual(orders.parse_duration('1h1m1s'), 3661)
        with self.assertRaises(ValueError):
            orders.parse_duration('')
        with self.assertRaises(ValueError):
            orders.parse_duration('5x')
        self.assertEqual(orders.parse_duration('10m5s'), 605)

    def test_payroll_moving_average(self):
        self.assertEqual(payroll.moving_average([1, 2, 3, 4], 2), [1.5, 2.5, 3.5])
        self.assertEqual(payroll.moving_average([5], 1), [5.0])
        self.assertEqual(payroll.moving_average([1, 2, 3], 3), [2.0])
        self.assertEqual(payroll.moving_average([2, 4, 6, 8, 10], 3), [4.0, 6.0, 8.0])
        with self.assertRaises(ValueError):
            payroll.moving_average([1, 2], 0)

    def test_payroll_rle(self):
        self.assertEqual(payroll.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(payroll.rle(''), [])
        self.assertEqual(payroll.rle('abc'), [('a', 1), ('b', 1), ('c', 1)])
        self.assertEqual(payroll.rle('zz'), [('z', 2)])
