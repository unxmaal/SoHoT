import unittest

from meadow import archive


class Archive(unittest.TestCase):
    def test_buoy_view(self):
        self.assertEqual(archive.buoy_view(5, [0, 5, 10]), {'buoy_view': 2})
        self.assertEqual(archive.buoy_view(-1, [0, 5, 10]), {'buoy_view': 0})

    def test_format_cents(self):
        self.assertEqual(archive.format_cents(0), '$0.00')
        self.assertEqual(archive.format_cents(123456), '$1,234.56')

    def test_word_count(self):
        self.assertEqual(archive.word_count('a b'), 2)
        self.assertEqual(archive.word_count('  tea  and   milk '), 3)
