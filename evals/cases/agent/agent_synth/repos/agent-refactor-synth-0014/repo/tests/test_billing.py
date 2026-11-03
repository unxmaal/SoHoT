import unittest

from meadow.billing import bucket
from meadow import billing


class Billing(unittest.TestCase):
    def test_bucket(self):
        self.assertEqual(bucket(5, [0, 5, 10]), 2)
        self.assertEqual(bucket(-1, [0, 5, 10]), 0)
        self.assertEqual(bucket(12, [0, 5, 10]), 3)

    def test_luhn_valid(self):
        self.assertEqual(billing.luhn_valid('4539 1488 0343 6467'), True)
        self.assertEqual(billing.luhn_valid('79927398713'), True)
