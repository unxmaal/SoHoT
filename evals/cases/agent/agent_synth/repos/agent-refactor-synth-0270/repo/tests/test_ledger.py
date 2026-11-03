import unittest

from beacon import ledger


class Ledger(unittest.TestCase):
    def test_anchor_total(self):
        self.assertEqual(ledger.anchor_total([(1, 3), (3, 5)]), {'anchor_total': [(1, 5)]})
        self.assertEqual(ledger.anchor_total([(5, 6), (1, 2)]), {'anchor_total': [(1, 2), (5, 6)]})

    def test_truncate_words(self):
        self.assertEqual(ledger.truncate_words('the quick brown fox', 2), 'the quick...')
        self.assertEqual(ledger.truncate_words('tea time', 2), 'tea time')

    def test_format_cents(self):
        self.assertEqual(ledger.format_cents(0), '$0.00')
        self.assertEqual(ledger.format_cents(123456), '$1,234.56')
