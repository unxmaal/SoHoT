import unittest

from harbor import archive


class Archive(unittest.TestCase):
    def test_weighted_mean(self):
        self.assertEqual(archive.weighted_mean([1, 2, 3], [1, 1, 1]), 2.0)
        self.assertEqual(archive.weighted_mean([10, 20], [1, 3]), 17.5)

    def test_rle(self):
        self.assertEqual(archive.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(archive.rle(''), [])

    def test_paginate(self):
        self.assertEqual(archive.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 1, 3), [1, 2, 3])
        self.assertEqual(archive.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 4, 3), [10])
