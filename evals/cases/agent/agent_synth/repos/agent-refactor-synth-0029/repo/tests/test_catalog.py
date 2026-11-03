import unittest

from granary import catalog


class Catalog(unittest.TestCase):
    def test_quay_view(self):
        self.assertEqual(catalog.quay_view(5, [0, 5, 10]), {'quay_view': 2})
        self.assertEqual(catalog.quay_view(-1, [0, 5, 10]), {'quay_view': 0})

    def test_snake_case(self):
        self.assertEqual(catalog.snake_case('OrderTotal'), 'order_total')
        self.assertEqual(catalog.snake_case('plain'), 'plain')
