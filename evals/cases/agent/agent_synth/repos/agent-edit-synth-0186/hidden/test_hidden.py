import unittest

from mill import survey
from mill import rosters
from mill import timesheet


class Hidden(unittest.TestCase):
    def test_survey_rle(self):
        self.assertEqual(survey.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(survey.rle(''), [])
        self.assertEqual(survey.rle('abc'), [('a', 1), ('b', 1), ('c', 1)])
        self.assertEqual(survey.rle('zz'), [('z', 2)])

    def test_survey_weighted_mean(self):
        self.assertEqual(survey.weighted_mean([1, 2, 3], [1, 1, 1]), 2.0)
        self.assertEqual(survey.weighted_mean([10, 20], [1, 3]), 17.5)
        self.assertEqual(survey.weighted_mean([4], [2]), 4.0)
        with self.assertRaises(ValueError):
            survey.weighted_mean([5, 5], [0, 0])
        self.assertEqual(survey.weighted_mean([1, 2], [0.5, 1.5]), 1.75)

    def test_rosters_merge_ranges(self):
        self.assertEqual(rosters.merge_ranges([(1, 3), (3, 5)]), [(1, 5)])
        self.assertEqual(rosters.merge_ranges([(5, 6), (1, 2)]), [(1, 2), (5, 6)])
        self.assertEqual(rosters.merge_ranges([(1, 10), (2, 3)]), [(1, 10)])
        self.assertEqual(rosters.merge_ranges([]), [])
        self.assertEqual(rosters.merge_ranges([(4, 8), (1, 5)]), [(1, 8)])

    def test_rosters_invert(self):
        self.assertEqual(rosters.invert({'a': 1, 'b': 2, 'c': 1}), {1: ['a', 'c'], 2: ['b']})
        self.assertEqual(rosters.invert({}), {})
        self.assertEqual(rosters.invert({'x': 'y'}), {'y': ['x']})
        self.assertEqual(rosters.invert({'q': 0, 'p': 0, 'r': 0}), {0: ['p', 'q', 'r']})

    def test_timesheet_luhn_valid(self):
        self.assertEqual(timesheet.luhn_valid('4539 1488 0343 6467'), True)
        self.assertEqual(timesheet.luhn_valid('79927398713'), True)
        self.assertEqual(timesheet.luhn_valid('79927398710'), False)
        self.assertEqual(timesheet.luhn_valid(''), False)
        self.assertEqual(timesheet.luhn_valid('059'), True)

    def test_timesheet_chunk(self):
        self.assertEqual(timesheet.chunk([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]])
        self.assertEqual(timesheet.chunk([1, 2, 3, 4], 2), [[1, 2], [3, 4]])
        self.assertEqual(timesheet.chunk([], 3), [])
        self.assertEqual(timesheet.chunk(['a'], 1), [['a']])
        self.assertEqual(timesheet.chunk([1, 2, 3], 5), [[1, 2, 3]])
        with self.assertRaises(ValueError):
            timesheet.chunk([1, 2], 0)

    def test_timesheet_top_n(self):
        self.assertEqual(timesheet.top_n({'tea': 3, 'milk': 3, 'jam': 1}, 2), ['milk', 'tea'])
        self.assertEqual(timesheet.top_n({'a': 1}, 5), ['a'])
        self.assertEqual(timesheet.top_n({}, 2), [])
        self.assertEqual(timesheet.top_n({'x': 2, 'y': 5, 'z': 2}, 2), ['y', 'x'])

    def test_feature(self):
        with self.assertRaises(ValueError):
            survey.weighted_mean([1, 2, 3], [1, 1])
        with self.assertRaises(ValueError):
            survey.weighted_mean([4], [1, 2])
