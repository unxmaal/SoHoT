import unittest

from wharf import orders
from wharf import weather
from wharf import catalog
from wharf import survey
from wharf import metrics
from wharf import report


class Hidden(unittest.TestCase):
    def test_orders_invert(self):
        self.assertEqual(orders.invert({'a': 1, 'b': 2, 'c': 1}), {1: ['a', 'c'], 2: ['b']})
        self.assertEqual(orders.invert({}), {})
        self.assertEqual(orders.invert({'x': 'y'}), {'y': ['x']})
        self.assertEqual(orders.invert({'q': 0, 'p': 0, 'r': 0}), {0: ['p', 'q', 'r']})

    def test_orders_merge_ranges(self):
        self.assertEqual(orders.merge_ranges([(1, 3), (3, 5)]), [(1, 5)])
        self.assertEqual(orders.merge_ranges([(5, 6), (1, 2)]), [(1, 2), (5, 6)])
        self.assertEqual(orders.merge_ranges([(1, 10), (2, 3)]), [(1, 10)])
        self.assertEqual(orders.merge_ranges([]), [])
        self.assertEqual(orders.merge_ranges([(4, 8), (1, 5)]), [(1, 8)])

    def test_orders_moving_average(self):
        self.assertEqual(orders.moving_average([1, 2, 3, 4], 2), [1.5, 2.5, 3.5])
        self.assertEqual(orders.moving_average([5], 1), [5.0])
        self.assertEqual(orders.moving_average([1, 2, 3], 3), [2.0])
        self.assertEqual(orders.moving_average([2, 4, 6, 8, 10], 3), [4.0, 6.0, 8.0])
        with self.assertRaises(ValueError):
            orders.moving_average([1, 2], 0)

    def test_weather_rle(self):
        self.assertEqual(weather.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(weather.rle(''), [])
        self.assertEqual(weather.rle('abc'), [('a', 1), ('b', 1), ('c', 1)])
        self.assertEqual(weather.rle('zz'), [('z', 2)])

    def test_weather_median(self):
        self.assertEqual(weather.median([3, 1, 2]), 2)
        self.assertEqual(weather.median([4, 1, 3, 2]), 2.5)
        self.assertEqual(weather.median([5]), 5)
        self.assertEqual(weather.median([1, 2]), 1.5)
        self.assertEqual(weather.median([10, 2, 38, 23, 38, 23]), 23.0)
        with self.assertRaises(ValueError):
            weather.median([])

    def test_weather_running_total(self):
        self.assertEqual(weather.running_total([1, 2, 3]), [1, 3, 6])
        self.assertEqual(weather.running_total([]), [])
        self.assertEqual(weather.running_total([5]), [5])
        self.assertEqual(weather.running_total([2, -2, 2]), [2, 0, 2])

    def test_catalog_grade(self):
        self.assertEqual(catalog.grade(95), 'A')
        self.assertEqual(catalog.grade(90), 'A')
        self.assertEqual(catalog.grade(85), 'B')
        self.assertEqual(catalog.grade(80), 'B')
        self.assertEqual(catalog.grade(61), 'D')
        self.assertEqual(catalog.grade(59), 'F')
        self.assertEqual(catalog.grade(0), 'F')

    def test_catalog_truncate_words(self):
        self.assertEqual(catalog.truncate_words('the quick brown fox', 2), 'the quick...')
        self.assertEqual(catalog.truncate_words('tea time', 2), 'tea time')
        self.assertEqual(catalog.truncate_words('', 3), '')
        self.assertEqual(catalog.truncate_words('one two three', 1), 'one...')

    def test_catalog_parse_duration(self):
        self.assertEqual(catalog.parse_duration('1h30m'), 5400)
        self.assertEqual(catalog.parse_duration('45s'), 45)
        self.assertEqual(catalog.parse_duration('2h'), 7200)
        self.assertEqual(catalog.parse_duration('1h1m1s'), 3661)
        with self.assertRaises(ValueError):
            catalog.parse_duration('')
        with self.assertRaises(ValueError):
            catalog.parse_duration('5x')
        self.assertEqual(catalog.parse_duration('10m5s'), 605)

    def test_survey_top_n(self):
        self.assertEqual(survey.top_n({'tea': 3, 'milk': 3, 'jam': 1}, 2), ['milk', 'tea'])
        self.assertEqual(survey.top_n({'a': 1}, 5), ['a'])
        self.assertEqual(survey.top_n({}, 2), [])
        self.assertEqual(survey.top_n({'x': 2, 'y': 5, 'z': 2}, 2), ['y', 'x'])

    def test_survey_is_leap(self):
        self.assertEqual(survey.is_leap(2024), True)
        self.assertEqual(survey.is_leap(1900), False)
        self.assertEqual(survey.is_leap(2000), True)
        self.assertEqual(survey.is_leap(2023), False)
        self.assertEqual(survey.is_leap(2400), True)
        self.assertEqual(survey.is_leap(2100), False)

    def test_metrics_luhn_valid(self):
        self.assertEqual(metrics.luhn_valid('4539 1488 0343 6467'), True)
        self.assertEqual(metrics.luhn_valid('79927398713'), True)
        self.assertEqual(metrics.luhn_valid('79927398710'), False)
        self.assertEqual(metrics.luhn_valid(''), False)
        self.assertEqual(metrics.luhn_valid('059'), True)

    def test_metrics_weighted_mean(self):
        self.assertEqual(metrics.weighted_mean([1, 2, 3], [1, 1, 1]), 2.0)
        self.assertEqual(metrics.weighted_mean([10, 20], [1, 3]), 17.5)
        self.assertEqual(metrics.weighted_mean([4], [2]), 4.0)
        with self.assertRaises(ValueError):
            metrics.weighted_mean([5, 5], [0, 0])
        self.assertEqual(metrics.weighted_mean([1, 2], [0.5, 1.5]), 1.75)

    def test_metrics_dedupe(self):
        self.assertEqual(metrics.dedupe([3, 1, 3, 2, 1]), [3, 1, 2])
        self.assertEqual(metrics.dedupe(['b', 'a', 'b']), ['b', 'a'])
        self.assertEqual(metrics.dedupe([]), [])
        self.assertEqual(metrics.dedupe([1, 1, 1]), [1])

    def test_report_mooring_total(self):
        self.assertEqual(report.mooring_total({'a': 1, 'b': 2, 'c': 1}), {'mooring_total': {1: ['a', 'c'], 2: ['b']}})
        self.assertEqual(report.mooring_total({}), {'mooring_total': {}})
        self.assertEqual(report.mooring_total({'x': 'y'}), {'mooring_total': {'y': ['x']}})
        self.assertEqual(report.mooring_total({'q': 0, 'p': 0, 'r': 0}), {'mooring_total': {0: ['p', 'q', 'r']}})

    def test_report_harbor_row(self):
        self.assertEqual(report.harbor_row([(1, 3), (3, 5)]), {'harbor_row': [(1, 5)]})
        self.assertEqual(report.harbor_row([(5, 6), (1, 2)]), {'harbor_row': [(1, 2), (5, 6)]})
        self.assertEqual(report.harbor_row([(1, 10), (2, 3)]), {'harbor_row': [(1, 10)]})
        self.assertEqual(report.harbor_row([]), {'harbor_row': []})
        self.assertEqual(report.harbor_row([(4, 8), (1, 5)]), {'harbor_row': [(1, 8)]})

    def test_report_berth_view(self):
        self.assertEqual(report.berth_view([1, 2, 3, 4], 2), {'berth_view': [1.5, 2.5, 3.5]})
        self.assertEqual(report.berth_view([5], 1), {'berth_view': [5.0]})
        self.assertEqual(report.berth_view([1, 2, 3], 3), {'berth_view': [2.0]})
        self.assertEqual(report.berth_view([2, 4, 6, 8, 10], 3), {'berth_view': [4.0, 6.0, 8.0]})
        with self.assertRaises(ValueError):
            report.berth_view([1, 2], 0)

    def test_report_buoy_view(self):
        self.assertEqual(report.buoy_view('aaab'), {'buoy_view': [('a', 3), ('b', 1)]})
        self.assertEqual(report.buoy_view(''), {'buoy_view': []})
        self.assertEqual(report.buoy_view('abc'), {'buoy_view': [('a', 1), ('b', 1), ('c', 1)]})
        self.assertEqual(report.buoy_view('zz'), {'buoy_view': [('z', 2)]})

    def test_report_berth_total(self):
        self.assertEqual(report.berth_total('the quick brown fox', 2), {'berth_total': 'the quick...'})
        self.assertEqual(report.berth_total('tea time', 2), {'berth_total': 'tea time'})
        self.assertEqual(report.berth_total('', 3), {'berth_total': ''})
        self.assertEqual(report.berth_total('one two three', 1), {'berth_total': 'one...'})
