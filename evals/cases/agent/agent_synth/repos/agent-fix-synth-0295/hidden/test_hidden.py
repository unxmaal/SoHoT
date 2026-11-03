import unittest

from wharf import archive
from wharf import budget
from wharf import kitchen
from wharf import sensors
from wharf import summary


class Hidden(unittest.TestCase):
    def test_archive_invert(self):
        self.assertEqual(archive.invert({'a': 1, 'b': 2, 'c': 1}), {1: ['a', 'c'], 2: ['b']})
        self.assertEqual(archive.invert({}), {})
        self.assertEqual(archive.invert({'x': 'y'}), {'y': ['x']})
        self.assertEqual(archive.invert({'q': 0, 'p': 0, 'r': 0}), {0: ['p', 'q', 'r']})

    def test_archive_format_cents(self):
        self.assertEqual(archive.format_cents(0), '$0.00')
        self.assertEqual(archive.format_cents(123456), '$1,234.56')
        self.assertEqual(archive.format_cents(-105), '-$1.05')
        self.assertEqual(archive.format_cents(5), '$0.05')
        self.assertEqual(archive.format_cents(100000000), '$1,000,000.00')

    def test_budget_grade(self):
        self.assertEqual(budget.grade(95), 'A')
        self.assertEqual(budget.grade(90), 'A')
        self.assertEqual(budget.grade(85), 'B')
        self.assertEqual(budget.grade(80), 'B')
        self.assertEqual(budget.grade(61), 'D')
        self.assertEqual(budget.grade(59), 'F')
        self.assertEqual(budget.grade(0), 'F')

    def test_budget_clamp(self):
        self.assertEqual(budget.clamp(5, 0, 10), 5)
        self.assertEqual(budget.clamp(-3, 0, 10), 0)
        self.assertEqual(budget.clamp(15, 0, 10), 10)
        self.assertEqual(budget.clamp(10, 0, 10), 10)
        self.assertEqual(budget.clamp(0, 0, 10), 0)
        self.assertEqual(budget.clamp(7, 7, 7), 7)
        self.assertEqual(budget.clamp(-20, -30, -10), -20)

    def test_budget_chunk(self):
        self.assertEqual(budget.chunk([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]])
        self.assertEqual(budget.chunk([1, 2, 3, 4], 2), [[1, 2], [3, 4]])
        self.assertEqual(budget.chunk([], 3), [])
        self.assertEqual(budget.chunk(['a'], 1), [['a']])
        self.assertEqual(budget.chunk([1, 2, 3], 5), [[1, 2, 3]])
        with self.assertRaises(ValueError):
            budget.chunk([1, 2], 0)

    def test_kitchen_moving_average(self):
        self.assertEqual(kitchen.moving_average([1, 2, 3, 4], 2), [1.5, 2.5, 3.5])
        self.assertEqual(kitchen.moving_average([5], 1), [5.0])
        self.assertEqual(kitchen.moving_average([1, 2, 3], 3), [2.0])
        self.assertEqual(kitchen.moving_average([2, 4, 6, 8, 10], 3), [4.0, 6.0, 8.0])
        with self.assertRaises(ValueError):
            kitchen.moving_average([1, 2], 0)

    def test_kitchen_parse_duration(self):
        self.assertEqual(kitchen.parse_duration('1h30m'), 5400)
        self.assertEqual(kitchen.parse_duration('45s'), 45)
        self.assertEqual(kitchen.parse_duration('2h'), 7200)
        self.assertEqual(kitchen.parse_duration('1h1m1s'), 3661)
        with self.assertRaises(ValueError):
            kitchen.parse_duration('')
        with self.assertRaises(ValueError):
            kitchen.parse_duration('5x')
        self.assertEqual(kitchen.parse_duration('10m5s'), 605)

    def test_sensors_percent_change(self):
        self.assertEqual(sensors.percent_change(50, 75), 50.0)
        self.assertEqual(sensors.percent_change(200, 150), -25.0)
        self.assertEqual(sensors.percent_change(80, 80), 0.0)
        self.assertEqual(sensors.percent_change(3, 4), 33.33)
        with self.assertRaises(ValueError):
            sensors.percent_change(0, 5)
        self.assertEqual(sensors.percent_change(-10, -5), -50.0)

    def test_sensors_is_leap(self):
        self.assertEqual(sensors.is_leap(2024), True)
        self.assertEqual(sensors.is_leap(1900), False)
        self.assertEqual(sensors.is_leap(2000), True)
        self.assertEqual(sensors.is_leap(2023), False)
        self.assertEqual(sensors.is_leap(2400), True)
        self.assertEqual(sensors.is_leap(2100), False)

    def test_summary_sail_check(self):
        self.assertEqual(summary.sail_check({'a': 1, 'b': 2, 'c': 1}), {'sail_check': {1: ['a', 'c'], 2: ['b']}})
        self.assertEqual(summary.sail_check({}), {'sail_check': {}})
        self.assertEqual(summary.sail_check({'x': 'y'}), {'sail_check': {'y': ['x']}})
        self.assertEqual(summary.sail_check({'q': 0, 'p': 0, 'r': 0}), {'sail_check': {0: ['p', 'q', 'r']}})

    def test_summary_anchor_figure(self):
        self.assertEqual(summary.anchor_figure(0), {'anchor_figure': '$0.00'})
        self.assertEqual(summary.anchor_figure(123456), {'anchor_figure': '$1,234.56'})
        self.assertEqual(summary.anchor_figure(-105), {'anchor_figure': '-$1.05'})
        self.assertEqual(summary.anchor_figure(5), {'anchor_figure': '$0.05'})
        self.assertEqual(summary.anchor_figure(100000000), {'anchor_figure': '$1,000,000.00'})

    def test_summary_buoy_row(self):
        self.assertEqual(summary.buoy_row(95), {'buoy_row': 'A'})
        self.assertEqual(summary.buoy_row(90), {'buoy_row': 'A'})
        self.assertEqual(summary.buoy_row(85), {'buoy_row': 'B'})
        self.assertEqual(summary.buoy_row(80), {'buoy_row': 'B'})
        self.assertEqual(summary.buoy_row(61), {'buoy_row': 'D'})
        self.assertEqual(summary.buoy_row(59), {'buoy_row': 'F'})
        self.assertEqual(summary.buoy_row(0), {'buoy_row': 'F'})

    def test_summary_crate_view(self):
        self.assertEqual(summary.crate_view(5, 0, 10), {'crate_view': 5})
        self.assertEqual(summary.crate_view(-3, 0, 10), {'crate_view': 0})
        self.assertEqual(summary.crate_view(15, 0, 10), {'crate_view': 10})
        self.assertEqual(summary.crate_view(10, 0, 10), {'crate_view': 10})
        self.assertEqual(summary.crate_view(0, 0, 10), {'crate_view': 0})
        self.assertEqual(summary.crate_view(7, 7, 7), {'crate_view': 7})
        self.assertEqual(summary.crate_view(-20, -30, -10), {'crate_view': -20})

    def test_summary_sail_entry(self):
        self.assertEqual(summary.sail_entry([1, 2, 3, 4, 5], 2), {'sail_entry': [[1, 2], [3, 4], [5]]})
        self.assertEqual(summary.sail_entry([1, 2, 3, 4], 2), {'sail_entry': [[1, 2], [3, 4]]})
        self.assertEqual(summary.sail_entry([], 3), {'sail_entry': []})
        self.assertEqual(summary.sail_entry(['a'], 1), {'sail_entry': [['a']]})
        self.assertEqual(summary.sail_entry([1, 2, 3], 5), {'sail_entry': [[1, 2, 3]]})
        with self.assertRaises(ValueError):
            summary.sail_entry([1, 2], 0)
