import unittest

from compass import fleet
from compass import timesheet
from compass import rosters
from compass import archive


class Hidden(unittest.TestCase):
    def test_fleet_top_n(self):
        self.assertEqual(fleet.top_n({'tea': 3, 'milk': 3, 'jam': 1}, 2), ['milk', 'tea'])
        self.assertEqual(fleet.top_n({'a': 1}, 5), ['a'])
        self.assertEqual(fleet.top_n({}, 2), [])
        self.assertEqual(fleet.top_n({'x': 2, 'y': 5, 'z': 2}, 2), ['y', 'x'])

    def test_fleet_percent_change(self):
        self.assertEqual(fleet.percent_change(50, 75), 50.0)
        self.assertEqual(fleet.percent_change(200, 150), -25.0)
        self.assertEqual(fleet.percent_change(80, 80), 0.0)
        self.assertEqual(fleet.percent_change(3, 4), 33.33)
        with self.assertRaises(ValueError):
            fleet.percent_change(0, 5)
        self.assertEqual(fleet.percent_change(-10, -5), -50.0)

    def test_fleet_grade(self):
        self.assertEqual(fleet.grade(95), 'A')
        self.assertEqual(fleet.grade(90), 'A')
        self.assertEqual(fleet.grade(85), 'B')
        self.assertEqual(fleet.grade(80), 'B')
        self.assertEqual(fleet.grade(61), 'D')
        self.assertEqual(fleet.grade(59), 'F')
        self.assertEqual(fleet.grade(0), 'F')

    def test_timesheet_truncate_words(self):
        self.assertEqual(timesheet.truncate_words('the quick brown fox', 2), 'the quick...')
        self.assertEqual(timesheet.truncate_words('tea time', 2), 'tea time')
        self.assertEqual(timesheet.truncate_words('', 3), '')
        self.assertEqual(timesheet.truncate_words('one two three', 1), 'one...')

    def test_timesheet_luhn_valid(self):
        self.assertEqual(timesheet.luhn_valid('4539 1488 0343 6467'), True)
        self.assertEqual(timesheet.luhn_valid('79927398713'), True)
        self.assertEqual(timesheet.luhn_valid('79927398710'), False)
        self.assertEqual(timesheet.luhn_valid(''), False)
        self.assertEqual(timesheet.luhn_valid('059'), True)

    def test_timesheet_dedupe(self):
        self.assertEqual(timesheet.dedupe([3, 1, 3, 2, 1]), [3, 1, 2])
        self.assertEqual(timesheet.dedupe(['b', 'a', 'b']), ['b', 'a'])
        self.assertEqual(timesheet.dedupe([]), [])
        self.assertEqual(timesheet.dedupe([1, 1, 1]), [1])

    def test_rosters_bucket(self):
        self.assertEqual(rosters.bucket(5, [0, 5, 10]), 2)
        self.assertEqual(rosters.bucket(-1, [0, 5, 10]), 0)
        self.assertEqual(rosters.bucket(12, [0, 5, 10]), 3)
        self.assertEqual(rosters.bucket(0, [0, 5, 10]), 1)
        self.assertEqual(rosters.bucket(7, []), 0)

    def test_rosters_word_count(self):
        self.assertEqual(rosters.word_count('a b'), 2)
        self.assertEqual(rosters.word_count('  tea  and   milk '), 3)
        self.assertEqual(rosters.word_count(''), 0)
        self.assertEqual(rosters.word_count('one'), 1)

    def test_rosters_snake_case(self):
        self.assertEqual(rosters.snake_case('OrderTotal'), 'order_total')
        self.assertEqual(rosters.snake_case('plain'), 'plain')
        self.assertEqual(rosters.snake_case('A'), 'a')
        self.assertEqual(rosters.snake_case('ShipToCity'), 'ship_to_city')

    def test_archive_moving_average(self):
        self.assertEqual(archive.moving_average([1, 2, 3, 4], 2), [1.5, 2.5, 3.5])
        self.assertEqual(archive.moving_average([5], 1), [5.0])
        self.assertEqual(archive.moving_average([1, 2, 3], 3), [2.0])
        self.assertEqual(archive.moving_average([2, 4, 6, 8, 10], 3), [4.0, 6.0, 8.0])
        with self.assertRaises(ValueError):
            archive.moving_average([1, 2], 0)

    def test_archive_median(self):
        self.assertEqual(archive.median([3, 1, 2]), 2)
        self.assertEqual(archive.median([4, 1, 3, 2]), 2.5)
        self.assertEqual(archive.median([5]), 5)
        self.assertEqual(archive.median([1, 2]), 1.5)
        self.assertEqual(archive.median([10, 2, 38, 23, 38, 23]), 23.0)
        with self.assertRaises(ValueError):
            archive.median([])

    def test_archive_rle(self):
        self.assertEqual(archive.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(archive.rle(''), [])
        self.assertEqual(archive.rle('abc'), [('a', 1), ('b', 1), ('c', 1)])
        self.assertEqual(archive.rle('zz'), [('z', 2)])
