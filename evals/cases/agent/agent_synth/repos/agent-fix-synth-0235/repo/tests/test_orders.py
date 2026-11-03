import unittest

from foundry import orders


class Orders(unittest.TestCase):
    def test_clamp(self):
        self.assertEqual(orders.clamp(5, 0, 10), 5)
        self.assertEqual(orders.clamp(-3, 0, 10), 0)

    def test_percent_change(self):
        self.assertEqual(orders.percent_change(50, 75), 50.0)
        self.assertEqual(orders.percent_change(200, 150), -25.0)

    def test_snake_case(self):
        self.assertEqual(orders.snake_case('OrderTotal'), 'order_total')
        self.assertEqual(orders.snake_case('plain'), 'plain')
        self.assertEqual(orders.snake_case('A'), 'a')
