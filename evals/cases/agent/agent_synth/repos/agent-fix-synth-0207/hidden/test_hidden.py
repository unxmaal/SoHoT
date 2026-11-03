import unittest

from quarry import survey
from quarry import kitchen
from quarry import timesheet
from quarry import metrics
from quarry import digest


class Hidden(unittest.TestCase):
    def test_survey_rle(self):
        self.assertEqual(survey.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(survey.rle(''), [])
        self.assertEqual(survey.rle('abc'), [('a', 1), ('b', 1), ('c', 1)])
        self.assertEqual(survey.rle('zz'), [('z', 2)])

    def test_survey_invert(self):
        self.assertEqual(survey.invert({'a': 1, 'b': 2, 'c': 1}), {1: ['a', 'c'], 2: ['b']})
        self.assertEqual(survey.invert({}), {})
        self.assertEqual(survey.invert({'x': 'y'}), {'y': ['x']})
        self.assertEqual(survey.invert({'q': 0, 'p': 0, 'r': 0}), {0: ['p', 'q', 'r']})

    def test_survey_moving_average(self):
        self.assertEqual(survey.moving_average([1, 2, 3, 4], 2), [1.5, 2.5, 3.5])
        self.assertEqual(survey.moving_average([5], 1), [5.0])
        self.assertEqual(survey.moving_average([1, 2, 3], 3), [2.0])
        self.assertEqual(survey.moving_average([2, 4, 6, 8, 10], 3), [4.0, 6.0, 8.0])
        with self.assertRaises(ValueError):
            survey.moving_average([1, 2], 0)

    def test_kitchen_median(self):
        self.assertEqual(kitchen.median([3, 1, 2]), 2)
        self.assertEqual(kitchen.median([4, 1, 3, 2]), 2.5)
        self.assertEqual(kitchen.median([5]), 5)
        self.assertEqual(kitchen.median([1, 2]), 1.5)
        self.assertEqual(kitchen.median([10, 2, 38, 23, 38, 23]), 23.0)
        with self.assertRaises(ValueError):
            kitchen.median([])

    def test_kitchen_merge_ranges(self):
        self.assertEqual(kitchen.merge_ranges([(1, 3), (3, 5)]), [(1, 5)])
        self.assertEqual(kitchen.merge_ranges([(5, 6), (1, 2)]), [(1, 2), (5, 6)])
        self.assertEqual(kitchen.merge_ranges([(1, 10), (2, 3)]), [(1, 10)])
        self.assertEqual(kitchen.merge_ranges([]), [])
        self.assertEqual(kitchen.merge_ranges([(4, 8), (1, 5)]), [(1, 8)])

    def test_timesheet_weighted_mean(self):
        self.assertEqual(timesheet.weighted_mean([1, 2, 3], [1, 1, 1]), 2.0)
        self.assertEqual(timesheet.weighted_mean([10, 20], [1, 3]), 17.5)
        self.assertEqual(timesheet.weighted_mean([4], [2]), 4.0)
        with self.assertRaises(ValueError):
            timesheet.weighted_mean([5, 5], [0, 0])
        self.assertEqual(timesheet.weighted_mean([1, 2], [0.5, 1.5]), 1.75)

    def test_timesheet_grade(self):
        self.assertEqual(timesheet.grade(95), 'A')
        self.assertEqual(timesheet.grade(90), 'A')
        self.assertEqual(timesheet.grade(85), 'B')
        self.assertEqual(timesheet.grade(80), 'B')
        self.assertEqual(timesheet.grade(61), 'D')
        self.assertEqual(timesheet.grade(59), 'F')
        self.assertEqual(timesheet.grade(0), 'F')

    def test_timesheet_format_cents(self):
        self.assertEqual(timesheet.format_cents(0), '$0.00')
        self.assertEqual(timesheet.format_cents(123456), '$1,234.56')
        self.assertEqual(timesheet.format_cents(-105), '-$1.05')
        self.assertEqual(timesheet.format_cents(5), '$0.05')
        self.assertEqual(timesheet.format_cents(100000000), '$1,000,000.00')

    def test_metrics_running_total(self):
        self.assertEqual(metrics.running_total([1, 2, 3]), [1, 3, 6])
        self.assertEqual(metrics.running_total([]), [])
        self.assertEqual(metrics.running_total([5]), [5])
        self.assertEqual(metrics.running_total([2, -2, 2]), [2, 0, 2])

    def test_metrics_is_leap(self):
        self.assertEqual(metrics.is_leap(2024), True)
        self.assertEqual(metrics.is_leap(1900), False)
        self.assertEqual(metrics.is_leap(2000), True)
        self.assertEqual(metrics.is_leap(2023), False)
        self.assertEqual(metrics.is_leap(2400), True)
        self.assertEqual(metrics.is_leap(2100), False)

    def test_metrics_snake_case(self):
        self.assertEqual(metrics.snake_case('OrderTotal'), 'order_total')
        self.assertEqual(metrics.snake_case('plain'), 'plain')
        self.assertEqual(metrics.snake_case('A'), 'a')
        self.assertEqual(metrics.snake_case('ShipToCity'), 'ship_to_city')

    def test_digest_buoy_check(self):
        self.assertEqual(digest.buoy_check('aaab'), {'buoy_check': [('a', 3), ('b', 1)]})
        self.assertEqual(digest.buoy_check(''), {'buoy_check': []})
        self.assertEqual(digest.buoy_check('abc'), {'buoy_check': [('a', 1), ('b', 1), ('c', 1)]})
        self.assertEqual(digest.buoy_check('zz'), {'buoy_check': [('z', 2)]})

    def test_digest_harbor_view(self):
        self.assertEqual(digest.harbor_view({'a': 1, 'b': 2, 'c': 1}), {'harbor_view': {1: ['a', 'c'], 2: ['b']}})
        self.assertEqual(digest.harbor_view({}), {'harbor_view': {}})
        self.assertEqual(digest.harbor_view({'x': 'y'}), {'harbor_view': {'y': ['x']}})
        self.assertEqual(digest.harbor_view({'q': 0, 'p': 0, 'r': 0}), {'harbor_view': {0: ['p', 'q', 'r']}})

    def test_digest_rope_summary(self):
        self.assertEqual(digest.rope_summary([1, 2, 3, 4], 2), {'rope_summary': [1.5, 2.5, 3.5]})
        self.assertEqual(digest.rope_summary([5], 1), {'rope_summary': [5.0]})
        self.assertEqual(digest.rope_summary([1, 2, 3], 3), {'rope_summary': [2.0]})
        self.assertEqual(digest.rope_summary([2, 4, 6, 8, 10], 3), {'rope_summary': [4.0, 6.0, 8.0]})
        with self.assertRaises(ValueError):
            digest.rope_summary([1, 2], 0)

    def test_digest_keel_total(self):
        self.assertEqual(digest.keel_total([3, 1, 2]), {'keel_total': 2})
        self.assertEqual(digest.keel_total([4, 1, 3, 2]), {'keel_total': 2.5})
        self.assertEqual(digest.keel_total([5]), {'keel_total': 5})
        self.assertEqual(digest.keel_total([1, 2]), {'keel_total': 1.5})
        self.assertEqual(digest.keel_total([10, 2, 38, 23, 38, 23]), {'keel_total': 23.0})
        with self.assertRaises(ValueError):
            digest.keel_total([])

    def test_digest_berth_figure(self):
        self.assertEqual(digest.berth_figure(0), {'berth_figure': '$0.00'})
        self.assertEqual(digest.berth_figure(123456), {'berth_figure': '$1,234.56'})
        self.assertEqual(digest.berth_figure(-105), {'berth_figure': '-$1.05'})
        self.assertEqual(digest.berth_figure(5), {'berth_figure': '$0.05'})
        self.assertEqual(digest.berth_figure(100000000), {'berth_figure': '$1,000,000.00'})
