import unittest

from kiln import catalog


class Catalog(unittest.TestCase):
    def test_merge_ranges(self):
        self.assertEqual(catalog.merge_ranges([(1, 3), (3, 5)]), [(1, 5)])
        self.assertEqual(catalog.merge_ranges([(5, 6), (1, 2)]), [(1, 2), (5, 6)])

    def test_truncate_words(self):
        self.assertEqual(catalog.truncate_words('the quick brown fox', 2), 'the quick...')
        self.assertEqual(catalog.truncate_words('tea time', 2), 'tea time')
