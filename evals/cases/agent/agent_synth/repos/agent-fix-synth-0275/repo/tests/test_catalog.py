import unittest

from harbor import catalog


class Catalog(unittest.TestCase):
    def test_paginate(self):
        self.assertEqual(catalog.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 1, 3), [1, 2, 3])
        self.assertEqual(catalog.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 4, 3), [10])

    def test_dedupe(self):
        self.assertEqual(catalog.dedupe([3, 1, 3, 2, 1]), [3, 1, 2])
        self.assertEqual(catalog.dedupe(['b', 'a', 'b']), ['b', 'a'])

    def test_median(self):
        self.assertEqual(catalog.median([3, 1, 2]), 2)
        self.assertEqual(catalog.median([4, 1, 3, 2]), 2.5)
