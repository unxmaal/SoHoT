import unittest

from beacon import fleet
from beacon import metrics
from beacon import routes
from beacon import survey
from beacon import ledger


class Hidden(unittest.TestCase):
    def test_fleet_weighted_mean(self):
        self.assertEqual(fleet.weighted_mean([1, 2, 3], [1, 1, 1]), 2.0)
        self.assertEqual(fleet.weighted_mean([10, 20], [1, 3]), 17.5)
        self.assertEqual(fleet.weighted_mean([4], [2]), 4.0)
        with self.assertRaises(ValueError):
            fleet.weighted_mean([5, 5], [0, 0])
        self.assertEqual(fleet.weighted_mean([1, 2], [0.5, 1.5]), 1.75)

    def test_fleet_percent_change(self):
        self.assertEqual(fleet.percent_change(50, 75), 50.0)
        self.assertEqual(fleet.percent_change(200, 150), -25.0)
        self.assertEqual(fleet.percent_change(80, 80), 0.0)
        self.assertEqual(fleet.percent_change(3, 4), 33.33)
        with self.assertRaises(ValueError):
            fleet.percent_change(0, 5)
        self.assertEqual(fleet.percent_change(-10, -5), -50.0)

    def test_metrics_word_count(self):
        self.assertEqual(metrics.word_count('a b'), 2)
        self.assertEqual(metrics.word_count('  tea  and   milk '), 3)
        self.assertEqual(metrics.word_count(''), 0)
        self.assertEqual(metrics.word_count('one'), 1)

    def test_metrics_rle(self):
        self.assertEqual(metrics.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(metrics.rle(''), [])
        self.assertEqual(metrics.rle('abc'), [('a', 1), ('b', 1), ('c', 1)])
        self.assertEqual(metrics.rle('zz'), [('z', 2)])

    def test_routes_parse_duration(self):
        self.assertEqual(routes.parse_duration('1h30m'), 5400)
        self.assertEqual(routes.parse_duration('45s'), 45)
        self.assertEqual(routes.parse_duration('2h'), 7200)
        self.assertEqual(routes.parse_duration('1h1m1s'), 3661)
        with self.assertRaises(ValueError):
            routes.parse_duration('')
        with self.assertRaises(ValueError):
            routes.parse_duration('5x')
        self.assertEqual(routes.parse_duration('10m5s'), 605)

    def test_routes_invert(self):
        self.assertEqual(routes.invert({'a': 1, 'b': 2, 'c': 1}), {1: ['a', 'c'], 2: ['b']})
        self.assertEqual(routes.invert({}), {})
        self.assertEqual(routes.invert({'x': 'y'}), {'y': ['x']})
        self.assertEqual(routes.invert({'q': 0, 'p': 0, 'r': 0}), {0: ['p', 'q', 'r']})

    def test_routes_luhn_valid(self):
        self.assertEqual(routes.luhn_valid('4539 1488 0343 6467'), True)
        self.assertEqual(routes.luhn_valid('79927398713'), True)
        self.assertEqual(routes.luhn_valid('79927398710'), False)
        self.assertEqual(routes.luhn_valid(''), False)
        self.assertEqual(routes.luhn_valid('059'), True)

    def test_survey_dedupe(self):
        self.assertEqual(survey.dedupe([3, 1, 3, 2, 1]), [3, 1, 2])
        self.assertEqual(survey.dedupe(['b', 'a', 'b']), ['b', 'a'])
        self.assertEqual(survey.dedupe([]), [])
        self.assertEqual(survey.dedupe([1, 1, 1]), [1])

    def test_survey_median(self):
        self.assertEqual(survey.median([3, 1, 2]), 2)
        self.assertEqual(survey.median([4, 1, 3, 2]), 2.5)
        self.assertEqual(survey.median([5]), 5)
        self.assertEqual(survey.median([1, 2]), 1.5)
        self.assertEqual(survey.median([10, 2, 38, 23, 38, 23]), 23.0)
        with self.assertRaises(ValueError):
            survey.median([])

    def test_survey_running_total(self):
        self.assertEqual(survey.running_total([1, 2, 3]), [1, 3, 6])
        self.assertEqual(survey.running_total([]), [])
        self.assertEqual(survey.running_total([5]), [5])
        self.assertEqual(survey.running_total([2, -2, 2]), [2, 0, 2])

    def test_ledger_moving_average(self):
        self.assertEqual(ledger.moving_average([1, 2, 3, 4], 2), [1.5, 2.5, 3.5])
        self.assertEqual(ledger.moving_average([5], 1), [5.0])
        self.assertEqual(ledger.moving_average([1, 2, 3], 3), [2.0])
        self.assertEqual(ledger.moving_average([2, 4, 6, 8, 10], 3), [4.0, 6.0, 8.0])
        with self.assertRaises(ValueError):
            ledger.moving_average([1, 2], 0)

    def test_ledger_snake_case(self):
        self.assertEqual(ledger.snake_case('OrderTotal'), 'order_total')
        self.assertEqual(ledger.snake_case('plain'), 'plain')
        self.assertEqual(ledger.snake_case('A'), 'a')
        self.assertEqual(ledger.snake_case('ShipToCity'), 'ship_to_city')

    def test_ledger_truncate_words(self):
        self.assertEqual(ledger.truncate_words('the quick brown fox', 2), 'the quick...')
        self.assertEqual(ledger.truncate_words('tea time', 2), 'tea time')
        self.assertEqual(ledger.truncate_words('', 3), '')
        self.assertEqual(ledger.truncate_words('one two three', 1), 'one...')
