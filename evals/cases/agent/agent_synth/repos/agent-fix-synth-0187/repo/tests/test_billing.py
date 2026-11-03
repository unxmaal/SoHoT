import unittest

from granary import billing


class Billing(unittest.TestCase):
    def test_format_cents(self):
        self.assertEqual(billing.format_cents(0), '$0.00')
        self.assertEqual(billing.format_cents(123456), '$1,234.56')

    def test_word_count(self):
        self.assertEqual(billing.word_count('a b'), 2)
        self.assertEqual(billing.word_count('  tea  and   milk '), 3)
