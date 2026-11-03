import unittest

from kiln.archive import first_words
from kiln import archive


class Archive(unittest.TestCase):
    def test_first_words(self):
        self.assertEqual(first_words('the quick brown fox', 2), 'the quick...')
        self.assertEqual(first_words('tea time', 2), 'tea time')
        self.assertEqual(first_words('', 3), '')

    def test_invert(self):
        self.assertEqual(archive.invert({'a': 1, 'b': 2, 'c': 1}), {1: ['a', 'c'], 2: ['b']})
        self.assertEqual(archive.invert({}), {})
