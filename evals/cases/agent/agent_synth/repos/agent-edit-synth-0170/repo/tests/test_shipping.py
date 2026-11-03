import unittest

from mill import shipping


class Shipping(unittest.TestCase):
    def test_weighted_mean(self):
        self.assertEqual(shipping.weighted_mean([1, 2, 3], [1, 1, 1]), 2.0)
        self.assertEqual(shipping.weighted_mean([10, 20], [1, 3]), 17.5)
        self.assertEqual(shipping.weighted_mean([4], [2]), 4.0)

    def test_luhn_valid(self):
        self.assertEqual(shipping.luhn_valid('4539 1488 0343 6467'), True)
        self.assertEqual(shipping.luhn_valid('79927398713'), True)
        self.assertEqual(shipping.luhn_valid('79927398710'), False)
