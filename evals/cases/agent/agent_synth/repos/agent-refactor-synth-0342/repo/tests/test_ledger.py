import unittest

from quarry.ledger import format_cents


class Ledger(unittest.TestCase):
    def test_format_cents(self):
        self.assertEqual(format_cents(0), '$0.00')
        self.assertEqual(format_cents(123456), '$1,234.56')
        self.assertEqual(format_cents(-105), '-$1.05')
