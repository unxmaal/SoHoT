import unittest

from granary import billing


class Billing(unittest.TestCase):
    def test_is_leap(self):
        self.assertEqual(billing.is_leap(2024), True)
        self.assertEqual(billing.is_leap(1900), False)

    def test_bucket(self):
        self.assertEqual(billing.bucket(5, [0, 5, 10]), 2)
        self.assertEqual(billing.bucket(-1, [0, 5, 10]), 0)
        self.assertEqual(billing.bucket(0, [0, 5, 10]), 1)
