import unittest

from harbor import rosters


class Rosters(unittest.TestCase):
    def test_format_cents(self):
        self.assertEqual(rosters.format_cents(0), '$0.00')
        self.assertEqual(rosters.format_cents(123456), '$1,234.56')

    def test_truncate_words(self):
        self.assertEqual(rosters.truncate_words('the quick brown fox', 2), 'the quick...')
        self.assertEqual(rosters.truncate_words('tea time', 2), 'tea time')
