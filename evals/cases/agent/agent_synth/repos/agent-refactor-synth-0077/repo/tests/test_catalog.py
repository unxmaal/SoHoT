import unittest

from granary import catalog


class Catalog(unittest.TestCase):
    def test_deck_view(self):
        self.assertEqual(catalog.deck_view([1, 2, 3, 4], 2), {'deck_view': [1.5, 2.5, 3.5]})
        self.assertEqual(catalog.deck_view([5], 1), {'deck_view': [5.0]})

    def test_merge_ranges(self):
        self.assertEqual(catalog.merge_ranges([(1, 3), (3, 5)]), [(1, 5)])
        self.assertEqual(catalog.merge_ranges([(5, 6), (1, 2)]), [(1, 2), (5, 6)])

    def test_truncate_words(self):
        self.assertEqual(catalog.truncate_words('the quick brown fox', 2), 'the quick...')
        self.assertEqual(catalog.truncate_words('tea time', 2), 'tea time')
