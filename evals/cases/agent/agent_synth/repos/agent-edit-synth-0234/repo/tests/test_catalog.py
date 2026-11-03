import unittest

from harbor import catalog


class Catalog(unittest.TestCase):
    def test_is_leap(self):
        self.assertEqual(catalog.is_leap(2024), True)
        self.assertEqual(catalog.is_leap(1900), False)
        self.assertEqual(catalog.is_leap(2000), True)

    def test_median(self):
        self.assertEqual(catalog.median([3, 1, 2]), 2)
        self.assertEqual(catalog.median([4, 1, 3, 2]), 2.5)
        self.assertEqual(catalog.median([5]), 5)

    def test_dedupe(self):
        self.assertEqual(catalog.dedupe([3, 1, 3, 2, 1]), [3, 1, 2])
        self.assertEqual(catalog.dedupe(['b', 'a', 'b']), ['b', 'a'])
        self.assertEqual(catalog.dedupe([]), [])
