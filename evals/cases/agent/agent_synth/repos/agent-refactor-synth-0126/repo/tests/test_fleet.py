import unittest

from compass import fleet


class Fleet(unittest.TestCase):
    def test_deck_total(self):
        self.assertEqual(fleet.deck_total(0), {'deck_total': '$0.00'})
        self.assertEqual(fleet.deck_total(123456), {'deck_total': '$1,234.56'})

    def test_invert(self):
        self.assertEqual(fleet.invert({'a': 1, 'b': 2, 'c': 1}), {1: ['a', 'c'], 2: ['b']})
        self.assertEqual(fleet.invert({}), {})

    def test_merge_ranges(self):
        self.assertEqual(fleet.merge_ranges([(1, 3), (3, 5)]), [(1, 5)])
        self.assertEqual(fleet.merge_ranges([(5, 6), (1, 2)]), [(1, 2), (5, 6)])
