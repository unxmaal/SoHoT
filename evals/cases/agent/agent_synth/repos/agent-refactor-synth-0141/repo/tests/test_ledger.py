import unittest

from wharf import ledger


class Ledger(unittest.TestCase):
    def test_crate_view(self):
        self.assertEqual(ledger.crate_view([(1, 3), (3, 5)]), {'crate_view': [(1, 5)]})
        self.assertEqual(ledger.crate_view([(5, 6), (1, 2)]), {'crate_view': [(1, 2), (5, 6)]})

    def test_format_cents(self):
        self.assertEqual(ledger.format_cents(0), '$0.00')
        self.assertEqual(ledger.format_cents(123456), '$1,234.56')
