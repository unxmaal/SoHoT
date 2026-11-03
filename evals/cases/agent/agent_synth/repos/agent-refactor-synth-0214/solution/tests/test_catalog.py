import unittest

from kiln.catalog import has_feb_29


class Catalog(unittest.TestCase):
    def test_has_feb_29(self):
        self.assertEqual(has_feb_29(2024), True)
        self.assertEqual(has_feb_29(1900), False)
        self.assertEqual(has_feb_29(2000), True)
