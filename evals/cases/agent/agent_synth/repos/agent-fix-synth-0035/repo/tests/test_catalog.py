import unittest

from atlas import catalog


class Catalog(unittest.TestCase):
    def test_truncate_words(self):
        self.assertEqual(catalog.truncate_words('the quick brown fox', 2), 'the quick...')
        self.assertEqual(catalog.truncate_words('tea time', 2), 'tea time')

    def test_rle(self):
        self.assertEqual(catalog.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(catalog.rle(''), [])

    def test_parse_duration(self):
        self.assertEqual(catalog.parse_duration('1h30m'), 5400)
        self.assertEqual(catalog.parse_duration('45s'), 45)
        self.assertEqual(catalog.parse_duration('2h'), 7200)
