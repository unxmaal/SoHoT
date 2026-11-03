import unittest

from meadow.numbers import merge_ranges
from meadow import archive


class Archive(unittest.TestCase):
    def test_merge_ranges(self):
        self.assertEqual(merge_ranges([(1, 3), (3, 5)]), [(1, 5)])
        self.assertEqual(merge_ranges([(5, 6), (1, 2)]), [(1, 2), (5, 6)])
        self.assertEqual(merge_ranges([(1, 10), (2, 3)]), [(1, 10)])

    def test_truncate_words(self):
        self.assertEqual(archive.truncate_words('the quick brown fox', 2), 'the quick...')
        self.assertEqual(archive.truncate_words('tea time', 2), 'tea time')
