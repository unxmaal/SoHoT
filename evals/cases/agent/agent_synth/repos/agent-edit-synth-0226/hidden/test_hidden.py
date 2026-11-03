import unittest

from mill import billing
from mill import catalog
from mill import stock
from mill import sensors


class Hidden(unittest.TestCase):
    def test_billing_running_total(self):
        self.assertEqual(billing.running_total([1, 2, 3]), [1, 3, 6])
        self.assertEqual(billing.running_total([]), [])
        self.assertEqual(billing.running_total([5]), [5])
        self.assertEqual(billing.running_total([2, -2, 2]), [2, 0, 2])

    def test_billing_paginate(self):
        self.assertEqual(billing.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 1, 3), [1, 2, 3])
        self.assertEqual(billing.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 4, 3), [10])
        self.assertEqual(billing.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 5, 3), [])
        self.assertEqual(billing.paginate([], 1, 5), [])
        with self.assertRaises(ValueError):
            billing.paginate([1, 2], 0, 2)

    def test_billing_merge_ranges(self):
        self.assertEqual(billing.merge_ranges([(1, 3), (3, 5)]), [(1, 5)])
        self.assertEqual(billing.merge_ranges([(5, 6), (1, 2)]), [(1, 2), (5, 6)])
        self.assertEqual(billing.merge_ranges([(1, 10), (2, 3)]), [(1, 10)])
        self.assertEqual(billing.merge_ranges([]), [])
        self.assertEqual(billing.merge_ranges([(4, 8), (1, 5)]), [(1, 8)])

    def test_catalog_clamp(self):
        self.assertEqual(catalog.clamp(5, 0, 10), 5)
        self.assertEqual(catalog.clamp(-3, 0, 10), 0)
        self.assertEqual(catalog.clamp(15, 0, 10), 10)
        self.assertEqual(catalog.clamp(10, 0, 10), 10)
        self.assertEqual(catalog.clamp(0, 0, 10), 0)
        self.assertEqual(catalog.clamp(7, 7, 7), 7)
        self.assertEqual(catalog.clamp(-20, -30, -10), -20)

    def test_catalog_truncate_words(self):
        self.assertEqual(catalog.truncate_words('the quick brown fox', 2), 'the quick...')
        self.assertEqual(catalog.truncate_words('tea time', 2), 'tea time')
        self.assertEqual(catalog.truncate_words('', 3), '')
        self.assertEqual(catalog.truncate_words('one two three', 1), 'one...')

    def test_catalog_rle(self):
        self.assertEqual(catalog.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(catalog.rle(''), [])
        self.assertEqual(catalog.rle('abc'), [('a', 1), ('b', 1), ('c', 1)])
        self.assertEqual(catalog.rle('zz'), [('z', 2)])

    def test_stock_is_leap(self):
        self.assertEqual(stock.is_leap(2024), True)
        self.assertEqual(stock.is_leap(1900), False)
        self.assertEqual(stock.is_leap(2000), True)
        self.assertEqual(stock.is_leap(2023), False)
        self.assertEqual(stock.is_leap(2400), True)
        self.assertEqual(stock.is_leap(2100), False)

    def test_stock_percent_change(self):
        self.assertEqual(stock.percent_change(50, 75), 50.0)
        self.assertEqual(stock.percent_change(200, 150), -25.0)
        self.assertEqual(stock.percent_change(80, 80), 0.0)
        self.assertEqual(stock.percent_change(3, 4), 33.33)
        with self.assertRaises(ValueError):
            stock.percent_change(0, 5)
        self.assertEqual(stock.percent_change(-10, -5), -50.0)

    def test_stock_word_count(self):
        self.assertEqual(stock.word_count('a b'), 2)
        self.assertEqual(stock.word_count('  tea  and   milk '), 3)
        self.assertEqual(stock.word_count(''), 0)
        self.assertEqual(stock.word_count('one'), 1)

    def test_sensors_dedupe(self):
        self.assertEqual(sensors.dedupe([3, 1, 3, 2, 1]), [3, 1, 2])
        self.assertEqual(sensors.dedupe(['b', 'a', 'b']), ['b', 'a'])
        self.assertEqual(sensors.dedupe([]), [])
        self.assertEqual(sensors.dedupe([1, 1, 1]), [1])

    def test_sensors_moving_average(self):
        self.assertEqual(sensors.moving_average([1, 2, 3, 4], 2), [1.5, 2.5, 3.5])
        self.assertEqual(sensors.moving_average([5], 1), [5.0])
        self.assertEqual(sensors.moving_average([1, 2, 3], 3), [2.0])
        self.assertEqual(sensors.moving_average([2, 4, 6, 8, 10], 3), [4.0, 6.0, 8.0])
        with self.assertRaises(ValueError):
            sensors.moving_average([1, 2], 0)

    def test_sensors_top_n(self):
        self.assertEqual(sensors.top_n({'tea': 3, 'milk': 3, 'jam': 1}, 2), ['milk', 'tea'])
        self.assertEqual(sensors.top_n({'a': 1}, 5), ['a'])
        self.assertEqual(sensors.top_n({}, 2), [])
        self.assertEqual(sensors.top_n({'x': 2, 'y': 5, 'z': 2}, 2), ['y', 'x'])

    def test_feature(self):
        with self.assertRaises(ValueError):
            sensors.moving_average([1, 2], 3)
        with self.assertRaises(ValueError):
            sensors.moving_average([], 1)
