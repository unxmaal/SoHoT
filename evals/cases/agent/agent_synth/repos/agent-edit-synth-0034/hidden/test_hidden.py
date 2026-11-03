import unittest

from granary import survey
from granary import routes
from granary import pricing
from granary import stock


class Hidden(unittest.TestCase):
    def test_survey_running_total(self):
        self.assertEqual(survey.running_total([1, 2, 3]), [1, 3, 6])
        self.assertEqual(survey.running_total([]), [])
        self.assertEqual(survey.running_total([5]), [5])
        self.assertEqual(survey.running_total([2, -2, 2]), [2, 0, 2])

    def test_survey_chunk(self):
        self.assertEqual(survey.chunk([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]])
        self.assertEqual(survey.chunk([1, 2, 3, 4], 2), [[1, 2], [3, 4]])
        self.assertEqual(survey.chunk([], 3), [])
        self.assertEqual(survey.chunk(['a'], 1), [['a']])
        self.assertEqual(survey.chunk([1, 2, 3], 5), [[1, 2, 3]])
        with self.assertRaises(ValueError):
            survey.chunk([1, 2], 0)

    def test_survey_snake_case(self):
        self.assertEqual(survey.snake_case('OrderTotal'), 'order_total')
        self.assertEqual(survey.snake_case('plain'), 'plain')
        self.assertEqual(survey.snake_case('A'), 'a')
        self.assertEqual(survey.snake_case('ShipToCity'), 'ship_to_city')

    def test_routes_weighted_mean(self):
        self.assertEqual(routes.weighted_mean([1, 2, 3], [1, 1, 1]), 2.0)
        self.assertEqual(routes.weighted_mean([10, 20], [1, 3]), 17.5)
        self.assertEqual(routes.weighted_mean([4], [2]), 4.0)
        with self.assertRaises(ValueError):
            routes.weighted_mean([5, 5], [0, 0])
        self.assertEqual(routes.weighted_mean([1, 2], [0.5, 1.5]), 1.75)

    def test_routes_invert(self):
        self.assertEqual(routes.invert({'a': 1, 'b': 2, 'c': 1}), {1: ['a', 'c'], 2: ['b']})
        self.assertEqual(routes.invert({}), {})
        self.assertEqual(routes.invert({'x': 'y'}), {'y': ['x']})
        self.assertEqual(routes.invert({'q': 0, 'p': 0, 'r': 0}), {0: ['p', 'q', 'r']})

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

    def test_pricing_percent_change(self):
        self.assertEqual(pricing.percent_change(50, 75), 50.0)
        self.assertEqual(pricing.percent_change(200, 150), -25.0)
        self.assertEqual(pricing.percent_change(80, 80), 0.0)
        self.assertEqual(pricing.percent_change(3, 4), 33.33)
        with self.assertRaises(ValueError):
            pricing.percent_change(0, 5)
        self.assertEqual(pricing.percent_change(-10, -5), -50.0)

    def test_stock_median(self):
        self.assertEqual(stock.median([3, 1, 2]), 2)
        self.assertEqual(stock.median([4, 1, 3, 2]), 2.5)
        self.assertEqual(stock.median([5]), 5)
        self.assertEqual(stock.median([1, 2]), 1.5)
        self.assertEqual(stock.median([10, 2, 38, 23, 38, 23]), 23.0)
        with self.assertRaises(ValueError):
            stock.median([])

    def test_stock_dedupe(self):
        self.assertEqual(stock.dedupe([3, 1, 3, 2, 1]), [3, 1, 2])
        self.assertEqual(stock.dedupe(['b', 'a', 'b']), ['b', 'a'])
        self.assertEqual(stock.dedupe([]), [])
        self.assertEqual(stock.dedupe([1, 1, 1]), [1])

    def test_feature(self):
        with self.assertRaises(ValueError):
            routes.weighted_mean([1, 2, 3], [1, 1])
        with self.assertRaises(ValueError):
            routes.weighted_mean([4], [1, 2])
