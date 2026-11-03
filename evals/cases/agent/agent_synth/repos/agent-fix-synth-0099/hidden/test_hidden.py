import unittest

from harbor import stock
from harbor import timesheet
from harbor import sensors
from harbor import shipping


class Hidden(unittest.TestCase):
    def test_stock_snake_case(self):
        self.assertEqual(stock.snake_case('OrderTotal'), 'order_total')
        self.assertEqual(stock.snake_case('plain'), 'plain')
        self.assertEqual(stock.snake_case('A'), 'a')
        self.assertEqual(stock.snake_case('ShipToCity'), 'ship_to_city')

    def test_stock_percent_change(self):
        self.assertEqual(stock.percent_change(50, 75), 50.0)
        self.assertEqual(stock.percent_change(200, 150), -25.0)
        self.assertEqual(stock.percent_change(80, 80), 0.0)
        self.assertEqual(stock.percent_change(3, 4), 33.33)
        with self.assertRaises(ValueError):
            stock.percent_change(0, 5)
        self.assertEqual(stock.percent_change(-10, -5), -50.0)

    def test_timesheet_dedupe(self):
        self.assertEqual(timesheet.dedupe([3, 1, 3, 2, 1]), [3, 1, 2])
        self.assertEqual(timesheet.dedupe(['b', 'a', 'b']), ['b', 'a'])
        self.assertEqual(timesheet.dedupe([]), [])
        self.assertEqual(timesheet.dedupe([1, 1, 1]), [1])

    def test_timesheet_rle(self):
        self.assertEqual(timesheet.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(timesheet.rle(''), [])
        self.assertEqual(timesheet.rle('abc'), [('a', 1), ('b', 1), ('c', 1)])
        self.assertEqual(timesheet.rle('zz'), [('z', 2)])

    def test_sensors_top_n(self):
        self.assertEqual(sensors.top_n({'tea': 3, 'milk': 3, 'jam': 1}, 2), ['milk', 'tea'])
        self.assertEqual(sensors.top_n({'a': 1}, 5), ['a'])
        self.assertEqual(sensors.top_n({}, 2), [])
        self.assertEqual(sensors.top_n({'x': 2, 'y': 5, 'z': 2}, 2), ['y', 'x'])

    def test_sensors_merge_ranges(self):
        self.assertEqual(sensors.merge_ranges([(1, 3), (3, 5)]), [(1, 5)])
        self.assertEqual(sensors.merge_ranges([(5, 6), (1, 2)]), [(1, 2), (5, 6)])
        self.assertEqual(sensors.merge_ranges([(1, 10), (2, 3)]), [(1, 10)])
        self.assertEqual(sensors.merge_ranges([]), [])
        self.assertEqual(sensors.merge_ranges([(4, 8), (1, 5)]), [(1, 8)])

    def test_shipping_paginate(self):
        self.assertEqual(shipping.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 1, 3), [1, 2, 3])
        self.assertEqual(shipping.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 4, 3), [10])
        self.assertEqual(shipping.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 5, 3), [])
        self.assertEqual(shipping.paginate([], 1, 5), [])
        with self.assertRaises(ValueError):
            shipping.paginate([1, 2], 0, 2)

    def test_shipping_chunk(self):
        self.assertEqual(shipping.chunk([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]])
        self.assertEqual(shipping.chunk([1, 2, 3, 4], 2), [[1, 2], [3, 4]])
        self.assertEqual(shipping.chunk([], 3), [])
        self.assertEqual(shipping.chunk(['a'], 1), [['a']])
        self.assertEqual(shipping.chunk([1, 2, 3], 5), [[1, 2, 3]])
        with self.assertRaises(ValueError):
            shipping.chunk([1, 2], 0)
