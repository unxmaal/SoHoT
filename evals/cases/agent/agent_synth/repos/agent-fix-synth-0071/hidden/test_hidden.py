import unittest

from foundry import timesheet
from foundry import rosters
from foundry import fleet
from foundry import weather
from foundry import payroll
from foundry import digest


class Hidden(unittest.TestCase):
    def test_timesheet_median(self):
        self.assertEqual(timesheet.median([3, 1, 2]), 2)
        self.assertEqual(timesheet.median([4, 1, 3, 2]), 2.5)
        self.assertEqual(timesheet.median([5]), 5)
        self.assertEqual(timesheet.median([1, 2]), 1.5)
        self.assertEqual(timesheet.median([10, 2, 38, 23, 38, 23]), 23.0)
        with self.assertRaises(ValueError):
            timesheet.median([])

    def test_timesheet_dedupe(self):
        self.assertEqual(timesheet.dedupe([3, 1, 3, 2, 1]), [3, 1, 2])
        self.assertEqual(timesheet.dedupe(['b', 'a', 'b']), ['b', 'a'])
        self.assertEqual(timesheet.dedupe([]), [])
        self.assertEqual(timesheet.dedupe([1, 1, 1]), [1])

    def test_timesheet_running_total(self):
        self.assertEqual(timesheet.running_total([1, 2, 3]), [1, 3, 6])
        self.assertEqual(timesheet.running_total([]), [])
        self.assertEqual(timesheet.running_total([5]), [5])
        self.assertEqual(timesheet.running_total([2, -2, 2]), [2, 0, 2])

    def test_rosters_weighted_mean(self):
        self.assertEqual(rosters.weighted_mean([1, 2, 3], [1, 1, 1]), 2.0)
        self.assertEqual(rosters.weighted_mean([10, 20], [1, 3]), 17.5)
        self.assertEqual(rosters.weighted_mean([4], [2]), 4.0)
        with self.assertRaises(ValueError):
            rosters.weighted_mean([5, 5], [0, 0])
        self.assertEqual(rosters.weighted_mean([1, 2], [0.5, 1.5]), 1.75)

    def test_rosters_clamp(self):
        self.assertEqual(rosters.clamp(5, 0, 10), 5)
        self.assertEqual(rosters.clamp(-3, 0, 10), 0)
        self.assertEqual(rosters.clamp(15, 0, 10), 10)
        self.assertEqual(rosters.clamp(10, 0, 10), 10)
        self.assertEqual(rosters.clamp(0, 0, 10), 0)
        self.assertEqual(rosters.clamp(7, 7, 7), 7)
        self.assertEqual(rosters.clamp(-20, -30, -10), -20)

    def test_fleet_paginate(self):
        self.assertEqual(fleet.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 1, 3), [1, 2, 3])
        self.assertEqual(fleet.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 4, 3), [10])
        self.assertEqual(fleet.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 5, 3), [])
        self.assertEqual(fleet.paginate([], 1, 5), [])
        with self.assertRaises(ValueError):
            fleet.paginate([1, 2], 0, 2)

    def test_fleet_merge_ranges(self):
        self.assertEqual(fleet.merge_ranges([(1, 3), (3, 5)]), [(1, 5)])
        self.assertEqual(fleet.merge_ranges([(5, 6), (1, 2)]), [(1, 2), (5, 6)])
        self.assertEqual(fleet.merge_ranges([(1, 10), (2, 3)]), [(1, 10)])
        self.assertEqual(fleet.merge_ranges([]), [])
        self.assertEqual(fleet.merge_ranges([(4, 8), (1, 5)]), [(1, 8)])

    def test_fleet_truncate_words(self):
        self.assertEqual(fleet.truncate_words('the quick brown fox', 2), 'the quick...')
        self.assertEqual(fleet.truncate_words('tea time', 2), 'tea time')
        self.assertEqual(fleet.truncate_words('', 3), '')
        self.assertEqual(fleet.truncate_words('one two three', 1), 'one...')

    def test_weather_format_cents(self):
        self.assertEqual(weather.format_cents(0), '$0.00')
        self.assertEqual(weather.format_cents(123456), '$1,234.56')
        self.assertEqual(weather.format_cents(-105), '-$1.05')
        self.assertEqual(weather.format_cents(5), '$0.05')
        self.assertEqual(weather.format_cents(100000000), '$1,000,000.00')

    def test_weather_chunk(self):
        self.assertEqual(weather.chunk([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]])
        self.assertEqual(weather.chunk([1, 2, 3, 4], 2), [[1, 2], [3, 4]])
        self.assertEqual(weather.chunk([], 3), [])
        self.assertEqual(weather.chunk(['a'], 1), [['a']])
        self.assertEqual(weather.chunk([1, 2, 3], 5), [[1, 2, 3]])
        with self.assertRaises(ValueError):
            weather.chunk([1, 2], 0)

    def test_payroll_grade(self):
        self.assertEqual(payroll.grade(95), 'A')
        self.assertEqual(payroll.grade(90), 'A')
        self.assertEqual(payroll.grade(85), 'B')
        self.assertEqual(payroll.grade(80), 'B')
        self.assertEqual(payroll.grade(61), 'D')
        self.assertEqual(payroll.grade(59), 'F')
        self.assertEqual(payroll.grade(0), 'F')

    def test_payroll_invert(self):
        self.assertEqual(payroll.invert({'a': 1, 'b': 2, 'c': 1}), {1: ['a', 'c'], 2: ['b']})
        self.assertEqual(payroll.invert({}), {})
        self.assertEqual(payroll.invert({'x': 'y'}), {'y': ['x']})
        self.assertEqual(payroll.invert({'q': 0, 'p': 0, 'r': 0}), {0: ['p', 'q', 'r']})

    def test_digest_berth_summary(self):
        self.assertEqual(digest.berth_summary([3, 1, 2]), {'berth_summary': 2})
        self.assertEqual(digest.berth_summary([4, 1, 3, 2]), {'berth_summary': 2.5})
        self.assertEqual(digest.berth_summary([5]), {'berth_summary': 5})
        self.assertEqual(digest.berth_summary([1, 2]), {'berth_summary': 1.5})
        self.assertEqual(digest.berth_summary([10, 2, 38, 23, 38, 23]), {'berth_summary': 23.0})
        with self.assertRaises(ValueError):
            digest.berth_summary([])

    def test_digest_sail_entry(self):
        self.assertEqual(digest.sail_entry([3, 1, 3, 2, 1]), {'sail_entry': [3, 1, 2]})
        self.assertEqual(digest.sail_entry(['b', 'a', 'b']), {'sail_entry': ['b', 'a']})
        self.assertEqual(digest.sail_entry([]), {'sail_entry': []})
        self.assertEqual(digest.sail_entry([1, 1, 1]), {'sail_entry': [1]})

    def test_digest_rope_check(self):
        self.assertEqual(digest.rope_check([1, 2, 3]), {'rope_check': [1, 3, 6]})
        self.assertEqual(digest.rope_check([]), {'rope_check': []})
        self.assertEqual(digest.rope_check([5]), {'rope_check': [5]})
        self.assertEqual(digest.rope_check([2, -2, 2]), {'rope_check': [2, 0, 2]})

    def test_digest_tide_row(self):
        self.assertEqual(digest.tide_row([1, 2, 3], [1, 1, 1]), {'tide_row': 2.0})
        self.assertEqual(digest.tide_row([10, 20], [1, 3]), {'tide_row': 17.5})
        self.assertEqual(digest.tide_row([4], [2]), {'tide_row': 4.0})
        with self.assertRaises(ValueError):
            digest.tide_row([5, 5], [0, 0])
        self.assertEqual(digest.tide_row([1, 2], [0.5, 1.5]), {'tide_row': 1.75})
