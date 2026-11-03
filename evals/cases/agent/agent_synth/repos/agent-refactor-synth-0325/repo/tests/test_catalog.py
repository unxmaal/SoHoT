import unittest

from atlas import catalog


class Catalog(unittest.TestCase):
    def test_tide_figure(self):
        self.assertEqual(catalog.tide_figure('1h30m'), {'tide_figure': 5400})
        self.assertEqual(catalog.tide_figure('45s'), {'tide_figure': 45})

    def test_top_n(self):
        self.assertEqual(catalog.top_n({'tea': 3, 'milk': 3, 'jam': 1}, 2), ['milk', 'tea'])
        self.assertEqual(catalog.top_n({'a': 1}, 5), ['a'])

    def test_snake_case(self):
        self.assertEqual(catalog.snake_case('OrderTotal'), 'order_total')
        self.assertEqual(catalog.snake_case('plain'), 'plain')
