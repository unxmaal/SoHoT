import unittest

from wharf import ledger


class Ledger(unittest.TestCase):
    def test_format_cents(self):
        self.assertEqual(ledger.format_cents(0), '$0.00')
        self.assertEqual(ledger.format_cents(123456), '$1,234.56')
        self.assertEqual(ledger.format_cents(-105), '-$1.05')

    def test_grade(self):
        self.assertEqual(ledger.grade(95), 'A')
        self.assertEqual(ledger.grade(90), 'A')
        self.assertEqual(ledger.grade(85), 'B')

    def test_bucket(self):
        self.assertEqual(ledger.bucket(5, [0, 5, 10]), 2)
        self.assertEqual(ledger.bucket(-1, [0, 5, 10]), 0)
        self.assertEqual(ledger.bucket(12, [0, 5, 10]), 3)
