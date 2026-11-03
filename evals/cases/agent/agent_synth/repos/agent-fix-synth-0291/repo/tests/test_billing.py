import unittest

from atlas import billing


class Billing(unittest.TestCase):
    def test_format_cents(self):
        self.assertEqual(billing.format_cents(0), '$0.00')
        self.assertEqual(billing.format_cents(123456), '$1,234.56')
        self.assertEqual(billing.format_cents(-105), '-$1.05')

    def test_median(self):
        self.assertEqual(billing.median([3, 1, 2]), 2)
        self.assertEqual(billing.median([4, 1, 3, 2]), 2.5)
