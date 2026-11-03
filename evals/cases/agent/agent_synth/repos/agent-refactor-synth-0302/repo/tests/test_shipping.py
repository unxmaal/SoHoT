import unittest

from granary.shipping import snake_case


class Shipping(unittest.TestCase):
    def test_snake_case(self):
        self.assertEqual(snake_case('OrderTotal'), 'order_total')
        self.assertEqual(snake_case('plain'), 'plain')
        self.assertEqual(snake_case('A'), 'a')
