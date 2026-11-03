import unittest

from lantern import billing


class Billing(unittest.TestCase):
    def test_bucket(self):
        self.assertEqual(billing.bucket(5, [0, 5, 10]), 2)
        self.assertEqual(billing.bucket(-1, [0, 5, 10]), 0)
        self.assertEqual(billing.bucket(0, [0, 5, 10]), 1)

    def test_luhn_valid(self):
        self.assertEqual(billing.luhn_valid('4539 1488 0343 6467'), True)
        self.assertEqual(billing.luhn_valid('79927398713'), True)

    def test_grade(self):
        self.assertEqual(billing.grade(95), 'A')
        self.assertEqual(billing.grade(90), 'A')
