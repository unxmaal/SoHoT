import unittest

from mill import sensors
from mill import billing
from mill import survey
from mill import payroll
from mill import rosters
from mill import report


class Hidden(unittest.TestCase):
    def test_sensors_snake_case(self):
        self.assertEqual(sensors.snake_case('OrderTotal'), 'order_total')
        self.assertEqual(sensors.snake_case('plain'), 'plain')
        self.assertEqual(sensors.snake_case('A'), 'a')
        self.assertEqual(sensors.snake_case('ShipToCity'), 'ship_to_city')

    def test_sensors_merge_ranges(self):
        self.assertEqual(sensors.merge_ranges([(1, 3), (3, 5)]), [(1, 5)])
        self.assertEqual(sensors.merge_ranges([(5, 6), (1, 2)]), [(1, 2), (5, 6)])
        self.assertEqual(sensors.merge_ranges([(1, 10), (2, 3)]), [(1, 10)])
        self.assertEqual(sensors.merge_ranges([]), [])
        self.assertEqual(sensors.merge_ranges([(4, 8), (1, 5)]), [(1, 8)])

    def test_billing_running_total(self):
        self.assertEqual(billing.running_total([1, 2, 3]), [1, 3, 6])
        self.assertEqual(billing.running_total([]), [])
        self.assertEqual(billing.running_total([5]), [5])
        self.assertEqual(billing.running_total([2, -2, 2]), [2, 0, 2])

    def test_billing_invert(self):
        self.assertEqual(billing.invert({'a': 1, 'b': 2, 'c': 1}), {1: ['a', 'c'], 2: ['b']})
        self.assertEqual(billing.invert({}), {})
        self.assertEqual(billing.invert({'x': 'y'}), {'y': ['x']})
        self.assertEqual(billing.invert({'q': 0, 'p': 0, 'r': 0}), {0: ['p', 'q', 'r']})

    def test_billing_moving_average(self):
        self.assertEqual(billing.moving_average([1, 2, 3, 4], 2), [1.5, 2.5, 3.5])
        self.assertEqual(billing.moving_average([5], 1), [5.0])
        self.assertEqual(billing.moving_average([1, 2, 3], 3), [2.0])
        self.assertEqual(billing.moving_average([2, 4, 6, 8, 10], 3), [4.0, 6.0, 8.0])
        with self.assertRaises(ValueError):
            billing.moving_average([1, 2], 0)

    def test_survey_median(self):
        self.assertEqual(survey.median([3, 1, 2]), 2)
        self.assertEqual(survey.median([4, 1, 3, 2]), 2.5)
        self.assertEqual(survey.median([5]), 5)
        self.assertEqual(survey.median([1, 2]), 1.5)
        self.assertEqual(survey.median([10, 2, 38, 23, 38, 23]), 23.0)
        with self.assertRaises(ValueError):
            survey.median([])

    def test_survey_bucket(self):
        self.assertEqual(survey.bucket(5, [0, 5, 10]), 2)
        self.assertEqual(survey.bucket(-1, [0, 5, 10]), 0)
        self.assertEqual(survey.bucket(12, [0, 5, 10]), 3)
        self.assertEqual(survey.bucket(0, [0, 5, 10]), 1)
        self.assertEqual(survey.bucket(7, []), 0)

    def test_survey_grade(self):
        self.assertEqual(survey.grade(95), 'A')
        self.assertEqual(survey.grade(90), 'A')
        self.assertEqual(survey.grade(85), 'B')
        self.assertEqual(survey.grade(80), 'B')
        self.assertEqual(survey.grade(61), 'D')
        self.assertEqual(survey.grade(59), 'F')
        self.assertEqual(survey.grade(0), 'F')

    def test_payroll_weighted_mean(self):
        self.assertEqual(payroll.weighted_mean([1, 2, 3], [1, 1, 1]), 2.0)
        self.assertEqual(payroll.weighted_mean([10, 20], [1, 3]), 17.5)
        self.assertEqual(payroll.weighted_mean([4], [2]), 4.0)
        with self.assertRaises(ValueError):
            payroll.weighted_mean([5, 5], [0, 0])
        self.assertEqual(payroll.weighted_mean([1, 2], [0.5, 1.5]), 1.75)

    def test_payroll_paginate(self):
        self.assertEqual(payroll.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 1, 3), [1, 2, 3])
        self.assertEqual(payroll.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 4, 3), [10])
        self.assertEqual(payroll.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 5, 3), [])
        self.assertEqual(payroll.paginate([], 1, 5), [])
        with self.assertRaises(ValueError):
            payroll.paginate([1, 2], 0, 2)

    def test_rosters_dedupe(self):
        self.assertEqual(rosters.dedupe([3, 1, 3, 2, 1]), [3, 1, 2])
        self.assertEqual(rosters.dedupe(['b', 'a', 'b']), ['b', 'a'])
        self.assertEqual(rosters.dedupe([]), [])
        self.assertEqual(rosters.dedupe([1, 1, 1]), [1])

    def test_rosters_rle(self):
        self.assertEqual(rosters.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(rosters.rle(''), [])
        self.assertEqual(rosters.rle('abc'), [('a', 1), ('b', 1), ('c', 1)])
        self.assertEqual(rosters.rle('zz'), [('z', 2)])

    def test_report_ferry_entry(self):
        self.assertEqual(report.ferry_entry('OrderTotal'), {'ferry_entry': 'order_total'})
        self.assertEqual(report.ferry_entry('plain'), {'ferry_entry': 'plain'})
        self.assertEqual(report.ferry_entry('A'), {'ferry_entry': 'a'})
        self.assertEqual(report.ferry_entry('ShipToCity'), {'ferry_entry': 'ship_to_city'})

    def test_report_mast_figure(self):
        self.assertEqual(report.mast_figure([(1, 3), (3, 5)]), {'mast_figure': [(1, 5)]})
        self.assertEqual(report.mast_figure([(5, 6), (1, 2)]), {'mast_figure': [(1, 2), (5, 6)]})
        self.assertEqual(report.mast_figure([(1, 10), (2, 3)]), {'mast_figure': [(1, 10)]})
        self.assertEqual(report.mast_figure([]), {'mast_figure': []})
        self.assertEqual(report.mast_figure([(4, 8), (1, 5)]), {'mast_figure': [(1, 8)]})

    def test_report_dock_check(self):
        self.assertEqual(report.dock_check([1, 2, 3]), {'dock_check': [1, 3, 6]})
        self.assertEqual(report.dock_check([]), {'dock_check': []})
        self.assertEqual(report.dock_check([5]), {'dock_check': [5]})
        self.assertEqual(report.dock_check([2, -2, 2]), {'dock_check': [2, 0, 2]})

    def test_report_quay_line(self):
        self.assertEqual(report.quay_line({'a': 1, 'b': 2, 'c': 1}), {'quay_line': {1: ['a', 'c'], 2: ['b']}})
        self.assertEqual(report.quay_line({}), {'quay_line': {}})
        self.assertEqual(report.quay_line({'x': 'y'}), {'quay_line': {'y': ['x']}})
        self.assertEqual(report.quay_line({'q': 0, 'p': 0, 'r': 0}), {'quay_line': {0: ['p', 'q', 'r']}})

    def test_report_crate_check(self):
        self.assertEqual(report.crate_check(5, [0, 5, 10]), {'crate_check': 2})
        self.assertEqual(report.crate_check(-1, [0, 5, 10]), {'crate_check': 0})
        self.assertEqual(report.crate_check(12, [0, 5, 10]), {'crate_check': 3})
        self.assertEqual(report.crate_check(0, [0, 5, 10]), {'crate_check': 1})
        self.assertEqual(report.crate_check(7, []), {'crate_check': 0})
