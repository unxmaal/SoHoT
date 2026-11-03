import unittest

from meadow import routes
from meadow import survey
from meadow import archive
from meadow import orders
from meadow import fleet


class Hidden(unittest.TestCase):
    def test_routes_paginate(self):
        self.assertEqual(routes.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 1, 3), [1, 2, 3])
        self.assertEqual(routes.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 4, 3), [10])
        self.assertEqual(routes.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 5, 3), [])
        self.assertEqual(routes.paginate([], 1, 5), [])
        with self.assertRaises(ValueError):
            routes.paginate([1, 2], 0, 2)

    def test_routes_clamp(self):
        self.assertEqual(routes.clamp(5, 0, 10), 5)
        self.assertEqual(routes.clamp(-3, 0, 10), 0)
        self.assertEqual(routes.clamp(15, 0, 10), 10)
        self.assertEqual(routes.clamp(10, 0, 10), 10)
        self.assertEqual(routes.clamp(0, 0, 10), 0)
        self.assertEqual(routes.clamp(7, 7, 7), 7)
        self.assertEqual(routes.clamp(-20, -30, -10), -20)

    def test_routes_moving_average(self):
        self.assertEqual(routes.moving_average([1, 2, 3, 4], 2), [1.5, 2.5, 3.5])
        self.assertEqual(routes.moving_average([5], 1), [5.0])
        self.assertEqual(routes.moving_average([1, 2, 3], 3), [2.0])
        self.assertEqual(routes.moving_average([2, 4, 6, 8, 10], 3), [4.0, 6.0, 8.0])
        with self.assertRaises(ValueError):
            routes.moving_average([1, 2], 0)

    def test_survey_grade(self):
        self.assertEqual(survey.grade(95), 'A')
        self.assertEqual(survey.grade(90), 'A')
        self.assertEqual(survey.grade(85), 'B')
        self.assertEqual(survey.grade(80), 'B')
        self.assertEqual(survey.grade(61), 'D')
        self.assertEqual(survey.grade(59), 'F')
        self.assertEqual(survey.grade(0), 'F')

    def test_survey_merge_ranges(self):
        self.assertEqual(survey.merge_ranges([(1, 3), (3, 5)]), [(1, 5)])
        self.assertEqual(survey.merge_ranges([(5, 6), (1, 2)]), [(1, 2), (5, 6)])
        self.assertEqual(survey.merge_ranges([(1, 10), (2, 3)]), [(1, 10)])
        self.assertEqual(survey.merge_ranges([]), [])
        self.assertEqual(survey.merge_ranges([(4, 8), (1, 5)]), [(1, 8)])

    def test_archive_bucket(self):
        self.assertEqual(archive.bucket(5, [0, 5, 10]), 2)
        self.assertEqual(archive.bucket(-1, [0, 5, 10]), 0)
        self.assertEqual(archive.bucket(12, [0, 5, 10]), 3)
        self.assertEqual(archive.bucket(0, [0, 5, 10]), 1)
        self.assertEqual(archive.bucket(7, []), 0)

    def test_archive_median(self):
        self.assertEqual(archive.median([3, 1, 2]), 2)
        self.assertEqual(archive.median([4, 1, 3, 2]), 2.5)
        self.assertEqual(archive.median([5]), 5)
        self.assertEqual(archive.median([1, 2]), 1.5)
        self.assertEqual(archive.median([10, 2, 38, 23, 38, 23]), 23.0)
        with self.assertRaises(ValueError):
            archive.median([])

    def test_archive_is_leap(self):
        self.assertEqual(archive.is_leap(2024), True)
        self.assertEqual(archive.is_leap(1900), False)
        self.assertEqual(archive.is_leap(2000), True)
        self.assertEqual(archive.is_leap(2023), False)
        self.assertEqual(archive.is_leap(2400), True)
        self.assertEqual(archive.is_leap(2100), False)

    def test_orders_rle(self):
        self.assertEqual(orders.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(orders.rle(''), [])
        self.assertEqual(orders.rle('abc'), [('a', 1), ('b', 1), ('c', 1)])
        self.assertEqual(orders.rle('zz'), [('z', 2)])

    def test_orders_parse_duration(self):
        self.assertEqual(orders.parse_duration('1h30m'), 5400)
        self.assertEqual(orders.parse_duration('45s'), 45)
        self.assertEqual(orders.parse_duration('2h'), 7200)
        self.assertEqual(orders.parse_duration('1h1m1s'), 3661)
        with self.assertRaises(ValueError):
            orders.parse_duration('')
        with self.assertRaises(ValueError):
            orders.parse_duration('5x')
        self.assertEqual(orders.parse_duration('10m5s'), 605)

    def test_fleet_percent_change(self):
        self.assertEqual(fleet.percent_change(50, 75), 50.0)
        self.assertEqual(fleet.percent_change(200, 150), -25.0)
        self.assertEqual(fleet.percent_change(80, 80), 0.0)
        self.assertEqual(fleet.percent_change(3, 4), 33.33)
        with self.assertRaises(ValueError):
            fleet.percent_change(0, 5)
        self.assertEqual(fleet.percent_change(-10, -5), -50.0)

    def test_fleet_luhn_valid(self):
        self.assertEqual(fleet.luhn_valid('4539 1488 0343 6467'), True)
        self.assertEqual(fleet.luhn_valid('79927398713'), True)
        self.assertEqual(fleet.luhn_valid('79927398710'), False)
        self.assertEqual(fleet.luhn_valid(''), False)
        self.assertEqual(fleet.luhn_valid('059'), True)
