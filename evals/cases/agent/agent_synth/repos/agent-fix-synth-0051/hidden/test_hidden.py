import unittest

from depot import fleet
from depot import archive
from depot import kitchen
from depot import tickets


class Hidden(unittest.TestCase):
    def test_fleet_running_total(self):
        self.assertEqual(fleet.running_total([1, 2, 3]), [1, 3, 6])
        self.assertEqual(fleet.running_total([]), [])
        self.assertEqual(fleet.running_total([5]), [5])
        self.assertEqual(fleet.running_total([2, -2, 2]), [2, 0, 2])

    def test_fleet_luhn_valid(self):
        self.assertEqual(fleet.luhn_valid('4539 1488 0343 6467'), True)
        self.assertEqual(fleet.luhn_valid('79927398713'), True)
        self.assertEqual(fleet.luhn_valid('79927398710'), False)
        self.assertEqual(fleet.luhn_valid(''), False)
        self.assertEqual(fleet.luhn_valid('059'), True)

    def test_fleet_grade(self):
        self.assertEqual(fleet.grade(95), 'A')
        self.assertEqual(fleet.grade(90), 'A')
        self.assertEqual(fleet.grade(85), 'B')
        self.assertEqual(fleet.grade(80), 'B')
        self.assertEqual(fleet.grade(61), 'D')
        self.assertEqual(fleet.grade(59), 'F')
        self.assertEqual(fleet.grade(0), 'F')

    def test_archive_truncate_words(self):
        self.assertEqual(archive.truncate_words('the quick brown fox', 2), 'the quick...')
        self.assertEqual(archive.truncate_words('tea time', 2), 'tea time')
        self.assertEqual(archive.truncate_words('', 3), '')
        self.assertEqual(archive.truncate_words('one two three', 1), 'one...')

    def test_archive_rle(self):
        self.assertEqual(archive.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(archive.rle(''), [])
        self.assertEqual(archive.rle('abc'), [('a', 1), ('b', 1), ('c', 1)])
        self.assertEqual(archive.rle('zz'), [('z', 2)])

    def test_kitchen_percent_change(self):
        self.assertEqual(kitchen.percent_change(50, 75), 50.0)
        self.assertEqual(kitchen.percent_change(200, 150), -25.0)
        self.assertEqual(kitchen.percent_change(80, 80), 0.0)
        self.assertEqual(kitchen.percent_change(3, 4), 33.33)
        with self.assertRaises(ValueError):
            kitchen.percent_change(0, 5)
        self.assertEqual(kitchen.percent_change(-10, -5), -50.0)

    def test_kitchen_paginate(self):
        self.assertEqual(kitchen.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 1, 3), [1, 2, 3])
        self.assertEqual(kitchen.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 4, 3), [10])
        self.assertEqual(kitchen.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 5, 3), [])
        self.assertEqual(kitchen.paginate([], 1, 5), [])
        with self.assertRaises(ValueError):
            kitchen.paginate([1, 2], 0, 2)

    def test_kitchen_is_leap(self):
        self.assertEqual(kitchen.is_leap(2024), True)
        self.assertEqual(kitchen.is_leap(1900), False)
        self.assertEqual(kitchen.is_leap(2000), True)
        self.assertEqual(kitchen.is_leap(2023), False)
        self.assertEqual(kitchen.is_leap(2400), True)
        self.assertEqual(kitchen.is_leap(2100), False)

    def test_tickets_top_n(self):
        self.assertEqual(tickets.top_n({'tea': 3, 'milk': 3, 'jam': 1}, 2), ['milk', 'tea'])
        self.assertEqual(tickets.top_n({'a': 1}, 5), ['a'])
        self.assertEqual(tickets.top_n({}, 2), [])
        self.assertEqual(tickets.top_n({'x': 2, 'y': 5, 'z': 2}, 2), ['y', 'x'])

    def test_tickets_merge_ranges(self):
        self.assertEqual(tickets.merge_ranges([(1, 3), (3, 5)]), [(1, 5)])
        self.assertEqual(tickets.merge_ranges([(5, 6), (1, 2)]), [(1, 2), (5, 6)])
        self.assertEqual(tickets.merge_ranges([(1, 10), (2, 3)]), [(1, 10)])
        self.assertEqual(tickets.merge_ranges([]), [])
        self.assertEqual(tickets.merge_ranges([(4, 8), (1, 5)]), [(1, 8)])

    def test_tickets_invert(self):
        self.assertEqual(tickets.invert({'a': 1, 'b': 2, 'c': 1}), {1: ['a', 'c'], 2: ['b']})
        self.assertEqual(tickets.invert({}), {})
        self.assertEqual(tickets.invert({'x': 'y'}), {'y': ['x']})
        self.assertEqual(tickets.invert({'q': 0, 'p': 0, 'r': 0}), {0: ['p', 'q', 'r']})
