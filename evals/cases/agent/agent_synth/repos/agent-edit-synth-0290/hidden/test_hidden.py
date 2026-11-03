import unittest

from granary import catalog
from granary import routes
from granary import survey
from granary import kitchen


class Hidden(unittest.TestCase):
    def test_catalog_grade(self):
        self.assertEqual(catalog.grade(95), 'A')
        self.assertEqual(catalog.grade(90), 'A')
        self.assertEqual(catalog.grade(85), 'B')
        self.assertEqual(catalog.grade(80), 'B')
        self.assertEqual(catalog.grade(61), 'D')
        self.assertEqual(catalog.grade(59), 'F')
        self.assertEqual(catalog.grade(0), 'F')

    def test_catalog_word_count(self):
        self.assertEqual(catalog.word_count('a b'), 2)
        self.assertEqual(catalog.word_count('  tea  and   milk '), 3)
        self.assertEqual(catalog.word_count(''), 0)
        self.assertEqual(catalog.word_count('one'), 1)

    def test_routes_parse_duration(self):
        self.assertEqual(routes.parse_duration('1h30m'), 5400)
        self.assertEqual(routes.parse_duration('45s'), 45)
        self.assertEqual(routes.parse_duration('2h'), 7200)
        self.assertEqual(routes.parse_duration('1h1m1s'), 3661)
        with self.assertRaises(ValueError):
            routes.parse_duration('')
        with self.assertRaises(ValueError):
            routes.parse_duration('5x')
        self.assertEqual(routes.parse_duration('10m5s'), 605)

    def test_routes_merge_ranges(self):
        self.assertEqual(routes.merge_ranges([(1, 3), (3, 5)]), [(1, 5)])
        self.assertEqual(routes.merge_ranges([(5, 6), (1, 2)]), [(1, 2), (5, 6)])
        self.assertEqual(routes.merge_ranges([(1, 10), (2, 3)]), [(1, 10)])
        self.assertEqual(routes.merge_ranges([]), [])
        self.assertEqual(routes.merge_ranges([(4, 8), (1, 5)]), [(1, 8)])

    def test_routes_top_n(self):
        self.assertEqual(routes.top_n({'tea': 3, 'milk': 3, 'jam': 1}, 2), ['milk', 'tea'])
        self.assertEqual(routes.top_n({'a': 1}, 5), ['a'])
        self.assertEqual(routes.top_n({}, 2), [])
        self.assertEqual(routes.top_n({'x': 2, 'y': 5, 'z': 2}, 2), ['y', 'x'])

    def test_survey_rle(self):
        self.assertEqual(survey.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(survey.rle(''), [])
        self.assertEqual(survey.rle('abc'), [('a', 1), ('b', 1), ('c', 1)])
        self.assertEqual(survey.rle('zz'), [('z', 2)])

    def test_survey_running_total(self):
        self.assertEqual(survey.running_total([1, 2, 3]), [1, 3, 6])
        self.assertEqual(survey.running_total([]), [])
        self.assertEqual(survey.running_total([5]), [5])
        self.assertEqual(survey.running_total([2, -2, 2]), [2, 0, 2])

    def test_kitchen_percent_change(self):
        self.assertEqual(kitchen.percent_change(50, 75), 50.0)
        self.assertEqual(kitchen.percent_change(200, 150), -25.0)
        self.assertEqual(kitchen.percent_change(80, 80), 0.0)
        self.assertEqual(kitchen.percent_change(3, 4), 33.33)
        with self.assertRaises(ValueError):
            kitchen.percent_change(0, 5)
        self.assertEqual(kitchen.percent_change(-10, -5), -50.0)

    def test_kitchen_dedupe(self):
        self.assertEqual(kitchen.dedupe([3, 1, 3, 2, 1]), [3, 1, 2])
        self.assertEqual(kitchen.dedupe(['b', 'a', 'b']), ['b', 'a'])
        self.assertEqual(kitchen.dedupe([]), [])
        self.assertEqual(kitchen.dedupe([1, 1, 1]), [1])

    def test_kitchen_paginate(self):
        self.assertEqual(kitchen.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 1, 3), [1, 2, 3])
        self.assertEqual(kitchen.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 4, 3), [10])
        self.assertEqual(kitchen.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 5, 3), [])
        self.assertEqual(kitchen.paginate([], 1, 5), [])
        with self.assertRaises(ValueError):
            kitchen.paginate([1, 2], 0, 2)

    def test_feature(self):
        self.assertEqual(routes.parse_duration('1d'), 86400)
        self.assertEqual(routes.parse_duration('2d3h'), 183600)
