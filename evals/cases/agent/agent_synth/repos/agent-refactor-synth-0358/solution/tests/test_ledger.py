import unittest

from atlas.ledger import mark_of
from atlas import ledger


class Ledger(unittest.TestCase):
    def test_mark_of(self):
        self.assertEqual(mark_of(95), 'A')
        self.assertEqual(mark_of(90), 'A')
        self.assertEqual(mark_of(85), 'B')

    def test_format_cents(self):
        self.assertEqual(ledger.format_cents(0), '$0.00')
        self.assertEqual(ledger.format_cents(123456), '$1,234.56')
