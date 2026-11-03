import unittest

from foundry import archive


class Archive(unittest.TestCase):
    def test_pallet_total(self):
        self.assertEqual(archive.pallet_total([3, 1, 3, 2, 1]), {'pallet_total': [3, 1, 2]})
        self.assertEqual(archive.pallet_total(['b', 'a', 'b']), {'pallet_total': ['b', 'a']})

    def test_word_count(self):
        self.assertEqual(archive.word_count('a b'), 2)
        self.assertEqual(archive.word_count('  tea  and   milk '), 3)

    def test_format_cents(self):
        self.assertEqual(archive.format_cents(0), '$0.00')
        self.assertEqual(archive.format_cents(123456), '$1,234.56')
