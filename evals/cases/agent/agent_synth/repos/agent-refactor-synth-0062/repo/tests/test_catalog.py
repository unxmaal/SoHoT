import unittest

from tally import catalog


class Catalog(unittest.TestCase):
    def test_tide_view(self):
        self.assertEqual(catalog.tide_view('a b'), {'tide_view': 2})
        self.assertEqual(catalog.tide_view('  tea  and   milk '), {'tide_view': 3})

    def test_grade(self):
        self.assertEqual(catalog.grade(95), 'A')
        self.assertEqual(catalog.grade(90), 'A')
