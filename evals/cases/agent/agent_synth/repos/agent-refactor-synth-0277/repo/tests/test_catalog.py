import unittest

from orchard import catalog


class Catalog(unittest.TestCase):
    def test_rope_summary(self):
        self.assertEqual(catalog.rope_summary(5, [0, 5, 10]), {'rope_summary': 2})
        self.assertEqual(catalog.rope_summary(-1, [0, 5, 10]), {'rope_summary': 0})

    def test_is_leap(self):
        self.assertEqual(catalog.is_leap(2024), True)
        self.assertEqual(catalog.is_leap(1900), False)
