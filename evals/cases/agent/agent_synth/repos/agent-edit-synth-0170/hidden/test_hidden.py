import unittest

from mill import shipping
from mill import timesheet
from mill import fleet


class Hidden(unittest.TestCase):
    def test_shipping_weighted_mean(self):
        self.assertEqual(shipping.weighted_mean([1, 2, 3], [1, 1, 1]), 2.0)
        self.assertEqual(shipping.weighted_mean([10, 20], [1, 3]), 17.5)
        self.assertEqual(shipping.weighted_mean([4], [2]), 4.0)
        with self.assertRaises(ValueError):
            shipping.weighted_mean([5, 5], [0, 0])
        self.assertEqual(shipping.weighted_mean([1, 2], [0.5, 1.5]), 1.75)

    def test_shipping_luhn_valid(self):
        self.assertEqual(shipping.luhn_valid('4539 1488 0343 6467'), True)
        self.assertEqual(shipping.luhn_valid('79927398713'), True)
        self.assertEqual(shipping.luhn_valid('79927398710'), False)
        self.assertEqual(shipping.luhn_valid(''), False)
        self.assertEqual(shipping.luhn_valid('059'), True)

    def test_timesheet_moving_average(self):
        self.assertEqual(timesheet.moving_average([1, 2, 3, 4], 2), [1.5, 2.5, 3.5])
        self.assertEqual(timesheet.moving_average([5], 1), [5.0])
        self.assertEqual(timesheet.moving_average([1, 2, 3], 3), [2.0])
        self.assertEqual(timesheet.moving_average([2, 4, 6, 8, 10], 3), [4.0, 6.0, 8.0])
        with self.assertRaises(ValueError):
            timesheet.moving_average([1, 2], 0)

    def test_timesheet_chunk(self):
        self.assertEqual(timesheet.chunk([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]])
        self.assertEqual(timesheet.chunk([1, 2, 3, 4], 2), [[1, 2], [3, 4]])
        self.assertEqual(timesheet.chunk([], 3), [])
        self.assertEqual(timesheet.chunk(['a'], 1), [['a']])
        self.assertEqual(timesheet.chunk([1, 2, 3], 5), [[1, 2, 3]])
        with self.assertRaises(ValueError):
            timesheet.chunk([1, 2], 0)

    def test_timesheet_grade(self):
        self.assertEqual(timesheet.grade(95), 'A')
        self.assertEqual(timesheet.grade(90), 'A')
        self.assertEqual(timesheet.grade(85), 'B')
        self.assertEqual(timesheet.grade(80), 'B')
        self.assertEqual(timesheet.grade(61), 'D')
        self.assertEqual(timesheet.grade(59), 'F')
        self.assertEqual(timesheet.grade(0), 'F')

    def test_fleet_merge_ranges(self):
        self.assertEqual(fleet.merge_ranges([(1, 3), (3, 5)]), [(1, 5)])
        self.assertEqual(fleet.merge_ranges([(5, 6), (1, 2)]), [(1, 2), (5, 6)])
        self.assertEqual(fleet.merge_ranges([(1, 10), (2, 3)]), [(1, 10)])
        self.assertEqual(fleet.merge_ranges([]), [])
        self.assertEqual(fleet.merge_ranges([(4, 8), (1, 5)]), [(1, 8)])

    def test_fleet_parse_duration(self):
        self.assertEqual(fleet.parse_duration('1h30m'), 5400)
        self.assertEqual(fleet.parse_duration('45s'), 45)
        self.assertEqual(fleet.parse_duration('2h'), 7200)
        self.assertEqual(fleet.parse_duration('1h1m1s'), 3661)
        with self.assertRaises(ValueError):
            fleet.parse_duration('')
        with self.assertRaises(ValueError):
            fleet.parse_duration('5x')
        self.assertEqual(fleet.parse_duration('10m5s'), 605)

    def test_fleet_format_cents(self):
        self.assertEqual(fleet.format_cents(0), '$0.00')
        self.assertEqual(fleet.format_cents(123456), '$1,234.56')
        self.assertEqual(fleet.format_cents(-105), '-$1.05')
        self.assertEqual(fleet.format_cents(5), '$0.05')
        self.assertEqual(fleet.format_cents(100000000), '$1,000,000.00')

    def test_feature(self):
        self.assertEqual(fleet.parse_duration('1d'), 86400)
        self.assertEqual(fleet.parse_duration('2d3h'), 183600)
