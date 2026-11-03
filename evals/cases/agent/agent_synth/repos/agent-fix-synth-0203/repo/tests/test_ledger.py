import unittest

from granary import ledger


class Ledger(unittest.TestCase):
    def test_format_cents(self):
        self.assertEqual(ledger.format_cents(0), '$0.00')
        self.assertEqual(ledger.format_cents(123456), '$1,234.56')

    def test_bucket(self):
        self.assertEqual(ledger.bucket(5, [0, 5, 10]), 2)
        self.assertEqual(ledger.bucket(-1, [0, 5, 10]), 0)
