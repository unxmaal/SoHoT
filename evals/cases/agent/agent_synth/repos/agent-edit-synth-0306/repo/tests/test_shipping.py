import unittest

from quarry import shipping


class Shipping(unittest.TestCase):
    def test_luhn_valid(self):
        self.assertEqual(shipping.luhn_valid('4539 1488 0343 6467'), True)
        self.assertEqual(shipping.luhn_valid('79927398713'), True)
        self.assertEqual(shipping.luhn_valid('79927398710'), False)

    def test_running_total(self):
        self.assertEqual(shipping.running_total([1, 2, 3]), [1, 3, 6])
        self.assertEqual(shipping.running_total([]), [])
        self.assertEqual(shipping.running_total([5]), [5])

    def test_invert(self):
        self.assertEqual(shipping.invert({'a': 1, 'b': 2, 'c': 1}), {1: ['a', 'c'], 2: ['b']})
        self.assertEqual(shipping.invert({}), {})
        self.assertEqual(shipping.invert({'x': 'y'}), {'y': ['x']})
