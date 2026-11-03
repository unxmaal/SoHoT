import unittest

from atlas import pricing
from atlas import archive


class Hidden(unittest.TestCase):
    def test_pricing_parse_duration(self):
        self.assertEqual(pricing.parse_duration('1h30m'), 5400)
        self.assertEqual(pricing.parse_duration('45s'), 45)
        self.assertEqual(pricing.parse_duration('2h'), 7200)
        self.assertEqual(pricing.parse_duration('1h1m1s'), 3661)
        with self.assertRaises(ValueError):
            pricing.parse_duration('')
        with self.assertRaises(ValueError):
            pricing.parse_duration('5x')
        self.assertEqual(pricing.parse_duration('10m5s'), 605)

    def test_pricing_rle(self):
        self.assertEqual(pricing.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(pricing.rle(''), [])
        self.assertEqual(pricing.rle('abc'), [('a', 1), ('b', 1), ('c', 1)])
        self.assertEqual(pricing.rle('zz'), [('z', 2)])

    def test_archive_chunk(self):
        self.assertEqual(archive.chunk([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]])
        self.assertEqual(archive.chunk([1, 2, 3, 4], 2), [[1, 2], [3, 4]])
        self.assertEqual(archive.chunk([], 3), [])
        self.assertEqual(archive.chunk(['a'], 1), [['a']])
        self.assertEqual(archive.chunk([1, 2, 3], 5), [[1, 2, 3]])
        with self.assertRaises(ValueError):
            archive.chunk([1, 2], 0)

    def test_archive_weighted_mean(self):
        self.assertEqual(archive.weighted_mean([1, 2, 3], [1, 1, 1]), 2.0)
        self.assertEqual(archive.weighted_mean([10, 20], [1, 3]), 17.5)
        self.assertEqual(archive.weighted_mean([4], [2]), 4.0)
        with self.assertRaises(ValueError):
            archive.weighted_mean([5, 5], [0, 0])
        self.assertEqual(archive.weighted_mean([1, 2], [0.5, 1.5]), 1.75)

    def test_feature(self):
        self.assertEqual(pricing.parse_duration('1d'), 86400)
        self.assertEqual(pricing.parse_duration('2d3h'), 183600)
