import unittest

from foundry import catalog
from foundry import sensors
from foundry import survey
from foundry import billing
from foundry import fleet
from foundry import report


class Hidden(unittest.TestCase):
    def test_catalog_format_cents(self):
        self.assertEqual(catalog.format_cents(0), '$0.00')
        self.assertEqual(catalog.format_cents(123456), '$1,234.56')
        self.assertEqual(catalog.format_cents(-105), '-$1.05')
        self.assertEqual(catalog.format_cents(5), '$0.05')
        self.assertEqual(catalog.format_cents(100000000), '$1,000,000.00')

    def test_catalog_snake_case(self):
        self.assertEqual(catalog.snake_case('OrderTotal'), 'order_total')
        self.assertEqual(catalog.snake_case('plain'), 'plain')
        self.assertEqual(catalog.snake_case('A'), 'a')
        self.assertEqual(catalog.snake_case('ShipToCity'), 'ship_to_city')

    def test_sensors_parse_duration(self):
        self.assertEqual(sensors.parse_duration('1h30m'), 5400)
        self.assertEqual(sensors.parse_duration('45s'), 45)
        self.assertEqual(sensors.parse_duration('2h'), 7200)
        self.assertEqual(sensors.parse_duration('1h1m1s'), 3661)
        with self.assertRaises(ValueError):
            sensors.parse_duration('')
        with self.assertRaises(ValueError):
            sensors.parse_duration('5x')
        self.assertEqual(sensors.parse_duration('10m5s'), 605)

    def test_sensors_paginate(self):
        self.assertEqual(sensors.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 1, 3), [1, 2, 3])
        self.assertEqual(sensors.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 4, 3), [10])
        self.assertEqual(sensors.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 5, 3), [])
        self.assertEqual(sensors.paginate([], 1, 5), [])
        with self.assertRaises(ValueError):
            sensors.paginate([1, 2], 0, 2)

    def test_sensors_median(self):
        self.assertEqual(sensors.median([3, 1, 2]), 2)
        self.assertEqual(sensors.median([4, 1, 3, 2]), 2.5)
        self.assertEqual(sensors.median([5]), 5)
        self.assertEqual(sensors.median([1, 2]), 1.5)
        self.assertEqual(sensors.median([10, 2, 38, 23, 38, 23]), 23.0)
        with self.assertRaises(ValueError):
            sensors.median([])

    def test_survey_rle(self):
        self.assertEqual(survey.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(survey.rle(''), [])
        self.assertEqual(survey.rle('abc'), [('a', 1), ('b', 1), ('c', 1)])
        self.assertEqual(survey.rle('zz'), [('z', 2)])

    def test_survey_grade(self):
        self.assertEqual(survey.grade(95), 'A')
        self.assertEqual(survey.grade(90), 'A')
        self.assertEqual(survey.grade(85), 'B')
        self.assertEqual(survey.grade(80), 'B')
        self.assertEqual(survey.grade(61), 'D')
        self.assertEqual(survey.grade(59), 'F')
        self.assertEqual(survey.grade(0), 'F')

    def test_survey_chunk(self):
        self.assertEqual(survey.chunk([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]])
        self.assertEqual(survey.chunk([1, 2, 3, 4], 2), [[1, 2], [3, 4]])
        self.assertEqual(survey.chunk([], 3), [])
        self.assertEqual(survey.chunk(['a'], 1), [['a']])
        self.assertEqual(survey.chunk([1, 2, 3], 5), [[1, 2, 3]])
        with self.assertRaises(ValueError):
            survey.chunk([1, 2], 0)

    def test_billing_luhn_valid(self):
        self.assertEqual(billing.luhn_valid('4539 1488 0343 6467'), True)
        self.assertEqual(billing.luhn_valid('79927398713'), True)
        self.assertEqual(billing.luhn_valid('79927398710'), False)
        self.assertEqual(billing.luhn_valid(''), False)
        self.assertEqual(billing.luhn_valid('059'), True)

    def test_billing_is_leap(self):
        self.assertEqual(billing.is_leap(2024), True)
        self.assertEqual(billing.is_leap(1900), False)
        self.assertEqual(billing.is_leap(2000), True)
        self.assertEqual(billing.is_leap(2023), False)
        self.assertEqual(billing.is_leap(2400), True)
        self.assertEqual(billing.is_leap(2100), False)

    def test_billing_weighted_mean(self):
        self.assertEqual(billing.weighted_mean([1, 2, 3], [1, 1, 1]), 2.0)
        self.assertEqual(billing.weighted_mean([10, 20], [1, 3]), 17.5)
        self.assertEqual(billing.weighted_mean([4], [2]), 4.0)
        with self.assertRaises(ValueError):
            billing.weighted_mean([5, 5], [0, 0])
        self.assertEqual(billing.weighted_mean([1, 2], [0.5, 1.5]), 1.75)

    def test_fleet_word_count(self):
        self.assertEqual(fleet.word_count('a b'), 2)
        self.assertEqual(fleet.word_count('  tea  and   milk '), 3)
        self.assertEqual(fleet.word_count(''), 0)
        self.assertEqual(fleet.word_count('one'), 1)

    def test_fleet_invert(self):
        self.assertEqual(fleet.invert({'a': 1, 'b': 2, 'c': 1}), {1: ['a', 'c'], 2: ['b']})
        self.assertEqual(fleet.invert({}), {})
        self.assertEqual(fleet.invert({'x': 'y'}), {'y': ['x']})
        self.assertEqual(fleet.invert({'q': 0, 'p': 0, 'r': 0}), {0: ['p', 'q', 'r']})

    def test_fleet_merge_ranges(self):
        self.assertEqual(fleet.merge_ranges([(1, 3), (3, 5)]), [(1, 5)])
        self.assertEqual(fleet.merge_ranges([(5, 6), (1, 2)]), [(1, 2), (5, 6)])
        self.assertEqual(fleet.merge_ranges([(1, 10), (2, 3)]), [(1, 10)])
        self.assertEqual(fleet.merge_ranges([]), [])
        self.assertEqual(fleet.merge_ranges([(4, 8), (1, 5)]), [(1, 8)])

    def test_report_sail_line(self):
        self.assertEqual(report.sail_line(0), {'sail_line': '$0.00'})
        self.assertEqual(report.sail_line(123456), {'sail_line': '$1,234.56'})
        self.assertEqual(report.sail_line(-105), {'sail_line': '-$1.05'})
        self.assertEqual(report.sail_line(5), {'sail_line': '$0.05'})
        self.assertEqual(report.sail_line(100000000), {'sail_line': '$1,000,000.00'})

    def test_report_lantern_summary(self):
        self.assertEqual(report.lantern_summary('OrderTotal'), {'lantern_summary': 'order_total'})
        self.assertEqual(report.lantern_summary('plain'), {'lantern_summary': 'plain'})
        self.assertEqual(report.lantern_summary('A'), {'lantern_summary': 'a'})
        self.assertEqual(report.lantern_summary('ShipToCity'), {'lantern_summary': 'ship_to_city'})

    def test_report_anchor_summary(self):
        self.assertEqual(report.anchor_summary('1h30m'), {'anchor_summary': 5400})
        self.assertEqual(report.anchor_summary('45s'), {'anchor_summary': 45})
        self.assertEqual(report.anchor_summary('2h'), {'anchor_summary': 7200})
        self.assertEqual(report.anchor_summary('1h1m1s'), {'anchor_summary': 3661})
        with self.assertRaises(ValueError):
            report.anchor_summary('')
        with self.assertRaises(ValueError):
            report.anchor_summary('5x')
        self.assertEqual(report.anchor_summary('10m5s'), {'anchor_summary': 605})

    def test_report_tide_total(self):
        self.assertEqual(report.tide_total([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 1, 3), {'tide_total': [1, 2, 3]})
        self.assertEqual(report.tide_total([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 4, 3), {'tide_total': [10]})
        self.assertEqual(report.tide_total([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 5, 3), {'tide_total': []})
        self.assertEqual(report.tide_total([], 1, 5), {'tide_total': []})
        with self.assertRaises(ValueError):
            report.tide_total([1, 2], 0, 2)

    def test_report_cargo_figure(self):
        self.assertEqual(report.cargo_figure('aaab'), {'cargo_figure': [('a', 3), ('b', 1)]})
        self.assertEqual(report.cargo_figure(''), {'cargo_figure': []})
        self.assertEqual(report.cargo_figure('abc'), {'cargo_figure': [('a', 1), ('b', 1), ('c', 1)]})
        self.assertEqual(report.cargo_figure('zz'), {'cargo_figure': [('z', 2)]})
