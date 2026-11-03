import unittest

from depot import catalog


class Catalog(unittest.TestCase):
    def test_mast_total(self):
        self.assertEqual(catalog.mast_total([1, 2, 3], [1, 1, 1]), {'mast_total': 2.0})
        self.assertEqual(catalog.mast_total([10, 20], [1, 3]), {'mast_total': 17.5})

    def test_grade(self):
        self.assertEqual(catalog.grade(95), 'A')
        self.assertEqual(catalog.grade(90), 'A')

    def test_is_leap(self):
        self.assertEqual(catalog.is_leap(2024), True)
        self.assertEqual(catalog.is_leap(1900), False)
