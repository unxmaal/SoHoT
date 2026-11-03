import unittest

from granary.shipping import to_snake


class Shipping(unittest.TestCase):
    def test_to_snake(self):
        self.assertEqual(to_snake('OrderTotal'), 'order_total')
        self.assertEqual(to_snake('plain'), 'plain')
        self.assertEqual(to_snake('A'), 'a')
