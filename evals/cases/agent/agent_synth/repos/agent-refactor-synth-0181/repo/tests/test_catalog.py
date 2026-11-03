import unittest

from harbor.catalog import grade
from harbor import catalog


class Catalog(unittest.TestCase):
    def test_grade(self):
        self.assertEqual(grade(95), 'A')
        self.assertEqual(grade(90), 'A')
        self.assertEqual(grade(85), 'B')

    def test_invert(self):
        self.assertEqual(catalog.invert({'a': 1, 'b': 2, 'c': 1}), {1: ['a', 'c'], 2: ['b']})
        self.assertEqual(catalog.invert({}), {})
