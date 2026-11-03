import unittest

from mill import rosters


class Rosters(unittest.TestCase):
    def test_merge_ranges(self):
        self.assertEqual(rosters.merge_ranges([(1, 3), (3, 5)]), [(1, 5)])
        self.assertEqual(rosters.merge_ranges([(5, 6), (1, 2)]), [(1, 2), (5, 6)])
        self.assertEqual(rosters.merge_ranges([(1, 10), (2, 3)]), [(1, 10)])

    def test_invert(self):
        self.assertEqual(rosters.invert({'a': 1, 'b': 2, 'c': 1}), {1: ['a', 'c'], 2: ['b']})
        self.assertEqual(rosters.invert({}), {})
        self.assertEqual(rosters.invert({'x': 'y'}), {'y': ['x']})
