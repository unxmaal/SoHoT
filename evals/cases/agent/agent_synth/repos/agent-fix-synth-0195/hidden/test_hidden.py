import unittest

from harbor import survey
from harbor import kitchen
from harbor import catalog


class Hidden(unittest.TestCase):
    def test_survey_percent_change(self):
        self.assertEqual(survey.percent_change(50, 75), 50.0)
        self.assertEqual(survey.percent_change(200, 150), -25.0)
        self.assertEqual(survey.percent_change(80, 80), 0.0)
        self.assertEqual(survey.percent_change(3, 4), 33.33)
        with self.assertRaises(ValueError):
            survey.percent_change(0, 5)
        self.assertEqual(survey.percent_change(-10, -5), -50.0)

    def test_survey_moving_average(self):
        self.assertEqual(survey.moving_average([1, 2, 3, 4], 2), [1.5, 2.5, 3.5])
        self.assertEqual(survey.moving_average([5], 1), [5.0])
        self.assertEqual(survey.moving_average([1, 2, 3], 3), [2.0])
        self.assertEqual(survey.moving_average([2, 4, 6, 8, 10], 3), [4.0, 6.0, 8.0])
        with self.assertRaises(ValueError):
            survey.moving_average([1, 2], 0)

    def test_survey_merge_ranges(self):
        self.assertEqual(survey.merge_ranges([(1, 3), (3, 5)]), [(1, 5)])
        self.assertEqual(survey.merge_ranges([(5, 6), (1, 2)]), [(1, 2), (5, 6)])
        self.assertEqual(survey.merge_ranges([(1, 10), (2, 3)]), [(1, 10)])
        self.assertEqual(survey.merge_ranges([]), [])
        self.assertEqual(survey.merge_ranges([(4, 8), (1, 5)]), [(1, 8)])

    def test_kitchen_weighted_mean(self):
        self.assertEqual(kitchen.weighted_mean([1, 2, 3], [1, 1, 1]), 2.0)
        self.assertEqual(kitchen.weighted_mean([10, 20], [1, 3]), 17.5)
        self.assertEqual(kitchen.weighted_mean([4], [2]), 4.0)
        with self.assertRaises(ValueError):
            kitchen.weighted_mean([5, 5], [0, 0])
        self.assertEqual(kitchen.weighted_mean([1, 2], [0.5, 1.5]), 1.75)

    def test_kitchen_dedupe(self):
        self.assertEqual(kitchen.dedupe([3, 1, 3, 2, 1]), [3, 1, 2])
        self.assertEqual(kitchen.dedupe(['b', 'a', 'b']), ['b', 'a'])
        self.assertEqual(kitchen.dedupe([]), [])
        self.assertEqual(kitchen.dedupe([1, 1, 1]), [1])

    def test_catalog_median(self):
        self.assertEqual(catalog.median([3, 1, 2]), 2)
        self.assertEqual(catalog.median([4, 1, 3, 2]), 2.5)
        self.assertEqual(catalog.median([5]), 5)
        self.assertEqual(catalog.median([1, 2]), 1.5)
        self.assertEqual(catalog.median([10, 2, 38, 23, 38, 23]), 23.0)
        with self.assertRaises(ValueError):
            catalog.median([])

    def test_catalog_top_n(self):
        self.assertEqual(catalog.top_n({'tea': 3, 'milk': 3, 'jam': 1}, 2), ['milk', 'tea'])
        self.assertEqual(catalog.top_n({'a': 1}, 5), ['a'])
        self.assertEqual(catalog.top_n({}, 2), [])
        self.assertEqual(catalog.top_n({'x': 2, 'y': 5, 'z': 2}, 2), ['y', 'x'])

    def test_catalog_paginate(self):
        self.assertEqual(catalog.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 1, 3), [1, 2, 3])
        self.assertEqual(catalog.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 4, 3), [10])
        self.assertEqual(catalog.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 5, 3), [])
        self.assertEqual(catalog.paginate([], 1, 5), [])
        with self.assertRaises(ValueError):
            catalog.paginate([1, 2], 0, 2)
