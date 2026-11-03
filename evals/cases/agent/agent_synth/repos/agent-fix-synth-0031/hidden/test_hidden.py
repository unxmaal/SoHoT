import unittest

from mill import kitchen
from mill import timesheet
from mill import sensors
from mill import digest


class Hidden(unittest.TestCase):
    def test_kitchen_clamp(self):
        self.assertEqual(kitchen.clamp(5, 0, 10), 5)
        self.assertEqual(kitchen.clamp(-3, 0, 10), 0)
        self.assertEqual(kitchen.clamp(15, 0, 10), 10)
        self.assertEqual(kitchen.clamp(10, 0, 10), 10)
        self.assertEqual(kitchen.clamp(0, 0, 10), 0)
        self.assertEqual(kitchen.clamp(7, 7, 7), 7)
        self.assertEqual(kitchen.clamp(-20, -30, -10), -20)

    def test_kitchen_dedupe(self):
        self.assertEqual(kitchen.dedupe([3, 1, 3, 2, 1]), [3, 1, 2])
        self.assertEqual(kitchen.dedupe(['b', 'a', 'b']), ['b', 'a'])
        self.assertEqual(kitchen.dedupe([]), [])
        self.assertEqual(kitchen.dedupe([1, 1, 1]), [1])

    def test_timesheet_top_n(self):
        self.assertEqual(timesheet.top_n({'tea': 3, 'milk': 3, 'jam': 1}, 2), ['milk', 'tea'])
        self.assertEqual(timesheet.top_n({'a': 1}, 5), ['a'])
        self.assertEqual(timesheet.top_n({}, 2), [])
        self.assertEqual(timesheet.top_n({'x': 2, 'y': 5, 'z': 2}, 2), ['y', 'x'])

    def test_timesheet_parse_duration(self):
        self.assertEqual(timesheet.parse_duration('1h30m'), 5400)
        self.assertEqual(timesheet.parse_duration('45s'), 45)
        self.assertEqual(timesheet.parse_duration('2h'), 7200)
        self.assertEqual(timesheet.parse_duration('1h1m1s'), 3661)
        with self.assertRaises(ValueError):
            timesheet.parse_duration('')
        with self.assertRaises(ValueError):
            timesheet.parse_duration('5x')
        self.assertEqual(timesheet.parse_duration('10m5s'), 605)

    def test_sensors_moving_average(self):
        self.assertEqual(sensors.moving_average([1, 2, 3, 4], 2), [1.5, 2.5, 3.5])
        self.assertEqual(sensors.moving_average([5], 1), [5.0])
        self.assertEqual(sensors.moving_average([1, 2, 3], 3), [2.0])
        self.assertEqual(sensors.moving_average([2, 4, 6, 8, 10], 3), [4.0, 6.0, 8.0])
        with self.assertRaises(ValueError):
            sensors.moving_average([1, 2], 0)

    def test_sensors_is_leap(self):
        self.assertEqual(sensors.is_leap(2024), True)
        self.assertEqual(sensors.is_leap(1900), False)
        self.assertEqual(sensors.is_leap(2000), True)
        self.assertEqual(sensors.is_leap(2023), False)
        self.assertEqual(sensors.is_leap(2400), True)
        self.assertEqual(sensors.is_leap(2100), False)

    def test_sensors_percent_change(self):
        self.assertEqual(sensors.percent_change(50, 75), 50.0)
        self.assertEqual(sensors.percent_change(200, 150), -25.0)
        self.assertEqual(sensors.percent_change(80, 80), 0.0)
        self.assertEqual(sensors.percent_change(3, 4), 33.33)
        with self.assertRaises(ValueError):
            sensors.percent_change(0, 5)
        self.assertEqual(sensors.percent_change(-10, -5), -50.0)

    def test_digest_ferry_row(self):
        self.assertEqual(digest.ferry_row(5, 0, 10), {'ferry_row': 5})
        self.assertEqual(digest.ferry_row(-3, 0, 10), {'ferry_row': 0})
        self.assertEqual(digest.ferry_row(15, 0, 10), {'ferry_row': 10})
        self.assertEqual(digest.ferry_row(10, 0, 10), {'ferry_row': 10})
        self.assertEqual(digest.ferry_row(0, 0, 10), {'ferry_row': 0})
        self.assertEqual(digest.ferry_row(7, 7, 7), {'ferry_row': 7})
        self.assertEqual(digest.ferry_row(-20, -30, -10), {'ferry_row': -20})

    def test_digest_mast_check(self):
        self.assertEqual(digest.mast_check([3, 1, 3, 2, 1]), {'mast_check': [3, 1, 2]})
        self.assertEqual(digest.mast_check(['b', 'a', 'b']), {'mast_check': ['b', 'a']})
        self.assertEqual(digest.mast_check([]), {'mast_check': []})
        self.assertEqual(digest.mast_check([1, 1, 1]), {'mast_check': [1]})

    def test_digest_lantern_view(self):
        self.assertEqual(digest.lantern_view({'tea': 3, 'milk': 3, 'jam': 1}, 2), {'lantern_view': ['milk', 'tea']})
        self.assertEqual(digest.lantern_view({'a': 1}, 5), {'lantern_view': ['a']})
        self.assertEqual(digest.lantern_view({}, 2), {'lantern_view': []})
        self.assertEqual(digest.lantern_view({'x': 2, 'y': 5, 'z': 2}, 2), {'lantern_view': ['y', 'x']})

    def test_digest_tide_line(self):
        self.assertEqual(digest.tide_line('1h30m'), {'tide_line': 5400})
        self.assertEqual(digest.tide_line('45s'), {'tide_line': 45})
        self.assertEqual(digest.tide_line('2h'), {'tide_line': 7200})
        self.assertEqual(digest.tide_line('1h1m1s'), {'tide_line': 3661})
        with self.assertRaises(ValueError):
            digest.tide_line('')
        with self.assertRaises(ValueError):
            digest.tide_line('5x')
        self.assertEqual(digest.tide_line('10m5s'), {'tide_line': 605})
