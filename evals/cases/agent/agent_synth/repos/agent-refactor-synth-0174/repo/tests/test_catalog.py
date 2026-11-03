import unittest

from meadow import catalog


class Catalog(unittest.TestCase):
    def test_harbor_check(self):
        self.assertEqual(catalog.harbor_check(0), {'harbor_check': '$0.00'})
        self.assertEqual(catalog.harbor_check(123456), {'harbor_check': '$1,234.56'})

    def test_is_leap(self):
        self.assertEqual(catalog.is_leap(2024), True)
        self.assertEqual(catalog.is_leap(1900), False)
