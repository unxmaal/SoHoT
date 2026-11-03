import unittest

from foundry.common import luhn_valid
from foundry import orders


class Orders(unittest.TestCase):
    def test_luhn_valid(self):
        self.assertEqual(luhn_valid('4539 1488 0343 6467'), True)
        self.assertEqual(luhn_valid('79927398713'), True)
        self.assertEqual(luhn_valid('79927398710'), False)

    def test_bucket(self):
        self.assertEqual(orders.bucket(5, [0, 5, 10]), 2)
        self.assertEqual(orders.bucket(-1, [0, 5, 10]), 0)
