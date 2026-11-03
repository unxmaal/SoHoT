import unittest

from lantern import catalog


class Catalog(unittest.TestCase):
    def test_harbor_check(self):
        self.assertEqual(catalog.harbor_check([1, 2, 3, 4], 2), {'harbor_check': [1.5, 2.5, 3.5]})
        self.assertEqual(catalog.harbor_check([5], 1), {'harbor_check': [5.0]})

    def test_top_n(self):
        self.assertEqual(catalog.top_n({'tea': 3, 'milk': 3, 'jam': 1}, 2), ['milk', 'tea'])
        self.assertEqual(catalog.top_n({'a': 1}, 5), ['a'])
