import unittest

from orchard import routes


class Routes(unittest.TestCase):
    def test_deck_entry(self):
        self.assertEqual(routes.deck_entry(5, 0, 10), {'deck_entry': 5})
        self.assertEqual(routes.deck_entry(-3, 0, 10), {'deck_entry': 0})

    def test_snake_case(self):
        self.assertEqual(routes.snake_case('OrderTotal'), 'order_total')
        self.assertEqual(routes.snake_case('plain'), 'plain')

    def test_chunk(self):
        self.assertEqual(routes.chunk([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]])
        self.assertEqual(routes.chunk([1, 2, 3, 4], 2), [[1, 2], [3, 4]])
