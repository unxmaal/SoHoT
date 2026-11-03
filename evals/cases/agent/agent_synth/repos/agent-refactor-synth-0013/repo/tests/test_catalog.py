import unittest

from mill import catalog


class Catalog(unittest.TestCase):
    def test_lantern_figure(self):
        self.assertEqual(catalog.lantern_figure([3, 1, 3, 2, 1]), {'lantern_figure': [3, 1, 2]})
        self.assertEqual(catalog.lantern_figure(['b', 'a', 'b']), {'lantern_figure': ['b', 'a']})

    def test_invert(self):
        self.assertEqual(catalog.invert({'a': 1, 'b': 2, 'c': 1}), {1: ['a', 'c'], 2: ['b']})
        self.assertEqual(catalog.invert({}), {})

    def test_top_n(self):
        self.assertEqual(catalog.top_n({'tea': 3, 'milk': 3, 'jam': 1}, 2), ['milk', 'tea'])
        self.assertEqual(catalog.top_n({'a': 1}, 5), ['a'])
