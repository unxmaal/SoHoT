import unittest

from foundry import catalog


class Catalog(unittest.TestCase):
    def test_word_count(self):
        self.assertEqual(catalog.word_count('a b'), 2)
        self.assertEqual(catalog.word_count('  tea  and   milk '), 3)
        self.assertEqual(catalog.word_count(''), 0)

    def test_format_cents(self):
        self.assertEqual(catalog.format_cents(0), '$0.00')
        self.assertEqual(catalog.format_cents(123456), '$1,234.56')
