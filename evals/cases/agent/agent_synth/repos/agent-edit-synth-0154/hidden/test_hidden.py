import unittest

from depot import fleet
from depot import routes


class Hidden(unittest.TestCase):
    def test_fleet_chunk(self):
        self.assertEqual(fleet.chunk([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]])
        self.assertEqual(fleet.chunk([1, 2, 3, 4], 2), [[1, 2], [3, 4]])
        self.assertEqual(fleet.chunk([], 3), [])
        self.assertEqual(fleet.chunk(['a'], 1), [['a']])
        self.assertEqual(fleet.chunk([1, 2, 3], 5), [[1, 2, 3]])
        with self.assertRaises(ValueError):
            fleet.chunk([1, 2], 0)

    def test_fleet_grade(self):
        self.assertEqual(fleet.grade(95), 'A')
        self.assertEqual(fleet.grade(90), 'A')
        self.assertEqual(fleet.grade(85), 'B')
        self.assertEqual(fleet.grade(80), 'B')
        self.assertEqual(fleet.grade(61), 'D')
        self.assertEqual(fleet.grade(59), 'F')
        self.assertEqual(fleet.grade(0), 'F')

    def test_fleet_rle(self):
        self.assertEqual(fleet.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(fleet.rle(''), [])
        self.assertEqual(fleet.rle('abc'), [('a', 1), ('b', 1), ('c', 1)])
        self.assertEqual(fleet.rle('zz'), [('z', 2)])

    def test_routes_percent_change(self):
        self.assertEqual(routes.percent_change(50, 75), 50.0)
        self.assertEqual(routes.percent_change(200, 150), -25.0)
        self.assertEqual(routes.percent_change(80, 80), 0.0)
        self.assertEqual(routes.percent_change(3, 4), 33.33)
        with self.assertRaises(ValueError):
            routes.percent_change(0, 5)
        self.assertEqual(routes.percent_change(-10, -5), -50.0)

    def test_routes_truncate_words(self):
        self.assertEqual(routes.truncate_words('the quick brown fox', 2), 'the quick...')
        self.assertEqual(routes.truncate_words('tea time', 2), 'tea time')
        self.assertEqual(routes.truncate_words('', 3), '')
        self.assertEqual(routes.truncate_words('one two three', 1), 'one...')

    def test_routes_merge_ranges(self):
        self.assertEqual(routes.merge_ranges([(1, 3), (3, 5)]), [(1, 5)])
        self.assertEqual(routes.merge_ranges([(5, 6), (1, 2)]), [(1, 2), (5, 6)])
        self.assertEqual(routes.merge_ranges([(1, 10), (2, 3)]), [(1, 10)])
        self.assertEqual(routes.merge_ranges([]), [])
        self.assertEqual(routes.merge_ranges([(4, 8), (1, 5)]), [(1, 8)])

    def test_feature(self):
        self.assertEqual(routes.merge_ranges([(1, 2), (3, 4)]), [(1, 4)])
        self.assertEqual(routes.merge_ranges([(7, 9), (1, 6)]), [(1, 9)])
