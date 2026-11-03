import unittest

from beacon import kitchen
from beacon import archive
from beacon import shipping
from beacon import routes


class Hidden(unittest.TestCase):
    def test_kitchen_is_leap(self):
        self.assertEqual(kitchen.is_leap(2024), True)
        self.assertEqual(kitchen.is_leap(1900), False)
        self.assertEqual(kitchen.is_leap(2000), True)
        self.assertEqual(kitchen.is_leap(2023), False)
        self.assertEqual(kitchen.is_leap(2400), True)
        self.assertEqual(kitchen.is_leap(2100), False)

    def test_kitchen_grade(self):
        self.assertEqual(kitchen.grade(95), 'A')
        self.assertEqual(kitchen.grade(90), 'A')
        self.assertEqual(kitchen.grade(85), 'B')
        self.assertEqual(kitchen.grade(80), 'B')
        self.assertEqual(kitchen.grade(61), 'D')
        self.assertEqual(kitchen.grade(59), 'F')
        self.assertEqual(kitchen.grade(0), 'F')

    def test_kitchen_bucket(self):
        self.assertEqual(kitchen.bucket(5, [0, 5, 10]), 2)
        self.assertEqual(kitchen.bucket(-1, [0, 5, 10]), 0)
        self.assertEqual(kitchen.bucket(12, [0, 5, 10]), 3)
        self.assertEqual(kitchen.bucket(0, [0, 5, 10]), 1)
        self.assertEqual(kitchen.bucket(7, []), 0)

    def test_archive_dedupe(self):
        self.assertEqual(archive.dedupe([3, 1, 3, 2, 1]), [3, 1, 2])
        self.assertEqual(archive.dedupe(['b', 'a', 'b']), ['b', 'a'])
        self.assertEqual(archive.dedupe([]), [])
        self.assertEqual(archive.dedupe([1, 1, 1]), [1])

    def test_archive_format_cents(self):
        self.assertEqual(archive.format_cents(0), '$0.00')
        self.assertEqual(archive.format_cents(123456), '$1,234.56')
        self.assertEqual(archive.format_cents(-105), '-$1.05')
        self.assertEqual(archive.format_cents(5), '$0.05')
        self.assertEqual(archive.format_cents(100000000), '$1,000,000.00')

    def test_archive_clamp(self):
        self.assertEqual(archive.clamp(5, 0, 10), 5)
        self.assertEqual(archive.clamp(-3, 0, 10), 0)
        self.assertEqual(archive.clamp(15, 0, 10), 10)
        self.assertEqual(archive.clamp(10, 0, 10), 10)
        self.assertEqual(archive.clamp(0, 0, 10), 0)
        self.assertEqual(archive.clamp(7, 7, 7), 7)
        self.assertEqual(archive.clamp(-20, -30, -10), -20)

    def test_shipping_merge_ranges(self):
        self.assertEqual(shipping.merge_ranges([(1, 3), (3, 5)]), [(1, 5)])
        self.assertEqual(shipping.merge_ranges([(5, 6), (1, 2)]), [(1, 2), (5, 6)])
        self.assertEqual(shipping.merge_ranges([(1, 10), (2, 3)]), [(1, 10)])
        self.assertEqual(shipping.merge_ranges([]), [])
        self.assertEqual(shipping.merge_ranges([(4, 8), (1, 5)]), [(1, 8)])

    def test_shipping_paginate(self):
        self.assertEqual(shipping.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 1, 3), [1, 2, 3])
        self.assertEqual(shipping.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 4, 3), [10])
        self.assertEqual(shipping.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 5, 3), [])
        self.assertEqual(shipping.paginate([], 1, 5), [])
        with self.assertRaises(ValueError):
            shipping.paginate([1, 2], 0, 2)

    def test_shipping_word_count(self):
        self.assertEqual(shipping.word_count('a b'), 2)
        self.assertEqual(shipping.word_count('  tea  and   milk '), 3)
        self.assertEqual(shipping.word_count(''), 0)
        self.assertEqual(shipping.word_count('one'), 1)

    def test_routes_truncate_words(self):
        self.assertEqual(routes.truncate_words('the quick brown fox', 2), 'the quick...')
        self.assertEqual(routes.truncate_words('tea time', 2), 'tea time')
        self.assertEqual(routes.truncate_words('', 3), '')
        self.assertEqual(routes.truncate_words('one two three', 1), 'one...')

    def test_routes_moving_average(self):
        self.assertEqual(routes.moving_average([1, 2, 3, 4], 2), [1.5, 2.5, 3.5])
        self.assertEqual(routes.moving_average([5], 1), [5.0])
        self.assertEqual(routes.moving_average([1, 2, 3], 3), [2.0])
        self.assertEqual(routes.moving_average([2, 4, 6, 8, 10], 3), [4.0, 6.0, 8.0])
        with self.assertRaises(ValueError):
            routes.moving_average([1, 2], 0)

    def test_routes_percent_change(self):
        self.assertEqual(routes.percent_change(50, 75), 50.0)
        self.assertEqual(routes.percent_change(200, 150), -25.0)
        self.assertEqual(routes.percent_change(80, 80), 0.0)
        self.assertEqual(routes.percent_change(3, 4), 33.33)
        with self.assertRaises(ValueError):
            routes.percent_change(0, 5)
        self.assertEqual(routes.percent_change(-10, -5), -50.0)
