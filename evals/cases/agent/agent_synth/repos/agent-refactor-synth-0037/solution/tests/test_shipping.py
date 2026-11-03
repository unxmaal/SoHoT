import unittest

from tally.numbers import luhn_valid
from tally import shipping


class Shipping(unittest.TestCase):
    def test_luhn_valid(self):
        self.assertEqual(luhn_valid('4539 1488 0343 6467'), True)
        self.assertEqual(luhn_valid('79927398713'), True)
        self.assertEqual(luhn_valid('79927398710'), False)

    def test_snake_case(self):
        self.assertEqual(shipping.snake_case('OrderTotal'), 'order_total')
        self.assertEqual(shipping.snake_case('plain'), 'plain')
