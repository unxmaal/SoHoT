import unittest

from depot import archive


class Archive(unittest.TestCase):
    def test_truncate_words(self):
        self.assertEqual(archive.truncate_words('the quick brown fox', 2), 'the quick...')
        self.assertEqual(archive.truncate_words('tea time', 2), 'tea time')

    def test_rle(self):
        self.assertEqual(archive.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(archive.rle(''), [])
        self.assertEqual(archive.rle('abc'), [('a', 1), ('b', 1), ('c', 1)])
