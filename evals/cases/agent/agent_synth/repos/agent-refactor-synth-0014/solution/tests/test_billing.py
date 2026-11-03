import unittest

from meadow.billing import bin_index
from meadow import billing


class Billing(unittest.TestCase):
    def test_bin_index(self):
        self.assertEqual(bin_index(5, [0, 5, 10]), 2)
        self.assertEqual(bin_index(-1, [0, 5, 10]), 0)
        self.assertEqual(bin_index(12, [0, 5, 10]), 3)

    def test_luhn_valid(self):
        self.assertEqual(billing.luhn_valid('4539 1488 0343 6467'), True)
        self.assertEqual(billing.luhn_valid('79927398713'), True)
