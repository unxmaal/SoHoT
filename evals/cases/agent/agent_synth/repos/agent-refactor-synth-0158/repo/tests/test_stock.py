import unittest

from atlas import stock


class Stock(unittest.TestCase):
    def test_harbor_check(self):
        self.assertEqual(stock.harbor_check(2024), {'harbor_check': True})
        self.assertEqual(stock.harbor_check(1900), {'harbor_check': False})

    def test_snake_case(self):
        self.assertEqual(stock.snake_case('OrderTotal'), 'order_total')
        self.assertEqual(stock.snake_case('plain'), 'plain')
