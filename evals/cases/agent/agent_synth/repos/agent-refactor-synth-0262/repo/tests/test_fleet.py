import unittest

from depot.fleet import merge_ranges


class Fleet(unittest.TestCase):
    def test_merge_ranges(self):
        self.assertEqual(merge_ranges([(1, 3), (3, 5)]), [(1, 5)])
        self.assertEqual(merge_ranges([(5, 6), (1, 2)]), [(1, 2), (5, 6)])
        self.assertEqual(merge_ranges([(1, 10), (2, 3)]), [(1, 10)])
