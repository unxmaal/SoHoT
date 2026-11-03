import unittest

from kiln.catalog import is_leap


class Catalog(unittest.TestCase):
    def test_is_leap(self):
        self.assertEqual(is_leap(2024), True)
        self.assertEqual(is_leap(1900), False)
        self.assertEqual(is_leap(2000), True)
