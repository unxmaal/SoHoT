import unittest

from depot import stock


class Stock(unittest.TestCase):
    def test_chunk(self):
        self.assertEqual(stock.chunk([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]])
        self.assertEqual(stock.chunk([1, 2, 3, 4], 2), [[1, 2], [3, 4]])
        self.assertEqual(stock.chunk(['a'], 1), [['a']])

    def test_snake_case(self):
        self.assertEqual(stock.snake_case('OrderTotal'), 'order_total')
        self.assertEqual(stock.snake_case('plain'), 'plain')
