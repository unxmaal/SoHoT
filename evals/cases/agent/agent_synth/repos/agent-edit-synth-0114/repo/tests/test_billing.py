import unittest

from orchard import billing


class Billing(unittest.TestCase):
    def test_is_leap(self):
        self.assertEqual(billing.is_leap(2024), True)
        self.assertEqual(billing.is_leap(1900), False)
        self.assertEqual(billing.is_leap(2000), True)

    def test_format_cents(self):
        self.assertEqual(billing.format_cents(0), '$0.00')
        self.assertEqual(billing.format_cents(123456), '$1,234.56')
        self.assertEqual(billing.format_cents(-105), '-$1.05')
