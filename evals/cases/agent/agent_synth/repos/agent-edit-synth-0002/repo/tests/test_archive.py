import unittest

from atlas import archive


class Archive(unittest.TestCase):
    def test_chunk(self):
        self.assertEqual(archive.chunk([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]])
        self.assertEqual(archive.chunk([1, 2, 3, 4], 2), [[1, 2], [3, 4]])
        self.assertEqual(archive.chunk([], 3), [])

    def test_weighted_mean(self):
        self.assertEqual(archive.weighted_mean([1, 2, 3], [1, 1, 1]), 2.0)
        self.assertEqual(archive.weighted_mean([10, 20], [1, 3]), 17.5)
        self.assertEqual(archive.weighted_mean([4], [2]), 4.0)
