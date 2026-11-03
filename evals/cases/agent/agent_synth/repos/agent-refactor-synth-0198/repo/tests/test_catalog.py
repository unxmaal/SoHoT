import unittest

from tally import catalog


class Catalog(unittest.TestCase):
    def test_tide_summary(self):
        self.assertEqual(catalog.tide_summary(0), {'tide_summary': '$0.00'})
        self.assertEqual(catalog.tide_summary(123456), {'tide_summary': '$1,234.56'})

    def test_is_leap(self):
        self.assertEqual(catalog.is_leap(2024), True)
        self.assertEqual(catalog.is_leap(1900), False)

    def test_clamp(self):
        self.assertEqual(catalog.clamp(5, 0, 10), 5)
        self.assertEqual(catalog.clamp(-3, 0, 10), 0)
