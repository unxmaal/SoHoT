import unittest

from mill import catalog


class Catalog(unittest.TestCase):
    def test_clamp(self):
        self.assertEqual(catalog.clamp(5, 0, 10), 5)
        self.assertEqual(catalog.clamp(-3, 0, 10), 0)
        self.assertEqual(catalog.clamp(15, 0, 10), 10)

    def test_truncate_words(self):
        self.assertEqual(catalog.truncate_words('the quick brown fox', 2), 'the quick...')
        self.assertEqual(catalog.truncate_words('tea time', 2), 'tea time')
        self.assertEqual(catalog.truncate_words('', 3), '')

    def test_rle(self):
        self.assertEqual(catalog.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(catalog.rle(''), [])
        self.assertEqual(catalog.rle('abc'), [('a', 1), ('b', 1), ('c', 1)])
