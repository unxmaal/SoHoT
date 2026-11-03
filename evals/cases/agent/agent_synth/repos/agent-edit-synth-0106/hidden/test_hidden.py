import unittest

from wharf import tickets
from wharf import metrics
from wharf import timesheet
from wharf import stock


class Hidden(unittest.TestCase):
    def test_tickets_truncate_words(self):
        self.assertEqual(tickets.truncate_words('the quick brown fox', 2), 'the quick...')
        self.assertEqual(tickets.truncate_words('tea time', 2), 'tea time')
        self.assertEqual(tickets.truncate_words('', 3), '')
        self.assertEqual(tickets.truncate_words('one two three', 1), 'one...')

    def test_tickets_format_cents(self):
        self.assertEqual(tickets.format_cents(0), '$0.00')
        self.assertEqual(tickets.format_cents(123456), '$1,234.56')
        self.assertEqual(tickets.format_cents(-105), '-$1.05')
        self.assertEqual(tickets.format_cents(5), '$0.05')
        self.assertEqual(tickets.format_cents(100000000), '$1,000,000.00')

    def test_tickets_snake_case(self):
        self.assertEqual(tickets.snake_case('OrderTotal'), 'order_total')
        self.assertEqual(tickets.snake_case('plain'), 'plain')
        self.assertEqual(tickets.snake_case('A'), 'a')
        self.assertEqual(tickets.snake_case('ShipToCity'), 'ship_to_city')

    def test_metrics_merge_ranges(self):
        self.assertEqual(metrics.merge_ranges([(1, 3), (3, 5)]), [(1, 5)])
        self.assertEqual(metrics.merge_ranges([(5, 6), (1, 2)]), [(1, 2), (5, 6)])
        self.assertEqual(metrics.merge_ranges([(1, 10), (2, 3)]), [(1, 10)])
        self.assertEqual(metrics.merge_ranges([]), [])
        self.assertEqual(metrics.merge_ranges([(4, 8), (1, 5)]), [(1, 8)])

    def test_metrics_invert(self):
        self.assertEqual(metrics.invert({'a': 1, 'b': 2, 'c': 1}), {1: ['a', 'c'], 2: ['b']})
        self.assertEqual(metrics.invert({}), {})
        self.assertEqual(metrics.invert({'x': 'y'}), {'y': ['x']})
        self.assertEqual(metrics.invert({'q': 0, 'p': 0, 'r': 0}), {0: ['p', 'q', 'r']})

    def test_timesheet_chunk(self):
        self.assertEqual(timesheet.chunk([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]])
        self.assertEqual(timesheet.chunk([1, 2, 3, 4], 2), [[1, 2], [3, 4]])
        self.assertEqual(timesheet.chunk([], 3), [])
        self.assertEqual(timesheet.chunk(['a'], 1), [['a']])
        self.assertEqual(timesheet.chunk([1, 2, 3], 5), [[1, 2, 3]])
        with self.assertRaises(ValueError):
            timesheet.chunk([1, 2], 0)

    def test_timesheet_median(self):
        self.assertEqual(timesheet.median([3, 1, 2]), 2)
        self.assertEqual(timesheet.median([4, 1, 3, 2]), 2.5)
        self.assertEqual(timesheet.median([5]), 5)
        self.assertEqual(timesheet.median([1, 2]), 1.5)
        self.assertEqual(timesheet.median([10, 2, 38, 23, 38, 23]), 23.0)
        with self.assertRaises(ValueError):
            timesheet.median([])

    def test_stock_rle(self):
        self.assertEqual(stock.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(stock.rle(''), [])
        self.assertEqual(stock.rle('abc'), [('a', 1), ('b', 1), ('c', 1)])
        self.assertEqual(stock.rle('zz'), [('z', 2)])

    def test_stock_parse_duration(self):
        self.assertEqual(stock.parse_duration('1h30m'), 5400)
        self.assertEqual(stock.parse_duration('45s'), 45)
        self.assertEqual(stock.parse_duration('2h'), 7200)
        self.assertEqual(stock.parse_duration('1h1m1s'), 3661)
        with self.assertRaises(ValueError):
            stock.parse_duration('')
        with self.assertRaises(ValueError):
            stock.parse_duration('5x')
        self.assertEqual(stock.parse_duration('10m5s'), 605)

    def test_stock_paginate(self):
        self.assertEqual(stock.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 1, 3), [1, 2, 3])
        self.assertEqual(stock.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 4, 3), [10])
        self.assertEqual(stock.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 5, 3), [])
        self.assertEqual(stock.paginate([], 1, 5), [])
        with self.assertRaises(ValueError):
            stock.paginate([1, 2], 0, 2)

    def test_feature(self):
        self.assertEqual(timesheet.median([], default=0), 0)
        self.assertEqual(timesheet.median([], default=-1), -1)
        self.assertEqual(timesheet.median([1, 3], default=0), 2.0)
