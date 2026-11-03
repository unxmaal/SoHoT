import unittest

from harbor import stock


class Stock(unittest.TestCase):
    def test_snake_case(self):
        self.assertEqual(stock.snake_case('OrderTotal'), 'order_total')
        self.assertEqual(stock.snake_case('plain'), 'plain')
        self.assertEqual(stock.snake_case('A'), 'a')

    def test_percent_change(self):
        self.assertEqual(stock.percent_change(50, 75), 50.0)
        self.assertEqual(stock.percent_change(200, 150), -25.0)
