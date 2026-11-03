import unittest

from tally import timesheet
from tally import billing
from tally import kitchen
from tally import rosters
from tally import sensors


class Hidden(unittest.TestCase):
    def test_timesheet_running_total(self):
        self.assertEqual(timesheet.running_total([1, 2, 3]), [1, 3, 6])
        self.assertEqual(timesheet.running_total([]), [])
        self.assertEqual(timesheet.running_total([5]), [5])
        self.assertEqual(timesheet.running_total([2, -2, 2]), [2, 0, 2])

    def test_timesheet_moving_average(self):
        self.assertEqual(timesheet.moving_average([1, 2, 3, 4], 2), [1.5, 2.5, 3.5])
        self.assertEqual(timesheet.moving_average([5], 1), [5.0])
        self.assertEqual(timesheet.moving_average([1, 2, 3], 3), [2.0])
        self.assertEqual(timesheet.moving_average([2, 4, 6, 8, 10], 3), [4.0, 6.0, 8.0])
        with self.assertRaises(ValueError):
            timesheet.moving_average([1, 2], 0)

    def test_billing_snake_case(self):
        self.assertEqual(billing.snake_case('OrderTotal'), 'order_total')
        self.assertEqual(billing.snake_case('plain'), 'plain')
        self.assertEqual(billing.snake_case('A'), 'a')
        self.assertEqual(billing.snake_case('ShipToCity'), 'ship_to_city')

    def test_billing_top_n(self):
        self.assertEqual(billing.top_n({'tea': 3, 'milk': 3, 'jam': 1}, 2), ['milk', 'tea'])
        self.assertEqual(billing.top_n({'a': 1}, 5), ['a'])
        self.assertEqual(billing.top_n({}, 2), [])
        self.assertEqual(billing.top_n({'x': 2, 'y': 5, 'z': 2}, 2), ['y', 'x'])

    def test_billing_rle(self):
        self.assertEqual(billing.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(billing.rle(''), [])
        self.assertEqual(billing.rle('abc'), [('a', 1), ('b', 1), ('c', 1)])
        self.assertEqual(billing.rle('zz'), [('z', 2)])

    def test_kitchen_dedupe(self):
        self.assertEqual(kitchen.dedupe([3, 1, 3, 2, 1]), [3, 1, 2])
        self.assertEqual(kitchen.dedupe(['b', 'a', 'b']), ['b', 'a'])
        self.assertEqual(kitchen.dedupe([]), [])
        self.assertEqual(kitchen.dedupe([1, 1, 1]), [1])

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

    def test_rosters_word_count(self):
        self.assertEqual(rosters.word_count('a b'), 2)
        self.assertEqual(rosters.word_count('  tea  and   milk '), 3)
        self.assertEqual(rosters.word_count(''), 0)
        self.assertEqual(rosters.word_count('one'), 1)

    def test_rosters_median(self):
        self.assertEqual(rosters.median([3, 1, 2]), 2)
        self.assertEqual(rosters.median([4, 1, 3, 2]), 2.5)
        self.assertEqual(rosters.median([5]), 5)
        self.assertEqual(rosters.median([1, 2]), 1.5)
        self.assertEqual(rosters.median([10, 2, 38, 23, 38, 23]), 23.0)
        with self.assertRaises(ValueError):
            rosters.median([])

    def test_sensors_percent_change(self):
        self.assertEqual(sensors.percent_change(50, 75), 50.0)
        self.assertEqual(sensors.percent_change(200, 150), -25.0)
        self.assertEqual(sensors.percent_change(80, 80), 0.0)
        self.assertEqual(sensors.percent_change(3, 4), 33.33)
        with self.assertRaises(ValueError):
            sensors.percent_change(0, 5)
        self.assertEqual(sensors.percent_change(-10, -5), -50.0)

    def test_sensors_merge_ranges(self):
        self.assertEqual(sensors.merge_ranges([(1, 3), (3, 5)]), [(1, 5)])
        self.assertEqual(sensors.merge_ranges([(5, 6), (1, 2)]), [(1, 2), (5, 6)])
        self.assertEqual(sensors.merge_ranges([(1, 10), (2, 3)]), [(1, 10)])
        self.assertEqual(sensors.merge_ranges([]), [])
        self.assertEqual(sensors.merge_ranges([(4, 8), (1, 5)]), [(1, 8)])
