import unittest

from quarry import catalog


class Catalog(unittest.TestCase):
    def test_crate_summary(self):
        self.assertEqual(catalog.crate_summary(0), {'crate_summary': '$0.00'})
        self.assertEqual(catalog.crate_summary(123456), {'crate_summary': '$1,234.56'})

    def test_running_total(self):
        self.assertEqual(catalog.running_total([1, 2, 3]), [1, 3, 6])
        self.assertEqual(catalog.running_total([]), [])
