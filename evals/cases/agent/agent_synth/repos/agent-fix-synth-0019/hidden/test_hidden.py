import unittest

from wharf import metrics
from wharf import survey
from wharf import kitchen
from wharf import pricing
from wharf import stock


class Hidden(unittest.TestCase):
    def test_metrics_bucket(self):
        self.assertEqual(metrics.bucket(5, [0, 5, 10]), 2)
        self.assertEqual(metrics.bucket(-1, [0, 5, 10]), 0)
        self.assertEqual(metrics.bucket(12, [0, 5, 10]), 3)
        self.assertEqual(metrics.bucket(0, [0, 5, 10]), 1)
        self.assertEqual(metrics.bucket(7, []), 0)

    def test_metrics_weighted_mean(self):
        self.assertEqual(metrics.weighted_mean([1, 2, 3], [1, 1, 1]), 2.0)
        self.assertEqual(metrics.weighted_mean([10, 20], [1, 3]), 17.5)
        self.assertEqual(metrics.weighted_mean([4], [2]), 4.0)
        with self.assertRaises(ValueError):
            metrics.weighted_mean([5, 5], [0, 0])
        self.assertEqual(metrics.weighted_mean([1, 2], [0.5, 1.5]), 1.75)

    def test_survey_running_total(self):
        self.assertEqual(survey.running_total([1, 2, 3]), [1, 3, 6])
        self.assertEqual(survey.running_total([]), [])
        self.assertEqual(survey.running_total([5]), [5])
        self.assertEqual(survey.running_total([2, -2, 2]), [2, 0, 2])

    def test_survey_merge_ranges(self):
        self.assertEqual(survey.merge_ranges([(1, 3), (3, 5)]), [(1, 5)])
        self.assertEqual(survey.merge_ranges([(5, 6), (1, 2)]), [(1, 2), (5, 6)])
        self.assertEqual(survey.merge_ranges([(1, 10), (2, 3)]), [(1, 10)])
        self.assertEqual(survey.merge_ranges([]), [])
        self.assertEqual(survey.merge_ranges([(4, 8), (1, 5)]), [(1, 8)])

    def test_kitchen_invert(self):
        self.assertEqual(kitchen.invert({'a': 1, 'b': 2, 'c': 1}), {1: ['a', 'c'], 2: ['b']})
        self.assertEqual(kitchen.invert({}), {})
        self.assertEqual(kitchen.invert({'x': 'y'}), {'y': ['x']})
        self.assertEqual(kitchen.invert({'q': 0, 'p': 0, 'r': 0}), {0: ['p', 'q', 'r']})

    def test_kitchen_median(self):
        self.assertEqual(kitchen.median([3, 1, 2]), 2)
        self.assertEqual(kitchen.median([4, 1, 3, 2]), 2.5)
        self.assertEqual(kitchen.median([5]), 5)
        self.assertEqual(kitchen.median([1, 2]), 1.5)
        self.assertEqual(kitchen.median([10, 2, 38, 23, 38, 23]), 23.0)
        with self.assertRaises(ValueError):
            kitchen.median([])

    def test_kitchen_paginate(self):
        self.assertEqual(kitchen.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 1, 3), [1, 2, 3])
        self.assertEqual(kitchen.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 4, 3), [10])
        self.assertEqual(kitchen.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 5, 3), [])
        self.assertEqual(kitchen.paginate([], 1, 5), [])
        with self.assertRaises(ValueError):
            kitchen.paginate([1, 2], 0, 2)

    def test_pricing_parse_duration(self):
        self.assertEqual(pricing.parse_duration('1h30m'), 5400)
        self.assertEqual(pricing.parse_duration('45s'), 45)
        self.assertEqual(pricing.parse_duration('2h'), 7200)
        self.assertEqual(pricing.parse_duration('1h1m1s'), 3661)
        with self.assertRaises(ValueError):
            pricing.parse_duration('')
        with self.assertRaises(ValueError):
            pricing.parse_duration('5x')
        self.assertEqual(pricing.parse_duration('10m5s'), 605)

    def test_pricing_moving_average(self):
        self.assertEqual(pricing.moving_average([1, 2, 3, 4], 2), [1.5, 2.5, 3.5])
        self.assertEqual(pricing.moving_average([5], 1), [5.0])
        self.assertEqual(pricing.moving_average([1, 2, 3], 3), [2.0])
        self.assertEqual(pricing.moving_average([2, 4, 6, 8, 10], 3), [4.0, 6.0, 8.0])
        with self.assertRaises(ValueError):
            pricing.moving_average([1, 2], 0)

    def test_stock_dedupe(self):
        self.assertEqual(stock.dedupe([3, 1, 3, 2, 1]), [3, 1, 2])
        self.assertEqual(stock.dedupe(['b', 'a', 'b']), ['b', 'a'])
        self.assertEqual(stock.dedupe([]), [])
        self.assertEqual(stock.dedupe([1, 1, 1]), [1])

    def test_stock_rle(self):
        self.assertEqual(stock.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(stock.rle(''), [])
        self.assertEqual(stock.rle('abc'), [('a', 1), ('b', 1), ('c', 1)])
        self.assertEqual(stock.rle('zz'), [('z', 2)])
