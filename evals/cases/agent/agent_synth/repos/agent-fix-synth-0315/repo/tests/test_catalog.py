import unittest

from wharf import catalog


class Catalog(unittest.TestCase):
    def test_is_leap(self):
        self.assertEqual(catalog.is_leap(2024), True)
        self.assertEqual(catalog.is_leap(1900), False)

    def test_chunk(self):
        self.assertEqual(catalog.chunk([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]])
        self.assertEqual(catalog.chunk([1, 2, 3, 4], 2), [[1, 2], [3, 4]])
        self.assertEqual(catalog.chunk(['a'], 1), [['a']])

    def test_running_total(self):
        self.assertEqual(catalog.running_total([1, 2, 3]), [1, 3, 6])
        self.assertEqual(catalog.running_total([]), [])
