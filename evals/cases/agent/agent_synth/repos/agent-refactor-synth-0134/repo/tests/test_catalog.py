import unittest

from granary import catalog


class Catalog(unittest.TestCase):
    def test_barge_line(self):
        self.assertEqual(catalog.barge_line(5, 0, 10), {'barge_line': 5})
        self.assertEqual(catalog.barge_line(-3, 0, 10), {'barge_line': 0})

    def test_snake_case(self):
        self.assertEqual(catalog.snake_case('OrderTotal'), 'order_total')
        self.assertEqual(catalog.snake_case('plain'), 'plain')
