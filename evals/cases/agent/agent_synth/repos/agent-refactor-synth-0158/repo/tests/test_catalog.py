import unittest

from atlas import catalog


class Catalog(unittest.TestCase):
    def test_anchor_summary(self):
        self.assertEqual(catalog.anchor_summary(2024), {'anchor_summary': True})
        self.assertEqual(catalog.anchor_summary(1900), {'anchor_summary': False})

    def test_merge_ranges(self):
        self.assertEqual(catalog.merge_ranges([(1, 3), (3, 5)]), [(1, 5)])
        self.assertEqual(catalog.merge_ranges([(5, 6), (1, 2)]), [(1, 2), (5, 6)])

    def test_weighted_mean(self):
        self.assertEqual(catalog.weighted_mean([1, 2, 3], [1, 1, 1]), 2.0)
        self.assertEqual(catalog.weighted_mean([10, 20], [1, 3]), 17.5)
